import shutil
import json
import os
import logging
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

import config
from core.book_repository import BookRepository
from core import path_manager
from core.data_models import Book, Chapter, Character, ScenarioEntry, ChapterSummary
from api.models import (
    BookArtifactName, ChapterArtifactName, BookStatusResponse, 
    ChapterPlaylistResponse, PlaylistEntry, UpdateScenarioEntryRequest,
    UpdateCharacterRequest, UpdateBookRequest
)
from utils.book_converter import BookConverter
from utils.exporter import BookExporter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["Projects Management"]
)


# --- Project Discovery ---

@router.get("/dashboard/summary")
async def get_dashboard_summary():
    """Возвращает глобальную статистику по всей библиотеке."""
    import config
    import os
    from api import state
    
    output_dir = config.OUTPUT_DIR
    if not output_dir.exists():
        return {"total_books": 0, "recent_projects": []}
    
    # 1. Считаем книги
    all_projects = [d for d in output_dir.iterdir() if d.is_dir() and (d / "project.db").exists()]
    
    # 2. Находим последние активные
    recent_dirs = sorted(all_projects, key=lambda d: d.stat().st_mtime, reverse=True)[:4]
    recent_projects = []
    for d in recent_dirs:
        repo = BookRepository(book_id=d.name)
        book = repo.get_book()
        if book:
            chapters = repo.get_all_chapters()
            total = len(chapters)
            ready = 0
            for chap in chapters:
                audio_dir = path_manager.get_chapter_audio_dir(d.name, chap.id)
                if audio_dir.exists() and any(audio_dir.iterdir()):
                    ready += 1
            recent_projects.append({
                "id": d.name, "title": book.title,
                "progress": round((ready / total * 100), 1) if total > 0 else 0,
                "total_chapters": total
            })

    # 3. Общие метрики из баз данных всех книг
    total_tokens = 0
    total_audio_sec = 0
    for d in all_projects:
        repo = BookRepository(book_id=d.name)
        try:
            with repo.get_session() as session:
                from core.data_models import LLMMetric, AudioMetric
                llms = session.exec(select(LLMMetric)).all()
                total_tokens += sum(m.input_tokens + m.output_tokens for m in llms)
                audios = session.exec(select(AudioMetric)).all()
                total_audio_sec += sum(a.audio_duration_ms for a in audios) / 1000
        except Exception as e:
            logger.warning(f"Failed to read metrics from {d.name} DB: {e}")
            
    total_audio_min = round(total_audio_sec / 60, 1)

    # 4. РЕАЛЬНОЕ место на диске (из кэша в БД)
    total_bytes = 0
    for d in all_projects:
        repo = BookRepository(book_id=d.name)
        book = repo.get_book()
        if book:
            total_bytes += book.storage_size_bytes
    
    storage_gb = round(total_bytes / (1024**3), 2)

    # 5. Статус сервисов
    llm_ok = state.app_pipelines is not None and state.app_pipelines.character_pipeline is not None
    tts_ok = state.app_pipelines is not None and state.app_pipelines.tts_pipeline is not None
    
    # Активные задачи (реальные)
    from core.task_queue import list_tasks, TaskStatus
    active_tasks_count = sum(1 for t in list_tasks() if t.status == TaskStatus.PROCESSING)

    return {
        "total_books": len(all_projects),
        "total_tokens": total_tokens,
        "total_audio_minutes": total_audio_min,
        "recent_projects": recent_projects,
        "system": {
            "storage_gb": storage_gb,
            "llm_status": "Online" if llm_ok else "Offline",
            "tts_status": "Online" if tts_ok else "Offline",
            "active_tasks": active_tasks_count
        }
    }


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
    repo = BookRepository(book_id=book_name)
    book = repo.get_book()
    if not book:
        raise HTTPException(status_code=404, detail="Книга или база данных проекта не найдены.")
    
    with repo.get_session() as session:
        # Получаем главы
        statement = select(Chapter).where(Chapter.book_id == book_name).order_by(Chapter.order_index)
        chapters = session.exec(statement).all()
        
        chapters_status = []
        for chap in chapters:
            audio_dir = path_manager.get_chapter_audio_dir(book_name, chap.id)
            has_audio = audio_dir.exists() and any(audio_dir.iterdir())
            
            chapters_status.append({
                "volume_num": chap.volume_num,
                "chapter_num": chap.chapter_num,
                "id": chap.id,
                "title": chap.title,
                "status": chap.status,
                "has_audio": has_audio
            })

        return {
            "book_id": book.id,
            "title": book.title,
            "author": book.author,
            "chapters": chapters_status
        }


