import json
import random
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from threading import Lock
from services.base_service import BaseTorchService

import config

logger = logging.getLogger(__name__)


class VCService(BaseTorchService):
    """
    Сервис для Voice Conversion с ленивой загрузкой модели.
    Наследует логику работы с устройством от BaseTorchService.
    """

    def __init__(self, model_name="voice_conversion_models/multilingual/vctk/freevc24"):
        super().__init__()  # Важно!
        self.model_name = model_name
        self._vc_model = None
        self._load_lock = Lock()
        self._emotion_library = self._load_emotion_library()
        logger.info("Сервис VCService сконфигурирован (ленивая загрузка).")

    def _load_emotion_library(self) -> Dict[str, Any]:
        """Загружает библиотеку эмоциональных референсов из JSON."""
        if not config.EMOTION_REFERENCE_LIBRARY_FILE.exists():
            logger.warning("Файл библиотеки эмоций не найден.")
            return {}

        try:
            content = config.EMOTION_REFERENCE_LIBRARY_FILE.read_text("utf-8")
            return json.loads(content)
        except Exception as e:
            logger.error(f"Ошибка чтения библиотеки эмоций: {e}", exc_info=True)
            return {}

    @property
    def vc_model(self):
        """Ленивая загрузка модели Voice Conversion."""
        if self._vc_model is None:
            with self._load_lock:
                if self._vc_model is None:
                    try:
                        from TTS.api import TTS
                    except ImportError:
                        logger.critical("❌ Библиотека 'coqui-tts' не установлена! Voice Conversion недоступен.")
                        return None

                    logger.info(f"⏳ Загрузка VC модели '{self.model_name}' на {self.device}...")
                    try:
                        self._vc_model = TTS(model_name=self.model_name, progress_bar=False).to(self.device)
                        logger.info("✅ Модель VC успешно загружена.")
                    except Exception as e:
                        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА при загрузке модели VC: {e}", exc_info=True)
                        return None

        return self._vc_model

    def find_reference_wav_for_emotion(self, emotion: str) -> Optional[Path]:
        """Находит случайный WAV-файл референса для указанной эмоции."""
        emotion_samples = self._emotion_library.get(emotion)
        if not emotion_samples:
            return None

        reference_filename = random.choice(emotion_samples)
        reference_path = config.EMOTION_REFERENCES_DIR / reference_filename

        if not reference_path.exists():
            logger.warning(f"Файл-референс '{reference_path}' для эмоции '{emotion}' не найден.")
            return None
        return reference_path
