"""
Пайплайн для генерации кратких пересказов (тизеров и конспектов) для каждой главы книги.
"""
from __future__ import annotations
import logging
from typing import Optional, Callable

from core.project_context import ProjectContext
from core.data_models import ChapterSummary, RawChapterSummary
from pipelines import prompts
from services.model_manager import ModelManager
from utils import file_utils

# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)


class SummaryGenerationPipeline:
    def __init__(self, model_manager: ModelManager):  # <--- ИЗМЕНЕНИЕ
        self.model_manager = model_manager
        logger.info("✅ Пайплайн SummaryGenerationPipeline инициализирован.")

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Запускает процесс генерации пересказов для всех глав книги.
        """

        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        stage = "Подготовка"
        update_progress(0.0, stage, f"Запуск генерации пересказов для книги '{context.book_name}'")

        try:
            summary_archive = context.load_summary_archive()
            summary_archive_path = context.get_summary_archive_path()
            update_progress(0.05, stage, f"Загружен архив. Существующих пересказов: {len(summary_archive.summaries)}")

            all_chapters = file_utils.get_all_chapters(context.book_dir)
            if not all_chapters:
                update_progress(1.0, "Завершено", "В папке проекта не найдено глав для анализа.")
                return

            total_chapters = len(all_chapters)
            update_progress(0.1, stage, f"Найдено {total_chapters} глав для обработки.")
            processed_count = 0
            stage = "Обработка глав"

            llm_service = self.model_manager.get_llm_service('character_analyzer')

            for i, (vol_path, chap_path) in enumerate(all_chapters):
                progress = 0.1 + (i / total_chapters) * 0.9

                vol_name = vol_path.name
                chap_name = chap_path.stem
                vol_num = int(vol_name.split('_')[-1])
                chap_num = int(chap_name.split('_')[-1])
                chapter_id = f"vol_{vol_num}_chap_{chap_num}"

                # Сообщение о текущей главе выводим через логгер, а не на фронт, чтобы не спамить
                logger.info(f"Обработка главы [{i + 1}/{total_chapters}]: {chap_path.name}")

                if chapter_id in summary_archive.summaries:
                    # Это тоже логируем, пользователю это видеть не обязательно
                    logger.info(f"Пересказ для главы {chapter_id} уже существует. Пропуск.")
                    continue

                try:
                    update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: генерация пересказа...")
                    chapter_context = ProjectContext(context.book_name, vol_num, chap_num)
                    prompt = prompts.format_summary_generation_prompt(chapter_context)

                    raw_summary_result = llm_service.call_for_pydantic(RawChapterSummary, prompt)

                    if raw_summary_result:
                        final_summary = ChapterSummary(
                            chapter_id=chapter_id,
                            teaser=raw_summary_result.teaser,
                            synopsis=raw_summary_result.synopsis
                        )

                        summary_archive.summaries[chapter_id] = final_summary
                        summary_archive.save(summary_archive_path)
                        logger.info(f"Пересказ для главы {chapter_id} успешно сгенерирован и сохранен.")
                        processed_count += 1
                    else:
                        update_progress(progress, stage,
                                        f"Глава {i + 1}/{total_chapters}: не удалось сгенерировать пересказ.")
                        logger.warning(f"Не удалось сгенерировать пересказ для главы {chapter_id}.")

                except FileNotFoundError:
                    error_msg = f"Файл главы не найден: {chap_path}"
                    update_progress(progress, "Ошибка", error_msg)
                    logger.error(error_msg)
                except Exception as e:
                    error_msg = f"Непредвиденная ошибка при обработке главы {chapter_id}: {e}"
                    update_progress(progress, "Ошибка", error_msg)
                    logger.error(error_msg, exc_info=True)

            stage = "Завершение"
            if processed_count > 0:
                final_message = f"Процесс завершен. Сгенерированы пересказы для {processed_count} новых глав."
            else:
                final_message = "Процесс завершен. Все главы уже имели пересказы."

            update_progress(1.0, stage, final_message)
            logger.info(f"Финальный архив сохранен в: {summary_archive_path}")

        except Exception as e:
            error_msg = f"Критическая ошибка в пайплайне генерации пересказов: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise
