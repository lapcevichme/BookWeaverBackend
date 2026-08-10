import logging
import threading
import time
import json
import uuid
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from sqlmodel import SQLModel, Field, create_engine, Session, select
import config

logger = logging.getLogger(__name__)

# --- Models ---

class TaskStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"

class TaskCancelledException(Exception):
    """Исключение для прерывания задачи пользователем."""
    pass

class TaskRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    book_id: str = Field(index=True)
    type: str
    status: str = Field(default=TaskStatus.QUEUED)
    progress: float = Field(default=0.0)
    stage: str = Field(default="В очереди")
    message: str = Field(default="Задача поставлена в очередь.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    kwargs_json: str = Field(default="{}")

    @property
    def kwargs(self) -> Dict[str, Any]:
        return json.loads(self.kwargs_json)

    @kwargs.setter
    def kwargs(self, value: Dict[str, Any]):
        self.kwargs_json = json.dumps(value)

# --- Database Setup ---

TASKS_DB_PATH = config.OUTPUT_DIR / "tasks.db"
engine = create_engine(f"sqlite:///{TASKS_DB_PATH}", connect_args={"check_same_thread": False})

def init_tasks_db():
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)

# --- Worker Logic ---

class TaskWorker:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._registry: Dict[str, Callable] = {}

    def register_handler(self, task_type: str, handler: Callable):
        self._registry[task_type] = handler

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TaskWorkerThread")
        self._thread.start()
        logger.info("🚀 Task Worker started.")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🛑 Task Worker stopped.")

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._process_next_task()
            except Exception as e:
                logger.error(f"Error in task worker loop: {e}", exc_info=True)
            time.sleep(1)

    def _process_next_task(self):
        with Session(engine) as session:
            statement = select(TaskRecord).where(TaskRecord.status == TaskStatus.QUEUED).order_by(TaskRecord.created_at)
            task = session.exec(statement).first()

            if not task:
                return

            # Mark as processing
            task.status = TaskStatus.PROCESSING
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
            session.refresh(task)

            handler = self._registry.get(task.type)
            if not handler:
                logger.error(f"No handler registered for task type: {task.type}")
                task.status = TaskStatus.FAILED
                task.message = f"Internal Error: No handler for {task.type}"
                session.add(task)
                session.commit()
                return

            logger.info(f"Executing task {task.id} (type: {task.type}) for book: {task.book_id}")

            def progress_callback(p, s, m):
                # Update task and check for control signals
                with Session(engine) as p_session:
                    p_task = p_session.get(TaskRecord, task.id)
                    if not p_task: return
                    
                    # 1. Обработка ОТМЕНЫ
                    if p_task.status == TaskStatus.CANCELLED:
                        raise TaskCancelledException(f"Task {task.id} was cancelled by user.")
                    
                    # 2. Обработка ПАУЗЫ (блокируем выполнение)
                    while p_task.status == TaskStatus.PAUSED:
                        time.sleep(1)
                        p_session.rollback() # Сбрасываем кэш сессии, чтобы увидеть изменения в БД
                        p_task = p_session.get(TaskRecord, task.id)
                        if not p_task or p_task.status == TaskStatus.CANCELLED:
                            raise TaskCancelledException(f"Task {task.id} was cancelled during pause.")

                    # 3. Обычное обновление прогресса
                    p_task.progress = p
                    p_task.stage = s
                    p_task.message = m
                    p_task.updated_at = datetime.utcnow()
                    p_session.add(p_task)
                    p_session.commit()

            try:
                handler(progress_callback=progress_callback, **task.kwargs)
                
                # Update book storage size if applicable
                try:
                    from core.book_repository import BookRepository
                    BookRepository(task.book_id).update_storage_size()
                except Exception:
                    pass

                with Session(engine) as f_session:
                    f_task = f_session.get(TaskRecord, task.id)
                    # Если статус уже CANCELLED (могло произойти в финальной итерации), не перезаписываем на COMPLETE
                    if f_task.status not in [TaskStatus.CANCELLED, TaskStatus.FAILED]:
                        f_task.status = TaskStatus.COMPLETE
                        f_task.progress = 1.0
                        f_task.message = "Задача успешно завершена."
                        f_task.updated_at = datetime.utcnow()
                        f_session.add(f_task)
                        f_session.commit()
                logger.info(f"✅ Task {task.id} complete.")
            except TaskCancelledException as e:
                logger.warning(f"🛑 Task {task.id} was cancelled: {e}")
                with Session(engine) as f_session:
                    f_task = f_session.get(TaskRecord, task.id)
                    if f_task:
                        f_task.status = TaskStatus.CANCELLED
                        f_task.message = "Задача отменена пользователем."
                        f_task.updated_at = datetime.utcnow()
                        f_session.add(f_task)
                        f_session.commit()
            except Exception as e:
                logger.error(f"❌ Task {task.id} failed: {e}", exc_info=True)
                with Session(engine) as f_session:
                    f_task = f_session.get(TaskRecord, task.id)
                    if f_task:
                        f_task.status = TaskStatus.FAILED
                        f_task.message = f"Error: {str(e)}"
                        f_task.updated_at = datetime.utcnow()
                        f_session.add(f_task)
                        f_session.commit()

# Global worker instance
worker = TaskWorker()

def add_task(book_id: str, task_type: str, **kwargs) -> str:
    with Session(engine) as session:
        task = TaskRecord(book_id=book_id, type=task_type)
        task.kwargs = kwargs
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.id

def get_task(task_id: str) -> Optional[TaskRecord]:
    with Session(engine) as session:
        return session.get(TaskRecord, task_id)

def list_tasks(limit: int = 50) -> list[TaskRecord]:
    with Session(engine) as session:
        return session.exec(select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)).all()

def cancel_task(task_id: str):
    with Session(engine) as session:
        task = session.get(TaskRecord, task_id)
        if task and task.status in [TaskStatus.QUEUED, TaskStatus.PROCESSING, TaskStatus.PAUSED]:
            task.status = TaskStatus.CANCELLED
            session.add(task)
            session.commit()

def pause_task(task_id: str):
    with Session(engine) as session:
        task = session.get(TaskRecord, task_id)
        if task and task.status == TaskStatus.PROCESSING:
            task.status = TaskStatus.PAUSED
            session.add(task)
            session.commit()

def resume_task(task_id: str):
    with Session(engine) as session:
        task = session.get(TaskRecord, task_id)
        if task and task.status == TaskStatus.PAUSED:
            task.status = TaskStatus.PROCESSING
            session.add(task)
            session.commit()
