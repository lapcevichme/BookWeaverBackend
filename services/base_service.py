import logging
from abc import ABC
from threading import Lock

logger = logging.getLogger(__name__)


class BaseTorchService(ABC):
    """
    Базовый класс для сервисов, использующих PyTorch (TTS, VC).
    Реализует общую логику определения устройства и ленивой инициализации.
    """

    def __init__(self):
        self._device = None
        self._service_lock = Lock()

    @property
    def device(self) -> str:
        """
        Ленивое определение устройства (CPU/CUDA).
        Безопасно импортирует torch только при первом обращении.
        """
        if self._device is None:
            try:
                import torch
                if torch.cuda.is_available():
                    self._device = "cuda"
                    logger.info("BaseTorchService: Обнаружена CUDA. Исипользуем GPU.")
                else:
                    self._device = "cpu"
                    logger.info("BaseTorchService: CUDA не найдена. Используем CPU.")
            except ImportError:
                logger.warning("BaseTorchService: PyTorch не найден. Устанавливаем device='cpu'.")
                self._device = "cpu"
        return self._device
