import json
import logging
from sqlmodel import create_engine, Session, SQLModel
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Включает WAL-режим, foreign keys и busy_timeout для высоких нагрузок на чтение/запись."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()
    except Exception as e:
        logger.warning(f"Failed to set PRAGMA for SQLite connection: {e}")


def pydantic_json_serializer(obj):
    """Кастомный сериализатор для JSON-колонок, понимающий Pydantic модели."""
    return json.dumps(obj, default=lambda o: o.model_dump(mode='json') if isinstance(o, BaseModel) else str(o), ensure_ascii=False)

def get_engine_for_book(book_path: Path):
    """Создает engine для конкретного файла базы данных книги."""
    db_path = book_path / "project.db"
    return create_engine(
        f"sqlite:///{db_path}", 
        connect_args={"check_same_thread": False},
        json_serializer=pydantic_json_serializer # <--- Вот она, магия
    )

def init_book_db(book_path: Path):
    """Инициализирует таблицы и применяет миграции для конкретной книги."""
    from core import data_models
    engine = get_engine_for_book(book_path)
    SQLModel.metadata.create_all(engine)
    
    # Simple migration: add storage_size_bytes if missing
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            # SQLite check for column existence
            res = conn.execute(text("PRAGMA table_info(book)"))
            columns = [row[1] for row in res]
            if "storage_size_bytes" not in columns:
                logger.info(f"Migration: Adding storage_size_bytes column to {book_path.name}")
                conn.execute(text("ALTER TABLE book ADD COLUMN storage_size_bytes INTEGER DEFAULT 0"))
                conn.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Migration failed for {book_path.name}: {e}")
        
    return engine

def get_book_session(book_path: Path) -> Session:
    """Возвращает сессию для конкретной книги."""
    engine = get_engine_for_book(book_path)
    return Session(engine, expire_on_commit=False)

def get_system_engine():
    import config
    from sqlmodel import create_engine
    db_path = config.OUTPUT_DIR / "system.db"
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

def init_system_db():
    from core import system_models
    engine = get_system_engine()
    SQLModel.metadata.create_all(engine)
    return engine

def get_system_session() -> Session:
    return Session(get_system_engine(), expire_on_commit=False)
