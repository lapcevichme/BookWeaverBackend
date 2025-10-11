import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logging():
    """
    Настраивает централизованную систему логирования для всего приложения.
    """
    # Получаем корневой логгер
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Устанавливаем базовый уровень логирования

    # Создаем форматтер
    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # 1. Обработчик для вывода в консоль (stdout)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    # 2. Обработчик для записи в файл с ротацией
    # Ротация: 5 файлов по 5MB. Когда один файл достигает 5MB, он переименовывается,
    # и создается новый. Хранятся последние 5 файлов.
    file_handler = RotatingFileHandler(
        "bookweaver_backend.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    # Удаляем все существующие обработчики, чтобы избежать дублирования
    if logger.hasHandlers():
        logger.handlers.clear()

    # Добавляем новые обработчики
    logger.addHandler(stdout_handler)
    logger.addHandler(file_handler)

    logging.info("Система логирования успешно настроена.")