@router.patch("/{book_name}")
async def update_project_metadata(book_name: str, req: UpdateBookRequest):
    """Обновляет метаданные книги в БД."""
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
        book = session.get(Book, book_name)
        if not book:
            raise HTTPException(status_code=404, detail="Книга не найдена.")
        
        update_data = req.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(book, key, value)
            
        session.add(book)
        session.commit()
        session.refresh(book)
        return book


@router.delete("/{book_name}")
async def delete_project(book_name: str):
    """Полностью удаляет проект (БД, вывод и входные файлы)."""
    book_output_dir = path_manager.get_book_output_dir(book_name)
    book_input_dir = path_manager.get_book_dir(book_name)
    
    # 1. Удаляем папку в output
    if book_output_dir.exists():
        shutil.rmtree(book_output_dir)
        logger.info(f"Удалена папка вывода: {book_output_dir}")
        
    # 2. Удаляем папку в input (опционально, но логично для полной очистки)
    if book_input_dir.exists():
        shutil.rmtree(book_input_dir)
        logger.info(f"Удалена папка входа: {book_input_dir}")
        
    return {"message": f"Проект '{book_name}' успешно удален."}


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
    chapter_id = f"vol_{volume_num}_chap_{chapter_num}"
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
        statement = select(ScenarioEntry).where(
            ScenarioEntry.chapter_id == chapter_id
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
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
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
    repo = BookRepository(book_id=book_name)
    return repo.get_characters()


@router.patch("/{book_name}/characters/{char_id}")
async def update_character(
    book_name: str, 
    char_id: UUID, 
    req: UpdateCharacterRequest
):
    """Обновляет данные персонажа в БД книги."""
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
        char = session.get(Character, char_id)
        if not char:
            raise HTTPException(status_code=404, detail="Персонаж не найден.")
        
        update_data = req.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(char, key, value)
            
        session.add(char)
        session.commit()
        session.refresh(char)
        return char


@router.delete("/{book_name}/characters/{char_id}")
async def delete_character(book_name: str, char_id: UUID):
    """Удаляет персонажа из БД книги."""
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
        char = session.get(Character, char_id)
        if not char:
            raise HTTPException(status_code=404, detail="Персонаж не найден.")
        
        session.delete(char)
        session.commit()
        return {"message": "Персонаж удален."}


@router.get("/{book_name}/characters/{char_id}/portrait")
async def get_character_portrait(book_name: str, char_id: UUID):
    """Возвращает файл портрета персонажа."""
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
        char = session.get(Character, char_id)
        if not char:
            raise HTTPException(status_code=404, detail="Персонаж не найден.")
        
        img_path = None
        # Ищем в visual_timeline
        if char.visual_timeline:
            if "global" in char.visual_timeline and char.visual_timeline["global"].reference_image_path:
                img_path = char.visual_timeline["global"].reference_image_path
            else:
                for state in char.visual_timeline.values():
                    if state.reference_image_path:
                        img_path = state.reference_image_path
                        break
        
        # Если в timeline нет пути, поищем в папке изображений книги по ID
        if not img_path:
            images_dir = path_manager.get_book_output_dir(book_name) / "images"
            if images_dir.exists():
                for f in images_dir.iterdir():
                    if f.name.startswith(str(char_id)) and f.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                        img_path = f
                        break
        
        if not img_path:
            raise HTTPException(status_code=404, detail="Портрет персонажа не найден.")
            
        path = Path(img_path)
        if not path.is_absolute():
            path = path_manager.get_book_output_dir(book_name) / path
            
        if not path.exists():
            raise HTTPException(status_code=404, detail="Файл портрета не найден.")
        return FileResponse(path)


# --- Artifacts (Compatibility & Downloads) ---

@router.get("/{book_name}/artifacts/{artifact_name}")
async def get_book_artifact(book_name: str, artifact_name: BookArtifactName):
    """Возвращает данные артефакта уровня книги из БД."""
    repo = BookRepository(book_id=book_name)
    
    if artifact_name == BookArtifactName.MANIFEST:
        return repo.load_manifest()
    elif artifact_name == BookArtifactName.CHARACTER_ARCHIVE:
        return repo.get_character_archive()
    elif artifact_name == BookArtifactName.CHAPTER_SUMMARIES:
        return repo.get_summary_archive()
        
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
        converter.run()
        return {
            "message": f"Проект '{temp_file_path.stem}' успешно импортирован.",
            "book_id": converter.book_name
        }
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
    repo = BookRepository(book_id=book_name)
    book = repo.get_book()
    if not book or not book.cover_image_path:
        raise HTTPException(status_code=404, detail="Обложка не найдена.")
    
    path = Path(book.cover_image_path)
    if not path.is_absolute():
        path = path_manager.get_book_output_dir(book_name) / path
        
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл обложки не найден.")
    return FileResponse(path)


@router.get("/{book_name}/metrics")
async def get_project_metrics(book_name: str):
    """Возвращает детальные метрики книги: токены, RTF и агрегированные ошибки."""
    from core.data_models import LLMMetric, AudioMetric, MetricCounter
    
    repo = BookRepository(book_id=book_name)
    db_chapters = repo.get_all_chapters()
    
    total_tokens = 0
    book_chapters_data = []
    
    book_counters = {
        "json_parse_errors": 0,
        "name_collisions": 0,
        "tts_hallucinations": 0,
        "tts_retries": 0,
        "api_retries": 0
    }
    
    try:
        with repo.get_session() as session:
            # Получаем все метрики из БД этой книги
            llm_calls = session.exec(select(LLMMetric)).all()
            audio_calls = session.exec(select(AudioMetric)).all()
            counters = session.exec(select(MetricCounter)).all()
            
            for chap in db_chapters:
                chap_llm = [m for m in llm_calls if m.chapter_id == chap.id]
                chap_audio = [m for m in audio_calls if m.chapter_id == chap.id]
                chap_counters = [m for m in counters if m.chapter_id == chap.id]
                
                chap_errs = {c.counter_name: c.value for c in chap_counters}
                
                # Агрегируем общие счетчики
                for c in chap_counters:
                    if c.counter_name in book_counters:
                        book_counters[c.counter_name] += c.value
                
                avg_rtf = sum(a.rtf for a in chap_audio) / len(chap_audio) if chap_audio else 0
                total_audio_sec = sum(a.audio_duration_ms for a in chap_audio) / 1000
                chap_tokens = sum(m.input_tokens + m.output_tokens for m in chap_llm)
                total_tokens += chap_tokens
                
                book_chapters_data.append({
                    "chapter_id": chap.id,
                    "llm_calls": len(chap_llm),
                    "total_tokens": chap_tokens,
                    "audio_units": len(chap_audio),
                    "total_audio_duration_sec": round(total_audio_sec, 2),
                    "avg_rtf": round(avg_rtf, 3),
                    "avg_cer": round(sum(a.cer for a in chap_audio) / len(chap_audio), 4) if chap_audio else 0,
                    "errors": chap_errs
                })
    except Exception as e:
        logger.error(f"Error querying metrics from DB for project {book_name}: {e}")
        return {"chapters": [], "total_tokens": 0, "counters": {}}

    # Собираем данные для хитмапа персонажей (кол-во реплик по главам)
    character_activity = {}
    with repo.get_session() as session:
        from core.data_models import ScenarioEntry
        from sqlalchemy import func
        
        query = session.query(
            ScenarioEntry.chapter_id, 
            ScenarioEntry.speaker_id, 
            func.count(ScenarioEntry.id)
        ).filter(ScenarioEntry.speaker_id != None).group_by(
            ScenarioEntry.chapter_id, ScenarioEntry.speaker_id
        )
        
        for chap_id, char_id, count in query.all():
            char_id_str = str(char_id)
            if char_id_str not in character_activity:
                character_activity[char_id_str] = {}
            character_activity[char_id_str][chap_id] = count

    return {
        "book_id": book_name,
        "total_tokens": total_tokens,
        "counters": book_counters,
        "chapters": book_chapters_data,
        "character_activity": character_activity
    }


@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/audio/{audio_file_name}")
async def get_audio_file(book_name: str, volume_num: int, chapter_num: int, audio_file_name: str):
    chapter_id = f"vol_{volume_num}_chap_{chapter_num}"
    path = path_manager.get_chapter_audio_dir(book_name, chapter_id) / audio_file_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден.")
    return FileResponse(path)


from pydantic import BaseModel

class ChapterStructureItem(BaseModel):
    id: str
    volume_num: int
    chapter_num: int
    title: str

class BookStructureUpdate(BaseModel):
    title: str
    author: str
    chapters: List[ChapterStructureItem]

@router.get("/{book_name}/chapters/{volume_num}/{chapter_num}/preview")
async def get_chapter_preview(book_name: str, volume_num: int, chapter_num: int):
    """Возвращает текстовый превью главы (первые 1000 символов)."""
    vol_dir = path_manager.get_book_dir(book_name) / f"vol_{volume_num}"
    file_path = vol_dir / f"chapter_{chapter_num}.md"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл главы не найден.")
    try:
        text = file_path.read_text(encoding="utf-8")
        preview = text[:1000]
        if len(text) > 1000:
            preview += "\n..."
        return {"preview": preview}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения файла главы: {e}")

@router.post("/{book_name}/structure")
async def update_project_structure(book_name: str, req: BookStructureUpdate):
    """Обновляет метаданные книги и структуру глав, удаляя лишние главы."""
    repo = BookRepository(book_id=book_name)
    with repo.get_session() as session:
        book = session.get(Book, book_name)
        if not book:
            raise HTTPException(status_code=404, detail="Книга не найдена.")
        
        book.title = req.title
        book.author = req.author
        session.add(book)
        
        statement = select(Chapter).where(Chapter.book_id == book_name)
        current_chapters = session.exec(statement).all()
        current_chapters_dict = {c.id: c for c in current_chapters}
        
        keep_ids = set()
        for idx, item in enumerate(req.chapters, 1):
            keep_ids.add(item.id)
            if item.id in current_chapters_dict:
                chap = current_chapters_dict[item.id]
                chap.volume_num = item.volume_num
                chap.chapter_num = item.chapter_num
                chap.title = item.title
                chap.order_index = idx
                session.add(chap)
            else:
                new_chap = Chapter(
                    id=item.id,
                    book_id=book_name,
                    volume_num=item.volume_num,
                    chapter_num=item.chapter_num,
                    title=item.title,
                    order_index=idx,
                    status="ongoing"
                )
                session.add(new_chap)
                
        for c_id, chap in current_chapters_dict.items():
            if c_id not in keep_ids:
                session.delete(chap)
                try:
                    vol_dir = path_manager.get_book_dir(book_name) / f"vol_{chap.volume_num}"
                    file_path = vol_dir / f"chapter_{chap.chapter_num}.md"
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"Удален файл главы: {file_path}")
                    if vol_dir.exists() and not any(vol_dir.iterdir()):
                        vol_dir.rmdir()
                        logger.info(f"Удалена пустая папка тома: {vol_dir}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить файл для удаленной главы {c_id}: {e}")
                    
        session.commit()
    return {"message": "Структура книги успешно обновлена."}
