import os
from sqlmodel import create_engine, Session, SQLModel
from pathlib import Path

# Путь к базе данных SQLite
DB_DIR = Path(__file__).parent.parent / "storage"
DB_DIR.mkdir(exist_ok=True)
DB_URL = f"sqlite:///{DB_DIR}/bookweaver.db"

engine = create_engine(DB_URL, echo=False)

def init_db():
    """Создает все таблицы в базе данных."""
    from core import data_models # Импортируем модели, чтобы SQLModel о них узнал
    SQLModel.metadata.create_all(engine)

def get_session():
    """Возвращает новую сессию базы данных."""
    return Session(engine)
