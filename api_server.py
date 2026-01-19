import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import config
from api import state
from api import tasks, projects, library, ai_tasks
from api.mobile import mobile_api_router
from api.models import ServerStateEnum
# from api.mobile import gen_router
from main import Application
from utils.setup_logging import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет инициализацией и завершением работы приложения."""
    try:
        setup_logging()
        logger.info("=" * 50)
        logger.info("BookWeaver Backend: Запуск...")
        logger.info("=" * 50)

        config.INPUT_DIR.mkdir(exist_ok=True)
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        config.VOICES_DIR.mkdir(exist_ok=True)
        config.AMBIENT_DIR.mkdir(exist_ok=True)
        (config.INPUT_DIR / "books").mkdir(exist_ok=True)

        logger.info("=" * 50)
        logger.info(f"🔑 Bearer Token:")
        logger.info(state.SERVER_TOKEN)
        logger.info("=" * 50)

        logger.info("Инициализация AI-пайплайнов...")

        state.app_pipelines = Application(model_manager=state.model_manager)
        state.SERVER_STATUS.status = ServerStateEnum.READY
        state.SERVER_STATUS.message = "AI pipelines initialized successfully."
        logger.info(f"✅ {state.SERVER_STATUS.message}")
    except Exception as e:
        error_message = f"КРИТИЧЕСКАЯ ОШИБКА при инициализации: {e}"
        state.SERVER_STATUS.status = ServerStateEnum.ERROR
        state.SERVER_STATUS.message = error_message
        logger.critical(error_message, exc_info=True)

    yield

    logger.info("Сервер завершает работу.")


# Создание и конфигурация FastAPI приложения

app = FastAPI(
    title="BookWeaver AI Backend",
    description="Локальный сервер для выполнения тяжелых AI-задач.",
    version="1.0.0",
    lifespan=lifespan
)

# Подключаем все роутеры
app.include_router(tasks.router)
app.include_router(projects.router)
app.include_router(library.router)
app.include_router(ai_tasks.router)
app.include_router(mobile_api_router.api_router)
app.include_router(mobile_api_router.static_router)
app.include_router(mobile_api_router.download_router)
# app.include_router(gen_router.router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "BookWeaver Backend работает. Перейдите на /docs для просмотра API."}


if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=config.SERVER_PORT, reload=True)
