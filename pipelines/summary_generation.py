"""
Пайплайн для генерации кратких пересказов (тизеров и конспектов) для каждой главы книги.
"""
from __future__ import annotations
import logging
from typing import Optional, Callable
from pydantic import BaseModel

import config
from core.project_context import ProjectContext
from core.data_models import ChapterSummary, RawChapterSummary, VolumeSummary
from pipelines import prompts
from services.model_manager import ModelManager
from utils.metrics import metrics_collector

logger = logging.getLogger(__name__)


class SummaryGenerationPipeline:
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        logger.info("✅ Пайплайн SummaryGenerationPipeline (v2.0) инициализирован.")

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Запускает процесс генерации пересказов для всех глав книги.
        Автоматически создает Volume Summary для завершенных томов.
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

            ordered_chapters = context.get_ordered_chapters()
            if not ordered_chapters:
                update_progress(1.0, "Завершено", "В папке проекта не найдено глав для анализа.")
                return

            chapters_by_volume = {}
            for vol, chap in ordered_chapters:
                if vol not in chapters_by_volume:
                    chapters_by_volume[vol] = []
                chapters_by_volume[vol].append((vol, chap))

            llm_service = self.model_manager.get_llm_service('summary_generator')

            # ОБРАБОТКА ТОМОВ
            for vol_num in sorted(chapters_by_volume.keys()):
                vol_str = str(vol_num)

                all_chapters_ready = all(
                    f"vol_{v}_chap_{c}" in summary_archive.summaries
                    for v, c in chapters_by_volume[vol_num]
                )

                if all_chapters_ready and vol_str not in summary_archive.volume_summaries:
                    update_progress(0.1, "Анализ томов", f"Генерация глобального саммари для Тома {vol_num}...")

                    vol_chapter_summaries = []
                    for v, c in chapters_by_volume[vol_num]:
                        chap_id = f"vol_{v}_chap_{c}"
                        vol_chapter_summaries.append(f"[{chap_id}]: {summary_archive.summaries[chap_id].synopsis}")

                    vol_prompt = prompts.format_volume_summary_prompt(vol_num, vol_chapter_summaries)

                    class RawVolSum(BaseModel):
                        summary: str

                    res = llm_service.call_for_pydantic(RawVolSum, vol_prompt, prompt_type="volume_summary")
                    if res:
                        summary_archive.volume_summaries[vol_str] = VolumeSummary(
                            volume_num=vol_num,
                            summary=res.summary
                        )
                        summary_archive.save(summary_archive_path)
                        logger.info(f"✅ Создано глобальное саммари для Тома {vol_num}")

            # ОБРАБОТКА ОТДЕЛЬНЫХ ГЛАВ
            total_chapters = len(ordered_chapters)
            processed_count = 0
            stage = "Обработка глав"
            CONTEXT_WINDOW_SIZE = 3

            for i, (vol_num, chap_num) in enumerate(ordered_chapters):
                progress = 0.1 + (i / total_chapters) * 0.9
                chapter_id = f"vol_{vol_num}_chap_{chap_num}"
                
                metrics_collector.start_chapter(chapter_id)

                if chapter_id in summary_archive.summaries:
                    continue

                logger.info(f"Обработка главы [{i + 1}/{total_chapters}]: {chapter_id}")

                # Контекст из предыдущих глав
                previous_summaries = []
                start_index = max(0, i - CONTEXT_WINDOW_SIZE)
                prev_ids = [f"vol_{v}_chap_{c}" for v, c in ordered_chapters[start_index:i]]
                for pid in prev_ids:
                    if pid in summary_archive.summaries:
                        previous_summaries.append(summary_archive.summaries[pid])

                # Контекст предыдущего тома
                prev_volume_summary_text = None
                if vol_num > 1:
                    prev_vol_str = str(vol_num - 1)
                    if prev_vol_str in summary_archive.volume_summaries:
                        prev_volume_summary_text = summary_archive.volume_summaries[prev_vol_str].summary

                try:
                    update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: генерация пересказа...")
                    chapter_context = ProjectContext(context.book_name, vol_num, chap_num)

                    prompt = prompts.format_summary_generation_prompt(
                        chapter_context,
                        previous_summaries,
                        prev_volume_summary=prev_volume_summary_text
                    )

                    raw_summary_result = llm_service.call_for_pydantic(RawChapterSummary, prompt, prompt_type="chapter_summary")

                    if raw_summary_result:
                        final_summary = ChapterSummary(
                            chapter_id=chapter_id,
                            teaser=raw_summary_result.teaser,
                            synopsis=raw_summary_result.synopsis
                        )
                        summary_archive.summaries[chapter_id] = final_summary
                        summary_archive.save(summary_archive_path)
                        processed_count += 1
                        metrics_collector.save_to_file(config.LOGS_DIR / "metrics.json")
                    else:
                        logger.warning(f"⚠️ Не удалось сгенерировать пересказ для главы {chapter_id}.")

                except Exception as e:
                    error_msg = f"❌ Ошибка при обработке главы {chapter_id}: {e}"
                    update_progress(progress, "Ошибка", error_msg)
                    logger.error(error_msg, exc_info=True)

            stage = "Завершение"
            if processed_count > 0:
                final_message = f"Процесс завершен. Сгенерированы пересказы для {processed_count} новых глав."
            else:
                final_message = "Процесс завершен. Все главы уже имели пересказы."

            update_progress(1.0, stage, final_message)

        except Exception as e:
            error_msg = f"❌ Критическая ошибка в пайплайне генерации пересказов: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise
