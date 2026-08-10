from typing import List, Optional, Dict, Any, Tuple
from sqlmodel import Session, select
from core.database import get_book_session, init_book_db
from core.data_models import Book, Chapter, Character, ScenarioEntry, ChapterSummary, CharacterArchive, ChapterSummaryArchive, BookManifest, ManifestMeta, ManifestChapterEntry, ManifestConfig
from core import path_manager
from pathlib import Path

class BookRepository:
    def __init__(self, book_id: str):
        self.book_id = book_id
        self.book_output_dir = path_manager.get_book_output_dir(book_id)

    def get_session(self) -> Session:
        """Возвращает сессию для базы данных этой конкретной книги."""
        # Всегда вызываем инициализацию, чтобы применились миграции (ALTER TABLE и т.д.)
        init_book_db(self.book_output_dir)
        return get_book_session(self.book_output_dir)

    def get_book(self) -> Optional[Book]:
        with self.get_session() as session:
            return session.get(Book, self.book_id)

    def get_chapter(self, chapter_id: str) -> Optional[Chapter]:
        with self.get_session() as session:
            return session.get(Chapter, chapter_id)

    def get_all_chapters(self) -> List[Chapter]:
        with self.get_session() as session:
            return session.exec(select(Chapter).where(Chapter.book_id == self.book_id).order_by(Chapter.order_index)).all()

    def update_chapter_status(self, chapter_id: str, status: str):
        with self.get_session() as session:
            db_chap = session.get(Chapter, chapter_id)
            if db_chap:
                db_chap.status = status
                session.add(db_chap)
                session.commit()

    def save_characters(self, characters: List[Character]):
        with self.get_session() as session:
            for char in characters:
                char.book_id = self.book_id
                session.merge(char)
            session.commit()

    def get_chapter_text(self, chapter_id: str) -> str:
        """Возвращает сырой текст главы из БД или из файла (с кэшированием в БД)."""
        db_chap = self.get_chapter(chapter_id)
        if db_chap and db_chap.raw_text:
            return db_chap.raw_text
            
        if not db_chap:
            raise ValueError(f"Глава {chapter_id} не найдена в БД.")

        path = path_manager.get_chapter_text_path(self.book_id, db_chap.volume_num, db_chap.chapter_num)
        if path.exists():
            text = path.read_text("utf-8")
            # Кэшируем текст в БД для будущего
            with self.get_session() as session:
                db_chap = session.get(Chapter, chapter_id)
                db_chap.raw_text = text
                session.add(db_chap)
                session.commit()
            return text
        raise FileNotFoundError(f"Текст главы {chapter_id} не найден на диске.")

    def get_characters(self) -> List[Character]:
        with self.get_session() as session:
            return session.exec(select(Character).where(Character.book_id == self.book_id)).all()

    def get_character_archive(self) -> CharacterArchive:
        chars = self.get_characters()
        processed = set()
        for c in chars:
            processed.update(c.chapter_mentions.keys())
        return CharacterArchive(characters=chars, processed_chapters=list(processed))

    def get_summary_archive(self) -> ChapterSummaryArchive:
        with self.get_session() as session:
            statement = select(ChapterSummary).join(Chapter).where(Chapter.book_id == self.book_id)
            summaries = session.exec(statement).all()
            return ChapterSummaryArchive(summaries={s.chapter_id: s for s in summaries})

    def get_scenario_entries(self, chapter_id: str) -> List[ScenarioEntry]:
        with self.get_session() as session:
            statement = select(ScenarioEntry).where(ScenarioEntry.chapter_id == chapter_id).order_by(ScenarioEntry.order_index)
            return session.exec(statement).all()

    def set_cache(self, chapter_id: str, name: str, data: Any):
        with self.get_session() as session:
            db_chap = session.get(Chapter, chapter_id)
            if db_chap:
                setattr(db_chap, f"cache_{name}", data)
                session.add(db_chap)
                session.commit()

    def get_cache(self, chapter_id: str, name: str) -> Optional[Any]:
        db_chap = self.get_chapter(chapter_id)
        if not db_chap: return None
        return getattr(db_chap, f"cache_{name}", None)

    def update_storage_size(self):
        """Рекурсивно считает размер папки книги и сохраняет в БД."""
        def get_dir_size(path: Path):
            return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        
        size = get_dir_size(self.book_output_dir)
        with self.get_session() as session:
            book = session.get(Book, self.book_id)
            if book:
                book.storage_size_bytes = size
                session.add(book)
                session.commit()
        return size

    def load_manifest(self) -> BookManifest:
        book = self.get_book()
        if not book:
            raise ValueError(f"Книга {self.book_id} не найдена в БД.")
            
        meta = ManifestMeta(
            title=book.title,
            author=book.author,
            description=book.description,
            tags=book.tags,
            status=book.status
        )
        
        db_chapters = self.get_all_chapters()
        structure = [
            ManifestChapterEntry(
                order=c.order_index,
                title=c.title or f"Глава {c.chapter_num}",
                vol=c.volume_num,
                chap=c.chapter_num,
                status=c.status,
                id=c.id
            ) for c in db_chapters
        ]
            
        return BookManifest(
            project_id=self.book_id,
            meta=meta,
            structure=structure,
            config=ManifestConfig(**book.config)
        )
