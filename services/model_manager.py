from threading import Lock
from typing import Dict

import config
from services.llm_service import LLMService
from services.tts_service import TTSService
from services.vc_service import VCService


class ModelManager:
    """
    Централизованный менеджер для управления доступом к AI-сервисам.
    Гарантирует, что для каждого сервиса существует только один экземпляр (Singleton),
    и инкапсулирует логику ленивой инициализации.
    Теперь полностью управляется через config.py.
    """

    def __init__(self):
        self._services: Dict[str, object] = {}
        self._locks: Dict[str, Lock] = {
            'tts': Lock(),
            'vc': Lock(),
            'llm_character_analyzer': Lock(),
            'llm_scenario_generator': Lock(),
            'llm_summary_generator': Lock(),
        }

    def get_tts_service(self) -> TTSService:
        """Возвращает singleton-экземпляр TTSService."""
        service_key = 'tts'
        if service_key not in self._services:
            with self._locks[service_key]:
                if service_key not in self._services:
                    self._services[service_key] = TTSService(model_name=config.TTS_MODEL_NAME)
        return self._services[service_key]

    def get_vc_service(self) -> VCService:
        """Возвращает singleton-экземпляр VCService."""
        service_key = 'vc'
        if service_key not in self._services:
            with self._locks[service_key]:
                if service_key not in self._services:
                    self._services[service_key] = VCService(model_name=config.VC_MODEL_NAME)
        return self._services[service_key]

    def get_llm_service(self, service_type: str) -> LLMService:
        """
        Возвращает singleton-экземпляр LLMService для конкретной задачи.
        """
        if service_type == 'character_analyzer':
            service_key = 'llm_character_analyzer'
            model_name = config.FAST_MODEL_NAME
            temperature = config.ANALYZER_LLM_TEMPERATURE
        elif service_type == 'scenario_generator':
            service_key = 'llm_scenario_generator'
            model_name = config.POWERFUL_MODEL_NAME
            temperature = config.GENERATOR_LLM_TEMPERATURE
        elif service_type == 'summary_generator':
            service_key = 'llm_summary_generator'
            model_name = config.FAST_MODEL_NAME
            temperature = config.SUMMARY_LLM_TEMPERATURE
        else:
            raise ValueError(f"Неизвестный тип LLM-сервиса: {service_type}")

        if service_key not in self._services:
            with self._locks[service_key]:
                if service_key not in self._services:
                    self._services[service_key] = LLMService(model_name=model_name, temperature=temperature)
        return self._services[service_key]
