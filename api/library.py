import json
import re
import shutil
from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

import config
from api.models import AmbientMetadata

router = APIRouter(
    prefix="/api/v1",
    tags=["Asset Library"]
)

# --- Управление голосами ---

@router.get("/voices")
async def get_voices_library():
    """Возвращает список всех доступных голосов."""
    voices = []
    if not config.VOICES_DIR.exists():
        return []
    for voice_dir in config.VOICES_DIR.iterdir():
        if voice_dir.is_dir():
            files = [f.name for f in voice_dir.glob("*.wav")]
            voices.append({"voice_id": voice_dir.name, "files": files})
    return voices


@router.post("/voices")
async def upload_voice(
    voice_id: str = Form(..., description="Уникальный ID для голоса, например, 'author_male'"),
    file: UploadFile = File(..., description="WAV файл с образцом голоса.")
):
    """Загружает новый голос в библиотеку."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", voice_id):
        raise HTTPException(status_code=400, detail="Voice ID может содержать только буквы, цифры, _ и -.")

    voice_dir = config.VOICES_DIR / voice_id
    voice_dir.mkdir(exist_ok=True)

    file_path = voice_dir / file.filename
    if not file_path.name.lower().endswith(".wav"):
         raise HTTPException(status_code=400, detail="Поддерживаются только WAV файлы.")

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить файл: {e}")

    return JSONResponse(status_code=201, content={"voice_id": voice_id, "filename": file.filename})


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Удаляет голос из библиотеки."""
    voice_dir = config.VOICES_DIR / voice_id
    if not voice_dir.exists() or not voice_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Голос с ID '{voice_id}' не найден.")

    try:
        shutil.rmtree(voice_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении папки голоса: {e}")

    return JSONResponse(status_code=200, content={"message": f"Голос '{voice_id}' успешно удален."})


# --- Управление фоновыми звуками (Ambient) ---

def _read_ambient_library() -> List[Dict]:
    """Вспомогательная функция для чтения ambient_library.json."""
    if not config.AMBIENT_LIBRARY_FILE.exists():
        # Если файла нет, создаем его с записью 'none'
        default_data = [{"id": "none", "description": "Полная тишина.", "tags": ["тишина"]}]
        _write_ambient_library(default_data)
        return default_data
    try:
        with open(config.AMBIENT_LIBRARY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def _write_ambient_library(data: List[Dict]):
    """Вспомогательная функция для записи в ambient_library.json."""
    with open(config.AMBIENT_LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/ambient")
async def get_ambient_library():
    """
    Возвращает список фоновых звуков из ambient_library.json,
    проверяя наличие соответствующих аудиофайлов.
    """
    library_entries = _read_ambient_library()
    audio_files = {f.stem for f in config.AMBIENT_DIR.iterdir() if f.is_file()}

    for entry in library_entries:
        entry["has_audio_file"] = entry.get("id") in audio_files
    return library_entries


@router.post("/ambient")
async def upload_ambient(
    metadata: str = Form(..., description="JSON-строка с метаданными: {'id': '...', 'description': '...', 'tags': [...] }"),
    file: UploadFile = File(..., description="Аудиофайл (mp3, wav, ogg).")
):
    """
    Загружает новый фоновый звук: аудиофайл + метаданные в ambient_library.json.
    """
    try:
        meta_obj = AmbientMetadata.model_validate_json(metadata)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Некорректный формат JSON в поле metadata: {e}")

    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in ['.mp3', '.wav', '.ogg']:
         raise HTTPException(status_code=400, detail="Поддерживаемые форматы: mp3, wav, ogg.")

    file_path = config.AMBIENT_DIR / f"{meta_obj.id}{file_extension}"

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить аудиофайл: {e}")

    library = _read_ambient_library()
    library = [entry for entry in library if entry.get("id") != meta_obj.id] # Удаляем старую запись, если есть
    library.append(meta_obj.model_dump())
    _write_ambient_library(library)

    return JSONResponse(status_code=201, content={
        "message": "Эмбиент успешно добавлен.",
        "metadata": meta_obj.model_dump()
    })


@router.delete("/ambient/{ambient_id}")
async def delete_ambient(ambient_id: str):
    """
    Удаляет эмбиент из библиотеки (запись в JSON и соответствующий аудиофайл).
    """
    if ambient_id == "none":
        raise HTTPException(status_code=400, detail="Нельзя удалить базовый эмбиент 'none'.")

    library = _read_ambient_library()
    original_length = len(library)
    library = [entry for entry in library if entry.get("id") != ambient_id]

    if len(library) == original_length:
        raise HTTPException(status_code=404, detail=f"Эмбиент с ID '{ambient_id}' не найден в библиотеке.")

    _write_ambient_library(library)

    deleted_files = []
    for f in config.AMBIENT_DIR.glob(f"{ambient_id}.*"):
        if f.is_file():
            try:
                f.unlink()
                deleted_files.append(f.name)
            except Exception as e:
                print(f"Warning: Could not delete audio file {f.name}: {e}")

    return JSONResponse(status_code=200, content={
        "message": f"Эмбиент '{ambient_id}' успешно удален.",
        "deleted_audio_files": deleted_files
    })
