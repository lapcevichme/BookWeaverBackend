import logging
import shutil
import zipfile
import uuid
import argparse
import json
from pathlib import Path
from typing import Set
import config
from core.project_context import ProjectContext
from utils.setup_logging import setup_logging
from utils.audio_merger import merge_chapter_audio

logger = logging.getLogger(__name__)


class BookExporter:
    """
    Утилита для сборки всех необходимых артефактов проекта
    в единый, оптимизированный и портативный .bw (zip) архив с гранулированной структурой данных.
    """

    def __init__(self, book_name: str):
        self.book_name = book_name
        self.context = ProjectContext(book_name=self.book_name)
        self.export_dir = config.EXPORT_DIR
        self.archive_path = self.export_dir / f"{self.book_name}.bw"
        self.temp_build_dir = config.TEMP_DIR / f"temp_build_{self.book_name}_{uuid.uuid4().hex[:8]}"

        logger.debug(f"Инициализация экспортера для книги '{self.book_name}'")
        logger.debug(f" -> Путь архива: {self.archive_path}")
        logger.debug(f" -> Временная папка: {self.temp_build_dir}")

    def _cleanup(self):
        """Удаляет временную директорию сборки."""
        if self.temp_build_dir.exists():
            logger.debug(f"Очистка временной директории: {self.temp_build_dir}")
            shutil.rmtree(self.temp_build_dir)

    def _write_json(self, data: dict, filename: str):
        """Записывает словарь в JSON-файл во временной директории."""
        path = self.temp_build_dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _copy_static_assets(self, used_ambients: Set[str]):
        """Копирует статичные ассеты, такие как обложка и эмбиент."""
        # Копирование обложки
        if self.context.cover_file.exists():
            shutil.copy2(self.context.cover_file, self.temp_build_dir / self.context.cover_file.name)

        # Копирование используемых эмбиентов
        ambient_audio_dir = config.AMBIENT_DIR
        dest_ambient_dir = self.temp_build_dir / "ambient"
        if not used_ambients or not ambient_audio_dir.exists():
            return
        dest_ambient_dir.mkdir(exist_ok=True)
        for ambient_id in used_ambients:
            found = False
            for audio_file in ambient_audio_dir.glob(f"{ambient_id}.*"):
                if audio_file.is_file():
                    shutil.copy2(audio_file, dest_ambient_dir / audio_file.name)
                    found = True
                    break
            if not found:
                logger.warning(f"Аудиофайл для эмбиента '{ambient_id}' не найден.")

    def export(self) -> Path | None:
        """
        Основной метод, выполняющий сборку и архивацию проекта в единый файл.
        """
        logger.info(f"Начало экспорта проекта: '{self.book_name}'")
        self._cleanup()
        self.temp_build_dir.mkdir(parents=True, exist_ok=True)
        archive_created = False

        try:
            # Загрузка и сохранение метаданных верхнего уровня
            logger.info("Экспорт метаданных уровня книги (manifest, characters, summaries)...")
            self._write_json(self.context.load_manifest().model_dump(mode='json'), "manifest.json")
            self._write_json(self.context.load_character_archive().model_dump(mode='json'), "characters.json")
            self._write_json(self.context.load_summary_archive().model_dump(mode='json'), "summaries.json")

            used_ambients = set()

            # Обработка каждой главы
            logger.info("Обработка глав...")
            chapter_contexts = [ProjectContext(self.book_name, vol, chap) for vol, chap in
                                self.context.get_ordered_chapters()]

            for chapter_context in chapter_contexts:
                logger.info(f" -> Глава: {chapter_context.chapter_id}")
                chapter_output_dir = self.temp_build_dir / "chapters" / chapter_context.chapter_id
                chapter_output_dir.mkdir(parents=True, exist_ok=True)

                scenario = chapter_context.load_scenario()
                if not scenario:
                    logger.warning(f"Сценарий для главы {chapter_context.chapter_id} не найден. Пропуск.")
                    continue

                for entry in scenario.entries:
                    if entry.ambient and entry.ambient != "none":
                        used_ambients.add(entry.ambient)

                subtitles_map = {}
                if chapter_context.subtitles_file.exists():
                    try:
                        sub_json = json.loads(chapter_context.subtitles_file.read_text("utf-8"))
                        if isinstance(sub_json, list):
                            subtitles_map = {item.get("id"): item for item in sub_json if item.get("id")}
                    except Exception as e:
                        logger.warning(f"Ошибка чтения файла субтитров для {chapter_context.chapter_id}: {e}")

                # Склейка аудио и генерация карты синхронизации
                output_audio_file = chapter_output_dir / "full_chapter.mp3"
                source_audio_dir = chapter_context.get_audio_output_dir()
                sync_map = []

                if source_audio_dir.exists() and any(f.is_file() for f in source_audio_dir.iterdir()):
                    _, sync_map = merge_chapter_audio(
                        scenario=scenario,
                        audio_dir=source_audio_dir,
                        output_file_path=output_audio_file,
                        subtitles_map=subtitles_map
                    )
                else:
                    logger.info(f"Аудио для главы {chapter_context.chapter_id} не найдено. Будет создана текстовая карта.")

                # Сохранение данных главы
                chapter_data = {
                    "scenario": scenario.model_dump(mode='json'),
                    "sync_map": sync_map
                }
                (chapter_output_dir / "chapter_data.json").write_text(
                    json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding='utf-8')

            # Копирование статичных ассетов
            self._copy_static_assets(used_ambients)

            # Архивирование
            logger.info(f"Архивация проекта в {self.archive_path.name}...")
            with zipfile.ZipFile(self.archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in self.temp_build_dir.rglob('*'):
                    arcname = file_path.relative_to(self.temp_build_dir)
                    zipf.write(file_path, arcname)

            archive_created = True
            logger.info(f"✅ Экспорт успешно завершен! Архив: {self.archive_path}")

        except Exception as e:
            logger.error(f"🛑 Ошибка во время экспорта: {e}", exc_info=True)
            return None
        finally:
            self._cleanup()

        return self.archive_path if archive_created else None


if __name__ == '__main__':
    setup_logging()
    DEFAULT_TEST_BOOK = "kapitanskaya-dochka"
    parser = argparse.ArgumentParser(description="Сборка проекта книги в единый .bw архив для дистрибуции.")
    parser.add_argument(
        "book_name",
        type=str,
        nargs='?',
        default=DEFAULT_TEST_BOOK,
        help=f"Имя книги (имя папки). По умолчанию: {DEFAULT_TEST_BOOK}"
    )
    args = parser.parse_args()
    print(f"--- Запуск экспорта для: {args.book_name} ---")
    exporter = BookExporter(book_name=args.book_name)
    archive_file = exporter.export()
    if archive_file:
        print(f"--- Готово. Файл сохранен: {archive_file} ---")
    else:
        print(f"--- Ошибка. Экспорт не удался. Смотрите лог выше. ---")
