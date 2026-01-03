"""
Главный класс приложения (Facade), объединяющий все подсистемы:
Импорт -> Пайплайны (AI) -> Экспорт.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.model_manager import ModelManager
from core.project_context import ProjectContext

from pipelines.character_analysis import CharacterAnalysisPipeline
from pipelines.scenario_generation import ScenarioGenerationPipeline
from pipelines.summary_generation import SummaryGenerationPipeline
from pipelines.tts_pipeline import TTSPipeline
from pipelines.vc_pipeline import VCPipeline

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
        """Инициализирует все AI-пайплайны."""
        logger.info("🔧 Инициализация AI-пайплайнов...")
        self.character_pipeline = CharacterAnalysisPipeline(self.model_manager)
        self.scenario_pipeline = ScenarioGenerationPipeline(self.model_manager)
        self.summary_pipeline = SummaryGenerationPipeline(self.model_manager)
        self.tts_pipeline = TTSPipeline(self.model_manager)
        self.vc_pipeline = VCPipeline(self.model_manager)
        logger.info("✅ Пайплайны готовы к работе.")

    def import_book(self, file_path: Path) -> str:
        """
        Импортирует книгу из файла (EPUB/TXT), создает структуру проекта.
        Возвращает имя созданной папки (book_name).
        """
        logger.info(f"📚 Запуск импорта книги: {file_path}")
        converter = BookConverter(file_path)
        converter.run()
        return converter.book_name

    def run_full_cycle(self, book_name: str,
                       skip_summary: bool = False,
                       skip_chars: bool = False,
                       skip_scenario: bool = False):
        """
        Запускает последовательную генерацию: Саммари -> Персонажи -> Сценарии.
        """
        logger.info(f"🚀 Запуск полного цикла генерации для: {book_name}")
        ctx_book = ProjectContext(book_name)

        # 1: Саммари
        if not skip_summary:
            logger.info("\n=== ЭТАП 1: ГЕНЕРАЦИЯ ПЕРЕСКАЗОВ ===")
            self.summary_pipeline.run(ctx_book)

        # 2: Персонажи (нужны для ролей в сценариях)
        if not skip_chars:
            logger.info("\n=== ЭТАП 2: АНАЛИЗ ПЕРСОНАЖЕЙ ===")
            self.character_pipeline.run(book_name)

        # 3: Сценарии
        if not skip_scenario:
            logger.info("\n=== ЭТАП 3: ГЕНЕРАЦИЯ СЦЕНАРИЕВ ===")
            chapters = ctx_book.get_ordered_chapters()
            total = len(chapters)

            for i, (vol, chap) in enumerate(chapters, 1):
                chapter_ctx = ProjectContext(book_name, vol, chap)
                logger.info(f"🎬 Глава [{i}/{total}]: {chapter_ctx.chapter_id}")
                try:
                    self.scenario_pipeline.run(chapter_ctx)
                except Exception as e:
                    logger.error(f"❌ Ошибка в главе {chapter_ctx.chapter_id}: {e}")

        logger.info(f"\n✨ Полный цикл для '{book_name}' завершен!")

    def export_book(self, book_name: str) -> Optional[Path]:
        """
        Собирает готовый проект в .bw архив.
        """
        logger.info(f"📦 Запуск экспорта для: {book_name}")
        exporter = BookExporter(book_name)
        return exporter.export()