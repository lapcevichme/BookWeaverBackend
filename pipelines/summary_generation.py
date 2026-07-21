"""
Пайплайн для генерации пересказов глав и томов.
"""
import logging
from typing import List, Optional, Callable, Dict

import config
from core.data_models import ChapterSummary, RawChapterSummary, VolumeSummary, ChapterSummaryArchive
from core.project_context import ProjectContext
from pipelines import prompts
from services.model_manager import ModelManager
from utils.metrics import metrics_collector
from sqlmodel import select

logger = logging.getLogger(__name__)


class SummaryGenerationPipeline:
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        logger.info("✅ Пайплайн SummaryGenerationPipeline инициализирован.")

    def run(self, book_name: str, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        update_progress(0.0, "Подготовка", f"Запуск генерации пересказов для книги '{book_name}'")

        try:
            context = ProjectContext(book_name=book_name)
            llm_service = self.model_manager.get_llm_service('summary_generator')

            # Загружаем текущие саммари из БД
            summary_archive = context.load_summary_archive()
            ordered_chapters = context.get_ordered_chapters()

            if not ordered_chapters:
                update_progress(1.0, "Ошибка", "В проекте не найдено глав.")
                return

            # Группировка глав по томам для генерации глобальных саммари
            chapters_by_volume = {}
            for vol_num, chap_num in ordered_chapters:
                if vol_num not in chapters_by_volume:
                    chapters_by_volume[vol_num] = []
                chapters_by_volume[vol_num].append((vol_num, chap_num))

            # --- ОБРАБОТКА ОТДЕЛЬНЫХ ГЛАВ ---
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

                # Контекст предыдущего тома (пока упрощенно)
                prev_volume_summary_text = None

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
                        # Сохраняем в БД
                        with context.get_session() as session:
                            db_summary = session.get(ChapterSummary, chapter_id)
                            if not db_summary:
                                db_summary = ChapterSummary(chapter_id=chapter_id, teaser="", synopsis="")
                            
                            db_summary.teaser = raw_summary_result.teaser
                            db_summary.synopsis = raw_summary_result.synopsis
                            
                            session.add(db_summary)
                            session.commit()
                            
                        summary_archive.summaries[chapter_id] = db_summary
                        processed_count += 1
                        metrics_collector.save_to_file(config.LOGS_DIR / "metrics.json")
                    else:
                        logger.warning(f"⚠️ Не удалось сгенерировать пересказ для главы {chapter_id}.")

                except Exception as e:
                    logger.error(f"❌ Ошибка при обработке главы {chapter_id}: {e}", exc_info=True)

            update_progress(1.0, "Завершено", f"Генерация саммари завершена. Обработано глав: {processed_count}.")

        except Exception as e:
            logger.error(f"❌ Ошибка пайплайна: {e}", exc_info=True)
            raise
