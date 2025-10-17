import shutil
import json
import os
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse

import config
from core.project_context import ProjectContext
from utils.book_converter import BookConverter
from api.models import BookArtifactName, ChapterArtifactName, BookStatusResponse, ChapterPlaylistResponse, PlaylistEntry
from utils.exporter import BookExporter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["Projects & Files API"]
)


# --- Project Lifecycle ---

@router.post("/import")
async def import_project(file: UploadFile = File(...)):
    """
    Загружает файл книги (.txt, .epub) и преобразует его в структуру проекта.
    """
    temp_dir = config.BASE_DIR / "temp_uploads"
    temp_dir.mkdir(exist_ok=True)
    temp_file_path = temp_dir / file.filename
    try:
        contents = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(contents)

        books_dir = config.INPUT_DIR / "books"
        converter = BookConverter(input_file=temp_file_path, books_root_dir=books_dir)
        converter.convert()
        project_name = temp_file_path.stem
        return {"message": f"Проект '{project_name}' успешно импортирован."}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except Exception as e:
        project_name = temp_file_path.stem
        project_path = config.INPUT_DIR / "books" / project_name
        if project_path.exists():
            shutil.rmtree(project_path)
        raise HTTPException(status_code=500, detail=f"Не удалось обработать книгу: {e}")
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()



@router.get("/{book_name}/export", response_class=FileResponse)
async def export_project(book_name: str):
    """
    Собирает готовый проект в .bw архив и отдает его для скачивания.
    Предварительно проверяет, готов ли проект к экспорту.
    """
    # TODO: тут ввели логику, что должно быть аудио, но наверное достаточно манифеста (подумать)
    context = ProjectContext(book_name=book_name)
    if not context.book_dir.exists() or not context.book_dir.is_dir():
        raise HTTPException(status_code=404, detail="Проект (книга) не найден.")

    discovered_chapters = context.discover_chapters()
    chapters_with_tts = 0
    if discovered_chapters:
        for vol_num, chap_num in discovered_chapters:
            chapter_context = ProjectContext(book_name, vol_num, chap_num)
            chapter_status = chapter_context.check_chapter_status()
            if chapter_status.get('has_audio'):
                chapters_with_tts += 1

    if chapters_with_tts == 0:
        raise HTTPException(
            status_code=412, # Precondition Failed
            detail="Проект не готов к экспорту. Нет ни одной полностью озвученной главы."
        )

    try:
        exporter = BookExporter(book_name=book_name)
        archive_path = exporter.export()

        # Отдаем файл для скачивания
        return FileResponse(
            path=archive_path,
            filename=archive_path.name,
            media_type='application/zip'
        )
    except FileNotFoundError as e:
        logger.error(f"Ошибка экспорта: {e}")
        raise HTTPException(status_code=404, detail=f"Не удалось найти необходимые файлы для экспорта проекта '{book_name}'.")
    except Exception as e:
        logger.error(f"Критическая ошибка при экспорте проекта '{book_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера при создании архива: {e}")


# --- Project Details & Artifacts ---

@router.get("/")
async def list_projects():
    """Сканирует директорию input/books и возвращает список всех книг (проектов)."""
    books_dir = config.INPUT_DIR / "books"
    if not books_dir.exists():
        return []
    return [d.name for d in books_dir.iterdir() if d.is_dir()]


@router.get("/{book_name}")
async def get_project_details(book_name: str):
    """Возвращает детальную информацию о книге: список глав и статус их обработки."""
    context = ProjectContext(book_name=book_name)
    if not context.book_dir.exists() or not context.book_dir.is_dir():
        raise HTTPException(status_code=404, detail="Проект (книга) не найден.")

    chapters_status = []

    discovered_chapters = context.discover_chapters()

    for vol_num, chap_num in discovered_chapters:
        chapter_context = ProjectContext(book_name, vol_num, chap_num)
        chapters_status.append(chapter_context.check_chapter_status())

    return {"book_name": book_name, "chapters": chapters_status}


@router.get("/{book_name}/artifacts/{artifact_name}")
async def get_book_artifact(book_name: str, artifact_name: BookArtifactName):
    """Возвращает содержимое артефакта уровня книги (например, manifest.json)."""
    context = ProjectContext(book_name=book_name)
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path or not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Артефакт '{artifact_name.value}' не найден.")
    return FileResponse(artifact_path)


