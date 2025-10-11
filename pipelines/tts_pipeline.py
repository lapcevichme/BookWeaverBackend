import json
import logging
from typing import Callable, Optional

import numpy as np
import soundfile as sf

import config
from core.project_context import ProjectContext
from services.tts_service import TTSService
from utils import text_utils

logger = logging.getLogger(__name__)


class TTSPipeline:
    """
    Основной пайплайн для синтеза речи для всей главы на основе файла сценария.
    """

    def __init__(self, tts_service: TTSService):
        self.tts_service = tts_service
        self.pronunciation_dict = text_utils.load_pronunciation_dictionary(config.PRONUNCIATION_DICT_FILE)
        logger.info("✅ Пайплайн TTSPipeline инициализирован.")

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Выполняет полный пайплайн TTS для заданного контекста главы.
        """

        def update_progress(progress: float, stage: str, message: str):
            # Логируем то же сообщение, что отправляем на фронтенд
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        update_progress(0.0, "Подготовка", f"Запуск синтеза речи для главы {context.chapter_id}")

        try:
            # --- Шаг 1: Загрузка необходимых файлов ---
            stage = "Загрузка данных"
            update_progress(0.05, stage, "Загрузка файла сценария...")
            scenario = context.load_scenario()
            if not scenario:
                raise FileNotFoundError(f"Файл сценария не найден для главы {context.chapter_id}.")

            update_progress(0.07, stage, "Загрузка манифеста книги...")
            manifest = context.load_manifest()
            if not manifest:
                raise FileNotFoundError(f"Файл манифеста не найден для книги {context.book_name}.")

            update_progress(0.1, stage, "Сценарий и манифест успешно загружены.")

            # --- Шаг 2: Синтез аудио для каждой реплики ---
            audio_output_dir = context.get_audio_output_dir()
            subtitle_path = context.get_subtitles_file()
            context.ensure_dirs()  # Убедимся, что все директории созданы

            subtitles_data = []
            total_duration_ms = 0
            total_entries = len(scenario.entries)

            if total_entries == 0:
                update_progress(1.0, "Завершено", "Сценарий не содержит реплик для озвучивания.")
                return

            for i, entry in enumerate(scenario.entries):
                # Рассчитываем общий прогресс
                progress = 0.1 + (0.8 * (i / total_entries))
                stage = "Синтез речи"
                update_progress(progress, stage, f"Реплика {i + 1}/{total_entries} (Спикер: {entry.speaker})")

                # --- Логика выбора голоса ---
                character_name = entry.speaker if entry.speaker else "Рассказчик"
                voice_id = manifest.character_voices.get(character_name)

                if not voice_id:
                    logger.warning(
                        f"Голос для '{character_name}' не найден в манифесте. Используется голос рассказчика.")
                    voice_id = manifest.default_narrator_voice

                if not voice_id:
                    logger.error(
                        f"ID голоса не определен для '{character_name}' и отсутствует голос рассказчика по-умолчанию. Пропуск реплики.")
                    continue

                speaker_wav_path = context.get_voice_path(voice_id)
                if not speaker_wav_path.exists():
                    logger.error(
                        f"Референсный WAV-файл для голоса '{voice_id}' не найден по пути {speaker_wav_path}. Пропуск реплики.")
                    continue

                # --- Предобработка текста и синтез ---
                processed_text = text_utils.preprocess_text_for_tts(entry.text, self.pronunciation_dict)
                if not processed_text:
                    logger.info(f"Текст реплики {i + 1} пуст после обработки. Пропуск.")
                    continue

                synthesis_result = self.tts_service.synthesize(processed_text, speaker_wav_path)

                if synthesis_result:
                    audio_filename = f"entry_{i + 1}.wav" # todo: проверить что имя не конфликтует. Старый формат: chap_{context.chapter_id}_entry_{i + 1}.wav
                    audio_path = audio_output_dir / audio_filename

                    sf.write(str(audio_path), np.array(synthesis_result),
                             self.tts_service.tts_model.synthesizer.output_sample_rate)

                    audio_duration_ms = int(
                        (len(synthesis_result) / self.tts_service.tts_model.synthesizer.output_sample_rate) * 1000)
                    logger.info(
                        f"Аудио для реплики {i + 1} успешно сохранено в {audio_filename} (длительность: {audio_duration_ms} мс).")

                    # --- Создание субтитров с таймкодами ---
                    stage = "Создание субтитров"
                    update_progress(progress, stage, f"Реплика {i + 1}/{total_entries}: Генерация таймкодов...")

                    word_timings = self.tts_service.generate_word_timings(entry.text, audio_path)

                    subtitle_entry = self._create_subtitle_entry(
                        audio_filename, entry.text, total_duration_ms, audio_duration_ms, word_timings
                    )
                    subtitles_data.append(subtitle_entry)
                    total_duration_ms += audio_duration_ms

                    # Сохраняем обновленный файл субтитров после КАЖДОЙ реплики для отказоустойчивости
                    with open(subtitle_path, 'w', encoding='utf-8') as f:
                        json.dump(subtitles_data, f, ensure_ascii=False, indent=2)
                else:
                    logger.error(f"Синтез речи (TTS) не удался для реплики {i + 1}.")

            update_progress(1.0, "Завершено", f"Синтез речи для главы {context.chapter_id} успешно завершен!")

        except Exception as e:
            error_msg = f"Критическая ошибка в пайплайне TTS: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            # Передаем исключение выше, чтобы API мог его поймать и пометить задачу как 'failed'
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
