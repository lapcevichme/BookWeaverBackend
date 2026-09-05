"""
Пайплайн для анализа персонажей по всему тексту книги.
"""
import json
import logging
from typing import List, Optional, Callable
from uuid import UUID, uuid4

import config
from core.book_repository import BookRepository
from core.data_models import Character, CharacterArchive, CharacterReconResult, CharacterPatchList, CharacterType
from services.model_manager import ModelManager
from pipelines import prompts
from utils.metrics import metrics_collector

logger = logging.getLogger(__name__)


class CharacterAnalysisPipeline:
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        self._load_blacklist()
        logger.info("✅ Пайплайн CharacterAnalysisPipeline инициализирован.")

    def _load_blacklist(self):
        from core.database import get_system_session
        from core.system_models import SystemSetting
        
        try:
            with get_system_session() as session:
                setting = session.get(SystemSetting, "role_blacklist")
                if setting:
                    self.GENERIC_ROLES_BLACKLIST = set(setting.value)
                    logger.info(f"Загружен черный список ролей из БД: {len(self.GENERIC_ROLES_BLACKLIST)} записей.")
                else:
                    self.GENERIC_ROLES_BLACKLIST = set()
                    logger.warning("⚠️ Черный список ролей не найден в БД.")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки черного списка из БД: {e}")
            self.GENERIC_ROLES_BLACKLIST = set()

    def run(self, book_name: str, max_chapters: Optional[int] = None, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        stage = "Подготовка"
        update_progress(0.0, stage, f"Запуск анализа персонажей для книги '{book_name}'")

        try:
            repo = BookRepository(book_name)
            db_chapters = repo.get_all_chapters()
            if max_chapters and max_chapters > 0:
                db_chapters = db_chapters[:max_chapters]

            if not db_chapters:
                update_progress(1.0, "Ошибка", "В базе данных проекта не найдено глав.")
                return

            master_archive = repo.get_character_archive()
            summary_archive = repo.get_summary_archive()

            total_chapters = len(db_chapters)
            stage = "Анализ глав"

            for idx, chap in enumerate(db_chapters):
                progress = 0.1 + (idx / total_chapters) * 0.9
                chapter_id = chap.id
                vol_num = chap.volume_num
                chap_num = chap.chapter_num
                
                metrics_collector.start_chapter(f"{book_name}:{chapter_id}")

                try:
                    chapter_text = repo.get_chapter_text(chapter_id)
                except (FileNotFoundError, ValueError) as e:
                    logger.warning(f"Пропуск главы {chapter_id}: {e}")
                    continue

                if not chapter_text.strip():
                    self._mark_chapter_processed(master_archive, chapter_id)
                    repo.update_chapter_status(chapter_id, "processed")
                    continue

                chapter_summary_text = None
                if chapter_id in summary_archive.summaries:
                    chapter_summary_text = summary_archive.summaries[chapter_id].synopsis

                update_progress(progress, stage, f"Глава {idx + 1}/{total_chapters}: Разведка...")
                recon_result = self._perform_recon(master_archive, chapter_text, chapter_summary_text)

                if not recon_result:
                    logger.warning(f"⚠️ Recon вернул None для главы {chapter_id}")
                    self._mark_chapter_processed(master_archive, chapter_id)
                    continue

                logger.info(f"🔍 Recon: Найдено известных: {len(recon_result.mentioned_existing_character_ids)}, новых имен: {len(recon_result.newly_discovered_names)}")

                if not recon_result.mentioned_existing_character_ids and not recon_result.newly_discovered_names:
                    logger.info(f"В главе {chapter_id} персонажи не обнаружены.")
                    self._mark_chapter_processed(master_archive, chapter_id)
                    repo.update_chapter_status(chapter_id, "processed")
                    continue

                relevant_chars = self._filter_archive_by_ids(master_archive, recon_result.mentioned_existing_character_ids)
                
                # РАЗБИВАЕМ НА ЧАНКИ
                MAX_PER_CALL = 5
                new_names = recon_result.newly_discovered_names
                
                # 1. Обработка НОВЫХ имен пачками
                for i in range(0, len(new_names), MAX_PER_CALL):
                    chunk = new_names[i:i + MAX_PER_CALL]
                    update_progress(progress, stage, f"Глава {idx + 1}/{total_chapters}: Анализ новых ({i + len(chunk)}/{len(new_names)})...")
                    
                    patch_list = self._perform_operation("[]", chunk, chapter_text, vol_num, chap_num)
                    if patch_list and patch_list.patches:
                        master_archive = self._apply_patch(master_archive, patch_list, vol_num, chap_num, chapter_text, book_name)

                # 2. Обработка ИЗВЕСТНЫХ персонажей
                if relevant_chars:
                    for i in range(0, len(relevant_chars), MAX_PER_CALL):
                        chunk_chars = relevant_chars[i:i + MAX_PER_CALL]
                        chunk_json = json.dumps([char.model_dump(mode='json', include={'id', 'name', 'aliases', 'role_tier', 'visual_base', 'voice_base'}) for char in chunk_chars], ensure_ascii=False)
                        
                        update_progress(progress, stage, f"Глава {idx + 1}/{total_chapters}: Обновление известных ({i + len(chunk_chars)}/{len(relevant_chars)})...")
                        patch_list = self._perform_operation(chunk_json, [], chapter_text, vol_num, chap_num)
                        
                        if patch_list and patch_list.patches:
                             master_archive = self._apply_patch(master_archive, patch_list, vol_num, chap_num, chapter_text, book_name)
                        else:
                             ids = [c.id for c in chunk_chars]
                             master_archive = self._add_empty_mentions(master_archive, ids, chapter_id)

                self._mark_chapter_processed(master_archive, chapter_id)
                
                # СОХРАНЕНИЕ В БД
                repo.save_characters(master_archive.characters)
                repo.update_chapter_status(chapter_id, "processed")
                metrics_collector.save_to_file(config.LOGS_DIR / "metrics.json")

            update_progress(1.0, "Завершено", f"Анализ завершен. Персонажей: {len(master_archive.characters)}.")

        except Exception as e:
            logger.error(f"❌ Ошибка пайплайна: {e}", exc_info=True)
            raise

    def _is_role_name(self, name: str) -> bool:
        if not name or len(name) < 2: return True
        name_lower = name.lower()
        for role in self.GENERIC_ROLES_BLACKLIST:
            if role in name_lower: return True
        return False

    def _is_dangerous_rename(self, current_name: str, new_name: str) -> bool:
        current_is_role = self._is_role_name(current_name)
        new_is_role = self._is_role_name(new_name)
        return not current_is_role and new_is_role

    def _perform_recon(self, archive: CharacterArchive, chapter_text: str, chapter_summary: Optional[str] = None) -> Optional[CharacterReconResult]:
        fast_llm = self.model_manager.get_llm_service('character_analyzer')
        known_chars_for_recon = [{"id": str(char.id), "name": char.name, "aliases": char.aliases} for char in archive.characters]
        known_chars_json = json.dumps(known_chars_for_recon, ensure_ascii=False) if known_chars_for_recon else "[]"
        prompt = prompts.format_character_recon_prompt(chapter_text, known_chars_json, chapter_summary)
        return fast_llm.call_for_pydantic(CharacterReconResult, prompt, prompt_type="character_recon")

    def _perform_operation(self, relevant_chars_json: str, new_names: List[str], text: str, vol: int, chap: int) -> Optional[CharacterPatchList]:
        powerful_llm = self.model_manager.get_llm_service('scenario_generator')
        prompt = prompts.format_character_patch_prompt(relevant_chars_json, new_names, text, vol, chap)
        return powerful_llm.call_for_pydantic(CharacterPatchList, prompt, prompt_type="character_patch")

    def _apply_patch(self, archive: CharacterArchive, patch_list: CharacterPatchList, vol: int, chap: int, chapter_text: str, book_id: str) -> CharacterArchive:
        chapter_id = f"vol_{vol}_chap_{chap}"
        role_weights = {"background": 0, "minor": 1, "major": 2, "protagonist": 3}
        
        # Строим карты для быстрого поиска
        char_map_id = {char.id: char for char in archive.characters}
        char_map_name = {char.name.lower(): char for char in archive.characters}

        for patch in patch_list.patches:
            if patch.entity_type == CharacterType.OBJECT: continue
            if not patch.name: continue

            # 1. Пытаемся найти персонажа (по ID или по Имени)
            target_char = None
            
            if patch.id and patch.id in char_map_id:
                target_char = char_map_id[patch.id]
            
            # Если по ID не нашли, ищем по имени (без учета регистра)
            if not target_char and patch.name:
                name_key = patch.name.lower()
                if name_key in char_map_name:
                    target_char = char_map_name[name_key]
                    logger.info(f"🔍 Нашли {patch.name} по имени (ID не совпал)")

            # 2. Если нашли - ОБНОВЛЯЕМ
            if target_char:
                char = target_char
                logger.info(f"🔄 ОБНОВЛЕНИЕ: {char.name}")

                if patch.name and patch.name != char.name:
                    if not self._is_dangerous_rename(char.name, patch.name):
                        logger.info(f"   - ИМЯ: {char.name} -> {patch.name}")
                        if char.name not in char.aliases and not self._is_role_name(char.name):
                            char.aliases.append(char.name)
                        char.name = patch.name

                if patch.entity_type: char.entity_type = patch.entity_type
                if patch.aliases:
                    valid_new = [a for a in patch.aliases if not self._is_role_name(a)]
                    char.aliases = sorted(list(set(char.aliases).union(set(valid_new))))

                if patch.visual_base: char.visual_base = patch.visual_base
                if patch.voice_base: char.voice_base = patch.voice_base

                if patch.role_tier:
                    if role_weights.get(patch.role_tier, 0) > role_weights.get(char.role_tier, 0):
                        char.role_tier = patch.role_tier

                if patch.timeline_voice_update:
                    char.voice_timeline[chapter_id] = patch.timeline_voice_update
                if patch.timeline_visual_update:
                    char.visual_timeline[chapter_id] = patch.timeline_visual_update
                if patch.current_chapter_action:
                    char.chapter_mentions[chapter_id] = patch.current_chapter_action

            # 3. Если не нашли - СОЗДАЕМ
            elif not self._is_role_name(patch.name):
                valid_aliases = [a for a in (patch.aliases or []) if not self._is_role_name(a)]
                new_char = Character(
                    id=uuid4(),
                    book_id=book_id,
                    name=patch.name,
                    entity_type=patch.entity_type or CharacterType.PERSON,
                    description=patch.description or "Новый персонаж.",
                    spoiler_free_description=patch.spoiler_free_description or "Новый персонаж.",
                    aliases=valid_aliases,
                    role_tier=patch.role_tier or "minor",
                    chapter_mentions={chapter_id: patch.current_chapter_action} if patch.current_chapter_action else {},
                    gender=patch.gender,
                    visual_base=patch.visual_base or "",
                    voice_base=patch.voice_base or ""
                )
                if patch.timeline_voice_update:
                    new_char.voice_timeline[chapter_id] = patch.timeline_voice_update
                if patch.timeline_visual_update:
                    new_char.visual_timeline[chapter_id] = patch.timeline_visual_update

                archive.characters.append(new_char)
                char_map_id[new_char.id] = new_char
                char_map_name[new_char.name.lower()] = new_char
                logger.info(f"✨ НОВЫЙ: {patch.name} ({new_char.role_tier})")

        return archive

    def _is_chapter_processed(self, archive: CharacterArchive, chapter_id: str) -> bool:
        return chapter_id in getattr(archive, 'processed_chapters', [])

    def _mark_chapter_processed(self, archive: CharacterArchive, chapter_id: str):
        if not hasattr(archive, 'processed_chapters'): archive.processed_chapters = []
        if chapter_id not in archive.processed_chapters: archive.processed_chapters.append(chapter_id)

    def _filter_archive_by_ids(self, archive: CharacterArchive, ids: List[UUID]) -> List[Character]:
        id_set = set(ids)
        return [char for char in archive.characters if char.id in id_set]

    def _add_empty_mentions(self, archive: CharacterArchive, ids: List[UUID], chapter_id: str) -> CharacterArchive:
        for char in archive.characters:
            if char.id in ids and chapter_id not in char.chapter_mentions:
                char.chapter_mentions[chapter_id] = "Упоминается мельком."
        return archive
