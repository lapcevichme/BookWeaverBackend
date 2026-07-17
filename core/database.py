from sqlmodel import create_engine, Session, SQLModel
from pathlib import Path
from typing import Optional

def get_engine_for_book(book_path: Path):
    """Создает engine для конкретного файла базы данных книги."""
    db_path = book_path / "project.db"
    # Для SQLite нужно разрешить параллельные запросы в разных потоках
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

def init_book_db(book_path: Path):
    """Инициализирует таблицы в базе данных конкретной книги."""
    from core import data_models
    engine = get_engine_for_book(book_path)
    SQLModel.metadata.create_all(engine)
    return engine

def get_book_session(book_path: Path) -> Session:
    """Возвращает сессию для конкретной книги."""
    engine = get_engine_for_book(book_path)
    return Session(engine)
