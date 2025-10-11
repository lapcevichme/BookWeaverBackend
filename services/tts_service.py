import torch
import logging
from pathlib import Path
from threading import Lock

# Используем try-except для опциональных зависимостей
try:
    from TTS.api import TTS
except ImportError:
    TTS = None

try:
    import stable_whisper
except ImportError:
    stable_whisper = None

logger = logging.getLogger(__name__)


class TTSService:
    """
    Сервис для TTS и Whisper с ленивой загрузкой моделей.
    Реализован как Singleton.
    """
    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(TTSService, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name="tts_models/multilingual/multi-dataset/xtts_v2"):
        # Используем hasattr для гарантии однократной инициализации в Singleton
        if not hasattr(self, 'initialized'):
            self.model_name = model_name
            self.device = "cuda" if torch.cuda.is_available() else "cpu"

            self._tts_model = None
            self._whisper_model = None
            self._tts_lock = Lock()
            self._whisper_lock = Lock()

            logger.info(f"Сервис TTSService сконфигурирован для модели '{self.model_name}' (ленивая загрузка).")
            self.initialized = True

    @property
    def tts_model(self):
        """Ленивая загрузка TTS модели."""
        if TTS is None:
            logger.critical("Библиотека coqui-tts не установлена! TTS функционал недоступен.")
            return None

        if self._tts_model is None:
            with self._tts_lock:
                if self._tts_model is None:
                    logger.info(f"Загрузка TTS модели '{self.model_name}' на {self.device.upper()}...")
                    try:
                        self._tts_model = TTS(model_name=self.model_name).to(self.device)
                        logger.info("✅ Модель XTTS успешно загружена.")
                    except Exception as e:
                        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА при загрузке модели XTTS: {e}", exc_info=True)
        return self._tts_model

    @property
    def whisper_model(self):
        """Ленивая загрузка Whisper модели."""
        if stable_whisper is None:
            logger.error("Библиотека stable_whisper не установлена! Функционал выравнивания слов недоступен.")
            return None

        if self._whisper_model is None:
            with self._whisper_lock:
                if self._whisper_model is None:
                    logger.info("Загрузка модели stable_whisper...")
                    try:
                        self._whisper_model = stable_whisper.load_model("base")
                        logger.info("✅ Модель stable_whisper успешно загружена.")
                    except Exception as e:
                        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА при загрузке модели stable_whisper: {e}", exc_info=True)
        return self._whisper_model

    def synthesize(self, text: str, speaker_wav_path: Path, language: str = "ru") -> list | None:
        """Синтезирует аудио из текста."""
        model = self.tts_model  # Обращение к свойству инициирует загрузку
        if not model: return None
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
        model = self.whisper_model  # Обращение к свойству инициирует загрузку
        if not model: return None
        if not audio_path.exists():
            logger.error(f"Аудиофайл для выравнивания не найден: {audio_path}")
            return None
        try:
            result = model.align(str(audio_path), text, language=language)
            return [{'word': w.word, 'start': w.start, 'end': w.end} for s in result.segments for w in s.words]
        except Exception as e:
            logger.error(f"Ошибка выравнивания Whisper: {e}", exc_info=True)
            return None
