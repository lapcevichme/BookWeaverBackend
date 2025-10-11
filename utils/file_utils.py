import re
from pathlib import Path

def get_natural_sort_key(filename: str) -> list[int]:
    """
    Создает ключ для "естественной" сортировки строк с числами.
    Например: "chapter_10.txt" будет идти после "chapter_2.txt".
    """
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', filename)]


def get_all_chapters(book_path: Path) -> list[tuple[Path, Path]]:
    """
    Находит все главы во всех томах и возвращает отсортированный список.
    """
    all_chapters = []
    if not book_path.is_dir():
        return []

    volume_paths = sorted(
        [p for p in book_path.glob("vol_*") if p.is_dir()],
        key=lambda p: get_natural_sort_key(p.name)
    )
    for vol_path in volume_paths:
        chapter_paths = sorted(
            [p for p in vol_path.glob("chapter_*.txt") if p.is_file()],
            key=lambda p: get_natural_sort_key(p.name)
        )
        for chap_path in chapter_paths:
            all_chapters.append((vol_path, chap_path))
    return all_chapters