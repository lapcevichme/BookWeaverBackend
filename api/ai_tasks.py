from fastapi import APIRouter, BackgroundTasks

from core.project_context import ProjectContext
from api import state
from api.models import TaskStatusResponse, BookTaskRequest, ChapterTaskRequest

router = APIRouter(
    prefix="/api/v1",
    tags=["AI Tasks"]
)

@router.post("/analyze_characters", response_model=TaskStatusResponse, status_code=202)
async def start_character_analysis(req: BookTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для анализа персонажей во всей книге."""
    return state.start_task(state.app_pipelines.character_pipeline.run, runner, book_name=req.book_name)


@router.post("/generate_summaries", response_model=TaskStatusResponse, status_code=202)
async def start_summary_generation(req: BookTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для генерации пересказа для всех глав книги."""
    context = ProjectContext(book_name=req.book_name)
    return state.start_task(state.app_pipelines.summary_pipeline.run, runner, context=context)


@router.post("/generate_scenario", response_model=TaskStatusResponse, status_code=202)
async def start_scenario_generation(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для генерации сценария для одной главы."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return state.start_task(state.app_pipelines.scenario_pipeline.run, runner, context=context)


@router.post("/synthesize_tts", response_model=TaskStatusResponse, status_code=202)
async def start_tts_synthesis(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для синтеза речи (TTS) для одной главы."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return state.start_task(state.app_pipelines.tts_pipeline.run, runner, context=context)


@router.post("/apply_voice_conversion", response_model=TaskStatusResponse, status_code=202)
async def start_voice_conversion(req: ChapterTaskRequest, runner: BackgroundTasks):
    """Запускает фоновую задачу для применения эмоциональной окраски (VC) для одной главы."""
    context = ProjectContext(book_name=req.book_name, volume_num=req.volume_num, chapter_num=req.chapter_num)
    return state.start_task(state.app_pipelines.vc_pipeline.run, runner, context=context)

