"""
Этот модуль содержит глобальное состояние сервера и функции-хелперы для управления им.
Он импортируется как главным файлом api_server.py, так и отдельными роутерами,
чтобы избежать циклических импортов.
"""
import uuid
import logging
from typing import Dict, Any

from fastapi import BackgroundTasks, HTTPException

from api.models import ServerStatus, ServerStateEnum, TaskStatusResponse

from main import Application
from services.model_manager import ModelManager

logger = logging.getLogger(__name__)

# --- Глобальные переменные, управляющие состоянием сервера ---
SERVER_STATUS = ServerStatus(status=ServerStateEnum.INITIALIZING, message="Server is starting up...")
model_manager = ModelManager()
app_pipelines: Application | None = None
background_tasks: Dict[str, Dict[str, Any]] = {}


# --- Логика управления фоновыми задачами ---

def update_task_progress(task_id: str, progress: float, stage: str, message: str):
    """Обновляет статус задачи."""
    if task_id in background_tasks:
        background_tasks[task_id]["progress"] = progress
        background_tasks[task_id]["stage"] = stage
        background_tasks[task_id]["message"] = message

def run_task_wrapper(task_id: str, target_func, **kwargs):
    """Обертка для выполнения задачи в фоне с обработкой ошибок."""
    try:
        background_tasks[task_id]["status"] = "processing"
        progress_callback = lambda p, s, m: update_task_progress(task_id, p, s, m)
        kwargs["progress_callback"] = progress_callback
        target_func(**kwargs)
        background_tasks[task_id]["status"] = "complete"
    except Exception as e:
        logger.error(f"ОШИБКА в задаче {task_id}: {e}", exc_info=True)
        background_tasks[task_id]["status"] = "failed"
        background_tasks[task_id]["message"] = f"Критическая ошибка: {e}"
        background_tasks[task_id]["stage"] = "Ошибка"


def start_task(target_func, background_tasks_runner: BackgroundTasks, **kwargs):
    """Запускает новую фоновую задачу и возвращает ее ID."""
    if SERVER_STATUS.status != ServerStateEnum.READY:
        raise HTTPException(status_code=503, detail=f"Server is not ready. Current state: {SERVER_STATUS.status}")
    if app_pipelines is None:
         raise HTTPException(status_code=500, detail="AI Pipelines are not initialized due to a startup error.")

    task_id = str(uuid.uuid4())
    background_tasks[task_id] = {
        "status": "queued", "progress": 0.0, "stage": "В очереди", "message": "Задача поставлена в очередь."
    }
    background_tasks_runner.add_task(run_task_wrapper, task_id, target_func, **kwargs)
    return TaskStatusResponse(task_id=task_id, **background_tasks[task_id])
