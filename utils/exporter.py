import logging
import shutil
import zipfile
import uuid
import argparse 
from pathlib import Path
from typing import Set, List
from pydantic import ValidationError
import config
from core.project_context import ProjectContext
from utils.setup_logging import setup_logging

logger = logging.getLogger(__name__)


class BookExporter:
    """
    Утилита для сборки всех необходимых артефактов проекта
    в единый портативный .bw (zip) архив для мобильного приложения.
    """

    def __init__(self, book_name: str):
        self.book_name = book_name
        self.context = ProjectContext(book_name=self.book_name)
        self.export_dir = config.EXPORT_DIR
        self.archive_path = self.export_dir / f"{self.book_name}.bw"
        self.temp_build_dir = config.TEMP_DIR / f"temp_build_{self.book_name}_{uuid.uuid4().hex[:8]}"

        logger.debug(f"Инициализация экспортера:")
        logger.debug(f"  -> Книга: {self.book_name}")
        logger.debug(f"  -> Путь архива: {self.archive_path}")
        logger.debug(f"  -> Временная папка: {self.temp_build_dir}")

    def _cleanup(self):
        """Удаляет временную директорию сборки."""
        if self.temp_build_dir.exists():
            logger.debug(f"Очистка временной директории: {self.temp_build_dir}")
            shutil.rmtree(self.temp_build_dir)

    def _copy_artifact(self, src_path: Path, dest_sub_dir: str = ""):
        """Копирует файл или директорию во временную папку сборки."""
        if not src_path.exists():
            logger.warning(f"Артефакт не найден, пропуск: {src_path}")
            return

        destination = self.temp_build_dir / dest_sub_dir / src_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(src_path, destination)
        else:
            shutil.copy2(src_path, destination)

    def _collect_used_ambients(self, chapter_contexts: List[ProjectContext]) -> Set[str]:
        """Анализирует все сценарии глав и возвращает ID использованных эмбиентов."""
        used_ambients = set()
        for chapter_context in chapter_contexts:
            try:
                scenario = chapter_context.load_scenario()
                if scenario:
                    for entry in scenario.entries:
                        if entry.ambient and entry.ambient != "none":
                            used_ambients.add(entry.ambient)
            except ValidationError as e:
                logger.error(f"🛑 Ошибка валидации файла сценария для главы '{chapter_context.chapter_id}'. "
                             f"Возможно, он создан в старом формате (без ID). Глава будет пропущена. Ошибка: {e}")
            except Exception as e:
                logger.error(f"Не удалось обработать сценарий для главы '{chapter_context.chapter_id}': {e}")
        return used_ambients

    def _copy_ambients(self, ambient_ids: Set[str]):
        """Копирует аудиофайлы только используемых эмбиентов."""

        ambient_audio_dir = config.AMBIENT_DIR

        if not ambient_audio_dir.exists():
            logger.warning(f"Папка эмбиента не найдена, пропуск: {ambient_audio_dir}")
            return

        dest_dir = self.temp_build_dir / "ambient"
        dest_dir.mkdir(exist_ok=True)

        for ambient_id in ambient_ids:
            found = False
            for audio_file in ambient_audio_dir.glob(f"{ambient_id}.*"):
                if audio_file.is_file():
                    shutil.copy2(audio_file, dest_dir / audio_file.name)
                    found = True
                    break
            if not found:
                logger.warning(f"Аудиофайл для эмбиента '{ambient_id}' не найден в {ambient_audio_dir}.")

    def export(self) -> Path | None:
        """
        Основной метод, выполняющий сборку и архивацию проекта.
        Возвращает путь к готовому архиву или None в случае ошибки.
        """
        logger.info(f"Начало экспорта проекта: '{self.book_name}'")
        self._cleanup()  # Очистка на случай, если папка осталась от прошлого сбоя
        self.temp_build_dir.mkdir()
        archive_created = False

        try:
            logger.info("Сборка артефактов уровня книги...")
            self._copy_artifact(self.context.manifest_file)
            self._copy_artifact(self.context.character_archive_file)
            self._copy_artifact(self.context.summary_archive_file)
            self._copy_artifact(self.context.cover_file)

            self._copy_artifact(self.context.book_dir, dest_sub_dir="book_source")

            logger.info("Сборка артефактов по главам...")
            chapter_contexts = []
            for vol_num, chap_num in self.context.get_ordered_chapters():
                chapter_context = ProjectContext(self.book_name, vol_num, chap_num)
                chapter_contexts.append(chapter_context)

                chapter_dest_dir = chapter_context.chapter_id
                self._copy_artifact(chapter_context.scenario_file, dest_sub_dir=chapter_dest_dir)
                self._copy_artifact(chapter_context.subtitles_file, dest_sub_dir=chapter_dest_dir)
                self._copy_artifact(chapter_context.chapter_audio_dir, dest_sub_dir=chapter_dest_dir)

            logger.info("Сборка используемых эмбиент-файлов...")
            used_ambients = self._collect_used_ambients(chapter_contexts)
            self._copy_ambients(used_ambients)

            logger.info(f"Архивация временной папки в {self.archive_path.name}...")
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

    parser = argparse.ArgumentParser(
        description="Сборка проекта книги в единый .bw архив для дистрибуции."
    )
    parser.add_argument(
        "book_name",
        type=str,
        nargs='?',
        default=DEFAULT_TEST_BOOK,
        help=(f"Имя книги (имя папки). "
              f"Если не указано, используется: {DEFAULT_TEST_BOOK}")
    )

    args = parser.parse_args()

    book_to_export = args.book_name

    print(f"--- Запуск экспорта для: {book_to_export} ---")
    exporter = BookExporter(book_name=book_to_export)
    archive_file = exporter.export()

    if archive_file:
        print(f"--- Готово. Файл сохранен: {archive_file} ---")
    else:
        print(f"--- Ошибка. Экспорт не удался. Смотрите лог выше. ---")

