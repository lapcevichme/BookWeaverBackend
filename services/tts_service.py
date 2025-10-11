import torch
from pathlib import Path
from TTS.api import TTS
import logging

logger = logging.getLogger(__name__)

try:
    import stable_whisper
except ImportError:
    stable_whisper = None

class TTSService:
    """
    A service class to encapsulate the TTS model and its functionality.
    This makes the model a reusable, shareable resource across different pipelines.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TTSService, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name="tts_models/multilingual/multi-dataset/xtts_v2"):
        if not hasattr(self, 'initialized'):
            self.model_name = model_name
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Initializing TTSService with model '{self.model_name}' on device '{self.device.upper()}'.")
            try:
                self.tts_model = TTS(model_name=self.model_name).to(self.device)
                logger.info("XTTS model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load XTTS model: {e}", exc_info=True)
                self.tts_model = None
            self.whisper_model = None  # Lazy loading for Whisper
            self.initialized = True

    def _load_whisper_model(self):
        """Lazy loading of the Whisper model for subtitle generation."""
        if stable_whisper is None:
            logger.error("stable_whisper library is not installed. Install it with: pip install stable-ts")
            return None
        if self.whisper_model is None:
            logger.info("Loading stable_whisper model...")
            try:
                self.whisper_model = stable_whisper.load_model("base")  # Use 'base' or your preferred model size
                logger.info("stable_whisper model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load stable_whisper model: {e}", exc_info=True)
                self.whisper_model = None
        return self.whisper_model

    def synthesize(self, text: str, speaker_wav_path: Path, language: str = "ru") -> list | None:
        """
        Synthesizes audio from text and returns the audio waveform as a list.
        """
        if not self.tts_model:
            logger.error("TTS model is not available.")
            return None
        if not speaker_wav_path.exists():
            logger.error(f"Speaker WAV file not found: {speaker_wav_path}")
            return None

        try:
            logger.debug(f"Synthesizing text: '{text[:70]}...'")
            result = self.tts_model.tts(
                text=text,
                speaker_wav=str(speaker_wav_path),
                language=language,
                split_sentences=True
            )
            return result
        except Exception as e:
            logger.error(f"XTTS synthesis failed for text '{text[:50]}...': {e}", exc_info=True)
            return None

    def generate_word_timings(self, text: str, audio_path: Path, language: str = "ru") -> list | None:
        """
        Generates word-level timings using stable_whisper alignment.
        """
        whisper_model = self._load_whisper_model()
        if not whisper_model:
            logger.error("Whisper model is not available for alignment.")
            return None
        if not audio_path.exists():
            logger.error(f"Audio file not found for alignment: {audio_path}")
            return None

        try:
            logger.debug(f"Aligning audio '{audio_path.name}' to generate word timings...")
            result = whisper_model.align(str(audio_path), text, language=language)
            word_timings = []
            for segment in result.segments:
                for word in segment.words:
                    word_timings.append({
                        'word': word.word,
                        'start': word.start,
                        'end': word.end
                    })
            logger.debug(f"Word timings generated successfully for {audio_path.name}")
            return word_timings
        except Exception as e:
            logger.error(f"Whisper alignment failed for '{audio_path.name}': {e}", exc_info=True)
            return None
