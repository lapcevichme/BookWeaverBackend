import json
import numpy as np
import soundfile as sf
from typing import Callable, Optional

import config
from core.project_context import ProjectContext
from services.tts_service import TTSService
from utils import text_utils


class TTSPipeline:
    """
    The main pipeline for synthesizing speech for an entire chapter based on a scenario file.
    """

    def __init__(self, tts_service: TTSService):
        self.tts_service = tts_service
        self.pronunciation_dict = text_utils.load_pronunciation_dictionary(config.PRONUNCIATION_DICT_FILE)

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str], None]] = None):
        """
        Executes the full TTS pipeline for a given chapter context.
        """

        def update_progress(progress: float, message: str):
            print(message)
            if progress_callback:
                progress_callback(progress, message)

        update_progress(0.0, f"\n{'=' * 80}\n🚀 STARTING TTS PIPELINE for chapter {context.chapter_id} 🚀\n{'=' * 80}")

        try:
            # 1. Load necessary files
            update_progress(0.05, "--- Step 1: Loading project data ---")
            scenario = context.load_scenario()
            if not scenario:
                update_progress(1.0, f"❌ CRITICAL: Scenario file not found for {context.chapter_id}. Aborting.")
                return

            manifest = context.load_manifest()
            if not manifest:
                update_progress(1.0, f"❌ CRITICAL: Manifest file not found for {context.book_name}. Aborting.")
                return

            update_progress(0.1, "   -> Scenario and Manifest loaded successfully.")

            # 2. Synthesize audio for each entry
            update_progress(0.1, "\n--- Step 2: Synthesizing audio entries ---")
            audio_output_dir = context.get_audio_output_dir()
            audio_output_dir.mkdir(parents=True, exist_ok=True)

            subtitle_path = context.get_subtitles_file()

            update_progress(0.1,
                            f"   -> DEBUG: Attempting to create subtitles directory: {subtitle_path.parent.resolve()}")

            subtitle_path.parent.mkdir(parents=True, exist_ok=True)
            update_progress(0.1, f"   -> Subtitles will be saved to {subtitle_path.name}")

            subtitles_data = []
            total_duration_ms = 0
            total_entries = len(scenario.entries)

            for i, entry in enumerate(scenario.entries):
                progress = 0.1 + (0.8 * (i / total_entries))
                update_progress(progress, f"   -> Processing entry {i + 1}/{total_entries} (Speaker: {entry.speaker})")

                # --- Voice retrieval logic ---
                if entry.speaker:
                    character_name = entry.speaker
                    voice_id = manifest.character_voices.get(character_name)

                    if not voice_id:
                        update_progress(progress,
                                        f"      -> ⚠️ Voice for '{character_name}' not in manifest. Using narrator voice.")
                        voice_id = manifest.default_narrator_voice
                else:
                    character_name = "Рассказчик"
                    voice_id = manifest.default_narrator_voice

                if not voice_id:
                    update_progress(progress,
                                    f"      -> ❌ CRITICAL ERROR: Voice ID not defined for '{character_name}'. Skipping entry.")
                    continue

                speaker_wav_path = context.get_voice_path(voice_id)

                if not speaker_wav_path.exists():
                    update_progress(progress,
                                    f"      -> ❌ REFERENCE NOT FOUND for voice '{voice_id}' at {speaker_wav_path}. Skipping entry.")
                    continue

                # --- Text preprocessing ---
                processed_text = text_utils.preprocess_text_for_tts(entry.text, self.pronunciation_dict)
                if not processed_text:
                    update_progress(progress, "      -> ⏩ Entry text is empty after processing. Skipping.")
                    continue

                synthesis_result = self.tts_service.synthesize(processed_text, speaker_wav_path)

                if synthesis_result:
                    audio_filename = f"chap_{context.chapter_id}_entry_{i + 1}.wav"
                    audio_path = audio_output_dir / audio_filename

                    sf.write(str(audio_path), np.array(synthesis_result),
                             self.tts_service.tts_model.synthesizer.output_sample_rate)

                    audio_duration_ms = int((len(
                        synthesis_result) / self.tts_service.tts_model.synthesizer.output_sample_rate) * 1000)

                    # Generate word timings using Whisper alignment
                    word_timings = self.tts_service.generate_word_timings(entry.text, audio_path)

                    subtitle_entry = self._create_subtitle_entry(
                        audio_filename,
                        entry.text,
                        total_duration_ms,
                        audio_duration_ms,
                        word_timings
                    )
                    subtitles_data.append(subtitle_entry)
                    total_duration_ms += audio_duration_ms
                    update_progress(progress, f"      -> ✅ Audio saved to {audio_filename}")

                    # Сохраняем обновленный файл субтитров после КАЖДОЙ реплики
                    with open(subtitle_path, 'w', encoding='utf-8') as f:
                        json.dump(subtitles_data, f, ensure_ascii=False, indent=2)

                else:
                    update_progress(progress, f"      -> ❌ TTS synthesis failed for entry {i + 1}.")

            update_progress(1.0,
                            f"\n{'=' * 80}\n🎉 TTS PIPELINE COMPLETED for chapter {context.chapter_id}!\n{'=' * 80}")

        except Exception as e:
            update_progress(1.0, f"❌ CRITICAL ERROR in TTS pipeline: {e}")
            import traceback
            traceback.print_exc()

    def _create_subtitle_entry(self, audio_file, text, start_time_ms, duration_ms, word_timings):
        """Creates a structured subtitle entry with word-level timings."""
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