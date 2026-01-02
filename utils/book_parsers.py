import re
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Dict, Optional, Tuple


class BookParser:
    """Базовый интерфейс для парсеров книг."""

    def parse(self, file_path: Path) -> Tuple[Dict[int, Dict[int, str]], Optional[str], Optional[bytes], Optional[str]]:
        """
        Возвращает:
        1. Структуру {volume: {chapter: text}}
        2. Имя автора (если есть)
        3. Байты обложки (если есть)
        4. Название книги (если есть)
        """
        raise NotImplementedError


class EpubParser(BookParser):
    def parse(self, file_path: Path) -> Tuple[Dict[int, Dict[int, str]], Optional[str], Optional[bytes], Optional[str]]:
        book = epub.read_epub(str(file_path))

        # 1. Метаданные
        author = self._extract_metadata(book, 'creator')
        title = self._extract_metadata(book, 'title')
        cover_bytes = self._extract_cover(book)

        # 2. Текст (используем ToC)
        volumes = self._parse_content(book)

        return volumes, author, cover_bytes, title

    def _extract_metadata(self, book, meta_type: str) -> Optional[str]:
        try:
            # 'creator' = автор, 'title' = название
            meta = book.get_metadata('DC', meta_type)
            return meta[0][0] if meta else None
        except:
            return None

    def _extract_cover(self, book) -> Optional[bytes]:
        try:
            # Пытаемся найти item типа COVER
            cover_items = list(book.get_items_of_type(ebooklib.ITEM_COVER))
            if cover_items:
                return cover_items[0].get_content()

            # Fallback: ищем картинки в имени которых есть cover
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if 'cover' in item.get_name().lower():
                    return item.get_content()
        except:
            pass
        return None

    def _get_flat_toc_links(self, toc_items):
        """Рекурсивно разворачивает дерево ToC в плоский список."""
        links = []
        for item in toc_items:
            if isinstance(item, epub.Link):
                links.append(item)
            elif isinstance(item, (list, tuple)):
                links.extend(self._get_flat_toc_links(item))
            elif hasattr(item, 'children'):
                links.extend(self._get_flat_toc_links(item.children))
        return links

    def _parse_content(self, book) -> Dict[int, Dict[int, str]]:
        if not book.toc:
            # Fallback для книг без TOC: просто берем все документы подряд
            # (упрощенная логика, можно улучшить)
            return self._parse_content_linear(book)

        content_map = {item.file_name: item.get_content() for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
        volumes = {}

        flat_links = self._get_flat_toc_links(book.toc)

        current_vol = 1
        chapter_counter = 1

        for link in flat_links:
            href = link.href.split('#')[0]
            title = link.title

            # Пытаемся угадать том и главу из заголовка
            vol_match = re.search(r'(?:том|volume)\s*(\d+)', title, re.IGNORECASE)
            if vol_match:
                current_vol = int(vol_match.group(1))

            chap_match = re.search(r'(?:глава|chapter)\s*(\d+)', title, re.IGNORECASE)
            if chap_match:
                current_chap = int(chap_match.group(1))
            else:
                current_chap = chapter_counter
                chapter_counter += 1

            if href in content_map:
                soup = BeautifulSoup(content_map[href], 'html.parser')
                text = soup.get_text(separator='\n', strip=True)

                if not text:
                    continue

                if current_vol not in volumes:
                    volumes[current_vol] = {}

                if current_chap in volumes[current_vol]:
                    volumes[current_vol][current_chap] += f"\n\n{text}"
                else:
                    volumes[current_vol][current_chap] = text

        return volumes

    def _parse_content_linear(self, book):
        """Резервный метод для EPUB без оглавления."""
        volumes = {1: {}}
        chap_count = 1
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text = soup.get_text(separator='\n', strip=True)
            if len(text) > 100:  # Игнорируем совсем мелкие файлы
                volumes[1][chap_count] = text
                chap_count += 1
        return volumes


class TxtParser(BookParser):
    def parse(self, file_path: Path) -> Tuple[Dict[int, Dict[int, str]], Optional[str], Optional[bytes], Optional[str]]:
        full_text = file_path.read_text(encoding='utf-8')

        # Регулярка для поиска заголовков
        pattern = re.compile(
            r'^\s*(?=.*(?:том|volume|глава|chapter))(?:(том|volume)\s*(\d+))?\s*(?:(глава|chapter)\s*(\d+))?\s*$',
            re.IGNORECASE | re.MULTILINE
        )

        headers = list(pattern.finditer(full_text))
        volumes = {}

        if not headers:
            # Вся книга как одна глава
            return {1: {1: full_text}}, None, None, None

        content_splits = [full_text[h.end():(headers[i + 1].start() if i + 1 < len(headers) else None)]
                          for i, h in enumerate(headers)]

        # Пролог
        prologue = full_text[:headers[0].start()].strip()
        if prologue:
            content_splits[0] = f"ВВЕДЕНИЕ:\n{prologue}\n\n{content_splits[0]}"

        current_vol = 1

        for i, match in enumerate(headers):
            _, vol_num, _, chap_num = match.groups()

            if vol_num:
                current_vol = int(vol_num)

            c_num = int(chap_num) if chap_num else (i + 1)
            text = content_splits[i].strip()

            if text:
                if current_vol not in volumes:
                    volumes[current_vol] = {}
                volumes[current_vol][c_num] = text

        return volumes, None, None, None