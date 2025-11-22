import re
import os
from pathlib import Path
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import shutil
from typing import Optional
import config
from core.data_models import BookManifest


class BookConverter:
    """
    Преобразует входной файл книги (epub, txt) в стандартную
    структуру проекта:
    - input/books/[book_name]/vol_x/chapter_y.txt
    - output/[book_name]/manifest.json
    - output/[book_name]/cover.jpg
    """

    def __init__(self, input_file: Path):
        if not input_file.exists():
            raise FileNotFoundError(f"Исходный файл книги не найден: {input_file}")

        self.input_file = input_file
        self.book_name = input_file.stem
        self.project_input_dir = config.INPUT_DIR / config.BOOKS_DIR_NAME / self.book_name
        self.project_output_dir = config.OUTPUT_DIR / self.book_name

        print(f"Инициализация конвертера для книги: '{self.book_name}'")
        print(f"  -> Исходный файл: {self.input_file.name}")
        print(f"  -> Папка для глав (input): {self.project_input_dir}")
        print(f"  -> Папка для метаданных (output): {self.project_output_dir}")

    def convert(self):
        """
        Главный метод, который определяет тип файла, запускает парсер
        и создает начальный манифест.
        """
        if self.project_input_dir.exists() or self.project_output_dir.exists():
            raise FileExistsError(f"Проект '{self.book_name}' уже существует (в input или output). "
                                  f"Удалите папки {self.project_input_dir} и {self.project_output_dir} и попробуйте снова.")

        self.project_input_dir.mkdir(parents=True)
        self.project_output_dir.mkdir(parents=True, exist_ok=True)

        file_extension = self.input_file.suffix.lower()
        extracted_author: Optional[str] = None

        try:
            if file_extension == '.epub':
                print("Обнаружен формат EPUB. Запуск парсера...")
                book = epub.read_epub(self.input_file)
                extracted_author = self._extract_epub_metadata(book)
                self._extract_epub_cover(book)
                self._convert_from_epub(book)

            elif file_extension == '.txt':
                print("Обнаружен формат TXT. Запуск парсера...")
                self._convert_from_txt()

            else:
                raise NotImplementedError(f"Формат {file_extension} пока не поддерживается.")

            self._create_initial_manifest(author=extracted_author)
            print(f"✅ Книга '{self.book_name}' успешно преобразована в проект.")

        except Exception as e:
            print(f"🛑 Произошла ошибка во время конвертации: {e}. Удаляю созданные папки...")
            shutil.rmtree(self.project_input_dir, ignore_errors=True)
            shutil.rmtree(self.project_output_dir, ignore_errors=True)
            raise e

    def _save_chapter(self, volume_num: int, chapter_num: int, content: str):
        """Сохраняет текст главы в нужный файл с улучшенной очисткой."""
        vol_dir = self.project_input_dir / f"vol_{volume_num}"
        vol_dir.mkdir(exist_ok=True)
        chapter_path = vol_dir / f"chapter_{chapter_num}.txt"

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        clean_content = "\n".join(lines)
        clean_content = re.sub(r'\n{3,}', '\n\n', clean_content)

        if clean_content:
            chapter_path.write_text(clean_content, encoding='utf-8')
            print(f"  -> Сохранена: Том {volume_num}, Глава {chapter_num}")

    def _convert_from_epub(self, book: epub.EpubBook):
        """Парсит EPUB-файл, используя оглавление (ToC)."""
        volumes = {}
        content_map = {item.file_name: item.get_content() for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
        current_volume = 1
        chapter_counter = 1

        if not book.toc:
            raise ValueError("В EPUB файле отсутствует оглавление (ToC). Невозможно надежно разделить главы.")

        flat_toc_links = self._get_flat_toc_links(book.toc)
        if not flat_toc_links:
            raise ValueError("Не удалось извлечь ни одной главы из оглавления EPUB (ToC плоское, но пустое).")

        for item in flat_toc_links:
            href = item.href.split('#')[0]
            title = item.title

            vol_match = re.search(r'(?:том|volume)\s*(\d+)', title, re.IGNORECASE)
            if vol_match:
                current_volume = int(vol_match.group(1))

            chap_match = re.search(r'(?:глава|chapter)\s*(\d+)', title, re.IGNORECASE)
            if chap_match:
                current_chapter = int(chap_match.group(1))
            else:
                current_chapter = chapter_counter
                chapter_counter += 1

            if href in content_map:
                soup = BeautifulSoup(content_map[href], 'html.parser')
                text = soup.get_text(separator='\n', strip=True)

                if text:
                    if current_volume not in volumes:
                        volumes[current_volume] = {}
                    if current_chapter in volumes[current_volume]:
                        volumes[current_volume][current_chapter] += f"\n\n{text}"
                    else:
                        volumes[current_volume][current_chapter] = text

        if not volumes:
            raise ValueError("Не удалось извлечь ни одной главы из оглавления EPUB.")

        for vol_num, chapters in volumes.items():
            for chap_num, content in chapters.items():
                self._save_chapter(vol_num, chap_num, content)

    def _convert_from_txt(self):
        """Разделяет TXT-файл на главы и тома."""
        full_text = self.input_file.read_text(encoding='utf-8')
        pattern = re.compile(
            r'^\s*(?=.*(?:том|volume|глава|chapter))(?:(том|volume)\s*(\d+))?\s*(?:(глава|chapter)\s*(\d+))?\s*$',
            re.IGNORECASE | re.MULTILINE
        )

        headers = list(pattern.finditer(full_text))
        if not headers:
            print("Предупреждение: не найдено заголовков глав. Вся книга будет сохранена как одна глава.")
            self._save_chapter(volume_num=1, chapter_num=1, content=full_text)
            return

        current_volume = 1
        content_splits = [full_text[h.end():(headers[i + 1].start() if i + 1 < len(headers) else None)]
                          for i, h in enumerate(headers)]

        prologue = full_text[:headers[0].start()].strip()
        if prologue:
            content_splits[0] = f"{prologue}\n\n{content_splits[0]}"

        for i, header_match in enumerate(headers):
            vol_keyword, vol_num_str, chap_keyword, chap_num_str = header_match.groups()

            if vol_num_str:
                current_volume = int(vol_num_str)

            if chap_num_str:
                chapter_num = int(chap_num_str)
                content = content_splits[i].strip()
                if content:
                    self._save_chapter(current_volume, chapter_num, content)

    def _get_flat_toc_links(self, toc_items):
        """Рекурсивно возвращает 'плоский' список объектов epub.Link из ToC."""
        links = []
        for item in toc_items:
            if isinstance(item, epub.Link):
                links.append(item)
            elif isinstance(item, (list, tuple)):
                links.extend(self._get_flat_toc_links(item))
            elif hasattr(item, 'children'):
                links.extend(self._get_flat_toc_links(item.children))
        return links

    def _extract_epub_metadata(self, book: epub.EpubBook) -> Optional[str]:
        """Извлекает имя автора из метаданных DC:creator."""
        try:
            authors = book.get_metadata('DC', 'creator')
            if authors:
                author_name = authors[0][0]
                print(f"  -> Найден автор: {author_name}")
                return author_name
        except Exception as e:
            print(f"  -> Не удалось извлечь имя автора: {e}")
        return None

    def _extract_epub_cover(self, book: epub.EpubBook):
        """Находит, извлекает и сохраняет обложку книги в /output/.../cover.jpg."""
        try:
            cover_items = list(book.get_items_of_type(ebooklib.ITEM_COVER))
            if cover_items:
                cover_content = cover_items[0].get_content()
                cover_path = self.project_output_dir / "cover.jpg"
                cover_path.write_bytes(cover_content)
                print(f"  -> Обложка успешно сохранена в: {cover_path}")
            else:
                print("  -> Обложка в метаданных EPUB не найдена.")
        except Exception as e:
            print(f"  -> Не удалось извлечь обложку: {e}")

    def _create_initial_manifest(self, author: Optional[str] = None):
        """Создает первичный manifest.json в папке вывода."""
        manifest_path = self.project_output_dir / "manifest.json"

        if manifest_path.exists():
            print(f"  -> Манифест {manifest_path.name} уже существует, пропуск.")
            return

        print("  -> Создание первичного манифеста...")
        manifest = BookManifest(
            book_name=self.book_name,
            author=author
        )
        manifest.save(manifest_path)


if __name__ == '__main__':
    from pydantic import BaseModel, Field
    from typing import Dict
    from uuid import UUID


    class MockConfig:
        def __init__(self, root_dir: Path):
            self.BASE_DIR = root_dir
            self.INPUT_DIR = self.BASE_DIR / "input"
            self.OUTPUT_DIR = self.BASE_DIR / "output"
            self.BOOKS_DIR_NAME = "books"
            self.TEMP_DIR = self.BASE_DIR / "temp"
            self.EXPORT_DIR = self.BASE_DIR / "export"

            # Создаем папки
            self.INPUT_DIR.mkdir(parents=True, exist_ok=True)
            self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
            self.EXPORT_DIR.mkdir(parents=True, exist_ok=True)

            globals()['config'] = self


    class MockBookManifest(BaseModel):
        book_name: str
        author: Optional[str] = Field(None, description="Автор книги, извлеченный из метаданных.")
        character_voices: Dict[UUID, str] = Field(default_factory=dict)
        default_narrator_voice: str = Field("narrator_default")

        def save(self, path: Path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.model_dump_json(indent=2, exclude_defaults=True), encoding="utf-8")
            print(f"  -> (Mock) Манифест сохранен в: {path}")

        @classmethod
        def load(cls, path: Path) -> 'MockBookManifest':
            if not path.exists():
                raise FileNotFoundError(f"(Mock) Файл манифеста не найден: {path}")
            return cls.model_validate_json(path.read_text("utf-8"))


    import sys

    mock_core = type(sys)('core')
    mock_data_models = type(sys)('core.data_models')
    setattr(mock_data_models, 'BookManifest', MockBookManifest)
    setattr(mock_core, 'data_models', mock_data_models)
    sys.modules['core'] = mock_core
    sys.modules['core.data_models'] = mock_data_models

    mock_test_root = Path("./mock_converter_test_env")
    mock_config = MockConfig(mock_test_root)

    mock_source_files_dir = mock_config.INPUT_DIR / "source_files"

    if mock_test_root.exists():
        shutil.rmtree(mock_test_root)

    mock_source_files_dir.mkdir(parents=True, exist_ok=True)

    txt_content = """
    Это введение.

    Том 1
    Глава 1

    Текст первой главы первого тома.

    Глава 2

    Текст второй главы.

    Том 2 Глава 1

    Текст первой главы второго тома.
    """
    mock_txt_file = mock_source_files_dir / "my_test_book.txt"
    mock_txt_file.write_text(txt_content, encoding='utf-8')

    print("=" * 30)
    print("--- Конвертация TXT файла (Тест) ---")
    print("=" * 30)
    try:
        converter_txt = BookConverter(mock_txt_file)
        converter_txt.convert()

        print("\n--- Результат ---")
        print("Структура папок в:", mock_test_root)

        for root, dirs, files in os.walk(mock_test_root):
            level = root.replace(str(mock_test_root), '').count(os.sep)
            indent = ' ' * 4 * (level)
            print(f'{indent}{os.path.basename(root)}/')
            sub_indent = ' ' * 4 * (level + 1)
            for f in files:
                print(f'{sub_indent}{f}')

        manifest_path = mock_config.OUTPUT_DIR / "my_test_book" / "manifest.json"
        if manifest_path.exists():
            print(f"\nСодержимое {manifest_path.name}:")
            print(manifest_path.read_text())
        else:
            print(f"\n🛑 ОШИБКА: Манифест НЕ был создан по пути {manifest_path}")

    except Exception as e:
        print(f"🛑 Ошибка во время теста: {e}")
