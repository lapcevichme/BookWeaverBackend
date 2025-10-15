import shutil
import json
import os

from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse

import config
from core.project_context import ProjectContext
from utils.book_converter import BookConverter
from api.models import BookArtifactName, ChapterArtifactName

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["Projects & Files API"]
)


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

    # ИЗМЕНЕНО: Теперь вся логика поиска глав инкапсулирована в ProjectContext.
    # Эндпоинт просто вызывает один метод и перебирает результат.
    chapters_status = []

    # 1. Получаем список всех глав из контекста
    discovered_chapters = context.discover_chapters()

    # 2. Для каждой найденной главы создаем её собственный контекст и проверяем статус
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
    # Используем getattr для динамического получения пути из контекста
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path or not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Артефакт '{artifact_name.value}' не найден.")

    # Используем FileResponse для корректной отдачи JSON-файла
    return FileResponse(artifact_path, media_type="application/json")


# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ СТРИМИНГА (ДЛЯ МОБИЛЬНОГО ПРИЛОЖЕНИЯ) ---

@router.post("/{book_name}/cover")
async def upload_cover(book_name: str, file: UploadFile = File(...)):
    """Загружает или обновляет обложку для проекта."""
    context = ProjectContext(book_name=book_name)
    if not context.book_dir.exists():
        raise HTTPException(status_code=404, detail="Проект (книга) не найден.")

    # Проверяем расширение файла
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
        # Можно возвращать 404 или плейсхолдер
        raise HTTPException(status_code=404, detail="Обложка для этой книги не найдена.")

    return FileResponse(context.cover_file, media_type="image/jpeg")


@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/audio/{audio_file_name}")
async def get_chapter_audio_file(book_name: str, volume_num: int, chapter_num: int, audio_file_name: str):
    """Отдает конкретный аудиофайл из главы для стриминга."""
    context = ProjectContext(book_name, volume_num, chapter_num)
    # Формируем путь к файлу, используя папку из контекста
    audio_file_path = context.chapter_audio_dir / audio_file_name

    if not audio_file_path.exists():
        raise HTTPException(status_code=404, detail="Аудиофайл не найден.")

    return FileResponse(audio_file_path, media_type="audio/wav")


