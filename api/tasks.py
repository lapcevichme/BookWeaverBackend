from fastapi import APIRouter, HTTPException

from api import state
from api.models import ServerStatus, TaskStatusResponse

router = APIRouter()

@router.get("/health", response_model=ServerStatus, tags=["Health Check"])
async def health_check():
    """Проверяет текущее состояние готовности сервера."""
    return state.SERVER_STATUS


@router.get("/api/v1/tasks/{task_id}/status", response_model=TaskStatusResponse, tags=["Task Management"])
async def get_task_status(task_id: str):
    """Возвращает статус и прогресс для фоновой задачи по её ID."""
    task = state.background_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    return TaskStatusResponse(task_id=task_id, **task)

