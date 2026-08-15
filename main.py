"""
Точка входа в приложение
Импорт -> Пайплайны -> Экспорт.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Callable

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.model_manager import ModelManager

from pipelines.character_analysis import CharacterAnalysisPipeline
from pipelines.scenario_generation import ScenarioGenerationPipeline
from pipelines.summary_generation import SummaryGenerationPipeline
from pipelines.tts_pipeline import TTSPipeline
from pipelines.image_generation_pipeline import (ImageGenerationPipeline)

from utils.book_converter import BookConverter
from utils.exporter import BookExporter

logger = logging.getLogger(__name__)


class Application:
    """
    Единая точка входа для всей бизнес-логики BookWeaver.
    Используется и CLI, и API сервером.
    """
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        self._initialize_pipelines()

    def _initialize_pipelines(self):
        logger.info("Инициализация AI-пайплайнов...")
        self.character_pipeline = CharacterAnalysisPipeline(self.model_manager)
        self.scenario_pipeline = ScenarioGenerationPipeline(self.model_manager)
        self.summary_pipeline = SummaryGenerationPipeline(self.model_manager)
        self.tts_pipeline = TTSPipeline(self.model_manager)
        self.image_pipeline = ImageGenerationPipeline()

        logger.info("Пайплайны готовы к работе.")

    def import_book(self, file_path: Path) -> str:
        logger.info(f"Запуск импорта книги: {file_path}")
        converter = BookConverter(file_path)
        converter.run()
        return converter.book_name

    def run_full_cycle(self, book_name: str,
                       skip_summary: bool = False,
                       skip_chars: bool = False,
                       skip_scenario: bool = False,
                       generate_images: bool = False,
                       progress_callback: Optional[Callable] = None):
        """
        Запускает последовательную генерацию: Саммари -> Персонажи -> Сценарии.
        """
        def update_progress(progress: float, stage: str, message: str):
            if progress_callback:
                progress_callback(progress, stage, message)
            logger.info(f"[{stage}] {message}")

        logger.info(f"Запуск полного цикла генерации для: {book_name}")
        from core.book_repository import BookRepository
        from core import path_manager
        
        repo = BookRepository(book_name)
        
        stages = []
        if not skip_summary: stages.append("summary")
        if not skip_chars: stages.append("chars")
        if generate_images: stages.append("images")
        if not skip_scenario: stages.append("scenario")
        
        total_stages = len(stages)
        current_stage_idx = 0

        if not skip_summary:
            current_stage_idx += 1
            update_progress((current_stage_idx - 1) / total_stages, "Summary", "Начало генерации пересказов...")
            self.summary_pipeline.run(book_name, progress_callback=lambda p, s, m: update_progress((current_stage_idx - 1 + p) / total_stages, s, m))

        if not skip_chars:
            current_stage_idx += 1
            update_progress((current_stage_idx - 1) / total_stages, "Characters", "Начало анализа персонажей...")
            self.character_pipeline.run(book_name, progress_callback=lambda p, s, m: update_progress((current_stage_idx - 1 + p) / total_stages, s, m))

        if generate_images:
            current_stage_idx += 1
            update_progress((current_stage_idx - 1) / total_stages, "Images", "Начало генерации иллюстраций...")
            self.image_pipeline.run(book_name=book_name)

        if not skip_scenario:
            current_stage_idx += 1
            db_chapters = repo.get_all_chapters()
            if not db_chapters:
                chapter_ids = path_manager.get_ordered_chapter_ids(book_name)
            else:
                chapter_ids = [(c.volume_num, c.chapter_num) for c in db_chapters]
            
            total_chaps = len(chapter_ids)

            for i, (vol, chap) in enumerate(chapter_ids, 1):
                chap_progress = i / total_chaps
                chapter_id = f"vol_{vol}_chap_{chap}"
                update_progress((current_stage_idx - 1 + chap_progress) / total_stages, "Scenario", f"Глава {i}/{total_chaps}: {chapter_id}")
                try:
                    self.scenario_pipeline.run(book_name=book_name, volume_num=vol, chapter_num=chap)
                except Exception as e:
                    logger.error(f"Ошибка в главе {chapter_id}: {e}")

        update_progress(1.0, "Завершено", f"Полный цикл для '{book_name}' успешно выполнен!")

    def export_book(self, book_name: str) -> Optional[Path]:
        logger.info(f"Запуск экспорта для: {book_name}")
        exporter = BookExporter(book_name)
        return exporter.export()