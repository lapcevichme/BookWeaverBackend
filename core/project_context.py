"""
Класс-контекст, управляющий всеми путями и параметрами для конкретной задачи.
Заменяет "динамическую" часть старого config.py.
"""
from __future__ import annotations
from pathlib import Path
from typing import Tuple, List
import config
from core.data_models import Scenario, CharacterArchive, ChapterSummaryArchive, BookManifest
from utils import file_utils


class ProjectContext:
    """
    Инкапсулирует все пути и данные, связанные с обработкой
    одной конкретной главы или целой книги.
    """

    def __init__(self, book_name: str, volume_num: int | None = None, chapter_num: int | None = None):
        """
        volume_num и chapter_num теперь необязательные.
        Это позволяет создавать контекст для всей книги (например, для анализа персонажей),
        не указывая конкретную главу.
        """
        self.book_name = book_name
        self.volume_num = volume_num
        self.chapter_num = chapter_num

        # --- Базовые пути ---
        self.book_dir = config.INPUT_DIR / config.BOOKS_DIR_NAME / self.book_name
        self.book_output_dir = config.OUTPUT_DIR / self.book_name

        # --- Пути к файлам-архивам уровня книги ---
        self.character_archive_file = self.book_output_dir / "character_archive.json"
        self.summary_archive_file = self.book_output_dir / "chapter_summaries.json"
        self.manifest_file = self.book_output_dir / "manifest.json"
        self.cover_file = self.book_output_dir / "cover.jpg"

        # --- Пути уровня главы (определяются, только если переданы номера) ---
        if volume_num is not None and chapter_num is not None:
            self.chapter_id = f"vol_{volume_num}_chap_{chapter_num}"
            self.chapter_output_dir = self.book_output_dir / self.chapter_id
            self.chapter_file = self.book_dir / f"vol_{volume_num}" / f"chapter_{chapter_num}.txt"
            self.scenario_file = self.chapter_output_dir / "scenario.json"
            self.subtitles_file = self.chapter_output_dir / "subtitles.json"
            self.chapter_audio_dir = self.chapter_output_dir / "audio"

            # Пути к кэш-файлам для отказоустойчивости
            self.raw_scenario_cache_file = self.chapter_output_dir / "cache_raw_scenario.json"
            self.ambient_cache_file = self.chapter_output_dir / "cache_ambient.json"
            # TODO: и это кэшировать
            # self.emotion_cache_file = self.chapter_output_dir / "cache_emotion.json"

    def check_chapter_status(self) -> dict:
        """
        Проверяет наличие ключевых артефактов для главы.
        Возвращает словарь со статусами.
        """
        if not hasattr(self, 'chapter_id'):
            return {}

        # Проверяем, существует ли хотя бы один аудиофайл в папке
        has_audio = False
        if self.chapter_audio_dir.exists():
            if any(self.chapter_audio_dir.iterdir()):
                has_audio = True

        return {
            "volume_num": self.volume_num,
            "chapter_num": self.chapter_num,
            "has_scenario": self.scenario_file.exists(),
            "has_subtitles": self.subtitles_file.exists(),
            "has_audio": has_audio
        }

    def ensure_dirs(self):
        """Создает все необходимые выходные директории для проекта."""
        self.book_output_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(self, 'chapter_output_dir'):
            self.chapter_output_dir.mkdir(parents=True, exist_ok=True)
            self.chapter_audio_dir.mkdir(parents=True, exist_ok=True)

    def get_character_archive_path(self) -> Path:
        """Возвращает путь к главному архиву персонажей для всей книги."""
        return self.character_archive_file

    def get_summary_archive_path(self) -> Path:
        """Возвращает путь к архиву пересказов для всей книги."""
        return self.summary_archive_file

    def get_chapter_text(self) -> str:
        """Загружает и возвращает текст указанной главы."""
        if not hasattr(self, 'chapter_file') or not self.chapter_file.exists():
            raise FileNotFoundError(
                f"Файл главы не был определен или не найден. Убедитесь, что volume_num и chapter_num были переданы.")
        return self.chapter_file.read_text("utf-8")

    def load_character_archive(self) -> CharacterArchive:
        """Загружает главный архив персонажей для книги."""
        return CharacterArchive.load(self.character_archive_file)

    def load_summary_archive(self) -> ChapterSummaryArchive:
        """Загружает архив пересказов для книги."""
        return ChapterSummaryArchive.load(self.summary_archive_file)

    def load_scenario(self) -> Scenario | None:
        """Загружает сценарий для главы, если он существует."""
        if not hasattr(self, 'scenario_file'):
            return None
        try:
            return Scenario.load(self.scenario_file)
        except FileNotFoundError:
            print(f"Информация: Файл сценария {self.scenario_file.name} еще не создан.")
            return None

    def load_manifest(self) -> BookManifest:
        """Загружает манифест книги, создавая его при необходимости."""
        return BookManifest.load(self.manifest_file)

    def get_audio_output_dir(self) -> Path:
        """Возвращает путь к папке для аудиофайлов главы."""
        if not hasattr(self, 'chapter_audio_dir'):
            raise AttributeError("Контекст не инициализирован для конкретной главы (отсутствует chapter_audio_dir).")
        return self.chapter_audio_dir

    def get_voice_path(self, voice_id: str) -> Path:
        """Возвращает путь к референсному WAV-файлу для указанного ID голоса."""
        return config.VOICES_DIR / voice_id / "reference.wav"

    def get_subtitles_file(self) -> Path:
        """Возвращает путь к файлу субтитров для главы."""
        if not hasattr(self, 'subtitles_file'):
            raise AttributeError("Контекст не инициализирован для конкретной главы (отсутствует subtitles_file).")
        return self.subtitles_file

    def get_ordered_chapters(self) -> List[Tuple[int, int]]:
        """
        Сканирует директорию книги, используя централизованную,
        правильно отсортированную логику из file_utils.
        Возвращает список кортежей (номер_тома, номер_главы).
        """
        # Получаем ПРАВИЛЬНО отсортированный список путей
        chapter_paths = file_utils.get_all_chapters(self.book_dir)

        # Преобразуем пути в кортежи (том, глава) с помощью централизованной функции
        chapters = [file_utils.parse_vol_chap_from_path(p) for p in chapter_paths]

        return chapters

    def get_chapter_text_path(self, volume_num: int, chapter_num: int) -> Path:
        """
        Конструирует и возвращает путь к текстовому файлу главы.
        """
        return self.book_dir / f"vol_{volume_num}" / f"chapter_{chapter_num}.txt"
