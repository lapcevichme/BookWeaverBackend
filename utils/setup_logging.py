import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logging():
    """
    Настраивает систему логирования для всего приложения.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    formatter = logging.Formatter(log_format)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        "bookweaver_backend.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(stdout_handler)
    logger.addHandler(file_handler)

    logging.info("Система логирования успешно настроена.")
