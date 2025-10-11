"""
Основной файл для запуска локального API-сервера на FastAPI.
Этот сервер будет принимать запросы от десктопного приложения.
"""
import uuid
import json
import re
import shutil
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Any, Literal, List
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from enum import Enum
import uvicorn

import config
from main import Application
from services.model_manager import ModelManager
from core.project_context import ProjectContext
from utils.book_converter import BookConverter
from utils.setup_logging import setup_logging

logger = logging.getLogger(__name__)

# --- 1. Управление состоянием сервера ---

class ServerStateEnum(str, Enum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    ERROR = "ERROR"

class ServerStatus(BaseModel):
    status: ServerStateEnum
    message: str = ""

SERVER_STATUS = ServerStatus(status=ServerStateEnum.INITIALIZING, message="Server is starting up...")

# --- 2. Инициализация приложения и пайплайнов ---

# Создаем единственный глобальный экземпляр менеджера
model_manager = ModelManager()

app_pipelines: Application | None = None
background_tasks: Dict[str, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения. Код до yield выполняется при старте.
    """
    global SERVER_STATUS, app_pipelines
    try:
        # Настраиваем логирование при старте
        setup_logging()
        logger.info("Инициализация AI-пайплайнов при старте сервера...")

        app_pipelines = Application(model_manager=model_manager)

        SERVER_STATUS = ServerStatus(status=ServerStateEnum.READY, message="AI pipelines initialized successfully.")
        logger.info(f"✅ {SERVER_STATUS.message}")
    except Exception as e:
        error_message = f"КРИТИЧЕСКАЯ ОШИБКА при инициализации пайплайнов: {e}"
        SERVER_STATUS = ServerStatus(status=ServerStateEnum.ERROR, message=error_message)
        logger.critical(error_message, exc_info=True)

    yield # Приложение готово к работе

    # Код после yield (если нужен) будет выполняться при остановке сервера
    logger.info("Сервер останавливается.")


app = FastAPI(
    title="BookWeaver AI Backend",
    description="Локальный сервер для выполнения тяжелых AI-задач.",
    version="1.0.0",
    lifespan=lifespan
)

# --- 3. Модели данных для API (Pydantic) ---

class ChapterTaskRequest(BaseModel):
    book_name: str
    volume_num: int
    chapter_num: int

class BookTaskRequest(BaseModel):
    book_name: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: Literal["queued", "processing", "complete", "failed"]
    progress: float
    stage: str
    message: str

class ChapterStatus(BaseModel):
    volume_num: int
    chapter_num: int
    has_scenario: bool
    has_subtitles: bool
    has_audio: bool

class ProjectDetailsResponse(BaseModel):
    book_name: str
    chapters: List[ChapterStatus]

class BookArtifactName(str, Enum):
    manifest = "manifest"
    character_archive = "character_archive"
    summary_archive = "summary_archive"

class ChapterArtifactName(str, Enum):
    scenario = "scenario"
    subtitles = "subtitles"

# --- 4. Логика управления фоновыми задачами ---

def _update_task_progress(task_id: str, progress: float, stage: str, message: str):
    """Обновляет статус задачи, принимая три параметра."""
    if task_id in background_tasks:
        background_tasks[task_id]["progress"] = progress
        background_tasks[task_id]["stage"] = stage
        background_tasks[task_id]["message"] = message

def _run_task_wrapper(task_id: str, target_func, **kwargs):
    """Обертка для выполнения задачи в фоне."""
    try:
        background_tasks[task_id]["status"] = "processing"
        # Создаем callback, который передает все три параметра
        progress_callback = lambda p, s, m: _update_task_progress(task_id, p, s, m)
        kwargs["progress_callback"] = progress_callback
        target_func(**kwargs)
        background_tasks[task_id]["status"] = "complete"
    except Exception as e:
        logger.error(f"ОШИБКА в задаче {task_id}: {e}", exc_info=True)
        background_tasks[task_id]["status"] = "failed"
        background_tasks[task_id]["message"] = f"Критическая ошибка: {e}"
        background_tasks[task_id]["stage"] = "Ошибка"


def _start_task(target_func, background_tasks_runner: BackgroundTasks, **kwargs):
    """Запускает новую фоновую задачу."""
    if SERVER_STATUS.status != ServerStateEnum.READY:
        raise HTTPException(status_code=503, detail=f"Server is not ready. Current state: {SERVER_STATUS.status}")
    if app_pipelines is None:
         raise HTTPException(status_code=500, detail="AI Pipelines are not initialized due to a startup error.")

    task_id = str(uuid.uuid4())
    background_tasks[task_id] = {
        "status": "queued",
        "progress": 0.0,
        "stage": "В очереди",
        "message": "Задача поставлена в очередь."
    }
    background_tasks_runner.add_task(_run_task_wrapper, task_id, target_func, **kwargs)
    return TaskStatusResponse(task_id=task_id, **background_tasks[task_id])

# --- 5. API Эндпоинты ---

# --- Health Check & Task Management ---
@app.get("/health", response_model=ServerStatus, tags=["Health Check"])
async def health_check():
    """Проверяет текущее состояние готовности сервера."""
    return SERVER_STATUS

@app.get("/api/v1/tasks/{task_id}/status", response_model=TaskStatusResponse, tags=["Task Management"])
async def get_task_status(task_id: str):
    """Возвращает статус и прогресс для фоновой задачи по её ID."""
    task = background_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    return TaskStatusResponse(task_id=task_id, **task)

# --- AI Tasks ---
@app.post("/api/v1/analyze_characters", response_model=TaskStatusResponse, status_code=202, tags=["AI Tasks"])
async def start_character_analysis(req: BookTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для анализа персонажей во всей книге."""
    return _start_task(app_pipelines.character_pipeline.run, runner, book_name=req.book_name)

@app.post("/api/v1/generate_summaries", response_model=TaskStatusResponse, status_code=202, tags=["AI Tasks"])
async def start_summary_generation(req: BookTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для генерации пересказа для всех глав книги."""
    context = ProjectContext(book_name=req.book_name)
    return _start_task(app_pipelines.summary_pipeline.run, runner, context=context)

@app.post("/api/v1/generate_scenario", response_model=TaskStatusResponse, status_code=202, tags=["AI Tasks"])
async def start_scenario_generation(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для генерации сценария для одной главы."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return _start_task(app_pipelines.scenario_pipeline.run, runner, context=context)

@app.post("/api/v1/synthesize_tts", response_model=TaskStatusResponse, status_code=202, tags=["AI Tasks"])
async def start_tts_synthesis(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для синтеза речи (TTS) для одной главы."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return _start_task(app_pipelines.tts_pipeline.run, runner, context=context)

@app.post("/api/v1/apply_voice_conversion", response_model=TaskStatusResponse, status_code=202, tags=["AI Tasks"])
async def start_voice_conversion(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для применения эмоциональной окраски (VC) для одной главы."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return _start_task(app_pipelines.vc_pipeline.run, runner, context=context)

# --- Projects & Files API ---
TAG_PROJECTS = "Projects & Files API"

@app.post("/api/v1/projects/import", tags=[TAG_PROJECTS])
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
            os.remove(temp_file_path)

@app.get("/api/v1/projects", response_model=List[str], tags=[TAG_PROJECTS])
async def list_projects():
    """Сканирует директорию input/books и возвращает список всех книг (проектов)."""
    books_dir = config.INPUT_DIR / "books"
    if not books_dir.exists():
        return []
    return [d.name for d in books_dir.iterdir() if d.is_dir()]

@app.get("/api/v1/projects/{book_name}", response_model=ProjectDetailsResponse, tags=[TAG_PROJECTS])
async def get_project_details(book_name: str):
    """Возвращает детальную информацию о книге: список глав и статус их обработки."""
    book_dir = config.INPUT_DIR / "books" / book_name
    if not book_dir.exists() or not book_dir.is_dir():
        raise HTTPException(status_code=404, detail="Проект (книга) не найден.")
    chapters_status = []
    for vol_dir in sorted(book_dir.glob("vol_*")):
        if not vol_dir.is_dir(): continue
        vol_match = re.match(r"vol_(\d+)", vol_dir.name)
        if not vol_match: continue
        vol_num = int(vol_match.group(1))
        for chap_file in sorted(vol_dir.glob("chapter_*.txt")):
            chap_match = re.match(r"chapter_(\d+)\.txt", chap_file.name)
            if not chap_match: continue
            chap_num = int(chap_match.group(1))
            context = ProjectContext(book_name, vol_num, chap_num)
            chapters_status.append(ChapterStatus(**context.check_chapter_status()))
    return ProjectDetailsResponse(book_name=book_name, chapters=chapters_status)

@app.get("/api/v1/projects/{book_name}/artifacts/{artifact_name}", tags=[TAG_PROJECTS])
async def get_book_artifact(book_name: str, artifact_name: BookArtifactName):
    """Возвращает содержимое артефакта уровня книги (например, manifest.json)."""
    context = ProjectContext(book_name=book_name)
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path or not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Артефакт '{artifact_name.value}' не найден.")
    with open(artifact_path, 'r', encoding='utf-8') as f:
        return JSONResponse(content=json.load(f))

@app.post("/api/v1/projects/{book_name}/artifacts/{artifact_name}", tags=[TAG_PROJECTS])
async def update_book_artifact(book_name: str, artifact_name: BookArtifactName, request: Request):
    """
    Обновляет (перезаписывает) артефакт уровня книги (например, manifest.json).
    Принимает JSON в теле запроса.
    """
    context = ProjectContext(book_name=book_name)
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path:
        raise HTTPException(status_code=404, detail=f"Артефакт '{artifact_name.value}' не найден.")
    try:
        new_content = await request.json()
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump(new_content, f, ensure_ascii=False, indent=4)
        return {"message": f"Артефакт '{artifact_name.value}' для книги '{book_name}' успешно обновлен."}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Неверный формат JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при записи файла: {e}")

@app.get("/api/v1/projects/{book_name}/chapters/{volume_num}/{chapter_num}/artifacts/{artifact_name}", tags=[TAG_PROJECTS])
async def get_chapter_artifact(book_name: str, volume_num: int, chapter_num: int, artifact_name: ChapterArtifactName):
    """Возвращает содержимое артефакта уровня главы (например, scenario.json)."""
    context = ProjectContext(book_name=book_name, volume_num=volume_num, chapter_num=chapter_num)
    artifact_path = getattr(context, f"{artifact_name.value}_file", None)
    if not artifact_path or not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Артефакт '{artifact_name.value}' не найден.")
    with open(artifact_path, 'r', encoding='utf-8') as f:
        return JSONResponse(content=json.load(f))


# --- Root and Server Run ---
@app.get("/", include_in_schema=False)
async def root():
    """Корневой эндпоинт для простой проверки, что сервер запущен."""
    return {"message": "BookWeaver AI Backend работает. Перейдите на /docs для просмотра API."}

if __name__ == "__main__":
    # Этот блок теперь просто для информации, запуск через uvicorn
    logger.info("="*50)
    logger.info("🚀  ДЛЯ ЗАПУСКА СЕРВЕРА ВЫПОЛНИТЕ В ТЕРМИНАЛЕ:")
    logger.info("uvicorn api_server:app --reload")
    logger.info("="*50)
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=True)

