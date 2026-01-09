"""
Пайплайн для анализа персонажей по всему тексту книги.
"""
import json
import logging
from typing import List, Optional, Callable
from uuid import UUID

from core.project_context import ProjectContext
from core.data_models import Character, CharacterArchive, CharacterReconResult, CharacterPatchList
from services.model_manager import ModelManager
from pipelines import prompts

logger = logging.getLogger(__name__)


class CharacterAnalysisPipeline:
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager

        # BLACKLIST ТОЛЬКО ДЛЯ ПЕРЕИМЕНОВАНИЯ
        # Не удаляем персонажей с такими именами, просто запрещаем переименовывать нормальные имена в эти.
        # TODO: как-то в промптах дать модели знать, что нельзя так переименовывать - но вот галлюцинации хз как обойти.
        self.GENERIC_ROLES_BLACKLIST = {
            "доктор", "врач", "лекарь", "целитель",
            "служанка", "горничная", "фрейлина", "слуга",
            "стражник", "солдат", "офицер", "генерал",
            "евнух", "император", "супруга", "наложница",
            "повар", "кучер", "бандит", "вор",
            "деревенщина", "крестьянин", "житель",
            "мальчик", "девочка", "старик", "старуха", "мужчина", "женщина"
        }

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
            ordered_chapters = context.get_ordered_chapters()

            if not ordered_chapters:
                update_progress(1.0, "Ошибка", "В манифесте проекта не найдено глав.")
                return

            master_archive = context.load_character_archive()
            total_chapters = len(ordered_chapters)
            stage = "Анализ глав"

            for i, (vol_num, chap_num) in enumerate(ordered_chapters):
                progress = 0.1 + (i / total_chapters) * 0.9
                chapter_ctx = ProjectContext(book_name, vol_num, chap_num)
                chapter_id = chapter_ctx.chapter_id

                try:
                    chapter_text = chapter_ctx.get_chapter_text()
                except FileNotFoundError:
                    continue

                if self._is_chapter_processed(master_archive, chapter_id):
                    logger.info(f"Глава {chapter_id} пропущена (уже есть в базе).")
                    continue

                if not chapter_text.strip():
                    continue

                # Разведка
                update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: Разведка...")
                recon_result = self._perform_recon(master_archive, chapter_text)

                if not recon_result or (not recon_result.mentioned_existing_character_ids and not recon_result.newly_discovered_names):
                    continue

                # Генерация патчей
                relevant_chars = self._filter_archive_by_ids(master_archive, recon_result.mentioned_existing_character_ids)
                relevant_characters_json = json.dumps([char.model_dump(mode='json') for char in relevant_chars], ensure_ascii=False, indent=2)

                update_progress(progress, stage, f"Глава {i + 1}/{total_chapters}: Глубокий анализ...")
                patch_list = self._perform_operation(
                    relevant_characters_json,
                    recon_result.newly_discovered_names,
                    chapter_text, vol_num, chap_num
                )

                if patch_list and patch_list.patches:
                    master_archive = self._apply_patch(master_archive, patch_list, vol_num, chap_num, chapter_text)
                else:
                    master_archive = self._add_empty_mentions(master_archive, recon_result.mentioned_existing_character_ids, chapter_id)

                master_archive.save(context.get_character_archive_path())

            update_progress(1.0, "Завершено", f"Анализ завершен. Персонажей: {len(master_archive.characters)}.")

        except Exception as e:
            logger.error(f"Ошибка пайплайна: {e}", exc_info=True)
            raise

    # Валидаторы

    def _is_role_name(self, name: str) -> bool:
        """Проверяет, содержит ли имя слово из черного списка ролей."""
        if not name: return False
        name_lower = name.lower()
        for role in self.GENERIC_ROLES_BLACKLIST:
            if role in name_lower:
                return True
        return False

    def _is_dangerous_rename(self, current_name: str, new_name: str) -> bool:
        """
        Блокирует переименование Нормального Имени в Роль.
        Пример: "Андрей" (ОК) -> "Доктор" (РОЛЬ) => БЛОК.
        Пример: "Деревенщина 1" (РОЛЬ) -> "Андрей" (ОК) => РАЗРЕШЕНО.
        """
        current_is_role = self._is_role_name(current_name)
        new_is_role = self._is_role_name(new_name)

        if not current_is_role and new_is_role:
            return True

        return False

    def _perform_recon(self, archive: CharacterArchive, chapter_text: str) -> Optional[CharacterReconResult]:
        fast_llm = self.model_manager.get_llm_service('character_analyzer')
        known_chars_for_recon = [{"id": str(char.id), "name": char.name} for char in archive.characters]
        known_chars_json = json.dumps(known_chars_for_recon, ensure_ascii=False) if known_chars_for_recon else "[]"
        prompt = prompts.format_character_recon_prompt(chapter_text, known_chars_json)
        return fast_llm.call_for_pydantic(CharacterReconResult, prompt)

    def _perform_operation(self, relevant_chars_json: str, new_names: List[str], text: str, vol: int, chap: int) -> Optional[CharacterPatchList]:
        powerful_llm = self.model_manager.get_llm_service('scenario_generator')
        prompt = prompts.format_character_patch_prompt(relevant_chars_json, new_names, text, vol, chap)
        return powerful_llm.call_for_pydantic(CharacterPatchList, prompt)

    def _apply_patch(self, archive: CharacterArchive, patch_list: CharacterPatchList, vol: int, chap: int, chapter_text: str) -> CharacterArchive:
        """Применяет патчи с проверкой на коллизии имен (но без удаления мусора)."""
        chapter_id = f"vol_{vol}_chap_{chap}"
        role_weights = {"background": 0, "minor": 1, "major": 2, "protagonist": 3}
        char_map = {char.id: char for char in archive.characters}

        for patch in patch_list.patches:
            # EXISTING CHARACTER
            if patch.id and patch.id in char_map:
                char = char_map[patch.id]
                if patch.name and patch.name != char.name:
                    if self._is_dangerous_rename(char.name, patch.name):
                        logger.warning(f"🛡️ BLOCKED DOWNGRADE RENAME: {char.name} -> {patch.name}")
                        # Плохое имя в алиасы, вдруг это титул
                        if patch.name not in char.aliases:
                            char.aliases.append(patch.name)
                    else:
                        logger.info(f"♻️ RENAME APPROVED: {char.name} -> {patch.name}")
                        if char.name not in char.aliases:
                            char.aliases.append(char.name)
                        char.name = patch.name

                if patch.aliases:
                    current = set(char.aliases)
                    new = set(patch.aliases)
                    char.aliases = sorted(list(current.union(new)))
                    if char.name in char.aliases:
                        char.aliases.remove(char.name)

                update_data = patch.model_dump(exclude_unset=True, exclude={
                    'id', 'name', 'aliases', 'chapter_mentions',
                    'timeline_voice_update', 'timeline_visual_update', 'role_tier', 'naming_reasoning'
                })
                if update_data:
                    char = char.model_copy(update=update_data)
                    char_map[patch.id] = char

                if patch.role_tier:
                    old_w = role_weights.get(char.role_tier, 0)
                    new_w = role_weights.get(patch.role_tier, 0)
                    if new_w > old_w:
                        char.role_tier = patch.role_tier

                if patch.timeline_voice_update:
                    char.voice_timeline[chapter_id] = patch.timeline_voice_update
                if patch.timeline_visual_update:
                    char.visual_timeline[chapter_id] = patch.timeline_visual_update
                if patch.chapter_mentions:
                    char.chapter_mentions.update(patch.chapter_mentions)

            # NEW CHARACTER
            elif patch.id is None and patch.name:
                new_char = Character(
                    name=patch.name,
                    description=patch.description or "Новый персонаж.",
                    spoiler_free_description=patch.spoiler_free_description or "Новый персонаж.",
                    aliases=patch.aliases or [],
                    role_tier=patch.role_tier or "minor",
                    chapter_mentions=patch.chapter_mentions or {}
                )

                if patch.timeline_voice_update:
                    new_char.voice_timeline[chapter_id] = patch.timeline_voice_update
                if patch.timeline_visual_update:
                    new_char.visual_timeline[chapter_id] = patch.timeline_visual_update

                char_map[new_char.id] = new_char
                logger.info(f"✨ NEW CHAR ADDED: {patch.name}")

        archive.characters = list(char_map.values())
        return archive

    def _is_chapter_processed(self, archive: CharacterArchive, chapter_id: str) -> bool:
        for char in archive.characters:
            if chapter_id in char.chapter_mentions:
                return True
        return False

    def _filter_archive_by_ids(self, archive: CharacterArchive, ids: List[UUID]) -> List[Character]:
        id_set = set(ids)
        return [char for char in archive.characters if char.id in id_set]

    def _add_empty_mentions(self, archive: CharacterArchive, ids: List[UUID], chapter_id: str) -> CharacterArchive:
        for char in archive.characters:
            if char.id in ids and chapter_id not in char.chapter_mentions:
                char.chapter_mentions[chapter_id] = "Упоминается мельком."
        return archive