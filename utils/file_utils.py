import re
from pathlib import Path
from typing import Tuple


def get_natural_sort_key(filename: str) -> list:
    """
    Создает ключ для "естественной" сортировки строк с числами.
    Это гарантирует, что 'item_10' идет после 'item_2', а не перед.
    """
    # Разделяем строку на текстовые и числовые части.
    # Например, "vol_10" -> ['', '10', '']
    parts = re.split(r'(\d+)', filename)
    return [int(text) if text.isdigit() else text.lower() for text in parts]


def parse_vol_chap_from_path(chap_path: Path) -> Tuple[int, int]:
    """
    ЦЕНТРАЛИЗОВАННАЯ ФУНКЦИЯ: Извлекает номер тома и главы из пути к файлу.
    Пример пути: .../vol_1/chapter_10.txt -> (1, 10)
    """
    vol_match = re.search(r"vol_(\d+)", str(chap_path.parent.name))
    chap_match = re.search(r"chapter_(\d+)", str(chap_path.name))

    if not vol_match or not chap_match:
        raise ValueError(f"Не удалось извлечь номер тома/главы из пути: {chap_path}")

    return int(vol_match.group(1)), int(chap_match.group(1))


def get_all_chapters(book_path: Path) -> list[Path]:
    """
    ЦЕНТРАЛИЗОВАННАЯ ФУНКЦИЯ: Находит все главы во всех томах
    и возвращает ЕДИНЫЙ отсортированный список путей к файлам глав.
    """
    if not book_path.is_dir():
        return []

    all_chapter_paths = list(book_path.glob("vol_*/chapter_*.txt"))
    all_chapter_paths.sort(key=lambda p: get_natural_sort_key(str(p)))

    return all_chapter_paths
