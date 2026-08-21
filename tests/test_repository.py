import unittest
import tempfile
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import init_book_db, get_book_session, init_system_db, get_system_session
from core.book_repository import BookRepository
from core.data_models import Book, Chapter, Character, ScenarioEntry, ChapterSummary
from core.system_models import SystemSetting, AmbientTrack, SFXTrack


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.book_id = "repo_test_book"
        self.book_dir = self.temp_dir / self.book_id
        self.book_dir.mkdir(parents=True, exist_ok=True)

        init_book_db(self.book_dir)
        with get_book_session(self.book_dir) as session:
            book = Book(id=self.book_id, title="Repo Test Book", author="Test Author")
            session.add(book)
            chap1 = Chapter(id="vol_1_chap_1", book_id=self.book_id, volume_num=1, chapter_num=1, title="Chapter One", raw_text="Hello world raw text")
            session.add(chap1)
            char1 = Character(book_id=self.book_id, name="Alice", description="Protagonist", spoiler_free_description="Alice")
            session.add(char1)
            summary1 = ChapterSummary(chapter_id="vol_1_chap_1", teaser="Chapter 1 Teaser", synopsis="Chapter 1 Synopsis")
            session.add(summary1)
            session.commit()

        self.repo = BookRepository(book_id=self.book_id)
        self.repo.book_output_dir = self.book_dir

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_book(self):
        book = self.repo.get_book()
        self.assertIsNotNone(book)
        self.assertEqual(book.title, "Repo Test Book")

    def test_get_chapter_and_text(self):
        chap = self.repo.get_chapter("vol_1_chap_1")
        self.assertIsNotNone(chap)
        self.assertEqual(chap.title, "Chapter One")

        text = self.repo.get_chapter_text("vol_1_chap_1")
        self.assertEqual(text, "Hello world raw text")

    def test_update_chapter_status(self):
        self.repo.update_chapter_status("vol_1_chap_1", "completed")
        chap = self.repo.get_chapter("vol_1_chap_1")
        self.assertEqual(chap.status, "completed")

    def test_characters_crud(self):
        chars = self.repo.get_characters()
        self.assertEqual(len(chars), 1)
        self.assertEqual(chars[0].name, "Alice")

        new_char = Character(book_id=self.book_id, name="Bob", description="Sidekick", spoiler_free_description="Bob")
        self.repo.save_characters([new_char])

        chars_updated = self.repo.get_characters()
        self.assertEqual(len(chars_updated), 2)

    def test_scenario_entries(self):
        with self.repo.get_session() as session:
            entry1 = ScenarioEntry(chapter_id="vol_1_chap_1", type="narration", text="Once upon a time", order_index=1)
            entry2 = ScenarioEntry(chapter_id="vol_1_chap_1", type="dialogue", text="Hi Alice", speaker_name="Bob", order_index=2)
            session.add(entry1)
            session.add(entry2)
            session.commit()

        entries = self.repo.get_scenario_entries("vol_1_chap_1")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].text, "Once upon a time")
        self.assertEqual(entries[1].text, "Hi Alice")

    def test_load_manifest(self):
        manifest = self.repo.load_manifest()
        self.assertEqual(manifest.project_id, self.book_id)
        self.assertEqual(manifest.meta.title, "Repo Test Book")
        self.assertEqual(len(manifest.structure), 1)

    def test_system_models(self):
        engine = init_system_db()
        self.assertIsNotNone(engine)
        with get_system_session() as session:
            setting = SystemSetting(key="test_key", value_json='"test_val"')
            session.merge(setting)
            session.commit()

            fetched = session.get(SystemSetting, "test_key")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.value, "test_val")


if __name__ == "__main__":
    unittest.main()
