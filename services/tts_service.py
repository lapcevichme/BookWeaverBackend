import logging
from pathlib import Path
from threading import Lock
import config
from services.base_service import BaseTorchService
from services.cosyvoice_client import CosyVoiceClient

logger = logging.getLogger(__name__)


class TTSService(BaseTorchService):
    """
    Сервис для TTS (CosyVoice) и Whisper (Aligner).
    """

    def __init__(self):
        super().__init__()
        self.cosy_client = CosyVoiceClient(base_url=config.COSYVOICE_API_URL)

        self._whisper_model = None
        self._whisper_load_lock = Lock()
        self._reference_transcription_cache = {}

        logger.info(f"Сервис TTSService инициализирован. CosyVoice URL: {config.COSYVOICE_API_URL}")

    @property
    def whisper_model(self):
        """Ленивая загрузка Whisper (локально) для выравнивания и транскрипции референсов."""
        if self._whisper_model is None:
            with self._whisper_load_lock:
                if self._whisper_model is None:
                    try:
                        import stable_whisper
                    except ImportError:
                        logger.critical("❌ Библиотека 'stable-ts' не установлена!")
                        return None

                    logger.info("⏳ Загрузка весов stable_whisper (base)...")
                    try:
                        self._whisper_model = stable_whisper.load_model("base", device=self.device)
                        logger.info("✅ Модель Whisper готова.")
                    except Exception as e:
                        logger.error(f"❌ Ошибка загрузки Whisper: {e}", exc_info=True)
                        return None

        return self._whisper_model

    def _get_prompt_text(self, speaker_wav_path: Path) -> str:
        """Получает текст из референсного аудио (кэширует результат)."""
        path_str = str(speaker_wav_path)
        if path_str in self._reference_transcription_cache:
            return self._reference_transcription_cache[path_str]

        # logger.info(f"🎙️ Транскрипция референса: {speaker_wav_path.name}")
        model = self.whisper_model
        if not model:
            return " "

        try:
            result = model.transcribe(path_str)
            text = result.text.strip()
            self._reference_transcription_cache[path_str] = text
            return text
        except Exception as e:
            logger.error(f"Ошибка транскрипции референса: {e}")
            return " "

    def synthesize(self, text: str, speaker_wav_path: Path, emotion: str = None) -> bytes | None:
        """
        Синтезирует аудио через CosyVoice API.

        Args:
            text: Текст реплики.
            speaker_wav_path: Путь к голосу.
            emotion: Эмоциональный тег (например: 'angry', 'sad', 'whisper').
                     Если None или 'neutral', отправляется пустая инструкция.
        """
        if not speaker_wav_path.exists():
            logger.error(f"Файл-образец голоса не найден: {speaker_wav_path}")
            return None

        prompt_text = self._get_prompt_text(speaker_wav_path)

        instruct_text = emotion if emotion and emotion.lower() != "neutral" else ""

        audio_bytes = self.cosy_client.synthesize(
            text=text,
            prompt_wav_path=speaker_wav_path,
            prompt_text=prompt_text,
            instruct_text=instruct_text,
            mode="zero_shot"
        )

        return audio_bytes

    def generate_word_timings(self, text: str, audio_path: Path, language: str = "ru") -> list | None:
        """Генерирует таймкоды (субтитры) через Whisper."""
        model = self.whisper_model
        if not model or not audio_path.exists():
            return None

        try:
            result = model.align(str(audio_path), text, language=language)
            return [{'word': w.word, 'start': w.start, 'end': w.end} for s in result.segments for w in s.words]
        except Exception as e:
            logger.error(f"Ошибка выравнивания: {e}", exc_info=True)
            return None