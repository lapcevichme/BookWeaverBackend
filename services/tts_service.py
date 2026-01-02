import logging
from pathlib import Path
from threading import Lock
from services.base_service import BaseTorchService

logger = logging.getLogger(__name__)


class TTSService(BaseTorchService):
    """
    Сервис для TTS и Whisper с ленивой загрузкой моделей.
    Управление Singleton-ом передано в ModelManager.
    """

    def __init__(self, model_name="tts_models/multilingual/multi-dataset/xtts_v2"):
        super().__init__()
        self.model_name = model_name
        self._tts_model = None
        self._whisper_model = None
        self._tts_load_lock = Lock()
        self._whisper_load_lock = Lock()

        logger.info(f"Сервис TTSService сконфигурирован для модели '{self.model_name}' (ленивая загрузка).")

    @property
    def tts_model(self):
        """Ленивая загрузка TTS модели."""
        if self._tts_model is None:
            with self._tts_load_lock:
                if self._tts_model is None:
                    try:
                        from TTS.api import TTS
                    except ImportError:
                        logger.critical("❌ Библиотека 'coqui-tts' не установлена! Синтез недоступен.")
                        return None

                    logger.info(f"⏳ Загрузка весов XTTS ({self.model_name}) на {self.device}...")
                    try:
                        self._tts_model = TTS(model_name=self.model_name).to(self.device)
                        logger.info("✅ Модель XTTS готова к работе.")
                    except Exception as e:
                        logger.error(f"❌ Ошибка загрузки XTTS: {e}", exc_info=True)
                        return None

        return self._tts_model

    @property
    def whisper_model(self):
        """Ленивая загрузка Whisper модели."""
        if self._whisper_model is None:
            with self._whisper_load_lock:
                if self._whisper_model is None:
                    try:
                        import stable_whisper
                    except ImportError:
                        logger.critical("❌ Библиотека 'stable-ts' не установлена! Генерация субтитров недоступна.")
                        return None

                    logger.info("⏳ Загрузка весов stable_whisper (base)...")
                    try:
                        self._whisper_model = stable_whisper.load_model("base", device=self.device)
                        logger.info("✅ Модель Whisper готова к работе.")
                    except Exception as e:
                        logger.error(f"❌ Ошибка загрузки Whisper: {e}", exc_info=True)
                        return None

        return self._whisper_model

    def synthesize(self, text: str, speaker_wav_path: Path, language: str = "ru") -> list | None:
        """Синтезирует аудио из текста."""
        model = self.tts_model

        if not model:
            return None

        if not speaker_wav_path.exists():
            logger.error(f"Файл-образец голоса не найден: {speaker_wav_path}")
            return None

        try:
            return model.tts(text=text, speaker_wav=str(speaker_wav_path), language=language, split_sentences=True)
        except Exception as e:
            logger.error(f"Ошибка синтеза речи: {e}", exc_info=True)
            return None

    def generate_word_timings(self, text: str, audio_path: Path, language: str = "ru") -> list | None:
        """Генерирует таймкоды слов."""
        model = self.whisper_model

        if not model:
            return None

        if not audio_path.exists():
            logger.error(f"Аудиофайл для выравнивания не найден: {audio_path}")
            return None

        try:
            result = model.align(str(audio_path), text, language=language)
            return [{'word': w.word, 'start': w.start, 'end': w.end} for s in result.segments for w in s.words]
        except Exception as e:
            logger.error(f"Ошибка выравнивания Whisper: {e}", exc_info=True)
            return None
