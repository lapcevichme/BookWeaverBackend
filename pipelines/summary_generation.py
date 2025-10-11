"""
Пайплайн для генерации кратких пересказов (тизеров и конспектов) для каждой главы книги.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Callable

from core.project_context import ProjectContext
from core.data_models import ChapterSummary
from pipelines import prompts
from utils import file_utils

if TYPE_CHECKING:
    from services.llm_service import LLMService


class SummaryGenerationPipeline:
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str], None]] = None):
        """
        Запускает процесс генерации пересказов для всех глав книги.
        """
        def update_progress(progress: float, message: str):
            if progress_callback:
                progress_callback(progress, message)
            print(message)

        update_progress(0.0, "\n" + "=" * 80)
        update_progress(0.0, f"🚀 ЗАПУСК ПАЙПЛАЙНА: Генерация пересказов для книги '{context.book_name}' 🚀")
        update_progress(0.0, "=" * 80)

        summary_archive = context.load_summary_archive()
        summary_archive_path = context.get_summary_archive_path()
        update_progress(0.05, f"Загружен существующий архив. Пересказов: {len(summary_archive.summaries)}")

        all_chapters = file_utils.get_all_chapters(context.book_dir)
        if not all_chapters:
            update_progress(1.0, "❌ КРИТИЧЕСКАЯ ОШИБКА: В указанной папке не найдено глав для анализа.")
            return

        total_chapters = len(all_chapters)
        update_progress(0.1, f"Найдено {total_chapters} глав для обработки.")
        processed_count = 0

        for i, (vol_path, chap_path) in enumerate(all_chapters):
            progress = 0.1 + (i / total_chapters) * 0.9

            vol_name = vol_path.name
            chap_name = chap_path.stem
            vol_num = int(vol_name.split('_')[-1])
            chap_num = int(chap_name.split('_')[-1])
            chapter_id = f"vol_{vol_num}_chap_{chap_num}"

            update_progress(progress, f"\n--- Обработка главы [{i + 1}/{total_chapters}]: {chap_path.name} ---")

            if chapter_id in summary_archive.summaries:
                update_progress(progress, "  -> ✅ Пересказ для этой главы уже существует. Пропускаю.")
                continue

            try:
                chapter_context = ProjectContext(context.book_name, vol_num, chap_num)
                prompt = prompts.format_summary_generation_prompt(chapter_context)
                summary_result = self.llm.call_for_pydantic(ChapterSummary, prompt)

                if summary_result:
                    summary_archive.summaries[chapter_id] = summary_result
                    summary_archive.save(summary_archive_path)
                    update_progress(progress, f"  -> ✅ Пересказ сгенерирован и сохранен.")
                    processed_count += 1
                else:
                    update_progress(progress, "  -> ⚠️ Не удалось сгенерировать пересказ для главы.")

            except FileNotFoundError:
                update_progress(progress, f"  -> ❌ ОШИБКА: Файл главы не найден: {chap_path}")
            except Exception as e:
                update_progress(progress, f"  -> ❌ КРИТИЧЕСКАЯ НЕПРЕДВИДЕННАЯ ОШИБКА: {e}")

        if processed_count > 0:
            final_message = f"\n🎉 Процесс завершен. Обработано {processed_count} новых глав."
        else:
            final_message = f"\n🎉 Процесс завершен. Новых глав для обработки не найдено."

        update_progress(1.0, final_message)
        update_progress(1.0, f"   -> Финальный архив: {summary_archive_path}")
