"""
Пайплайн для анализа персонажей по всему тексту книги.
**ВЕРСИЯ 2.1 - Улучшенная логика применения патчей и валидация**
"""
import json
import logging
from typing import List, Optional, Callable
from uuid import UUID

from core.project_context import ProjectContext
from core.data_models import Character, CharacterArchive, CharacterReconResult, CharacterPatchList
from services.model_manager import ModelManager
from utils import file_utils
from pipelines import prompts

logger = logging.getLogger(__name__)


class CharacterAnalysisPipeline:
    """
    Класс-пайплайн, инкапсулирующий всю логику анализа персонажей в книге.
    Использует двухэтапный подход для эффективности:
    1. 'Разведка': Быстрый поиск релевантных персонажей в главе.
    2. 'Операция': Глубокий анализ и создание 'патча' для обновления архива.
    """

    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        logger.info("✅ Пайплайн CharacterAnalysisPipeline инициализирован.")

    def run(self, book_name: str, progress_callback: Optional[Callable[[float, str, str], None]] = None):
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
                update_progress(1.0, "Ошибка", "В проекте не найдено глав для анализа.")
                return

            master_archive = context.load_character_archive()
            update_progress(0.05, stage, f"Загружен архив. Существующих персонажей: {len(master_archive.characters)}")

            total_chapters = len(all_chapters)
            stage = "Анализ глав"
            for i, (vol_path, chap_path) in enumerate(all_chapters):
                progress = 0.1 + (i / total_chapters) * 0.9
                vol_num, chap_num = context.get_vol_chap_from_path(chap_path)
                chapter_id = f"vol_{vol_num}_chap_{chap_num}"
                logger.info(f"--- Обработка главы [{i + 1}/{total_chapters}]: {chap_path.name} ---")

                if self._is_chapter_processed(master_archive, chapter_id):
                    logger.info(f"Глава {chapter_id} уже была проанализирована. Пропуск.")
                    continue

                chapter_text = chap_path.read_text("utf-8")
                if not chapter_text.strip():
                    logger.warning(f"Файл главы {chap_path.name} пуст. Пропуск.")
                    continue

                update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: Поиск упоминаний...")
                recon_result = self._perform_recon(master_archive, chapter_text)
                if not recon_result or (
                        not recon_result.mentioned_existing_character_ids and not recon_result.newly_discovered_names):
                    logger.info("'Разведка' не нашла релевантных персонажей. Пропуск.")
                    continue

                logger.info(
                    f"Найдены ID: {recon_result.mentioned_existing_character_ids}, Новые имена: {recon_result.newly_discovered_names}")

                relevant_chars = self._filter_archive_by_ids(master_archive,
                                                             recon_result.mentioned_existing_character_ids)
                relevant_characters_json = json.dumps([char.model_dump(mode='json') for char in relevant_chars],
                                                      ensure_ascii=False, indent=2)

                update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: Глубокий анализ...")

                patch_list = self._perform_operation(
                    relevant_characters_json=relevant_characters_json,
                    newly_discovered_names=recon_result.newly_discovered_names,
                    chapter_text=chapter_text,
                    vol_num=vol_num,
                    chap_num=chap_num
                )
                if not patch_list or not patch_list.patches:
                    logger.warning("LLM не вернула патчей. Считаем, что в главе не было значимых изменений.")
                    master_archive = self._add_empty_mentions(master_archive,
                                                              recon_result.mentioned_existing_character_ids, chapter_id)
                else:
                    update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: Обновление архива...")
                    master_archive = self._apply_patch(master_archive, patch_list, vol_num, chap_num)

                master_archive.save(context.get_character_archive_path())
                logger.info(f"Архив обновлен. Текущее кол-во персонажей: {len(master_archive.characters)}")

            stage = "Завершение"
            update_progress(1.0, stage, f"Анализ завершен. Всего в архиве: {len(master_archive.characters)}.")

        except Exception as e:
            error_msg = f"Критическая ошибка в пайплайне анализа персонажей: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise

    def _perform_recon(self, archive: CharacterArchive, chapter_text: str) -> Optional[CharacterReconResult]:
        fast_llm = self.model_manager.get_llm_service('character_analyzer')
        logger.info("Шаг 1: 'Разведка' - сопоставление с известными и поиск новых...")
        known_chars_for_recon = [
            {"id": str(char.id), "name": char.name, "aliases": char.aliases}
            for char in archive.characters
        ]
        known_chars_json = json.dumps(known_chars_for_recon, ensure_ascii=False, indent=2)
        recon_prompt = prompts.format_character_recon_prompt(chapter_text, known_chars_json)
        return fast_llm.call_for_pydantic(CharacterReconResult, recon_prompt)

    def _perform_operation(
            self,
            relevant_characters_json: str,
            newly_discovered_names: List[str],
            chapter_text: str,
            vol_num: int,
            chap_num: int
    ) -> Optional[CharacterPatchList]:
        powerful_llm = self.model_manager.get_llm_service('scenario_generator')
        logger.info("Шаг 2: 'Операция' - запрос патча с изменениями...")
        patch_prompt = prompts.format_character_patch_prompt(
            relevant_chars_json=relevant_characters_json,
            newly_discovered_names=newly_discovered_names,
            chapter_text=chapter_text,
            volume=vol_num,
            chapter=chap_num
        )

        return powerful_llm.call_for_pydantic(CharacterPatchList, patch_prompt)

    def _is_chapter_processed(self, archive: CharacterArchive, chapter_id: str) -> bool:
        for char in archive.characters:
            if chapter_id in char.chapter_mentions:
                return True
        return False

    def _filter_archive_by_ids(self, archive: CharacterArchive, ids: List[UUID]) -> List[Character]:
        id_set = set(ids)
        return [char for char in archive.characters if char.id in id_set]

    def _apply_patch(self, archive: CharacterArchive, patch_list: CharacterPatchList, vol: int,
                     chap: int) -> CharacterArchive:
        logger.info(f"Применение {len(patch_list.patches)} патчей к архиву...")
        char_map = {char.id: char for char in archive.characters}
        for patch in patch_list.patches:
            if patch.id and patch.id in char_map:
                # --- ОБНОВЛЕНИЕ СУЩЕСТВУЮЩЕГО ---
                existing_char = char_map[patch.id]
                # Создаем словарь с обновлениями, исключая None значения и 'id'
                update_data = patch.model_dump(exclude_unset=True, exclude={'id'})

                # Особая логика для объединения списков (aliases)
                if 'aliases' in update_data and update_data['aliases']:
                    existing_aliases = set(existing_char.aliases)
                    new_aliases = set(update_data['aliases'])
                    update_data['aliases'] = sorted(list(existing_aliases.union(new_aliases)))

                # Особая логика для объединения словарей (chapter_mentions)
                if 'chapter_mentions' in update_data and update_data['chapter_mentions']:
                    # Мы не можем просто обновить, так как model_copy не делает глубокое слияние
                    # Поэтому обновляем вручную и удаляем из update_data
                    existing_char.chapter_mentions.update(update_data['chapter_mentions'])
                    del update_data['chapter_mentions']

                # Применяем остальные обновления через model_copy
                if update_data:
                    updated_char = existing_char.model_copy(update=update_data)
                    char_map[patch.id] = updated_char
                else:  # Если обновились только mentions
                    char_map[patch.id] = existing_char


            elif patch.id is None and patch.name:
                # --- СОЗДАНИЕ НОВОГО ---
                new_char = Character(
                    name=patch.name,
                    description=patch.description or "Описание не предоставлено.",
                    spoiler_free_description=patch.spoiler_free_description or "Описание не предоставлено.",
                    aliases=patch.aliases or [],
                    chapter_mentions=patch.chapter_mentions or {},
                    first_mention=f"Том {vol}, Глава {chap}"
                )
                char_map[new_char.id] = new_char
                logger.info(f"Обнаружен и добавлен новый персонаж: {patch.name} (ID: {new_char.id})")
            else:
                logger.warning(f"Пропущен некорректный патч: {patch.model_dump_json()}")

        archive.characters = list(char_map.values())
        return archive

    def _add_empty_mentions(self, archive: CharacterArchive, ids_to_mention: List[UUID],
                            chapter_id: str) -> CharacterArchive:
        for char in archive.characters:
            if char.id in ids_to_mention:
                if chapter_id not in char.chapter_mentions:
                    char.chapter_mentions[chapter_id] = "Персонаж упоминается в главе, но без значимых действий."
        return archive
