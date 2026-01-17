import os
from threading import Lock
from typing import Dict
from dotenv import load_dotenv

import config
from services.llm_service import LLMService
from services.vc_service import VCService

load_dotenv()

class ModelManager:
    """
    Централизованный менеджер для управления доступом к AI-сервисам.
    Гарантирует, что для каждого сервиса существует только один экземпляр.
    Вся логика Singleton находится здесь.
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

    def get_tts_service(self):
        """
        Возвращает сервис TTS.
        """
        service_key = "tts_service"
        if service_key not in self._services:
            from services.tts_service import TTSService
            self._services[service_key] = TTSService()
        return self._services[service_key]

    def get_vc_service(self) -> VCService:
        """Возвращает экземпляр VCService."""
        service_key = 'vc'
        if service_key not in self._services:
            with self._locks[service_key]:
                if service_key not in self._services:
                    self._services[service_key] = VCService(model_name=config.VC_MODEL_NAME)
        return self._services[service_key]

    def get_llm_service(self, service_type: str) -> LLMService:
        """
        Возвращает экземпляр LLMService для конкретной задачи.
        """
        provider = getattr(config, 'LLM_PROVIDER', 'google')

        api_key = None
        if provider == 'openrouter':
            api_key = os.getenv('OPENROUTER_API_KEY')
        elif provider == 'google':
            api_key = os.getenv('GOOGLE_API_KEY')

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
                    self._services[service_key] = LLMService(
                        model_name=model_name,
                        temperature=temperature,
                        provider=provider,
                        api_key=api_key
                    )
        return self._services[service_key]