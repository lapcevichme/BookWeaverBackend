"""
Пайплайн для полной обработки одной главы: от текста до готового сценария.
"""
import json
from typing import List, Dict, Optional, Callable
import logging

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
from pipelines import prompts
from services.model_manager import ModelManager

logger = logging.getLogger(__name__)


class ScenarioGenerationPipeline:
    """
    Класс-оркестратор, управляющий процессом генерации сценария для одной главы.
    """

    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        self._load_libraries()
        logger.info("✅ Пайплайн ScenarioGenerationPipeline инициализирован.")

    def _load_libraries(self):
        """Загружает вспомогательные библиотеки (эмбиент, эмоции)."""
        logger.info("Загрузка библиотек для генерации сценария...")
        try:
            self.ambient_library = json.loads(config.AMBIENT_LIBRARY_FILE.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Не удалось загрузить библиотеку эмбиента: {e}")
            self.ambient_library = []

        try:
            self.emotion_library = json.loads(config.EMOTION_REFERENCE_LIBRARY_FILE.read_text("utf-8"))
            self.available_emotions = list(self.emotion_library.keys())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Не удалось загрузить библиотеку эмоций: {e}")
            self.emotion_library = {}
            self.available_emotions = []

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Запускает полный процесс генерации сценария для главы, указанной в контексте.
        """

        def update_progress(progress: float, stage: str, message: str):
            if progress_callback:
                progress_callback(progress, stage, message)
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")

        update_progress(0.0, "Начало", f"Запуск генерации сценария для главы {context.chapter_id}")

        try:
            context.ensure_dirs()
            # --- Шаг 0: Определение путей для кэша ---
            raw_scenario_path = context.raw_scenario_cache_file
            ambient_enriched_path = context.ambient_cache_file

            # --- Шаг 1: Загрузка исходных данных ---
            stage = "Загрузка данных"
            update_progress(0.1, stage, "Загрузка архива персонажей...")
            character_archive = context.load_character_archive()
            update_progress(0.12, stage, "Загрузка архива пересказов...")
            summary_archive = context.load_summary_archive()
            update_progress(0.15, stage,
                            f"Архивы персонажей ({len(character_archive.characters)} шт.) и пересказов ({len(summary_archive.summaries)} шт.) успешно загружены.")

            # --- Шаг 2: Генерация "сырого" сценария ---
            stage = "Генерация сценария"
            if raw_scenario_path.exists():
                update_progress(0.2, stage, "Обнаружен кэш 'сырого' сценария, используется он.")
                raw_scenario = RawScenario.model_validate_json(raw_scenario_path.read_text("utf-8"))
            else:
                update_progress(0.2, stage, "Фильтрация персонажей для контекста...")
                contextual_characters = self._get_contextual_characters(character_archive, context.chapter_id)
                update_progress(0.25, stage, "Отправка запроса к LLM для генерации 'сырого' сценария...")
                raw_scenario = self._generate_raw_scenario(context, contextual_characters, summary_archive)
                if not raw_scenario:
                    raise ValueError("LLM не смогла сгенерировать 'сырой' сценарий.")
                raw_scenario_path.write_text(raw_scenario.model_dump_json(indent=2), encoding="utf-8")
                update_progress(0.5, stage, f"Промежуточный результат сохранен в {raw_scenario_path.name}")

            scenario_as_dicts = [entry.model_dump(mode='json') for entry in raw_scenario.scenario]

            # --- Шаг 3: Обогащение эмбиентом ---
            stage = "Анализ эмбиента"
            if ambient_enriched_path.exists():
                update_progress(0.55, stage, "Обнаружен кэш данных по эмбиенту, используется он.")
                ambient_enriched_scenario = json.loads(ambient_enriched_path.read_text("utf-8"))
            else:
                update_progress(0.55, stage, "Отправка запроса к LLM для анализа эмбиента...")
                ambient_enriched_scenario = self._enrich_with_ambient(scenario_as_dicts)
                ambient_enriched_path.write_text(json.dumps(ambient_enriched_scenario, indent=2, ensure_ascii=False),
                                                 encoding="utf-8")
                update_progress(0.7, stage, f"Промежуточный результат сохранен в {ambient_enriched_path.name}")

            # --- Шаг 4: Обогащение эмоциями ---
            stage = "Анализ эмоций"
            update_progress(0.75, stage, "Отправка запроса к LLM для анализа эмоций...")
            emotion_enriched_scenario = self._enrich_with_emotions(ambient_enriched_scenario, character_archive,
                                                                   context.chapter_id)
            update_progress(0.85, stage, "Анализ эмоций завершен.")

            # --- Шаг 5: Финальная обработка и сохранение ---
            stage = "Финализация"
            update_progress(0.9, stage, "Сборка финального сценария...")
            final_entries = [ScenarioEntry(**entry_data) for entry_data in emotion_enriched_scenario]
            final_scenario = Scenario(entries=final_entries)
            update_progress(0.95, stage, "Сохранение файла сценария на диск...")
            final_scenario.save(context.scenario_file)

            # --- Шаг 6: Очистка временных файлов ---
            raw_scenario_path.unlink(missing_ok=True)
            ambient_enriched_path.unlink(missing_ok=True)
            update_progress(0.98, stage, "Временные файлы кэша удалены.")

            update_progress(1.0, "Завершено", f"Сценарий для главы {context.chapter_id} успешно сгенерирован!")

        except FileNotFoundError as e:
            error_msg = f"Критическая ошибка: Файл не найден - {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise e
        except Exception as e:
            error_msg = f"Непредвиденная ошибка: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(f"Критическая непредвиденная ошибка в пайплайне", exc_info=True)
            raise e

    def _get_contextual_characters(self, archive: CharacterArchive, chapter_id: str) -> CharacterArchive:
        """
        Фильтрует полный архив и возвращает НОВЫЙ ОБЪЕКТ CharacterArchive
        только с релевантными для главы персонажами.
        """
        logger.debug("Фильтрация персонажей для создания контекстного списка...")
        contextual_chars = [char for char in archive.characters if chapter_id in char.chapter_mentions]
        logger.debug(f"Найдено {len(contextual_chars)} действующих лиц в главе.")
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
        powerful_llm = self.model_manager.get_llm_service('scenario_generator')

        chapter_summary_data = summary_archive.summaries.get(context.chapter_id)
        synopsis_text = chapter_summary_data.synopsis if chapter_summary_data else None

        if synopsis_text:
            logger.debug("Найден конспект главы. Он будет использован как дополнительный контекст.")
        else:
            logger.info("Конспект для главы не найден. Генерация будет идти только по тексту.")

        prompt = prompts.format_scenario_generation_prompt(
            context,
            character_archive,
            synopsis_text
        )
        return powerful_llm.call_for_pydantic(RawScenario, prompt)

    def _enrich_with_ambient(self, entries: List[Dict]) -> List[Dict]:
        """
        Определяет эмбиент для каждой записи сценария.
        """
        fast_llm = self.model_manager.get_llm_service('character_analyzer')

        # Теперь `entries` содержит UUID в виде строк, поэтому `json.dumps` сработает.
        raw_scenario_json_str = json.dumps(entries, ensure_ascii=False, indent=2)
        prompt = prompts.format_ambient_extraction_prompt(raw_scenario_json_str, self.ambient_library)

        ambient_data = fast_llm.call_for_pydantic(AmbientTransitionList, prompt)

        if not ambient_data or not ambient_data.transitions:
            logger.warning("Не найдено точек смены эмбиента. Вся глава будет без фоновых звуков.")
            for entry in entries:
                entry['ambient'] = 'none'
            return entries

        logger.info(f"Найдено {len(ambient_data.transitions)} точек смены эмбиента.")

        transitions_map = {str(t.entry_id): t.ambientSoundId for t in ambient_data.transitions}
        current_ambient = "none"

        for entry in entries:
            entry_id = entry.get('id')
            if entry_id in transitions_map:
                current_ambient = transitions_map[entry_id]
                logger.debug(f"Эмбиент изменен на '{current_ambient}' для entry_id: {entry_id}")
            entry['ambient'] = current_ambient

        return entries

    def _enrich_with_emotions(self, entries: List[Dict], archive: CharacterArchive, chapter_id: str) -> List[Dict]:
        """
        Определяет эмоции для всех реплик, где спикер - не "Рассказчик".
        Это включает в себя и диалоги, и внутренние монологи.
        """
        fast_llm = self.model_manager.get_llm_service('character_analyzer')

        if not self.available_emotions:
            logger.warning("Список доступных эмоций пуст. Анализ эмоций пропускается.")
            for entry in entries:
                if entry.get('speaker') != "Рассказчик":
                    entry['emotion'] = 'нейтрально'
            return entries

        replicas_to_analyze = []
        for entry in entries:
            if entry.get('speaker') and entry.get('speaker') != "Рассказчик":
                replicas_to_analyze.append({"id": entry['id'], "speaker": entry['speaker'], "text": entry['text']})

        if not replicas_to_analyze:
            logger.info("В главе нет реплик персонажей для анализа эмоций.")
            return entries

        char_profiles = {
            char.name: f"ОБЩЕЕ: {char.spoiler_free_description}. В ЭТОЙ ГЛАВЕ: {char.chapter_mentions.get(chapter_id, '')}"
            for char in archive.characters if chapter_id in char.chapter_mentions
        }

        prompt = prompts.format_emotion_analysis_prompt(
            replicas_to_analyze, char_profiles, self.available_emotions
        )
        emotion_map_data = fast_llm.call_for_pydantic(EmotionMap, prompt)

        if not emotion_map_data:
            logger.error("LLM не смогла проанализировать эмоции.")
            # Установим эмоцию по умолчанию для диалогов, если анализ не удался
            for entry in entries:
                if entry.get('speaker') != "Рассказчик" and 'emotion' not in entry:
                    entry['emotion'] = 'нейтрально'
            return entries

        logger.info(f"LLM успешно проанализировала {len(emotion_map_data.emotions)} реплик.")

        # Создаем словарь для быстрого поиска entry по id
        entries_by_id = {entry['id']: entry for entry in entries}

        for entry_id_uuid, emotion in emotion_map_data.emotions.items():
            entry_id_str = str(entry_id_uuid)
            if entry_id_str in entries_by_id:
                entries_by_id[entry_id_str]['emotion'] = emotion
            else:
                logger.warning(f"LLM вернула ID реплики, которого нет в сценарии: '{entry_id_str}'. Пропускаю.")

        # Убедимся, что у всех реплик персонажей есть эмоция (на случай, если LLM что-то пропустила)
        for entry in entries:
            if entry.get('speaker') != "Рассказчик" and 'emotion' not in entry:
                entry['emotion'] = 'нейтрально'

        return entries
