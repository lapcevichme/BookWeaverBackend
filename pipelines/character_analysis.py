"""
Пайплайн для анализа персонажей по всему тексту книги с использованием подхода с патчем
"""
import json
from typing import List, Optional, Callable

from core.project_context import ProjectContext
from core.data_models import Character, CharacterArchive, CharacterReconResult, CharacterPatchList
from services.llm_service import LLMService
from utils import file_utils
from pipelines import prompts


class CharacterAnalysisPipeline:
    """
    Класс-пайплайн, инкапсулирующий всю логику анализа персонажей в книге.
    Использует двухэтапный подход для эффективности:
    1. 'Разведка': Быстрый поиск релевантных персонажей в главе.
    2. 'Операция': Глубокий анализ и создание 'патча' для обновления архива.
    """

    def __init__(self, fast_llm: LLMService, powerful_llm: LLMService):
        self.fast_llm = fast_llm
        self.powerful_llm = powerful_llm
        print("✅ Пайплайн CharacterAnalysisPipeline (v3, Smart Recon) инициализирован.")

    def run(self, book_name: str, progress_callback: Optional[Callable[[float, str], None]] = None):
        """
        Запускает полный процесс анализа для книги, указанной в контексте.
        ДОБАВЛЕНО: `progress_callback` для интеграции с API.
        """
        # --- Вспомогательная функция для обновления прогресса ---
        def update_progress(progress: float, message: str):
            if progress_callback:
                progress_callback(progress, message)
            print(message)

        update_progress(0.0, "\n" + "=" * 80)
        update_progress(0.0, f"🚀 ЗАПУСК ПАЙПЛАЙНА: Анализ персонажей в книге '{book_name}' 🚀")
        update_progress(0.0, "=" * 80)

        try:
            context = ProjectContext(book_name=book_name)
            context.ensure_dirs()

            all_chapters = file_utils.get_all_chapters(context.book_dir)
            if not all_chapters:
                update_progress(1.0, f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не найдено глав для анализа в {context.book_dir}")
                return

            master_archive = context.load_character_archive()
            update_progress(0.05, f"Загружен существующий архив. Персонажей: {len(master_archive.characters)}")

            total_chapters = len(all_chapters)
            update_progress(0.1, f"Найдено {total_chapters} глав. Начинаю обработку...")

            for i, (vol_path, chap_path) in enumerate(all_chapters):
                # Рассчитываем прогресс для текущей главы
                progress = 0.1 + (i / total_chapters) * 0.9

                vol_num = int(vol_path.name.split('_')[-1])
                chap_num = int(chap_path.stem.split('_')[-1])
                chapter_id = f"vol_{vol_num}_chap_{chap_num}"

                update_progress(progress, f"\n--- Обработка главы [{i+1}/{total_chapters}]: {chap_path.name} ---")

                if self._is_chapter_processed(master_archive, chapter_id):
                    update_progress(progress, f"   -> ✅ Глава {chapter_id} уже была проанализирована ранее. Пропускаю.")
                    continue

                chapter_text = chap_path.read_text("utf-8")
                if not chapter_text.strip():
                    update_progress(progress, "   -> ⚠️ Глава пуста. Пропускаю.")
                    continue

                # --- ШАГ 1: "Умная разведка" ---
                recon_result = self._perform_recon(master_archive, chapter_text)

                if not recon_result or (not recon_result.mentioned_existing_characters and not recon_result.newly_discovered_names):
                    update_progress(progress, "   -> ⚠️ 'Разведка' не нашла релевантных персонажей в главе. Пропускаю.")
                    continue

                all_relevant_names = recon_result.mentioned_existing_characters + recon_result.newly_discovered_names
                update_progress(progress, f"   -> Найдено {len(all_relevant_names)} релевантных персонажей: {all_relevant_names}")

                # --- ШАГ 2: Фильтрация в Python ---
                relevant_chars = self._filter_archive(master_archive, recon_result.mentioned_existing_characters)
                relevant_chars_json = json.dumps([char.model_dump() for char in relevant_chars], ensure_ascii=False, indent=2)

                # --- ШАГ 3: "Операция" - запрос патча ---
                patch_list = self._perform_operation(relevant_chars_json, chapter_text, vol_num, chap_num)

                if not patch_list or not patch_list.patches:
                    update_progress(progress, "   -> ⚠️ LLM не вернула патчей. Считаем, что в главе не было изменений.")
                    master_archive = self._add_empty_mentions(master_archive, recon_result.mentioned_existing_characters, chapter_id)
                    master_archive.save(context.get_character_archive_path())
                    update_progress(progress, "   -> Добавлены пустые упоминания для найденных персонажей.")
                    continue

                # --- ШАГ 4: Применение патча ---
                update_progress(progress, f"   -> Шаг 3: Применение {len(patch_list.patches)} патчей к архиву...")
                master_archive = self._apply_patch(master_archive, patch_list, vol_num, chap_num)
                update_progress(progress, f"   -> ✅ Архив обновлен. Текущее кол-во персонажей: {len(master_archive.characters)}")
                master_archive.save(context.get_character_archive_path())

            final_message_header = "\n" + "=" * 80 + "\n🎉 Анализ персонажей успешно завершен!"
            final_message_body = (
                f"   Итоговый архив сохранен в: {context.get_character_archive_path()}\n"
                f"   Всего найдено уникальных персонажей: {len(master_archive.characters)}\n"
                + "=" * 80
            )
            update_progress(1.0, final_message_header + "\n" + final_message_body)


        except Exception as e:
            error_message = f"❌ КРИТИЧЕСКАЯ НЕПРЕДВИДЕННАЯ ОШИБКА в пайплайне: {e}"
            update_progress(1.0, error_message)
            import traceback
            traceback.print_exc()

    def _perform_recon(self, archive: CharacterArchive, chapter_text: str) -> Optional[CharacterReconResult]:
        """Этап 'Разведки': быстрый поиск упоминаний."""
        print("   -> Шаг 1: 'Умная разведка' - сопоставление с известными и поиск новых...")
        known_chars_for_recon = [
            {"name": char.name, "aliases": char.aliases}
            for char in archive.characters
        ]
        known_chars_json = json.dumps(known_chars_for_recon, ensure_ascii=False, indent=2)
        recon_prompt = prompts.format_character_recon_prompt(chapter_text, known_chars_json)
        return self.fast_llm.call_for_pydantic(CharacterReconResult, recon_prompt)

    def _perform_operation(self, relevant_chars_json: str, chapter_text: str, vol_num: int, chap_num: int) -> Optional[CharacterPatchList]:
        """Этап 'Операции': глубокий анализ и создание патча."""
        print("   -> Шаг 2: 'Операция' - запрос патча с изменениями...")
        patch_prompt = prompts.format_character_patch_prompt(
            relevant_chars_json, chapter_text, vol_num, chap_num
        )
        return self.powerful_llm.call_for_pydantic(CharacterPatchList, patch_prompt)


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
        archive.characters = list(char_map.values())
        return archive

    def _add_empty_mentions(self, archive: CharacterArchive, names_to_mention: List[str], chapter_id: str) -> CharacterArchive:
        """Добавляет 'пустое' упоминание для персонажей, которые были в главе, но для которых не было патча."""
        for char in archive.characters:
            if char.name in names_to_mention:
                if chapter_id not in char.chapter_mentions:
                    char.chapter_mentions[chapter_id] = "Персонаж упоминается в главе, но без значимых действий."
        return archive

