import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException

from api import state
from api.models import TaskStatusResponse, BookTaskRequest, ChapterTaskRequest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tasks/ai",
    tags=["AI Processing Tasks"]
)

@router.post("/analyze-characters", response_model=TaskStatusResponse, status_code=202)
async def start_character_analysis(req: BookTaskRequest):
    """Анализирует персонажей во всей книге (LLM)."""
    return state.start_task(
        task_type="process_book",
        book_id=req.book_name,
        book_name=req.book_name
    )


@router.post("/generate-summaries", response_model=TaskStatusResponse, status_code=202)
async def start_summary_generation(req: BookTaskRequest):
    """Генерирует пересказы для всех глав (LLM)."""
    return state.start_task(
        task_type="generate_summary",
        book_id=req.book_name,
        book_name=req.book_name
    )


@router.post("/generate-scenario", response_model=TaskStatusResponse, status_code=202)
async def start_scenario_generation(req: ChapterTaskRequest):
    """Генерирует сценарий для одной главы (LLM + Sound Design)."""
    # Мы сохраняем передачу параметров для создания ProjectContext внутри воркера
    # Или передаем сам объект (но JSON-сериализация объектов может быть сложной)
    # Лучше передать параметры
    return state.start_task(
        task_type="generate_scenario",
        book_id=req.book_name,
        book_name=req.book_name,
        volume_num=req.volume_num,
        chapter_num=req.chapter_num
    )


@router.post("/synthesize-tts", response_model=TaskStatusResponse, status_code=202)
async def start_tts_synthesis(req: ChapterTaskRequest):
    """Озвучивает главу (TTS)."""
    return state.start_task(
        task_type="generate_tts",
        book_id=req.book_name,
        book_name=req.book_name,
        volume_num=req.volume_num,
        chapter_num=req.chapter_num
    )

@router.post("/full-cycle", response_model=TaskStatusResponse, status_code=202)
async def start_full_cycle(req: BookTaskRequest):
    """Запускает полный цикл: Саммари -> Персонажи -> Сценарии для всей книги."""
    return state.start_task(
        task_type="full_cycle",
        book_id=req.book_name,
        book_name=req.book_name
    )


# VC Pipeline пока не интегрирован в БД полноценно или отключен в main.py
# @router.post("/apply-voice-conversion", response_model=TaskStatusResponse, status_code=202)
