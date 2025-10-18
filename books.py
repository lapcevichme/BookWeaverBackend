import os
import re
import shutil
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub


class BookConverter:
    """
    Преобразует входной файл книги (epub, txt) в стандартную
    структуру проекта: book_name/vol_1/chapter_x.txt.
    """

    def __init__(self, input_file: Path, books_root_dir: Path):
        self.input_file = input_file
        self.books_root_dir = books_root_dir
        self.book_name = input_file.stem  # Имя книги из имени файла без расширения
        self.project_dir = self.books_root_dir / self.book_name

    def convert(self):
        """
        Главный метод, который определяет тип файла и запускает нужный парсер.
        """
        if self.project_dir.exists():
            raise FileExistsError(f"Проект '{self.book_name}' уже существует.")

        self.project_dir.mkdir(parents=True)

        file_extension = self.input_file.suffix.lower()
        if file_extension == '.epub':
            self._convert_from_epub()
        elif file_extension == '.txt':
            self._convert_from_txt()
        else:
            # Здесь можно будет добавить поддержку docx, pdf и др.
            raise NotImplementedError(f"Формат {file_extension} пока не поддерживается.")

        print(f"Книга '{self.book_name}' успешно преобразована в проект.")

    def _save_chapter(self, volume_num: int, chapter_num: int, content: str):
        """Сохраняет текст главы в нужный файл."""
        vol_dir = self.project_dir / f"vol_{volume_num}"
        vol_dir.mkdir(exist_ok=True)
        chapter_path = vol_dir / f"chapter_{chapter_num}.txt"

        # Очистка текста от лишних пробелов и пустых строк
        clean_content = "\n".join(line.strip() for line in content.splitlines() if line.strip())

        if clean_content:
            chapter_path.write_text(clean_content, encoding='utf-8')

    def _convert_from_epub(self):
        """Парсит EPUB-файл."""
        book = epub.read_epub(self.input_file)
        chapters = []

        # Извлекаем оглавление
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            # Извлекаем только видимый текст, без HTML-тегов
            text = soup.get_text(separator='\n', strip=True)
            if text and len(text) > 100:  # Простая эвристика, чтобы отсеять пустые страницы
                chapters.append(text)

        if not chapters:
            raise ValueError("Не удалось найти главы в EPUB файле.")

        # Сохраняем каждую главу
        for i, content in enumerate(chapters):
            self._save_chapter(volume_num=1, chapter_num=i + 1, content=content)

    def _convert_from_txt(self):
        """
        FIXED: Разделяет большой TXT-файл на главы, корректно обрабатывая пролог.
        """
        full_text = self.input_file.read_text(encoding='utf-8')

        pattern = r'^\s*(?:Глава|Chapter)\s+\d+\s*$'
        splits = re.split(pattern, full_text, flags=re.IGNORECASE | re.MULTILINE)

        # Если разделения не произошло (нет заголовков глав), то вся книга - одна глава.
        if len(splits) == 1:
            content = splits[0].strip()
            if content:
                self._save_chapter(volume_num=1, chapter_num=1, content=content)
            else:
                print("Предупреждение: входной TXT файл пуст или не содержит текста.")
            return

        # Если разделение произошло, первый элемент - это пролог.
        prologue = splits[0].strip()
        chapters = [s.strip() for s in splits[1:] if s and not s.isspace()]

        if not chapters:
            # Это может произойти, если есть пролог, но после заголовка главы нет текста.
            # В таком случае, сохраняем только пролог как одну главу.
            if prologue:
                self._save_chapter(volume_num=1, chapter_num=1, content=prologue)
            return

        # Присоединяем пролог к первой главе, если он есть
        if prologue:
            chapters[0] = f"{prologue}\n\n{chapters[0]}"

        for i, content in enumerate(chapters):
            self._save_chapter(volume_num=1, chapter_num=i + 1, content=content)


# Пример использования:
if __name__ == '__main__':
    # Создадим тестовые файлы
    mock_input_dir = Path("./mock_input")
    mock_books_dir = mock_input_dir / "books"

    # Очищаем предыдущие результаты, если они есть
    if mock_input_dir.exists():
        shutil.rmtree(mock_input_dir)

    mock_books_dir.mkdir(parents=True, exist_ok=True)

    # Тестовый TXT
    txt_content = """
    Это пролог или введение к книге.
    Здесь может быть какая-то предыстория.

    Глава 1

    Это первая глава. В ней что-то происходит.

    Глава 2

    Это вторая глава. Она следует за первой.
    """
    mock_txt_file = mock_input_dir / "my_book.txt"
    mock_txt_file.write_text(txt_content, encoding='utf-8')

    print("--- Конвертация TXT файла ---")
    try:
        converter_txt = BookConverter(mock_txt_file, mock_books_dir)
        converter_txt.convert()

        # Проверим, что создалось
        project_path = mock_books_dir / "my_book"
        vol_path = project_path / "vol_1"
        print(f"Проект создан: {project_path}")
        print(f"Содержимое тома 1: {os.listdir(vol_path)}")

        # Посмотрим содержимое файлов
        if (vol_path / "chapter_1.txt").exists():
            print("\n--- Содержимое Глава 1 ---")
            print((vol_path / "chapter_1.txt").read_text(encoding='utf-8'))

        if (vol_path / "chapter_2.txt").exists():
            print("\n--- Содержимое Глава 2 ---")
            print((vol_path / "chapter_2.txt").read_text(encoding='utf-8'))

    except Exception as e:
        print(f"Ошибка: {e}")
