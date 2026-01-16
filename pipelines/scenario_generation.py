"""
Пайплайн для полной обработки одной главы: от текста до готового сценария.
"""
import json
import logging
from typing import List, Dict, Optional, Callable

import config
from core.project_context import ProjectContext
from core.data_models import (
    CharacterArchive,
    RawScenario,
    RawScenarioEntry,
    Scenario,
    ScenarioEntry,
    EmotionMap,
    ChapterSummaryArchive,
    SoundDesignResult
)
from pipelines import prompts
from services.model_manager import ModelManager
from utils.prompt_utils import generate_human_schema
from utils.text_utils import smart_split_text

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
        """
        Загружает библиотеки эмбиента, SFX и пресеты эмоций из конфигурационных файлов.
        """
        logger.info("Загрузка библиотек звукового дизайна...")

        try:
            if config.AMBIENT_LIBRARY_FILE.exists():
                self.ambient_library = json.loads(config.AMBIENT_LIBRARY_FILE.read_text("utf-8"))
            else:
                logger.warning(f"Файл библиотеки эмбиента не найден: {config.AMBIENT_LIBRARY_FILE}")
                self.ambient_library = []
        except json.JSONDecodeError as e:
            logger.warning(f"Ошибка чтения библиотеки эмбиента: {e}")
            self.ambient_library = []

        self.sfx_library = {}
        try:
            if config.SFX_LIBRARY_FILE.exists():
                self.sfx_library = json.loads(config.SFX_LIBRARY_FILE.read_text("utf-8"))
                logger.info(f"📚 Загружено SFX сэмплов: {len(self.sfx_library)}")
            else:
                logger.warning("⚠️ Библиотека SFX не найдена. Генерация SFX будет пропущена.")
        except Exception as e:
            logger.warning(f"Ошибка чтения SFX библиотеки: {e}")

        try:
            if config.EMOTION_REFERENCE_LIBRARY_FILE.exists():
                lib_data = json.loads(config.EMOTION_REFERENCE_LIBRARY_FILE.read_text("utf-8"))
                if isinstance(lib_data, dict):
                    self.character_emotions = lib_data.get("character_emotions", [])
                    self.narrator_styles = lib_data.get("narrator_styles", [])
                else:
                    self.character_emotions, self.narrator_styles = [], []
            else:
                self.character_emotions, self.narrator_styles = [], []
        except json.JSONDecodeError:
            self.character_emotions, self.narrator_styles = [], []

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Запускает полный процесс генерации сценария: текст -> звуки -> эмоции.
        """

        def update_progress(progress: float, stage: str, message: str):
            if progress_callback:
                progress_callback(progress, stage, message)
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")

        update_progress(0.0, "Начало", f"Запуск генерации сценария для главы {context.chapter_id}")

        try:
            context.ensure_dirs()

            # Текстовый слой сценария
            if context.raw_scenario_cache_file.exists():
                update_progress(0.2, "Генерация", "Используется кэш 'сырого' сценария.")
                raw_scenario = RawScenario.model_validate_json(context.raw_scenario_cache_file.read_text("utf-8"))
            else:
                update_progress(0.2, "Генерация", "Генерация текста сценария (LLM)...")
                contextual_characters = self._get_contextual_characters(context.load_character_archive(),
                                                                        context.chapter_id)

                raw_scenario = self._generate_raw_scenario(context, contextual_characters,
                                                           context.load_summary_archive(), update_progress)
                if not raw_scenario:
                    raise ValueError("Ошибка генерации raw scenario.")
                context.raw_scenario_cache_file.write_text(raw_scenario.model_dump_json(indent=2), encoding="utf-8")

            scenario_as_dicts = [entry.model_dump(mode='json') for entry in raw_scenario.scenario]

            # Звуковой слой (Ambient + SFX)
            if context.ambient_cache_file.exists():
                update_progress(0.55, "Звук", "Используется кэш звукового дизайна.")
                sound_enriched_scenario = json.loads(context.ambient_cache_file.read_text("utf-8"))
            else:
                update_progress(0.55, "Звук", "Анализ звукового оформления (Ambient + SFX)...")
                sound_enriched_scenario = self._enrich_sound_design(scenario_as_dicts)
                context.ambient_cache_file.write_text(json.dumps(sound_enriched_scenario, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")

            # Эмоциональный слой
            update_progress(0.75, "Эмоции", "Анализ интонаций и стилей...")
            emotion_enriched_scenario = self._enrich_with_emotions(sound_enriched_scenario,
                                                                   context.load_character_archive(), context.chapter_id)

            # Сборка финального объекта
            final_entries = [ScenarioEntry(**entry_data) for entry_data in emotion_enriched_scenario]
            final_scenario = Scenario(entries=final_entries)
            final_scenario.save(context.scenario_file)

            self._update_manifest_status(context)
            update_progress(1.0, "Завершено", "Готово!")

        except Exception as e:
            update_progress(1.0, "Ошибка", str(e))
            logger.error(f"Error: {e}", exc_info=True)
            raise e

    def _update_manifest_status(self, context: ProjectContext):
        try:
            manifest = context.load_manifest()
            for chapter in manifest.structure:
                if chapter.id == context.chapter_id and chapter.status != "audio_ready":
                    chapter.status = "scenario_ready"
                    manifest.save(context.manifest_file)
                    break
        except Exception as e:
            logger.warning(f"Не удалось обновить статус в манифесте: {e}")

    def _get_contextual_characters(self, archive: CharacterArchive, chapter_id: str) -> CharacterArchive:
        relevant_chars = [
            char for char in archive.characters
            if chapter_id in char.chapter_mentions or char.role_tier in ['protagonist', 'major']
        ]
        return CharacterArchive(characters=relevant_chars)

    def _generate_raw_scenario(
            self,
            context: ProjectContext,
            archive: CharacterArchive,
            summary_archive: ChapterSummaryArchive,
            progress_callback: Optional[Callable] = None
    ) -> RawScenario | None:
        """
        Генерирует сценарий, при необходимости разбивая текст на чанки.
        Размер чанка берется из конфига.
        """
        llm = self.model_manager.get_llm_service('scenario_generator')

        full_text = context.get_chapter_text()
        chapter_data = summary_archive.summaries.get(context.chapter_id)
        synopsis = chapter_data.synopsis if chapter_data else None

        chunk_size = getattr(config, 'SCENARIO_CHUNK_SIZE', 10000)

        logger.info(f"⚙️ Используется размер чанка: {chunk_size} символов")

        chunks = smart_split_text(full_text, chunk_size=chunk_size, overlap=300)
        total_chunks = len(chunks)

        all_entries: List[RawScenarioEntry] = []

        logger.info(f"📖 Текст главы разбит на {total_chunks} частей.")

        for i, chunk_text in enumerate(chunks):
            if progress_callback:
                current_progress = 0.2 + (0.3 * (i / total_chunks))
                progress_callback(current_progress, "Генерация", f"Обработка части {i + 1} из {total_chunks}...")

            # Формируем промпт для конкретного чанка
            prompt = prompts.format_scenario_generation_prompt(
                text_chunk=chunk_text,
                character_archive=archive,
                chapter_summary=synopsis,
                chunk_index=i,
                total_chunks=total_chunks
            )

            # Вызов LLM
            chunk_result = llm.call_for_pydantic(RawScenario, prompt)

            if chunk_result and chunk_result.scenario:
                logger.info(f"✅ Часть {i + 1} готова: получено {len(chunk_result.scenario)} строк.")
                all_entries.extend(chunk_result.scenario)
            else:
                logger.error(f"❌ Ошибка генерации части {i + 1}! Пропускаем этот кусок.")
                # TODO: Здесь можно добавить retry

        if not all_entries:
            return None

        return RawScenario(scenario=all_entries)

    def _enrich_sound_design(self, entries: List[Dict]) -> List[Dict]:
        """
        Подбирает эмбиент и SFX, используя Whitelist.
        """
        if not self.ambient_library and not self.sfx_library:
            for entry in entries: entry['ambient'] = 'none'
            return entries

        minimized_scenario = [
            {"id": e["id"], "text": e["text"][:120] + "..." if len(e["text"]) > 120 else e["text"]}
            for e in entries
        ]

        ambient_menu = json.dumps(
            [{"id": a["id"], "description": a.get("description", "")} for a in self.ambient_library],
            ensure_ascii=False)
        sfx_menu = json.dumps(self.sfx_library, ensure_ascii=False)

        schema_desc = generate_human_schema(SoundDesignResult)

        prompt = prompts.format_sound_design_prompt(
            scenario_json=json.dumps(minimized_scenario, ensure_ascii=False),
            ambient_menu=ambient_menu,
            sfx_menu=sfx_menu,
            schema_description=schema_desc
        )

        result = self.model_manager.get_llm_service('character_analyzer').call_for_pydantic(SoundDesignResult, prompt)
        if not result:
            return entries

        design_map = {item.entry_id: item for item in result.design}
        current_ambient = "none"

        valid_amb_ids = {a['id'] for a in self.ambient_library} | {"none"}
        valid_sfx_ids = set(self.sfx_library.keys())

        for entry in entries:
            eid = str(entry['id'])
            if eid in design_map:
                item = design_map[eid]
                # Ambient (Stateful)
                if item.ambient and (item.ambient in valid_amb_ids):
                    current_ambient = item.ambient

                # SFX (Stateless)
                if item.sfx and (item.sfx in valid_sfx_ids):
                    entry['sfx'] = item.sfx

            entry['ambient'] = current_ambient

        return entries

    def _enrich_with_emotions(self, entries: List[Dict], archive: CharacterArchive, chapter_id: str) -> List[Dict]:
        """Анализ эмоций."""
        if not self.character_emotions and not self.narrator_styles:
            return entries

        replicas = [
            {"id": e['id'], "speaker": e['speaker'], "text": e['text']}
            for e in entries if e.get('text') and e.get('speaker')
        ]

        if not replicas:
            return entries

        char_profiles = {
            char.name: f"ОБЩЕЕ: {char.spoiler_free_description}"
            for char in archive.characters if chapter_id in char.chapter_mentions
        }

        prompt = prompts.format_emotion_analysis_prompt(
            replicas, char_profiles, self.character_emotions, self.narrator_styles
        )

        emotion_map_data = self.model_manager.get_llm_service('character_analyzer').call_for_pydantic(EmotionMap,
                                                                                                      prompt)
        if not emotion_map_data:
            return entries

        entries_by_id = {str(entry['id']): entry for entry in entries}
        for entry_id_uuid, emotion_tag in emotion_map_data.emotions.items():
            entry_id_str = str(entry_id_uuid)
            if entry_id_str in entries_by_id:
                entries_by_id[entry_id_str]['emotion'] = emotion_tag

        for entry in entries:
            if 'emotion' not in entry:
                entry['emotion'] = 'neutral'

        return entries