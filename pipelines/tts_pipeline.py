import json
import logging
from typing import Callable, Optional

import numpy as np
import soundfile as sf

import config
from core.project_context import ProjectContext
from services.model_manager import ModelManager
from utils import text_utils

logger = logging.getLogger(__name__)


class TTSPipeline:
    """
    Основной пайплайн для синтеза речи для всей главы на основе файла сценария.
    """

    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        self.pronunciation_dict = text_utils.load_pronunciation_dictionary(config.PRONUNCIATION_DICT_FILE)
        logger.info("✅ Пайплайн TTSPipeline инициализирован.")

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Выполняет полный пайплайн TTS для заданного контекста главы.
        """

        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        update_progress(0.0, "Подготовка", f"Запуск синтеза речи для главы {context.chapter_id}")

        try:
            stage = "Загрузка данных"
            update_progress(0.02, stage, "Загрузка сервиса TTS...")
            tts_service = self.model_manager.get_tts_service()
            if not tts_service.tts_model:
                raise RuntimeError("TTS модель не смогла загрузиться. Пайплайн остановлен.")

            update_progress(0.04, stage, "Загрузка файла сценария...")
            scenario = context.load_scenario()
            if not scenario:
                raise FileNotFoundError(f"Файл сценария не найден для главы {context.chapter_id}.")

            update_progress(0.06, stage, "Загрузка манифеста книги...")
            manifest = context.load_manifest()
            if not manifest:
                raise FileNotFoundError(f"Файл манифеста не найден для книги {context.book_name}.")

            update_progress(0.08, stage, "Загрузка архива персонажей...")
            character_archive = context.load_character_archive()
            char_name_to_id_map = {char.name: char.id for char in character_archive.characters}

            update_progress(0.1, stage, "Все данные успешно загружены.")

            audio_output_dir = context.get_audio_output_dir()
            subtitle_path = context.get_subtitles_file()
            context.ensure_dirs()

            subtitles_data = []
            total_duration_ms = 0
            total_entries = len(scenario.entries)

            if total_entries == 0:
                update_progress(1.0, "Завершено", "Сценарий не содержит реплик для озвучивания.")
                return

            for i, entry in enumerate(scenario.entries):
                progress = 0.1 + (0.8 * (i / total_entries))

                audio_filename = f"{entry.id}.wav"
                audio_path = audio_output_dir / audio_filename

                character_name = entry.speaker
                voice_id = None

                if character_name == "Рассказчик":
                    voice_id = manifest.default_narrator_voice
                else:
                    character_uuid = char_name_to_id_map.get(character_name)
                    if character_uuid:
                        # ИСПРАВЛЕНИЕ: Убрано преобразование в str(). Ищем по объекту UUID.
                        voice_id = manifest.character_voices.get(character_uuid)
                        if not voice_id:
                            logger.warning(
                                f"Голос для '{character_name}' (ID: {character_uuid}) не найден в манифесте.")
                    else:
                        logger.warning(f"Персонаж '{character_name}' из сценария не найден в архиве персонажей.")

                if not voice_id:
                    logger.info(f"Для '{character_name}' будет использован голос рассказчика по умолчанию.")
                    voice_id = manifest.default_narrator_voice

                if not voice_id:
                    logger.error(f"ID голоса не определен для '{character_name}' и отсутствует голос рассказчика. Пропуск реплики {entry.id}.")
                    continue

                speaker_wav_path = context.get_voice_path(voice_id)
                if not speaker_wav_path.exists():
                    logger.error(
                        f"WAV-файл для голоса '{voice_id}' не найден ({speaker_wav_path}). Пропуск реплики {entry.id}.")
                    continue

                processed_text = text_utils.preprocess_text_for_tts(entry.text, self.pronunciation_dict)
                if not processed_text:
                    logger.info(f"Текст реплики {entry.id} пуст. Пропуск.")
                    continue

                synthesis_result = None
                audio_duration_ms = 0

                stage = "Синтез речи"
                if not audio_path.exists():
                    update_progress(progress, stage,
                                    f"Реплика {i + 1}/{total_entries}: Синтез (Спикер: {character_name})")
                    synthesis_result = tts_service.synthesize(processed_text, speaker_wav_path)

                    if synthesis_result:
                        audio_duration_ms = int(
                            (len(synthesis_result) / tts_service.tts_model.synthesizer.output_sample_rate) * 1000
                        )
                        sf.write(str(audio_path), np.array(synthesis_result),
                                 tts_service.tts_model.synthesizer.output_sample_rate)
                    else:
                        logger.error(f"Синтез речи (TTS) не удался для реплики {entry.id}.")
                        continue
                else:
                    logger.info(f"Аудио для {audio_filename} уже существует, пропуск синтеза.")
                    try:
                        with sf.SoundFile(str(audio_path)) as f:
                            audio_duration_ms = int((f.frames / f.samplerate) * 1000)
                    except Exception as e:
                        logger.error(f"Не удалось прочитать существующий аудиофайл {audio_path}: {e}. Пропуск реплики.")
                        continue

                if audio_duration_ms == 0:
                    logger.warning(
                        f"Длительность аудио для реплики {entry.id} равна нулю. Пропуск генерации субтитров для нее.")
                    continue

                stage = "Создание субтитров"
                update_progress(progress, stage, f"Реплика {i + 1}/{total_entries}: Генерация таймкодов...")
                word_timings = tts_service.generate_word_timings(entry.text, audio_path)

                subtitle_entry = self._create_subtitle_entry(
                    audio_filename, entry.text, total_duration_ms, audio_duration_ms, word_timings
                )
                subtitles_data.append(subtitle_entry)
                total_duration_ms += audio_duration_ms

                with open(subtitle_path, 'w', encoding='utf-8') as f:
                    json.dump(subtitles_data, f, ensure_ascii=False, indent=2)

            update_progress(1.0, "Завершено", f"Синтез речи для главы {context.chapter_id} успешно завершен!")

        except Exception as e:
            error_msg = f"Критическая ошибка в пайплайне TTS: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise

    def _create_subtitle_entry(self, audio_file, text, start_time_ms, duration_ms, word_timings):
        """Создает структурированную запись для файла субтитров."""
        words_data = []
        if word_timings:
            for item in word_timings:
                words_data.append({
                    "word": item['word'],
                    "start": int((item['start'] * 1000) + start_time_ms),
                    "end": int((item['end'] * 1000) + start_time_ms)
                })

        return {
            "audio_file": audio_file,
            "text": text,
            "start_ms": start_time_ms,
            "end_ms": start_time_ms + duration_ms,
            "duration_ms": duration_ms,
            "words": words_data
        }

