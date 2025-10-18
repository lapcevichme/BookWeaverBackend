import zipfile
import shutil
import logging
from pathlib import Path
from typing import Set
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

        # Создаем директорию для экспорта, если ее нет
        self.export_dir = config.BASE_DIR / "export"
        self.export_dir.mkdir(exist_ok=True)

        self.archive_path = self.export_dir / f"{self.book_name}.bw"
        self.temp_build_dir = self.export_dir / f"temp_{self.book_name}"

    def _cleanup(self):
        """Удаляет временную директорию сборки."""
        if self.temp_build_dir.exists():
            logging.info(f"Очистка временной директории: {self.temp_build_dir}")
            shutil.rmtree(self.temp_build_dir)

    def _copy_artifact(self, src_path: Path, dest_sub_dir: str = ""):
        """Копирует файл или директорию во временную папку сборки, сохраняя структуру."""
        if not src_path.exists():
            logging.warning(f"Артефакт не найден, пропуск: {src_path}")
            return

        destination = self.temp_build_dir / dest_sub_dir / src_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(src_path, destination)
        else:
            shutil.copy2(src_path, destination)
        logging.info(f"Скопирован: {src_path.name} -> {destination.relative_to(self.temp_build_dir)}")

    def _collect_used_ambients(self, chapter_contexts: list[ProjectContext]) -> Set[str]:
        """
        Анализирует все сценарии глав и возвращает множество ID использованных эмбиентов.
        """
        used_ambients = set()
        logging.info("Сбор информации об используемых эмбиентах...")
        for chapter_context in chapter_contexts:
            scenario = chapter_context.load_scenario()
            if scenario:
                for entry in scenario.entries:
                    if entry.ambient and entry.ambient != "none":
                        used_ambients.add(entry.ambient)
        logging.info(f"Найдено уникальных эмбиентов: {len(used_ambients)}")
        return used_ambients

    def _copy_ambients(self, ambient_ids: Set[str]):
        """Копирует только те аудиофайлы эмбиентов, которые используются в проекте."""
        ambient_audio_dir = config.INPUT_DIR / "ambient_library"  # Где лежат исходные звуки
        if not ambient_audio_dir.exists():
            logging.warning("Папка с эмбиентами не найдена, пропуск.")
            return

        dest_dir = self.temp_build_dir / "ambient"
        dest_dir.mkdir(exist_ok=True)

        for ambient_id in ambient_ids:
            # Ищем файл с любым расширением (mp3, wav, ogg)
            found = False
            for audio_file in ambient_audio_dir.glob(f"{ambient_id}.*"):
                if audio_file.is_file():
                    shutil.copy2(audio_file, dest_dir / audio_file.name)
                    logging.info(f"Скопирован эмбиент: {audio_file.name}")
                    found = True
                    break
            if not found:
                logging.warning(f"Аудиофайл для эмбиента '{ambient_id}' не найден.")

    def export(self):
        """Основной метод, выполняющий сборку и архивацию проекта."""
        logging.info(f"Начало экспорта проекта: '{self.book_name}'")
        self._cleanup()
        self.temp_build_dir.mkdir()

        try:
            # Копируем артефакты уровня книги
            logging.info("--- Этап 1: Копирование артефактов уровня книги ---")
            self._copy_artifact(self.context.manifest_file)
            self._copy_artifact(self.context.character_archive_file)
            self._copy_artifact(self.context.summary_archive_file)

            # Копируем исходный текст книги для "читалки"
            logging.info("--- Этап 2: Копирование исходного текста глав ---")
            self._copy_artifact(self.context.book_dir, dest_sub_dir="book_source")

            # 3Находим все главы и собираем информацию о них
            logging.info("--- Этап 3: Обработка глав ---")
            chapter_contexts = []
            for vol_num, chap_num in self.context.get_ordered_chapters():
                chapter_context = ProjectContext(self.book_name, vol_num, chap_num)
                # Обрабатываем только те главы, где есть готовый сценарий
                if chapter_context.scenario_file.exists():
                    chapter_contexts.append(chapter_context)
                    chapter_dest_dir = chapter_context.chapter_id
                    self._copy_artifact(chapter_context.scenario_file, dest_sub_dir=chapter_dest_dir)
                    self._copy_artifact(chapter_context.subtitles_file, dest_sub_dir=chapter_dest_dir)
                    self._copy_artifact(chapter_context.chapter_audio_dir, dest_sub_dir=chapter_dest_dir)
                else:
                    logging.warning(f"Пропуск главы {chapter_context.chapter_id}: отсутствует scenario.json")

            # Собираем и копируем только нужные эмбиенты
            logging.info("--- Этап 4: Сборка эмбиентов ---")
            used_ambients = self._collect_used_ambients(chapter_contexts)
            self._copy_ambients(used_ambients)

            # 5. Создаем ZIP-архив
            logging.info(f"--- Этап 5: Создание архива {self.archive_path.name} ---")
            with zipfile.ZipFile(self.archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in self.temp_build_dir.rglob('*'):
                    arcname = file_path.relative_to(self.temp_build_dir)
                    zipf.write(file_path, arcname)

            logging.info(f"✅ Экспорт успешно завершен! Архив сохранен в: {self.archive_path}")

        except Exception as e:
            logging.error(f"🛑 Произошла ошибка во время экспорта: {e}", exc_info=True)
        finally:
            self._cleanup()


if __name__ == '__main__':
    BOOK_TO_EXPORT = "kusuriya-no-hitorigoto-ln-novel"

    exporter = BookExporter(book_name=BOOK_TO_EXPORT)
    exporter.export()
