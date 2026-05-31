import json
import time
import logging
from typing import Callable, Optional
import soundfile as sf
import config

from core.project_context import ProjectContext
from services.model_manager import ModelManager
from utils import text_utils
from utils.metrics import metrics_collector, AudioMetrics

logger = logging.getLogger(__name__)


class TTSPipeline:
    """
    Основной пайплайн для синтеза речи для всей главы.
    Адаптирован для работы с CosyVoice 3: использует tts_text и instruct_prompt.
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
            update_progress(0.02, stage, "Подключение к сервису TTS...")

            tts_service = self.model_manager.get_tts_service()

            if hasattr(tts_service, 'cosy_client'):
                if not tts_service.cosy_client.check_health():
                    logger.warning("⚠️ Не удается достучаться до CosyVoice API. Проверьте Docker-контейнер!")

            update_progress(0.04, stage, "Загрузка файла сценария...")
            scenario = context.load_scenario()
            if not scenario:
                raise FileNotFoundError(f"Файл сценария не найден для главы {context.chapter_id}.")

            update_progress(0.06, stage, "Загрузка манифеста книги...")
            manifest = context.load_manifest()

            update_progress(0.08, stage, "Загрузка архива персонажей...")
            character_archive = context.load_character_archive()
            char_name_to_id_map = {char.name: char.id for char in character_archive.characters}

            update_progress(0.1, stage, "Все данные успешно загружены.")

            audio_output_dir = context.get_audio_output_dir()
            subtitle_path = context.get_subtitles_file()
            context.ensure_dirs()
            
            metrics_collector.start_chapter(context.chapter_id)

            subtitles_data = []
            total_duration_ms = 0
            total_entries = len(scenario.entries)

            if total_entries == 0:
                update_progress(1.0, "Завершено", "Сценарий не содержит реплик для озвучивания.")
                return

            for i, entry in enumerate(scenario.entries):
                progress = 0.1 + (0.8 * (i / total_entries))

                if entry.type == "image":
                    logger.debug(f"Пропуск записи {entry.id} (тип image).")
                    continue

                if not entry.text or not entry.text.strip():
                    logger.debug(f"Пропуск записи {entry.id} (пустой текст).")
                    continue

                audio_filename = f"{entry.id}.wav"
                audio_path = audio_output_dir / audio_filename

                character_name = entry.speaker
                voice_id = None

                if character_name == "Рассказчик" or not character_name:
                    voice_id = manifest.config.default_narrator_voice
                else:
                    character_uuid = char_name_to_id_map.get(character_name)
                    if character_uuid:
                        voice_id = manifest.config.character_voices.get(character_uuid)
                    else:
                        logger.warning(f"Персонаж '{character_name}' не найден в архиве.")

                if not voice_id:
                    voice_id = manifest.config.default_narrator_voice

                speaker_wav_path = context.get_voice_path(voice_id)
                actual_voice_path = None

                if speaker_wav_path.exists():
                    actual_voice_path = speaker_wav_path
                else:
                    voice_dir = speaker_wav_path.parent
                    if voice_dir.exists() and voice_dir.is_dir():
                        valid_extensions = ['.mp3', '.wav', '.flac', '.ogg', '.m4a']

                        for ext in valid_extensions:
                            candidate = voice_dir / f"reference{ext}"
                            if candidate.exists():
                                actual_voice_path = candidate
                                break

                        if not actual_voice_path:
                            for file in voice_dir.iterdir():
                                if file.suffix.lower() in valid_extensions:
                                    actual_voice_path = file
                                    break

                if not actual_voice_path:
                    logger.error(
                        f"❌ Аудиофайл для голоса '{voice_id}' не найден в папке {speaker_wav_path.parent}. Пропуск.")
                    continue

                instruct_prompt = getattr(entry, 'instruct_prompt', 'neutral')

                tts_text_raw = getattr(entry, 'tts_text', None)

                # Если tts_text пустой или отсутствует (сработала экономия токенов), падаем обратно на чистый text
                if not tts_text_raw:
                    tts_text_raw = entry.text

                processed_text = text_utils.preprocess_text_for_tts(tts_text_raw, self.pronunciation_dict)
                if not processed_text:
                    continue

                audio_duration_ms = 0
                stage = "Синтез речи"

                if not audio_path.exists():
                    max_attempts = 3
                    attempt = 0
                    success = False
                    
                    last_cer = 0.0
                    total_synthesis_time = 0.0
                    
                    while attempt < max_attempts and not success:
                        attempt += 1
                        current_instruct = instruct_prompt
                        
                        if attempt > 1:
                            if current_instruct == 'neutral' or not current_instruct:
                                current_instruct = "normal voice"
                            else:
                                current_instruct = f"{current_instruct}, natural"

                        update_progress(progress, stage, f"[{i + 1}/{total_entries}] Синтез (попытка {attempt}): {character_name or 'Рассказчик'} ({current_instruct})")

                        start_time = time.time()
                        wav_bytes = tts_service.synthesize(
                            text=processed_text,
                            speaker_wav_path=actual_voice_path,
                            emotion=current_instruct
                        )
                        call_duration = (time.time() - start_time) * 1000
                        total_synthesis_time += call_duration

                        if wav_bytes:
                            with open(audio_path, "wb") as f:
                                f.write(wav_bytes)

                            # Валидация - длина и галлюцинации
                            try:
                                with sf.SoundFile(str(audio_path)) as f:
                                    audio_duration_ms = int((f.frames / f.samplerate) * 1000)
                                
                                word_count = len(processed_text.split())
                                duration_sec = audio_duration_ms / 1000
                                
                                is_too_long = word_count > 0 and (duration_sec / word_count) > 4.0
                                
                                whisper_text = tts_service._get_prompt_text(audio_path)
                                last_cer = text_utils.calculate_cer(processed_text, whisper_text)
                                
                                rtf = (call_duration / 1000) / duration_sec if duration_sec > 0 else 0
                                
                                logger.debug(f"Проверка: CER {last_cer:.2%}, RTF {rtf:.2f}, Длина {duration_sec:.1f}с")
                                
                                if last_cer <= 0.25 and not is_too_long:
                                    success = True
                                else:
                                    reason = "высокий CER" if last_cer > 0.25 else "аномальная длительность"
                                    logger.warning(f"⚠️ Брак ({reason}). Повтор...")
                                    metrics_collector.increment("tts_hallucinations")
                                    if audio_path.exists(): audio_path.unlink()
                            except Exception as e:
                                logger.error(f"Ошибка при верификации: {e}")
                                success = True 
                        else:
                            break
                            
                    metrics_collector.log_audio_gen(AudioMetrics(
                        entry_id=str(entry.id),
                        speaker=character_name or "Narrator",
                        text_length=len(processed_text),
                        audio_duration_ms=audio_duration_ms,
                        synthesis_latency_ms=total_synthesis_time,
                        rtf=round((total_synthesis_time / 1000) / (audio_duration_ms / 1000), 3) if audio_duration_ms > 0 else 0,
                        cer=round(last_cer, 4),
                        attempts=attempt,
                        status="success" if success else "hallucination"
                    ))
                    metrics_collector.save_to_file(config.LOGS_DIR / "metrics.json")
                else:
                    try:
                        with sf.SoundFile(str(audio_path)) as f:
                            audio_duration_ms = int((f.frames / f.samplerate) * 1000)
                    except Exception:
                        audio_duration_ms = 0
                        continue

                if audio_duration_ms > 0:
                    stage = "Выравнивание (Whisper)"

                    word_timings = tts_service.generate_word_timings(processed_text, audio_path)

                    subtitle_entry = self._create_subtitle_entry(
                        audio_filename, entry.text, total_duration_ms, audio_duration_ms, word_timings
                    )
                    subtitles_data.append(subtitle_entry)
                    total_duration_ms += audio_duration_ms

                    with open(subtitle_path, 'w', encoding='utf-8') as f:
                        json.dump(subtitles_data, f, ensure_ascii=False, indent=2)

            self._update_manifest_status(context)
            update_progress(1.0, "Завершено", f"Глава озвучена! Длительность: {total_duration_ms / 1000:.1f} сек.")

        except Exception as e:
            error_msg = f"❌ Критическая ошибка в TTS пайплайне: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise

        if self.model_manager:
            logger.info("TTS Pipeline завершен. Освобождаем ресурсы...")
            self.model_manager.unload_service("tts_service")

    def _update_manifest_status(self, context: ProjectContext):
        """Обновляет статус главы на 'audio_ready'."""
        try:
            manifest = context.load_manifest()
            for chapter in manifest.structure:
                if chapter.id == context.chapter_id:
                    chapter.status = "audio_ready"
                    manifest.save(context.manifest_file)
                    logger.info(f"Статус главы обновлен: {chapter.id} -> audio_ready")
                    break
        except Exception as e:
            logger.warning(f"⚠️ Не удалось обновить статус манифеста: {e}")

    def _create_subtitle_entry(self, audio_file, text, start_time_ms, duration_ms, word_timings):
        """Формирует запись для JSON-субтитров."""
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
