"""
Пайплайн для полной обработки одной главы: от текста до готового сценария.
"""
import json
from typing import List, Dict, Optional, Callable

import config
from core.project_context import ProjectContext
from core.data_models import (
    CharacterArchive,
    RawScenario,
    Scenario,
    ScenarioEntry,
    AmbientTransitionList,
    EmotionMap, ChapterSummaryArchive,
)
from services.llm_service import LLMService
from pipelines import prompts


class ScenarioGenerationPipeline:
    """
    Класс-оркестратор, управляющий процессом генерации сценария для одной главы.
    """

    def __init__(self, fast_llm: LLMService, powerful_llm: LLMService):
        self.fast_llm = fast_llm
        self.powerful_llm = powerful_llm
        self._load_libraries()
        print("✅ Пайплайн ScenarioGenerationPipeline инициализирован.")

    def _load_libraries(self):
        """Загружает вспомогательные библиотеки (эмбиент, эмоции)."""
        print("   -> Загрузка библиотек для генерации сценария...")
        try:
            self.ambient_library = json.loads(config.AMBIENT_LIBRARY_FILE.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"   -> ⚠️ Не удалось загрузить библиотеку эмбиента: {e}")
            self.ambient_library = []

        try:
            self.emotion_library = json.loads(config.EMOTION_REFERENCE_LIBRARY_FILE.read_text("utf-8"))
            self.available_emotions = list(self.emotion_library.keys())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"   -> ⚠️ Не удалось загрузить библиотеку эмоций: {e}")
            self.emotion_library = {}
            self.available_emotions = []

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str], None]] = None):
        """
        Запускает полный процесс генерации сценария для главы, указанной в контексте.
        ДОБАВЛЕНО: `progress_callback` для отслеживания состояния из API.
        """
        def update_progress(progress: float, message: str):
            if progress_callback:
                progress_callback(progress, message)
            print(message) # Продолжаем выводить в консоль для отладки

        update_progress(0.0, "\n" + "=" * 80)
        update_progress(0.0, f"🚀 ЗАПУСК ПАЙПЛАЙНА: Генерация сценария для главы {context.chapter_id} 🚀")
        update_progress(0.0, "=" * 80)

        try:
            context.ensure_dirs()
            # --- Шаг 0: Определение путей для кэша ---
            raw_scenario_path = context.chapter_output_dir / "temp_raw_scenario.json"
            ambient_enriched_path = context.chapter_output_dir / "temp_ambient_enriched.json"

            # --- Шаг 1: Загрузка исходных данных ---
            update_progress(0.1, "\n--- Шаг 1: Загрузка исходных данных ---")
            character_archive = context.load_character_archive()
            summary_archive = context.load_summary_archive()
            update_progress(0.15, f"   -> Архивы персонажей ({len(character_archive.characters)} шт.) и пересказов ({len(summary_archive.summaries)} шт.) успешно загружены.")

            # --- Шаг 2: Генерация "сырого" сценария ---
            update_progress(0.2, "") # Пустая строка для перевода строки
            if raw_scenario_path.exists():
                update_progress(0.2, f"--- Шаг 2: Генерация 'сырого' сценария (пропущено, используется кэш) ---")
                raw_scenario = RawScenario.model_validate_json(raw_scenario_path.read_text("utf-8"))
            else:
                update_progress(0.2, "--- Шаг 2: Генерация 'сырого' сценария ---")
                contextual_characters = self._get_contextual_characters(character_archive, context.chapter_id)
                raw_scenario = self._generate_raw_scenario(context, contextual_characters, summary_archive)
                if not raw_scenario: return
                raw_scenario_path.write_text(raw_scenario.model_dump_json(indent=2), encoding="utf-8")
                update_progress(0.5, f"   -> Промежуточный результат сохранен в {raw_scenario_path.name}")

            scenario_as_dicts = [entry.model_dump() for entry in raw_scenario.scenario]

            # --- Шаг 3: Обогащение эмбиентом ---
            update_progress(0.55, "")
            if ambient_enriched_path.exists():
                 update_progress(0.55, f"--- Шаг 3: Обогащение эмбиентом (пропущено, используется кэш) ---")
                 ambient_enriched_scenario = json.loads(ambient_enriched_path.read_text("utf-8"))
            else:
                update_progress(0.55, "--- Шаг 3: Обогащение сценария эмбиентом ---")
                ambient_enriched_scenario = self._enrich_with_ambient(context, scenario_as_dicts)
                ambient_enriched_path.write_text(json.dumps(ambient_enriched_scenario, indent=2, ensure_ascii=False), encoding="utf-8")
                update_progress(0.7, f"   -> Промежуточный результат сохранен в {ambient_enriched_path.name}")

            # --- Шаг 4: Обогащение эмоциями ---
            update_progress(0.75, "\n--- Шаг 4: Обогащение сценария эмоциями ---")
            emotion_enriched_scenario = self._enrich_with_emotions(ambient_enriched_scenario, character_archive, context.chapter_id)

            # --- Шаг 5: Финальная обработка и сохранение ---
            update_progress(0.9, "\n--- Шаг 5: Финализация и сохранение ---")
            final_entries = [ScenarioEntry(**entry_data) for entry_data in emotion_enriched_scenario]
            final_scenario = Scenario(entries=final_entries)
            final_scenario.save(context.scenario_file)

            # --- Шаг 6: Очистка временных файлов ---
            raw_scenario_path.unlink(missing_ok=True)
            ambient_enriched_path.unlink(missing_ok=True)
            update_progress(0.95, "\n--- Шаг 6: Временные файлы кэша удалены ---")


            update_progress(1.0, "\n" + "=" * 80)
            update_progress(1.0, f"🎉 Сценарий для главы {context.chapter_id} успешно сгенерирован!")
            update_progress(1.0, f"   -> Финальный файл: {context.scenario_file}")
            update_progress(1.0, "=" * 80)

        except FileNotFoundError as e:
            update_progress(1.0, f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
            raise e # Передаем исключение выше, чтобы API мог его поймать
        except Exception as e:
            update_progress(1.0, f"❌ КРИТИЧЕСКАЯ НЕПРЕДВИДЕННАЯ ОШИБКА в пайплайне: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def _get_contextual_characters(self, archive: CharacterArchive, chapter_id: str) -> CharacterArchive:
        """
        Фильтрует полный архив и возвращает НОВЫЙ ОБЪЕКТ CharacterArchive
        только с релевантными для главы персонажами.
        """
        print("   -> Фильтрация персонажей для создания контекстного списка...")
        contextual_chars = [char for char in archive.characters if chapter_id in char.chapter_mentions]
        print(f"   -> Найдено {len(contextual_chars)} действующих лиц в главе.")
        return CharacterArchive(characters=contextual_chars)

    def _generate_raw_scenario(
            self,
            context: ProjectContext,
            character_archive: CharacterArchive,
            summary_archive: ChapterSummaryArchive
    ) -> RawScenario | None:
        """
        Вызывает LLM для преобразования текста главы в "сырой" сценарий.
        """
        chapter_summary_data = summary_archive.summaries.get(context.chapter_id)
        synopsis_text = chapter_summary_data.synopsis if chapter_summary_data else None

        if synopsis_text:
            print("   -> Найден конспект главы. Он будет использован как дополнительный контекст.")
        else:
            print("   -> ⚠️ Конспект для главы не найден. Генерация будет идти только по тексту.")

        prompt = prompts.format_scenario_generation_prompt(
            context,
            character_archive,
            synopsis_text
        )
        return self.powerful_llm.call_for_pydantic(RawScenario, prompt)

    def _enrich_with_ambient(self, context: ProjectContext, entries: List[Dict]) -> List[Dict]:
        """
        Определяет эмбиент для каждой записи сценария.
        """
        prompt = prompts.format_ambient_extraction_prompt(context, self.ambient_library)
        ambient_data = self.fast_llm.call_for_pydantic(AmbientTransitionList, prompt)

        if not ambient_data or not ambient_data.transitions:
            print("   -> ⚠️ Не найдено точек смены эмбиента. Вся глава будет без фоновых звуков.")
            for entry in entries:
                entry['ambient'] = 'none'
            return entries

        print(f"   -> Найдено {len(ambient_data.transitions)} точек смены эмбиента.")
        current_ambient = "none"
        transition_idx = 0
        for entry in entries:
            entry['ambient'] = current_ambient
            if transition_idx < len(ambient_data.transitions):
                transition = ambient_data.transitions[transition_idx]
                if entry['text'].strip().startswith(transition.triggerSentence.strip()):
                    current_ambient = transition.ambientSoundId
                    entry['ambient'] = current_ambient
                    transition_idx += 1
                    print(f"      -> Эмбиент изменен на '{current_ambient}'")
        return entries


    def _enrich_with_emotions(self, entries: List[Dict], archive: CharacterArchive, chapter_id: str) -> List[Dict]:
        """
        Определяет эмоции для всех реплик, где спикер - не "Рассказчик".
        Это включает в себя и диалоги, и внутренние монологи.
        """
        if not self.available_emotions:
            print("   -> ⚠️ Список доступных эмоций пуст. Анализ эмоций пропускается.")
            for entry in entries:
                if entry.get('speaker') != "Рассказчик":
                    entry['emotion'] = 'нейтрально'
            return entries

        replicas_to_analyze = []
        for i, entry in enumerate(entries):
            if entry.get('speaker') and entry.get('speaker') != "Рассказчик":
                replicas_to_analyze.append({"id": str(i), "speaker": entry['speaker'], "text": entry['text']})

        if not replicas_to_analyze:
            print("   -> В главе нет реплик персонажей для анализа эмоций.")
            return entries

        char_profiles = {
            char.name: f"ОБЩЕЕ: {char.spoiler_free_description}. В ЭТОЙ ГЛАВЕ: {char.chapter_mentions.get(chapter_id, '')}"
            for char in archive.characters if chapter_id in char.chapter_mentions
        }

        prompt = prompts.format_emotion_analysis_prompt(
            replicas_to_analyze, char_profiles, self.available_emotions
        )
        emotion_map_data = self.fast_llm.call_for_pydantic(EmotionMap, prompt)

        if not emotion_map_data:
            print("   -> ❌ LLM не смогла проанализировать эмоции.")
            return entries

        print(f"   -> ✅ LLM успешно проанализировала {len(emotion_map_data.emotions)} реплик.")
        for entry_id_str, emotion in emotion_map_data.emotions.items():
            try:
                entry_id = int(entry_id_str)
                if entry_id < len(entries):
                    entries[entry_id]['emotion'] = emotion
            except (ValueError, IndexError):
                print(f"   -> ⚠️ LLM вернула некорректный ID реплики: '{entry_id_str}'. Пропускаю.")
                continue
        return entries

