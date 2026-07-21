import shutil
import json
import os
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

import config
from core.project_context import ProjectContext
from core.data_models import Book, Chapter, Character, ScenarioEntry, ChapterSummary
from api.models import (
    BookArtifactName, ChapterArtifactName, BookStatusResponse, 
    ChapterPlaylistResponse, PlaylistEntry, UpdateScenarioEntryRequest
)
from utils.book_converter import BookConverter
from utils.exporter import BookExporter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["Projects Management"]
)


# --- Project Discovery ---

@router.get("/")
async def list_projects():
    """Сканирует папку output и возвращает список проектов с базами данных."""
    books_dir = config.OUTPUT_DIR
    if not books_dir.exists():
        return []
    
    projects = []
    for d in books_dir.iterdir():
        if d.is_dir() and (d / "project.db").exists():
            projects.append(d.name)
    return sorted(projects)


@router.get("/{book_name}")
async def get_project_details(book_name: str):
    """Возвращает детали книги из её локальной БД."""
    context = ProjectContext(book_name=book_name)
    if not (context.book_output_dir / "project.db").exists():
        raise HTTPException(status_code=404, detail="База данных проекта не найдена.")
    
    with context.get_session() as session:
        book = session.get(Book, book_name)
        if not book:
            raise HTTPException(status_code=404, detail="Запись о книге не найдена в БД.")
        
        # Получаем главы
        statement = select(Chapter).where(Chapter.book_id == book_name).order_by(Chapter.order_index)
        chapters = session.exec(statement).all()
        
        chapters_status = []
        for chap in chapters:
            ctx = ProjectContext(book_name, chap.volume_num, chap.chapter_num)
            status = ctx.check_chapter_status()
            status["title"] = chap.title
            status["status"] = chap.status
            chapters_status.append(status)

        return {
            "book_id": book.id,
            "title": book.title,
            "author": book.author,
            "chapters": chapters_status
        }


# --- Scenario Editing (For Web UI) ---

@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/entries")
async def get_chapter_entries(
    book_name: str, 
    volume_num: int, 
    chapter_num: int,
    offset: int = 0,
    limit: int = 100
):
    """Возвращает записи сценария для главы с поддержкой пагинации."""
    context = ProjectContext(book_name, volume_num, chapter_num)
    with context.get_session() as session:
        statement = select(ScenarioEntry).where(
            ScenarioEntry.chapter_id == context.chapter_id
        ).order_by(ScenarioEntry.order_index).offset(offset).limit(limit)
        
        entries = session.exec(statement).all()
        return entries


@router.patch("/{book_name}/entries/{entry_id}")
async def update_scenario_entry(
    book_name: str, 
    entry_id: UUID, 
    req: UpdateScenarioEntryRequest
):
    """Обновляет одну запись сценария в БД книги."""
    context = ProjectContext(book_name=book_name)
    with context.get_session() as session:
        entry = session.get(ScenarioEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Запись не найдена.")
        
        # Обновляем только переданные поля
        update_data = req.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(entry, key, value)
            
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


# --- Characters Management ---

@router.get("/{book_name}/characters")
async def get_book_characters(book_name: str):
    """Возвращает список всех персонажей книги."""
    context = ProjectContext(book_name=book_name)
    with context.get_session() as session:
        statement = select(Character).where(Character.book_id == book_name)
        return session.exec(statement).all()


# --- Artifacts (Compatibility & Downloads) ---

@router.get("/{book_name}/artifacts/{artifact_name}")
async def get_book_artifact(book_name: str, artifact_name: BookArtifactName):
    """Возвращает данные артефакта уровня книги из БД."""
    context = ProjectContext(book_name=book_name)
    
    if artifact_name == BookArtifactName.MANIFEST:
        return context.load_manifest()
    elif artifact_name == BookArtifactName.CHARACTER_ARCHIVE:
        return context.load_character_archive()
    elif artifact_name == BookArtifactName.CHAPTER_SUMMARIES:
        return context.load_summary_archive()
        
    raise HTTPException(status_code=404, detail="Артефакт не найден.")


# --- Project Actions ---

@router.post("/import")
async def import_project(file: UploadFile = File(...)):
    """Загружает и конвертирует новую книгу."""
    temp_dir = config.BASE_DIR / "temp_uploads"
    temp_dir.mkdir(exist_ok=True)
    temp_file_path = temp_dir / file.filename
    try:
        contents = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(contents)

        converter = BookConverter(input_file=temp_file_path)
        converter.convert()
        return {"message": f"Проект '{temp_file_path.stem}' успешно импортирован."}
    except Exception as e:
        logger.error(f"Import error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_file_path.exists(): temp_file_path.unlink()


@router.get("/{book_name}/export", response_class=FileResponse)
async def export_project(book_name: str):
    """Собирает .bw архив для мобилки."""
    try:
        exporter = BookExporter(book_name=book_name)
        archive_path = exporter.export()
        if not archive_path:
            raise HTTPException(status_code=500, detail="Ошибка при создании архива.")
        return FileResponse(path=archive_path, filename=archive_path.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Media ---

@router.get("/{book_name}/cover")
async def get_cover(book_name: str):
    context = ProjectContext(book_name=book_name)
    if not context.cover_file.exists():
        raise HTTPException(status_code=404, detail="Обложка не найдена.")
    return FileResponse(context.cover_file)


@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/audio/{audio_file_name}")
async def get_audio_file(book_name: str, volume_num: int, chapter_num: int, audio_file_name: str):
    context = ProjectContext(book_name, volume_num, chapter_num)
    path = context.chapter_audio_dir / audio_file_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден.")
    return FileResponse(path)
