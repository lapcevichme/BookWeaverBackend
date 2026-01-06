import time
import re
import logging
import os
from typing import Type, TypeVar, Optional
from threading import Lock
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()
logger = logging.getLogger(__name__)

PydanticModel = TypeVar("PydanticModel", bound=BaseModel)


class LLMService:
    """
    Централизованный класс для работы с LLM (Google Gemini или OpenRouter) с ленивой инициализацией.
    Принимает api_key явно, чтобы не зависеть жестко от окружения внутри класса.
    """

    def __init__(self, model_name: str, temperature: float = 0.5, provider: str = "google", api_key: str = None):
        self.model_name = model_name
        self.temperature = temperature
        self.provider = provider.lower()
        self.api_key = api_key
        self._model = None
        self._client = None
        self._config = None
        self._lock = Lock()
        logger.info(
            f"Сервис LLMService сконфигурирован: провайдер '{self.provider}', модель '{self.model_name}' (ленивая загрузка).")

    @property
    def model(self):
        """Ленивая инициализация клиента."""
        if self.provider == "google":
            return self._init_google_model()
        elif self.provider == "openrouter":
            return self._init_openrouter_client()
        else:
            logger.error(f"Неизвестный провайдер: {self.provider}")
            return None

    def _init_google_model(self):
        """Инициализация Google Gemini."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        import google.generativeai as genai
                    except ImportError:
                        logger.critical("❌ Библиотека 'google-generativeai' не установлена!")
                        return None

                    api_key = self.api_key or os.getenv("GOOGLE_API_KEY")
                    if api_key:
                        genai.configure(api_key=api_key)
                    else:
                        logger.warning(
                            "⚠️ Google API Key не передан и не найден в ENV. Библиотека попытается найти его сама.")

                    logger.info(f"⏳ Инициализация клиента Google Gemini для модели: {self.model_name}...")
                    try:
                        self._model = genai.GenerativeModel(self.model_name)
                        logger.info(f"✅ Клиент Google для модели '{self.model_name}' успешно инициализирован.")
                    except Exception as e:
                        logger.error(f"Ошибка при создании GenerativeModel: {e}", exc_info=True)
                        return None
        return self._model

    def _init_openrouter_client(self):
        """Инициализация клиента OpenAI для OpenRouter."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        from openai import OpenAI
                    except ImportError:
                        logger.critical("❌ Библиотека 'openai' не установлена! (Нужна для OpenRouter)")
                        return None

                    api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")

                    if not api_key:
                        logger.critical("❌ Не найден API Key для OpenRouter (ни передан, ни в ENV)!")
                        return None

                    logger.info(f"⏳ Инициализация клиента OpenRouter для модели: {self.model_name}...")
                    try:
                        self._client = OpenAI(
                            base_url="https://openrouter.ai/api/v1",
                            api_key=api_key,
                        )
                        logger.info(f"✅ Клиент OpenRouter для модели '{self.model_name}' успешно инициализирован.")
                    except Exception as e:
                        logger.error(f"Ошибка при создании клиента OpenAI: {e}", exc_info=True)
                        return None
        return self._client

    @property
    def generation_config(self):
        """Ленивое создание конфигурации (только для Google)."""
        if self.provider != "google":
            return None

        if self._config is None:
            try:
                from google.generativeai.types import GenerationConfig
                gen_config_args = {
                    "temperature": self.temperature
                }

                if "gemma" not in self.model_name.lower():
                    gen_config_args["response_mime_type"] = "application/json"

                self._config = GenerationConfig(**gen_config_args)
            except ImportError:
                return None
        return self._config

    def _sanitize_json_string(self, raw_text: str) -> str:
        """Очищает строку от невидимых управляющих символов."""
        control_char_regex = re.compile(r'[\x00-\x1F]')
        return control_char_regex.sub('', raw_text)

    def _extract_json_from_response(self, text: str) -> Optional[str]:
        """Извлекает первый валидный JSON из ответа."""
        match = re.search(r'```json\s*(\{.*}|\[.*])\s*```', text, re.DOTALL)
        if match: return match.group(1).strip()
        match = re.search(r'(\{.*}|\[.*])', text, re.DOTALL)
        if match: return match.group(1).strip()
        return None

    def call_for_pydantic(self, pydantic_model: Type[PydanticModel], prompt: str) -> Optional[PydanticModel]:
        """Основной метод. Вызывает LLM и пытается распарсить ответ в Pydantic-модель."""

        logger.debug(
            f"--- PROMPT SENT TO '{self.model_name}' (Provider: {self.provider}) ---\n{prompt}\n---------------------------------")

        if self.provider == "openrouter":
            return self._call_openrouter(pydantic_model, prompt)
        else:
            return self._call_google(pydantic_model, prompt)

    def _call_google(self, pydantic_model: Type[PydanticModel], prompt: str) -> Optional[PydanticModel]:
        try:
            from google.api_core import exceptions
            from google.generativeai.types import RequestOptions
        except ImportError:
            logger.critical("Необходимые библиотеки Google AI не найдены.")
            return None

        if not self.model or not self.generation_config:
            logger.error("LLM сервис (Google) не был инициализирован корректно.")
            return None

        logger.info(f"Вызов Google LLM для Pydantic-модели: {pydantic_model.__name__}")

        response_text = None
        max_retries = 3

        for attempt in range(max_retries):
            try:
                request_options = RequestOptions(timeout=120)
                response = self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config,
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
                    if hasattr(response, 'prompt_feedback') and hasattr(response.prompt_feedback, 'block_reason'):
                        block_reason = response.prompt_feedback.block_reason.name
                    logger.error(f"Запрос к LLM заблокирован! Причина: {block_reason}. Прекращаю попытки.")
                    return None

                response_text = response.text
                logger.info("Ответ от Google LLM успешно получен.")
                break

            except exceptions.ResourceExhausted as e:
                match = re.search(r"Please retry in ([\d.]+)s", str(e))
                if match:
                    delay = float(match.group(1)) + 1
                    logger.warning(f"Ошибка квоты API (429). Ждем {delay:.2f} сек.")
                    time.sleep(delay)
                else:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Ошибка квоты API (429). Повтор через {wait_time} сек.")
                    time.sleep(wait_time)
            except Exception as e:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"Ошибка API Gemini: {e}. Повтор через {wait_time} сек.", exc_info=True)
                time.sleep(wait_time)

        return self._process_response_text(response_text, pydantic_model)

    def _call_openrouter(self, pydantic_model: Type[PydanticModel], prompt: str) -> Optional[PydanticModel]:
        try:
            import openai
        except ImportError:
            logger.critical("Библиотека OpenAI не найдена.")
            return None

        client = self.model
        if not client:
            logger.error("LLM сервис (OpenRouter) не был инициализирован корректно.")
            return None

        logger.info(f"Вызов OpenRouter для Pydantic-модели: {pydantic_model.__name__}")

        response_text = None
        max_retries = 3

        for attempt in range(max_retries):
            try:
                completion = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that outputs strictly JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.temperature,
                    response_format={"type": "json_object"}
                )

                response_text = completion.choices[0].message.content
                logger.info("Ответ от OpenRouter успешно получен.")
                break

            except openai.RateLimitError as e:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"OpenRouter Rate Limit (429). Повтор через {wait_time} сек.")
                time.sleep(wait_time)
            except openai.APIError as e:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"Ошибка API OpenRouter: {e}. Повтор через {wait_time} сек.")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"Неизвестная ошибка OpenRouter: {e}", exc_info=True)
                break

        return self._process_response_text(response_text, pydantic_model)

    def _process_response_text(self, response_text: str, pydantic_model: Type[PydanticModel]) -> Optional[
        PydanticModel]:
        if not response_text:
            logger.error(f"Не удалось получить ответ от модели '{self.model_name}'.")
            return None

        logger.debug(
            f"--- RAW RESPONSE FROM '{self.model_name}' ---\n{response_text}\n---------------------------------")

        json_str = self._extract_json_from_response(self._sanitize_json_string(response_text))
        if not json_str:
            logger.error("Не удалось извлечь JSON из ответа модели.", extra={"full_response": response_text})
            return None

        try:
            return pydantic_model.model_validate_json(json_str)
        except ValidationError as e:
            logger.error(f"ОШИБКА ВАЛИДАЦИИ Pydantic для {pydantic_model.__name__}.",
                         extra={"pydantic_error": str(e), "invalid_json": json_str})
            return None
