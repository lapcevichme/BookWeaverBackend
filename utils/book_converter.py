import re
import os
from pathlib import Path
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import shutil


class BookConverter:
    """
    Преобразует входной файл книги (epub, txt) в стандартную
    структуру проекта: book_name/vol_x/chapter_y.txt.
    УМЕЕТ работать с несколькими томами.
    """

    def __init__(self, input_file: Path, books_root_dir: Path):
        self.input_file = input_file
        self.books_root_dir = books_root_dir
        self.book_name = input_file.stem
        self.project_dir = self.books_root_dir / self.book_name
        print(f"Инициализация конвертера для книги: '{self.book_name}'")

    def convert(self):
        """
        Главный метод, который определяет тип файла и запускает нужный парсер.
        """
        if self.project_dir.exists():
            raise FileExistsError(f"Проект '{self.book_name}' уже существует.")

        self.project_dir.mkdir(parents=True)

        file_extension = self.input_file.suffix.lower()
        try:
            if file_extension == '.epub':
                print("Обнаружен формат EPUB. Запуск парсера...")
                self._convert_from_epub()
            elif file_extension == '.txt':
                print("Обнаружен формат TXT. Запуск парсера...")
                self._convert_from_txt()
            else:
                raise NotImplementedError(f"Формат {file_extension} пока не поддерживается.")
            print(f"✅ Книга '{self.book_name}' успешно преобразована в проект.")
        except Exception as e:
            # Если что-то пошло не так, удаляем созданную папку проекта
            print(f"🛑 Произошла ошибка во время конвертации: {e}. Удаляю временные файлы...")
            shutil.rmtree(self.project_dir)
            # Передаем ошибку выше, чтобы API мог ее поймать
            raise e

    def _save_chapter(self, volume_num: int, chapter_num: int, content: str):
        """Сохраняет текст главы в нужный файл с улучшенной очисткой."""
        vol_dir = self.project_dir / f"vol_{volume_num}"
        vol_dir.mkdir(exist_ok=True)
        chapter_path = vol_dir / f"chapter_{chapter_num}.txt"

        # Убираем лишние пробелы в начале/конце каждой строки
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        clean_content = "\n".join(lines)
        # Заменяем 3+ переноса строки на 2 (оставляет пустую строку между абзацами)
        clean_content = re.sub(r'\n{3,}', '\n\n', clean_content)

        if clean_content:
            chapter_path.write_text(clean_content, encoding='utf-8')
            print(f"  -> Сохранена: Том {volume_num}, Глава {chapter_num}")

    def _convert_from_epub(self):
        """
        УЛУЧШЕНО: Парсит EPUB-файл, используя оглавление (ToC).
        Пытается извлечь номера томов и глав из названий.
        """
        book = epub.read_epub(self.input_file)

        volumes = {}
        content_map = {item.href: item.get_content() for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
        current_volume = 1
        chapter_counter = 1

        if not book.toc:
            raise ValueError("В EPUB файле отсутствует оглавление (ToC). Невозможно надежно разделить главы.")

        for item in book.toc:
            if isinstance(item, epub.Link):
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
        """
        УЛУЧШЕНО: Разделяет TXT-файл на главы и тома.
        """
        full_text = self.input_file.read_text(encoding='utf-8')

        # ИСПРАВЛЕНИЕ: Добавлена проверка (?=...), чтобы паттерн не срабатывал на пустые строки.
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


# Пример использования для отладки:
if __name__ == '__main__':
    mock_input_dir = Path("./mock_input")
    mock_books_dir = mock_input_dir / "books"

    if mock_input_dir.exists():
        shutil.rmtree(mock_input_dir)
    mock_books_dir.mkdir(parents=True, exist_ok=True)

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
    mock_txt_file = mock_input_dir / "my_multivolume_book.txt"
    mock_txt_file.write_text(txt_content, encoding='utf-8')

    print("--- Конвертация многотомного TXT файла ---")
    try:
        converter_txt = BookConverter(mock_txt_file, mock_books_dir)
        converter_txt.convert()

        project_path = mock_books_dir / "my_multivolume_book"
        print(f"\nПроект создан: {project_path}")
        print("Структура проекта:")
        for root, dirs, files in os.walk(project_path):
            level = root.replace(str(project_path), '').count(os.sep)
            indent = ' ' * 4 * (level)
            print(f'{indent}{os.path.basename(root)}/')
            sub_indent = ' ' * 4 * (level + 1)
            for f in files:
                print(f'{sub_indent}{f}')

    except Exception as e:
        print(f"Ошибка: {e}")

