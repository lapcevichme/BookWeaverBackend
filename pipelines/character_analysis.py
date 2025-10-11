"""
Пайплайн для анализа персонажей по всему тексту книги с использованием подхода с патчем.
"""
import json
import logging
from typing import List, Optional, Callable

from core.project_context import ProjectContext
from core.data_models import Character, CharacterArchive, CharacterReconResult, CharacterPatchList
from services.model_manager import ModelManager
from utils import file_utils
from pipelines import prompts

# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)


class CharacterAnalysisPipeline:
    """
    Класс-пайплайн, инкапсулирующий всю логику анализа персонажей в книге.
    Использует двухэтапный подход для эффективности:
    1. 'Разведка': Быстрый поиск релевантных персонажей в главе.
    2. 'Операция': Глубокий анализ и создание 'патча' для обновления архива.
    """

    def __init__(self, model_manager: ModelManager):  # <--- ИЗМЕНЕНИЕ
        self.model_manager = model_manager
        logger.info("✅ Пайплайн CharacterAnalysisPipeline инициализирован.")

    def run(self, book_name: str, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Запускает полный процесс анализа для книги, указанной в контексте.
        """
        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        stage = "Подготовка"
        update_progress(0.0, stage, f"Запуск анализа персонажей для книги '{book_name}'")

        try:
            context = ProjectContext(book_name=book_name)
            context.ensure_dirs()

            all_chapters = file_utils.get_all_chapters(context.book_dir)
            if not all_chapters:
                update_progress(1.0, "Ошибка", f"В проекте не найдено глав для анализа.")
                return

            master_archive = context.load_character_archive()
            update_progress(0.05, stage, f"Загружен архив. Существующих персонажей: {len(master_archive.characters)}")

            total_chapters = len(all_chapters)
            update_progress(0.1, stage, f"Найдено {total_chapters} глав. Начинаю обработку...")

            stage = "Анализ глав"
            for i, (vol_path, chap_path) in enumerate(all_chapters):
                progress = 0.1 + (i / total_chapters) * 0.9
                vol_num = int(vol_path.name.split('_')[-1])
                chap_num = int(chap_path.stem.split('_')[-1])
                chapter_id = f"vol_{vol_num}_chap_{chap_num}"

                logger.info(f"--- Обработка главы [{i+1}/{total_chapters}]: {chap_path.name} ---")

                if self._is_chapter_processed(master_archive, chapter_id):
                    logger.info(f"Глава {chapter_id} уже была проанализирована. Пропуск.")
                    continue

                chapter_text = chap_path.read_text("utf-8")
                if not chapter_text.strip():
                    logger.warning(f"Файл главы {chap_path.name} пуст. Пропуск.")
                    continue

                # --- ШАГ 1: "Умная разведка" ---
                update_progress(progress, stage, f"Глава {i+1}/{total_chapters}: Поиск упоминаний персонажей...")
                recon_result = self._perform_recon(master_archive, chapter_text)

                if not recon_result or (not recon_result.mentioned_existing_characters and not recon_result.newly_discovered_names):
                    logger.info("'Разведка' не нашла релевантных персонажей в главе. Пропуск.")
                    continue

                all_relevant_names = recon_result.mentioned_existing_characters + recon_result.newly_discovered_names
                logger.info(f"Найдено {len(all_relevant_names)} релевантных персонажей: {all_relevant_names}")

                # --- ШАГ 2: Фильтрация в Python ---
                relevant_chars = self._filter_archive(master_archive, recon_result.mentioned_existing_characters)
                relevant_chars_json = json.dumps([char.model_dump() for char in relevant_chars], ensure_ascii=False, indent=2)

                # --- ШАГ 3: "Операция" - запрос патча ---
                update_progress(progress, stage, f"Глава {i+1}/{total_chapters}: Глубокий анализ и сбор данных...")
                patch_list = self._perform_operation(relevant_chars_json, chapter_text, vol_num, chap_num)

                if not patch_list or not patch_list.patches:
                    logger.warning("LLM не вернула патчей. Считаем, что в главе не было значимых изменений.")
                    master_archive = self._add_empty_mentions(master_archive, recon_result.mentioned_existing_characters, chapter_id)
                    master_archive.save(context.get_character_archive_path())
                    logger.info("Добавлены пустые упоминания для найденных персонажей.")
                    continue

                # --- ШАГ 4: Применение патча ---
                update_progress(progress, stage, f"Глава {i+1}/{total_chapters}: Обновление архива персонажей...")
                master_archive = self._apply_patch(master_archive, patch_list, vol_num, chap_num)
                logger.info(f"Архив обновлен. Текущее кол-во персонажей: {len(master_archive.characters)}")
                master_archive.save(context.get_character_archive_path())

            stage = "Завершение"
            final_message = f"Анализ персонажей завершен. Всего в архиве: {len(master_archive.characters)}."
            update_progress(1.0, stage, final_message)
            logger.info(f"Итоговый архив сохранен в: {context.get_character_archive_path()}")

        except Exception as e:
            error_msg = f"Критическая ошибка в пайплайне анализа персонажей: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise

    def _perform_recon(self, archive: CharacterArchive, chapter_text: str) -> Optional[CharacterReconResult]:
        """Этап 'Разведки': быстрый поиск упоминаний."""
        fast_llm = self.model_manager.get_llm_service('character_analyzer')

        logger.info("Шаг 1: 'Умная разведка' - сопоставление с известными и поиск новых...")
        known_chars_for_recon = [
            {"name": char.name, "aliases": char.aliases}
            for char in archive.characters
        ]
        known_chars_json = json.dumps(known_chars_for_recon, ensure_ascii=False, indent=2)
        recon_prompt = prompts.format_character_recon_prompt(chapter_text, known_chars_json)
        return fast_llm.call_for_pydantic(CharacterReconResult, recon_prompt)

    def _perform_operation(self, relevant_chars_json: str, chapter_text: str, vol_num: int, chap_num: int) -> Optional[CharacterPatchList]:
        """Этап 'Операции': глубокий анализ и создание патча."""
        powerful_llm = self.model_manager.get_llm_service('scenario_generator')

        logger.info("Шаг 2: 'Операция' - запрос патча с изменениями...")
        patch_prompt = prompts.format_character_patch_prompt(
            relevant_chars_json, chapter_text, vol_num, chap_num
        )
        return powerful_llm.call_for_pydantic(CharacterPatchList, patch_prompt)


    def _is_chapter_processed(self, archive: CharacterArchive, chapter_id: str) -> bool:
        """Проверяет, есть ли упоминания главы в архиве."""
        for char in archive.characters:
            if chapter_id in char.chapter_mentions:
                return True
        return False

    def _filter_archive(self, archive: CharacterArchive, names: List[str]) -> List[Character]:
        """Возвращает полные данные персонажей из архива по списку канонических имен."""
        name_set = set(names)
        return [char for char in archive.characters if char.name in name_set]

    def _apply_patch(self, archive: CharacterArchive, patch_list: CharacterPatchList, vol: int, chap: int) -> CharacterArchive:
        """Применяет патчи к мастер-архиву."""
        logger.info(f"Применение {len(patch_list.patches)} патчей к архиву...")
        char_map = {char.name: char for char in archive.characters}
        for patch in patch_list.patches:
            existing_char = char_map.get(patch.name)
            if existing_char:
                update_data = patch.model_dump(exclude_unset=True)
                if 'chapter_mentions' in update_data and update_data['chapter_mentions']:
                    existing_char.chapter_mentions.update(update_data['chapter_mentions'])
                    del update_data['chapter_mentions']
                updated_char = existing_char.model_copy(update=update_data)
                char_map[patch.name] = updated_char
            else:
                new_char_data = {
                    "name": patch.name,
                    "description": patch.description or "Описание не предоставлено.",
                    "spoiler_free_description": patch.spoiler_free_description or "Описание не предоставлено.",
                    "aliases": patch.aliases or [],
                    "chapter_mentions": patch.chapter_mentions or {},
                    "first_mention": f"Том {vol}, Глава {chap}"
                }
                new_char = Character(**new_char_data)
                char_map[patch.name] = new_char
                logger.info(f"Обнаружен и добавлен новый персонаж: {patch.name}")
        archive.characters = list(char_map.values())
        return archive

    def _add_empty_mentions(self, archive: CharacterArchive, names_to_mention: List[str], chapter_id: str) -> CharacterArchive:
        """Добавляет 'пустое' упоминание для персонажей, которые были в главе, но для которых не было патча."""
        for char in archive.characters:
            if char.name in names_to_mention:
                if chapter_id not in char.chapter_mentions:
                    char.chapter_mentions[chapter_id] = "Персонаж упоминается в главе, но без значимых действий."
        return archive
