import logging
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CosyVoiceClient:
    """
    Клиент для взаимодействия с CosyVoice API, запущенным в Docker.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.tts_endpoint = f"{self.base_url}/api/tts"

    def check_health(self) -> bool:
        """Проверяет доступность сервиса."""
        try:
            resp = requests.get(f"{self.base_url}/api/status", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def synthesize(
            self,
            text: str,
            prompt_wav_path: Path,
            prompt_text: str,
            mode: str = "zero_shot",
            instruct_text: str = "",
            speed: float = 1.0
    ) -> Optional[bytes]:
        """
        Отправляет запрос на синтез речи.

        Args:
            text: Текст для озвучки.
            prompt_wav_path: Путь к референсному аудио (голос).
            prompt_text: Текст референса.
            mode: Режим (zero_shot).
            instruct_text: Инструкция для эмоций (например, "Angry", "Happy", "Whisper").
            speed: Скорость речи.
        """
        if not prompt_wav_path.exists():
            logger.error(f"Референс голоса не найден: {prompt_wav_path}")
            return None

        files = {
            'prompt_wav': (prompt_wav_path.name, open(prompt_wav_path, 'rb'), 'audio/wav')
        }

        data = {
            'text': text,
            'mode': mode,
            'prompt_text': prompt_text,
            'instruct_text': instruct_text,
            'speed': speed,
            'stream': 'false'
        }

        try:
            logger.debug(f"Запрос CosyVoice. Text: {len(text)} chars | Instruct: '{instruct_text}'")
            response = requests.post(self.tts_endpoint, data=data, files=files, timeout=60)

            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Ошибка API CosyVoice ({response.status_code}): {response.text}")
                return None

        except requests.exceptions.ConnectionError:
            logger.critical(f"Не удалось подключиться к CosyVoice ({self.base_url}).")
            return None
        except Exception as e:
            logger.error(f"Исключение при запросе к CosyVoice: {e}", exc_info=True)
            return None
        finally:
            files['prompt_wav'][1].close()