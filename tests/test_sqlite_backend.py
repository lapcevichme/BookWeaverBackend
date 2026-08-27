import unittest
import tempfile
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from core.database import init_book_db, get_book_session
from core.book_repository import BookRepository
from core.data_models import Book, Chapter, Character
from api_server import create_app


class TestSQLiteBackend(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.book_id = "test_book_1"
        self.book_dir = self.temp_dir / self.book_id
        self.book_dir.mkdir(parents=True, exist_ok=True)

        init_book_db(self.book_dir)
        with get_book_session(self.book_dir) as session:
            book = Book(id=self.book_id, title="Test Book", author="Test Author")
            session.add(book)
            chap = Chapter(id="vol_1_chap_1", book_id=self.book_id, volume_num=1, chapter_num=1, title="Intro")
            session.add(chap)
            char = Character(book_id=self.book_id, name="Hero", description="Main character", spoiler_free_description="Hero")
            session.add(char)
            session.commit()

        self.repo = BookRepository(book_id=self.book_id)
        # Point repository to temp directory for testing
        self.repo.book_output_dir = self.book_dir

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_book_repository_get_book(self):
        book = self.repo.get_book()
        self.assertIsNotNone(book)
        self.assertEqual(book.title, "Test Book")
        self.assertEqual(book.author, "Test Author")

    def test_book_repository_chapters_and_characters(self):
        chapters = self.repo.get_all_chapters()
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].id, "vol_1_chap_1")

        characters = self.repo.get_characters()
        self.assertEqual(len(characters), 1)
        self.assertEqual(characters[0].name, "Hero")

    def test_sqlite_pragmas(self):
        with get_book_session(self.book_dir) as session:
            from sqlalchemy import text
            journal_mode = session.execute(text("PRAGMA journal_mode;")).scalar()
            busy_timeout = session.execute(text("PRAGMA busy_timeout;")).scalar()
            self.assertEqual(str(journal_mode).lower(), "wal")
            self.assertEqual(int(busy_timeout), 5000)

    def test_fastapi_app_endpoints(self):
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        response = client.get("/api/v1/projects/dashboard/summary")
        self.assertEqual(response.status_code, 200)

        response = client.get("/api/v1/projects/")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
