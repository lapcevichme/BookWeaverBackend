import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.project_context import ProjectContext
from api import state
from api.models import TaskStatusResponse, BookTaskRequest, ChapterTaskRequest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tasks/ai",
    tags=["AI Processing Tasks"]
)

@router.post("/analyze-characters", response_model=TaskStatusResponse, status_code=202)
async def start_character_analysis(req: BookTaskRequest, runner: BackgroundTasks):
    """Анализирует персонажей во всей книге (LLM)."""
    return state.start_task(
        state.app_pipelines.character_pipeline.run, 
        runner, 
        book_name=req.book_name
    )


@router.post("/generate-summaries", response_model=TaskStatusResponse, status_code=202)
async def start_summary_generation(req: BookTaskRequest, runner: BackgroundTasks):
    """Генерирует пересказы для всех глав (LLM)."""
    return state.start_task(
        state.app_pipelines.summary_pipeline.run, 
        runner, 
        book_name=req.book_name
    )


@router.post("/generate-scenario", response_model=TaskStatusResponse, status_code=202)
async def start_scenario_generation(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Генерирует сценарий для одной главы (LLM + Sound Design)."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return state.start_task(
        state.app_pipelines.scenario_pipeline.run, 
        runner, 
        context=context
    )


@router.post("/synthesize-tts", response_model=TaskStatusResponse, status_code=202)
async def start_tts_synthesis(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Озвучивает главу (TTS)."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return state.start_task(
        state.app_pipelines.tts_pipeline.run, 
        runner, 
        context=context
    )

# VC Pipeline пока не интегрирован в БД полноценно или отключен в main.py
# @router.post("/apply-voice-conversion", response_model=TaskStatusResponse, status_code=202)
