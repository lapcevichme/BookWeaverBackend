import logging
import sys
from logging.handlers import RotatingFileHandler
import config

# FIXME: Когда переполняется файл логов, название идет формата "*.log.{num}"
def setup_logging():
    """
    Настраивает систему логирования для всего приложения.
    """
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    formatter = logging.Formatter(log_format)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        config.LOG_FILE_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(stdout_handler)
    logger.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    logging.info(f"Система логирования настроена. Лог: {config.LOG_FILE_PATH}")