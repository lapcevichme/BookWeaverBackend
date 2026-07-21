from fastapi import APIRouter, HTTPException

from api import state
from api.models import ServerStatus, TaskStatusResponse

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["Tasks Management"]
)

@router.get("/health", response_model=ServerStatus)
async def health_check():
    """Проверяет состояние готовности сервера."""
    return state.SERVER_STATUS


@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Возвращает прогресс фоновой задачи."""
    task = state.background_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    return TaskStatusResponse(task_id=task_id, **task)
