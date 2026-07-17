"""
Класс-контекст, управляющий всеми путями и параметрами для конкретной книги.
Теперь управляет и подключением к базе данных этой книги.
"""
from __future__ import annotations
from pathlib import Path
from typing import Tuple, List, Optional
from sqlmodel import Session, select
import config
from core.database import get_book_session, init_book_db
from core.data_models import Scenario, CharacterArchive, ChapterSummaryArchive, BookManifest, Book, Chapter, Character, ScenarioEntry, ChapterSummary
from utils import file_utils


class ProjectContext:
    def __init__(self, book_name: str, volume_num: int | None = None, chapter_num: int | None = None):
        self.book_name = book_name
        self.volume_num = volume_num
        self.chapter_num = chapter_num
        self.book_id = book_name

        # --- Базовые пути ---
        self.book_dir = config.INPUT_DIR / config.BOOKS_DIR_NAME / self.book_name
        self.book_output_dir = config.OUTPUT_DIR / self.book_name

        # --- Пути к файлам (Legacy/Assets) ---
        self.manifest_file = self.book_output_dir / "manifest.json"
        self.character_archive_file = self.book_output_dir / "character_archive.json"
        self.summary_archive_file = self.book_output_dir / "chapter_summaries.json"
        self.cover_file = self.book_output_dir / "cover.jpg"
        self.images_dir = self.book_output_dir / "images"

        # --- Идентификаторы главы ---
        if volume_num is not None and chapter_num is not None:
            self.chapter_id = f"vol_{volume_num}_chap_{chapter_num}"
            self.chapter_output_dir = self.book_output_dir / self.chapter_id
            
            # Текстовые файлы
            md_path = self.book_dir / f"vol_{volume_num}" / f"chapter_{chapter_num}.md"
            txt_path = self.book_dir / f"vol_{volume_num}" / f"chapter_{chapter_num}.txt"
            self.chapter_file = md_path if md_path.exists() else txt_path
            
            self.scenario_file = self.chapter_output_dir / "scenario.json"
            self.subtitles_file = self.chapter_output_dir / "subtitles.json"
            self.chapter_audio_dir = self.chapter_output_dir / "audio"
            
            # Кэши
            self.raw_scenario_cache_file = self.chapter_output_dir / "cache_raw_scenario.json"
            self.ambient_cache_file = self.chapter_output_dir / "cache_ambient.json"

    def get_session(self) -> Session:
        """Возвращает сессию для базы данных этой конкретной книги."""
        self.book_output_dir.mkdir(parents=True, exist_ok=True)
        # Инициализируем БД, если файла еще нет
        if not (self.book_output_dir / "project.db").exists():
            init_book_db(self.book_output_dir)
        return get_book_session(self.book_output_dir)

    def load_book(self) -> Book | None:
        """Загружает метаданные книги из её БД."""
        with self.get_session() as session:
            return session.get(Book, self.book_id)

    def load_chapter(self) -> Chapter | None:
        """Загружает главу из БД книги."""
        if not hasattr(self, 'chapter_id'): return None
        with self.get_session() as session:
            return session.get(Chapter, self.chapter_id)

    def load_scenario_entries(self) -> List[ScenarioEntry]:
        """Загружает записи сценария из БД книги."""
        if not hasattr(self, 'chapter_id'): return []
        with self.get_session() as session:
            statement = select(ScenarioEntry).where(ScenarioEntry.chapter_id == self.chapter_id).order_by(ScenarioEntry.order_index)
            return session.exec(statement).all()

    # --- Утилиты ---

    def ensure_dirs(self):
        """Создает все необходимые выходные директории."""
        self.book_output_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(self, 'chapter_output_dir'):
            self.chapter_output_dir.mkdir(parents=True, exist_ok=True)
            self.chapter_audio_dir.mkdir(parents=True, exist_ok=True)

    def check_chapter_status(self) -> dict:
        """Проверяет наличие артефактов главы."""
        if not hasattr(self, 'chapter_id'): return {}
        
        has_audio = False
        if self.chapter_audio_dir.exists():
            if any(self.chapter_audio_dir.iterdir()):
                has_audio = True

        # Сначала смотрим в БД
        db_chap = self.load_chapter()
        status = db_chap.status if db_chap else "none"

        return {
            "volume_num": self.volume_num,
            "chapter_num": self.chapter_num,
            "id": self.chapter_id,
            "status": status,
            "has_audio": has_audio
        }

    def get_chapter_text(self) -> str:
        """Загружает текст главы (с диска или из БД)."""
        # Пробуем из БД
        db_chap = self.load_chapter()
        if db_chap and db_chap.raw_text:
            return db_chap.raw_text
            
        # Fallback на диск
        if not hasattr(self, 'chapter_file') or not self.chapter_file.exists():
            raise FileNotFoundError(f"Файл главы не найден: {self.book_name} {self.chapter_id}")
        return self.chapter_file.read_text("utf-8")

    # --- Legacy (пока используются в пайплайнах) ---
    def load_manifest(self) -> BookManifest:
        return BookManifest.load(self.manifest_file)
    def load_character_archive(self) -> CharacterArchive:
        return CharacterArchive.load(self.character_archive_file)
    def load_summary_archive(self) -> ChapterSummaryArchive:
        return ChapterSummaryArchive.load(self.summary_archive_file)
    def load_scenario(self) -> Scenario | None:
        if not hasattr(self, 'scenario_file'): return None
        try: return Scenario.load(self.scenario_file)
        except: return None

    def get_audio_output_dir(self) -> Path:
        return self.chapter_audio_dir
    def get_voice_path(self, voice_id: str) -> Path:
        return config.VOICES_DIR / voice_id / "reference.wav"
    def get_subtitles_file(self) -> Path:
        return self.subtitles_file
    def get_character_archive_path(self) -> Path:
        return self.character_archive_file
    def get_summary_archive_path(self) -> Path:
        return self.summary_archive_file

    def get_ordered_chapters(self) -> List[Tuple[int, int]]:
        chapter_paths = file_utils.get_all_chapters(self.book_dir)
        return [file_utils.parse_vol_chap_from_path(p) for p in chapter_paths]

    def get_chapter_text_path(self, volume_num: int, chapter_num: int) -> Path:
        md_path = self.book_dir / f"vol_{volume_num}" / f"chapter_{chapter_num}.md"
        if md_path.exists(): return md_path
        return self.book_dir / f"vol_{volume_num}" / f"chapter_{chapter_num}.txt"
