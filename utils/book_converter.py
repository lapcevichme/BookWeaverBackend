import sys
import shutil
import re
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.project_context import ProjectContext
from utils.book_parsers import EpubParser, TxtParser
from utils.init_manifest import init_manifest
from utils.text_utils import cleanup_filename
from utils.setup_logging import setup_logging


class BookConverter:
    """
    Оркестратор импорта книги.
    """

    def __init__(self, input_file: Path):
        if not input_file.exists():
            raise FileNotFoundError(f"Файл не найден: {input_file}")

        self.input_file = input_file
        self.book_name = cleanup_filename(input_file.stem)
        self.context = ProjectContext(book_name=self.book_name)
        self.project_input_dir = self.context.book_dir
        self.project_output_dir = self.context.book_output_dir

    def run(self):
        print(f"🚀 Запуск конвертации: '{self.book_name}'")
        print(f"   📂 Файл: {self.input_file}")
        print(f"   🎯 Целевая папка Input: {self.project_input_dir}")

        # Проверка на существование старой папки INPUT
        if self.project_input_dir.exists():
            print(f"⚠️ Папка проекта {self.project_input_dir} уже существует.")
            shutil.rmtree(self.project_input_dir)
            print("   -> Старая папка удалена.")

        self.project_input_dir.mkdir(parents=True)

        # Выбор парсера
        suffix = self.input_file.suffix.lower()
        parser = None

        if suffix == '.epub':
            print("   -> Формат: EPUB")
            parser = EpubParser()
        elif suffix == '.txt':
            print("   -> Формат: TXT")
            parser = TxtParser()
        else:
            raise NotImplementedError(f"Формат {suffix} не поддерживается")

        # Парсинг
        try:
            volumes, author, cover_bytes, title = parser.parse(self.input_file)
            print(f"   -> Парсинг завершен.")
            print(f"      Томов: {len(volumes)}")
            if author: print(f"      Автор: {author}")
            if title: print(f"      Название: {title}")
        except Exception as e:
            print(f"🛑 Ошибка парсинга: {e}")
            if self.project_input_dir.exists():
                shutil.rmtree(self.project_input_dir)
            return

        # INPUT
        self._save_chapters(volumes)
        print(f"✅ Исходные тексты сохранены в {self.project_input_dir}")

        # OUTPUT
        self.project_output_dir.mkdir(parents=True, exist_ok=True)

        if cover_bytes:
            cover_path = self.context.cover_file
            cover_path.write_bytes(cover_bytes)
            print(f"   -> Обложка сохранена: {cover_path.name}")

        print("   -> Запуск генерации манифеста...")

        init_manifest(
            book_name=self.book_name,
            known_title=title,
            known_author=author
        )

        print(f"🎉 Готово! Проект '{self.book_name}' инициализирован.")

    def _save_chapters(self, volumes: dict):
        """Сохраняет текст по папкам vol_X/chapter_Y.txt"""
        for vol_num, chapters in volumes.items():
            vol_dir = self.context.book_dir / f"vol_{vol_num}"
            vol_dir.mkdir(exist_ok=True)

            for chap_num, text in chapters.items():
                clean_text = self._cleanup_text(text)
                if not clean_text:
                    continue

                file_path = vol_dir / f"chapter_{chap_num}.txt"
                file_path.write_text(clean_text, encoding='utf-8')

    def _cleanup_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        return re.sub(r'\n{3,}', '\n\n', text)


if __name__ == '__main__':
    import argparse

    setup_logging()

    parser = argparse.ArgumentParser(description="Конвертер книг в проект BookWeaver")
    parser.add_argument("file", type=Path, help="Путь к файлу книги (.epub или .txt)")
    args = parser.parse_args()

    converter = BookConverter(args.file)
    converter.run()
