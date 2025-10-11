"""
Сервис для инкапсуляции всех взаимодействий с языковыми моделями (LLM).
"""
import time
import re
import logging
from typing import Type, TypeVar, Optional

from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, RequestOptions
from pydantic import BaseModel, ValidationError

# Загружаем переменные окружения, в первую очередь GEMINI_API_KEY
load_dotenv()

# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)

# Определяем Generic Type для Pydantic моделей
PydanticModel = TypeVar("PydanticModel", bound=BaseModel)


class LLMService:
    """
    Централизованный класс для работы с API Google Gemini.
    Обрабатывает вызовы, повторные попытки, парсинг JSON и валидацию.
    """

    def __init__(self, model_name: str, temperature: float = 0.5):
        """
        Инициализирует сервис с конкретной моделью.
        """
        self.model_name = model_name
        self.config = GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json"
        )
        self.model = genai.GenerativeModel(self.model_name)
        logger.info(f"Сервис LLMService для модели '{self.model_name}' инициализирован.")

    def _sanitize_json_string(self, raw_text: str) -> str:
        """
        Очищает строку от невидимых управляющих символов, которые могут сломать JSON.
        """
        control_char_regex = re.compile(r'[\x00-\x1F]')
        sanitized_text = control_char_regex.sub('', raw_text)
        if len(raw_text) != len(sanitized_text):
            logger.debug("Обнаружены и удалены управляющие символы из ответа LLM.")
        return sanitized_text

    def _extract_json_from_response(self, text: str) -> Optional[str]:
        """
        Находит и извлекает первый валидный JSON-объект из текстового ответа модели.
        """
        # Ищем JSON, заключенный в ```json ... ```
        match = re.search(r'```json\s*(\{.*}|\[.*])\s*```', text, re.DOTALL)
        if match:
            logger.debug("JSON извлечен из блока ```json ... ```")
            return match.group(1).strip()

        # Если не нашли, ищем первый подходящий JSON-объект в тексте
        match = re.search(r'(\{.*}|\[.*])', text, re.DOTALL)
        if match:
            logger.debug("JSON извлечен из 'сырого' текста ответа.")
            return match.group(1).strip()

        logger.error("Не удалось найти JSON в ответе модели.")
        return None

    def call_for_pydantic(self, pydantic_model: Type[PydanticModel], prompt: str) -> Optional[PydanticModel]:
        """
        Основной метод. Вызывает LLM и пытается распарсить ответ в Pydantic-модель.
        """
        logger.info(f"Вызов LLM (модель: {self.model_name}) для Pydantic-модели: {pydantic_model.__name__}")
        logger.debug(f"Размер промпта: ~{len(prompt)} символов")

        response_text = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Отправка запроса к LLM... (Попытка {attempt + 1}/{max_retries})")

                request_options = RequestOptions(timeout=120) # Устанавливаем таймаут 2 минуты

                response = self.model.generate_content(
                    prompt,
                    generation_config=self.config,
                    safety_settings={
                        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                        'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                        'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
                    },
                    request_options=request_options
                )

                if not response.candidates:
                    block_reason = "Причина неизвестна"
                    if response.prompt_feedback and hasattr(response.prompt_feedback, 'block_reason'):
                         block_reason = response.prompt_feedback.block_reason.name
                    logger.error(f"Запрос к LLM заблокирован! Причина: {block_reason}. Прекращаю попытки.")
                    return None

                response_text = response.text
                logger.info("Ответ от LLM успешно получен.")
                break

            except Exception as e:
                wait_time = 2 ** attempt * 2
                logger.warning(f"Ошибка при вызове API Gemini: {e}. Повторная попытка через {wait_time} сек.", exc_info=True)
                time.sleep(wait_time)

        if not response_text:
            logger.error(f"Не удалось получить ответ от модели '{self.model_name}' после {max_retries} попыток.")
            return None

        sanitized_text = self._sanitize_json_string(response_text)
        json_str = self._extract_json_from_response(sanitized_text)

        if not json_str:
            logger.error("Не удалось извлечь JSON из ответа модели.")
            logger.debug(f"Полный ответ модели (проблема с JSON): \n{response_text}")
            return None

        try:
            validated_obj = pydantic_model.model_validate_json(json_str)
            logger.info(f"JSON-ответ успешно валидирован по модели {pydantic_model.__name__}.")
            return validated_obj
        except ValidationError as e:
            logger.error(f"ОШИБКА ВАЛИДАЦИИ Pydantic для модели {pydantic_model.__name__}. Ответ модели не соответствует схеме.")
            # Логируем детали ошибки и проблемный JSON для легкой отладки
            logger.debug(f"Детали ошибки Pydantic: {e}")
            logger.debug(f"JSON, вызвавший ошибку: \n{json_str}")
            return None
