import logging
import shutil
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
    в единый, оптимизированный и портативный .bw (zip) архив.
    """

    def __init__(self, book_name: str):
        self.book_name = book_name
        self.context = ProjectContext(book_name=self.book_name)
        self.export_dir = config.EXPORT_DIR
        self.archive_path = self.export_dir / f"{self.book_name}.bw"
        self.temp_build_dir = config.TEMP_DIR / f"temp_build_{self.book_name}_{uuid.uuid4().hex[:8]}"

        logger.debug(f"Инициализация экспортера для книги '{self.book_name}'")

    def _cleanup(self):
        """Удаляет временную директорию сборки."""
        if self.temp_build_dir.exists():
            shutil.rmtree(self.temp_build_dir)

    def _write_json(self, data: dict, filename: str):
        """Записывает словарь в JSON-файл во временной директории."""
        path = self.temp_build_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _copy_static_assets(self, used_ambients: Set[str]):
        """Копирует статичные ассеты (обложка, эмбиент)."""
        # Обложка
        if self.context.cover_file.exists():
            shutil.copy2(self.context.cover_file, self.temp_build_dir / self.context.cover_file.name)

        # Эмбиент
        ambient_audio_dir = config.AMBIENT_DIR
        dest_ambient_dir = self.temp_build_dir / "ambient"

        if used_ambients and ambient_audio_dir.exists():
            dest_ambient_dir.mkdir(exist_ok=True)
            for ambient_id in used_ambients:
                found = False
                for ext in ['.mp3', '.wav', '.ogg']:
                    src = ambient_audio_dir / f"{ambient_id}{ext}"
                    if src.exists():
                        shutil.copy2(src, dest_ambient_dir / src.name)
                        found = True
                        break
                if not found:
                    logger.warning(f"Аудиофайл для эмбиента '{ambient_id}' не найден в библиотеке.")

    def export(self) -> Path | None:
        """
        Основной метод сборки проекта.
        """
        logger.info(f"Начало экспорта проекта: '{self.book_name}'")
        self._cleanup()
        self.temp_build_dir.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Экспорт метаданных...")

            manifest = self.context.load_manifest()

            if self.context.character_archive_file.exists():
                shutil.copy2(self.context.character_archive_file, self.temp_build_dir / "characters.json")

            used_ambients = set()
            total_book_duration = 0

            content_dir = self.temp_build_dir / "content"
            content_dir.mkdir()

            chapters = self.context.get_ordered_chapters()
            logger.info(f"Обработка {len(chapters)} глав...")

            for vol, chap in chapters:
                chapter_ctx = ProjectContext(self.book_name, vol, chap)
                cid = chapter_ctx.chapter_id

                logger.info(f" -> Глава: {cid}")

                chapter_out_dir = content_dir / cid
                chapter_out_dir.mkdir()

                scenario = chapter_ctx.load_scenario()
                if not scenario:
                    logger.warning(f"Сценарий для {cid} не найден. Пропуск.")
                    continue

                for entry in scenario.entries:
                    if entry.ambient and entry.ambient != "none":
                        used_ambients.add(entry.ambient)

                subtitles_map = {}
                if chapter_ctx.subtitles_file.exists():
                    try:
                        sub_json = json.loads(chapter_ctx.subtitles_file.read_text("utf-8"))
                        if isinstance(sub_json, list):
                            subtitles_map = {item.get("audio_file").replace(".wav", ""): item for item in sub_json if
                                             item.get("audio_file")}
                    except Exception:
                        pass

                # Склейка
                full_audio_path = chapter_out_dir / "audio.mp3"
                source_audio_dir = chapter_ctx.get_audio_output_dir()

                duration_ms = 0
                sync_map = []

                if source_audio_dir.exists() and any(source_audio_dir.iterdir()):
                    duration_ms, sync_map = merge_chapter_audio(
                        scenario=scenario,
                        audio_dir=source_audio_dir,
                        output_file_path=full_audio_path,
                        subtitles_map=subtitles_map
                    )
                else:
                    logger.warning(f"Аудиофайлы для {cid} не найдены. Глава будет без звука.")

                total_book_duration += duration_ms

                # "легкий" JSON для мобилки
                chapter_data = {
                    "id": cid,
                    "duration_ms": duration_ms,
                    "scenario": scenario.model_dump(mode='json'),
                    "sync_map": sync_map
                }
                (chapter_out_dir / "data.json").write_text(
                    json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding='utf-8'
                )

            manifest.meta.total_duration_ms = total_book_duration
            for ch in manifest.structure:
                ch.path = f"content/{ch.id}/data.json"  # Путь для плеера

            self._write_json(manifest.model_dump(mode='json'), "manifest.json")

            self._copy_static_assets(used_ambients)

            # Архивация
            logger.info(f"Сжатие в {self.archive_path.name}...")
            shutil.make_archive(str(self.archive_path.with_suffix('')), 'zip', self.temp_build_dir)

            zip_path = self.archive_path.with_suffix('.zip')
            if zip_path.exists():
                shutil.move(str(zip_path), str(self.archive_path))

            logger.info(f"✅ Экспорт завершен: {self.archive_path}")
            return self.archive_path

        except Exception as e:
            logger.error(f"Экспорт провалился: {e}", exc_info=True)
            return None
        finally:
            self._cleanup()


if __name__ == '__main__':
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("book_name", type=str, help="Имя папки книги")
    args = parser.parse_args()

    exporter = BookExporter(args.book_name)
    exporter.export()