@router.post("/{book_name}/artifacts/{artifact_name}")
async def update_book_artifact(book_name: str, artifact_name: BookArtifactName, request: Request):
    """
    Обновляет (перезаписывает) артефакт уровня книги (например, manifest.json).
    Принимает JSON в теле запроса.
    """
    context = ProjectContext(book_name=book_name)
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path:
        raise HTTPException(status_code=400, detail=f"Неверное имя артефакта: {artifact_name.value}")
    try:
        new_content = await request.json()
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump(new_content, f, ensure_ascii=False, indent=4)
        return {"message": f"Артефакт '{artifact_name.value}' для книги '{book_name}' успешно обновлен."}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Неверный формат JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при записи файла: {e}")


@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/artifacts/{artifact_name}")
async def get_chapter_artifact(book_name: str, volume_num: int, chapter_num: int, artifact_name: ChapterArtifactName):
    """Возвращает содержимое артефакта уровня главы (например, scenario.json)."""
    context = ProjectContext(book_name=book_name, volume_num=volume_num, chapter_num=chapter_num)
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path or not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Артефакт '{artifact_name.value}' не найден.")

    return FileResponse(artifact_path, media_type="application/json")


# --- Mobile App / Streaming Endpoints ---

@router.post("/{book_name}/cover")
async def upload_cover(book_name: str, file: UploadFile = File(...)):
    """Загружает или обновляет обложку для проекта."""
    context = ProjectContext(book_name=book_name)
    if not context.book_dir.exists():
        raise HTTPException(status_code=404, detail="Проект (книга) не найден.")

    allowed_extensions = {".jpg", ".jpeg", ".png"}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=415, detail="Поддерживаются только .jpg и .png файлы.")

    # Сохраняем файл, используя путь из контекста
    try:
        with open(context.cover_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"message": "Обложка успешно загружена."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить файл обложки: {e}")


@router.get("/{book_name}/cover")
async def get_cover(book_name: str):
    """Отдает файл обложки книги для отображения в клиенте."""
    context = ProjectContext(book_name=book_name)
    if not context.cover_file.exists():
        raise HTTPException(status_code=404, detail="Обложка для этой книги не найдена.")

    return FileResponse(context.cover_file, media_type="image/jpeg")


@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/audio/{audio_file_name}")
async def get_chapter_audio_file(book_name: str, volume_num: int, chapter_num: int, audio_file_name: str):
    """Отдает конкретный аудиофайл из главы для стриминга."""
    context = ProjectContext(book_name, volume_num, chapter_num)
    audio_file_path = context.chapter_audio_dir / audio_file_name

    if not audio_file_path.exists():
        raise HTTPException(status_code=404, detail="Аудиофайл не найден.")

    return FileResponse(audio_file_path, media_type="audio/wav")


@router.get("/{book_name}/status", response_model=BookStatusResponse)
async def get_project_status(book_name: str):
    """
    Возвращает агрегированную сводку о готовности всего проекта.
    Быстро сканирует артефакты всех глав.
    """
    context = ProjectContext(book_name=book_name)
    if not context.book_dir.exists() or not context.book_dir.is_dir():
        raise HTTPException(status_code=404, detail="Проект (книга) не найден.")

    status = BookStatusResponse(book_name=book_name)

    discovered_chapters = context.discover_chapters()
    status.total_chapters = len(discovered_chapters)

    if status.total_chapters == 0:
        return status  # Возвращаем пустой статус, если глав нет

    for vol_num, chap_num in discovered_chapters:
        chapter_context = ProjectContext(book_name, vol_num, chap_num)
        chapter_status = chapter_context.check_chapter_status()

        if chapter_status.get('has_scenario'):
            status.chapters_with_scenario += 1
        if chapter_status.get('has_audio'):
            status.chapters_with_tts += 1

    # Проект готов к экспорту, если хотя бы одна глава полностью готова
    status.is_ready_for_export = status.chapters_with_tts > 0

    return status

# Streaming

@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/playlist", response_model=ChapterPlaylistResponse)
async def get_chapter_playlist(book_name: str, volume_num: int, chapter_num: int):
    """
    Возвращает "плейлист" для главы, оптимизированный для мобильного плеера.
    Клиент сначала запрашивает этот плейлист, а затем поочередно
    запрашивает аудиофайлы и эмбиенты из него.
    """
    context = ProjectContext(book_name, volume_num, chapter_num)

    scenario = context.load_scenario()
    if not scenario:
        raise HTTPException(
            status_code=404,
            detail=f"Сценарий для главы '{context.chapter_id}' не найден. Невозможно создать плейлист."
        )

    playlist_entries = []
    for entry in scenario.entries:
        if entry.audio_file:
            playlist_entries.append(PlaylistEntry(
                audio_file=entry.audio_file,
                text=entry.text,
                speaker=entry.speaker,
                ambient=entry.ambient if entry.ambient != "none" else None
            ))

    return ChapterPlaylistResponse(
        chapter_id=context.chapter_id,
        entries=playlist_entries
    )
