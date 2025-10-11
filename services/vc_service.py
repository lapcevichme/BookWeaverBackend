"""
Сервис для Voice Conversion (VC).
Отвечает за применение эмоциональной окраски к существующим аудиофайлам,
используя референсные аудиозаписи для каждой эмоции.
"""

import json
import random
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from TTS.api import TTS
except ImportError:
    TTS = None

import config


class VCService:
    """
    Класс-сервис для управления процессом Voice Conversion.
    Использует ленивую загрузку модели для экономии ресурсов.
    """

    def __init__(self):
        self._vc_model = None
        self._emotion_library = self._load_emotion_library()
        print("✅ Сервис VCService (Voice Conversion) инициализирован.")

    def _load_emotion_library(self) -> Dict[str, Any]:
        """Загружает библиотеку эмоциональных референсов из JSON."""
        if not config.EMOTION_REFERENCE_LIBRARY_FILE.exists():
            print("  -> ⚠️ Файл библиотеки эмоциональных референсов не найден. Сервис не сможет работать.")
            return {}
        try:
            return json.loads(config.EMOTION_REFERENCE_LIBRARY_FILE.read_text("utf-8"))
        except Exception as e:
            print(f"  -> 🛑 ОШИБКА при чтении библиотеки эмоций: {e}")
            return {}

    def get_vc_model(self):
        """Ленивая загрузка модели VC."""
        if TTS is None:
            print("  -> ❌ КРИТИЧЕСКАЯ ОШИБКА: Библиотека coqui-tts не установлена. Voice Conversion невозможен.")
            return None

        if self._vc_model is None:
            print("  -> ⏳ Загружаю модель Voice Conversion (это может занять время)...")
            try:
                # ВАЖНО: Укажите правильное имя модели, если оно отличается
                self._vc_model = TTS(model_name="voice_conversion_models/multilingual/vctk/freevc24", progress_bar=True)
                print("  -> ✅ Модель VC успешно загружена.")
            except Exception as e:
                print(f"  -> ❌ КРИТИЧЕСКАЯ ОШИБКА при загрузке модели VC: {e}")
                return None
        return self._vc_model

    def find_reference_wav_for_emotion(self, emotion: str) -> Optional[Path]:
        """
        Находит случайный WAV-файл референса для указанной эмоции.
        Этот метод вызывается из VCPipeline.
        """
        emotion_samples = self._emotion_library.get(emotion)
        if not emotion_samples or not isinstance(emotion_samples, list):
            return None

        # Выбираем случайный файл из списка для данной эмоции
        reference_filename = random.choice(emotion_samples)
        reference_path = config.EMOTION_REFERENCES_DIR / reference_filename

        if not reference_path.exists():
            print(f"  -> ⚠️ Файл-референс '{reference_filename}' для эмоции '{emotion}' не найден по пути {reference_path}")
            return None

        return reference_path
