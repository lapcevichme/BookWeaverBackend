import zipfile
import shutil
import logging
from pathlib import Path
from typing import Set, List
import config
from core.project_context import ProjectContext

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class BookExporter:
    """
    Утилита для сборки всех необходимых артефактов проекта
    в единый портативный .bw (zip) архив для мобильного приложения.
    """

    def __init__(self, book_name: str):
        self.book_name = book_name
        self.context = ProjectContext(book_name=self.book_name)

        self.export_dir = config.BASE_DIR / "export"
        self.export_dir.mkdir(exist_ok=True)

        self.archive_path = self.export_dir / f"{self.book_name}.bw"
        self.temp_build_dir = self.export_dir / f"temp_{self.book_name}"

    def _cleanup(self):
        """Удаляет временную директорию сборки."""
        if self.temp_build_dir.exists():
            shutil.rmtree(self.temp_build_dir)

    def _copy_artifact(self, src_path: Path, dest_sub_dir: str = ""):
        """Копирует файл или директорию во временную папку сборки."""
        if not src_path.exists():
            logging.warning(f"Артефакт не найден, пропуск: {src_path}")
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
            scenario = chapter_context.load_scenario()
            if scenario:
                for entry in scenario.entries:
                    if entry.ambient and entry.ambient != "none":
                        used_ambients.add(entry.ambient)
        return used_ambients

    def _copy_ambients(self, ambient_ids: Set[str]):
        """Копирует аудиофайлы только используемых эмбиентов."""
        ambient_audio_dir = config.INPUT_DIR / "ambient_library"
        if not ambient_audio_dir.exists(): return

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
                logging.warning(f"Аудиофайл для эмбиента '{ambient_id}' не найден.")

    def export(self) -> Path | None:
        """
        Основной метод, выполняющий сборку и архивацию проекта.
        Возвращает путь к готовому архиву или None в случае ошибки.
        """
        logging.info(f"Начало экспорта проекта: '{self.book_name}'")
        self._cleanup()
        self.temp_build_dir.mkdir()
        archive_created = False

        try:
            # Этапы 1-4: Копирование артефактов, исходников, глав и эмбиентов
            self._copy_artifact(self.context.manifest_file)
            self._copy_artifact(self.context.character_archive_file)
            self._copy_artifact(self.context.summary_archive_file)
            self._copy_artifact(self.context.book_dir, dest_sub_dir="book_source")

            chapter_contexts = []
            for vol_num, chap_num in self.context.discover_chapters():
                chapter_context = ProjectContext(self.book_name, vol_num, chap_num)
                if chapter_context.scenario_file.exists():
                    chapter_contexts.append(chapter_context)
                    chapter_dest_dir = chapter_context.chapter_id
                    self._copy_artifact(chapter_context.scenario_file, dest_sub_dir=chapter_dest_dir)
                    self._copy_artifact(chapter_context.subtitles_file, dest_sub_dir=chapter_dest_dir)
                    self._copy_artifact(chapter_context.chapter_audio_dir, dest_sub_dir=chapter_dest_dir)

            used_ambients = self._collect_used_ambients(chapter_contexts)
            self._copy_ambients(used_ambients)

            # Этап 5: Создание ZIP-архива
            with zipfile.ZipFile(self.archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in self.temp_build_dir.rglob('*'):
                    arcname = file_path.relative_to(self.temp_build_dir)
                    zipf.write(file_path, arcname)

            archive_created = True
            logging.info(f"✅ Экспорт успешно завершен! Архив: {self.archive_path}")

        except Exception as e:
            logging.error(f"🛑 Ошибка во время экспорта: {e}", exc_info=True)
            return None
        finally:
            self._cleanup()

        return self.archive_path if archive_created else None
