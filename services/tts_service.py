import logging
from pathlib import Path
from threading import Lock
import config
from services.base_service import BaseTorchService
from services.cosyvoice_client import CosyVoiceClient

logger = logging.getLogger(__name__)


class TTSService(BaseTorchService):
    """
    Сервис для TTS (CosyVoice API) и Whisper (Local Aligner).
    Поддерживает VRAM Orchestration для Whisper.
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
        """Ленивая загрузка Whisper (локально)."""
        if self._whisper_model is None:
            with self._whisper_load_lock:
                if self._whisper_model is None:
                    try:
                        import stable_whisper
                    except ImportError:
                        logger.critical("❌ Библиотека 'stable-ts' не установлена!")
                        return None

                    logger.info("⏳ VRAM: Загрузка весов stable_whisper (base) в видеопамять...")
                    try:
                        self._whisper_model = stable_whisper.load_model("base", device=self.device)
                        self._is_loaded = True
                        logger.info("✅ Модель Whisper загружена.")
                    except Exception as e:
                        logger.error(f"❌ Ошибка загрузки Whisper: {e}", exc_info=True)
                        return None

        return self._whisper_model

    def unload(self):
        """
        Принудительно выгружает Whisper из VRAM.
        """
        if self._whisper_model is not None:
            logger.info("🔻 VRAM: Выгрузка модели Whisper...")
            del self._whisper_model
            self._whisper_model = None
            self._is_loaded = False

            self._clear_cuda_cache()
        else:
            logger.debug("VRAM: Whisper уже выгружен или не был загружен.")

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
            # logger.debug(f"Transcribing ref: {speaker_wav_path.name}")
            result = model.transcribe(path_str)
            text = result.text.strip()
            self._reference_transcription_cache[path_str] = text
            return text
        except Exception as e:
            logger.error(f"Ошибка транскрипции референса: {e}")
            return " "

    def synthesize(self, text: str, speaker_wav_path: Path, emotion: str = None) -> bytes | None:
        """Синтез через API (не требует VRAM этого процесса)."""
        if not speaker_wav_path.exists():
            logger.error(f"Файл-образец голоса не найден: {speaker_wav_path}")
            return None

        prompt_text = self._get_prompt_text(speaker_wav_path)

        instruct_text = emotion if emotion and emotion.lower() != "neutral" else ""

        return self.cosy_client.synthesize(
            text=text,
            prompt_wav_path=speaker_wav_path,
            prompt_text=prompt_text,
            instruct_text=instruct_text,
            mode="zero_shot"
        )

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