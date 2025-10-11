"""
Сервис для инкапсуляции всех взаимодействий с языковыми моделями (LLM).
"""
import time
import re
from typing import Type, TypeVar, Optional
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, RequestOptions
from pydantic import BaseModel, ValidationError

# Загружаем переменные окружения, в первую очередь GEMINI_API_KEY
load_dotenv()

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
            response_mime_type="application/json" # Исправлено на правильный MIME-тип
        )
        self.model = genai.GenerativeModel(self.model_name)
        print(f"✅ Сервис LLMService для модели '{self.model_name}' инициализирован.")

    def _sanitize_json_string(self, raw_text: str) -> str:
        """
        Очищает строку от невидимых управляющих символов, которые ломают JSON.
        """
        # Regex для поиска управляющих символов (от U+0000 до U+001F)
        control_char_regex = re.compile(r'[\x00-\x1F]')
        return control_char_regex.sub('', raw_text)

    def _extract_json_from_response(self, text: str) -> Optional[str]:
        """
        Находит и извлекает первый валидный JSON-объект из текстового ответа модели.
        """
        # Ищем JSON, заключенный в ```json ... ```
        match = re.search(r'```json\s*(\{.*}|\[.*])\s*```', text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Если не нашли, ищем первый подходящий JSON-объект в тексте
        match = re.search(r'(\{.*}|\[.*])', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def call_for_pydantic(self, pydantic_model: Type[PydanticModel], prompt: str) -> Optional[PydanticModel]:
        """
        Основной метод. Вызывает LLM и пытается распарсить ответ в Pydantic-модель.
        """
        print(f"\\n--- [LLMService] -> [Модель: {self.model_name}] ---")
        print(f"    - Размер промпта: ~{len(prompt)} символов")

        response_text = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"    - Отправка запроса (попытка {attempt + 1}/{max_retries})...")

                # Используем специальный тип RequestOptions для большей надежности
                request_options = RequestOptions(timeout=120)

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
                print("    - ✅ Ответ успешно получен.")

                # Улучшенная проверка на заблокированный контент
                if not response.candidates:
                    block_reason = "Unknown"
                    if response.prompt_feedback:
                         block_reason = response.prompt_feedback.block_reason
                    print(f"    - ❌ ЗАПРОС ЗАБЛОКИРОВАН! Причина: {block_reason}. Прекращаю попытки.")
                    return None

                response_text = response.text
                break # Успех, выходим из цикла ретраев

            except Exception as e:
                print(f"    - ⚠️ Ошибка API: {e}. Повторная попытка через {2 ** attempt * 2} сек.")
                time.sleep(2 ** attempt * 2)

        if not response_text:
            print(f"    - ❌ Не удалось получить ответ от модели после {max_retries} попыток.")
            return None

        # 1. САНАТИЗАЦИЯ ответа
        sanitized_text = self._sanitize_json_string(response_text)

        # 2. Извлечение JSON
        json_str = self._extract_json_from_response(sanitized_text)

        if not json_str:
            print("    - ❌ Не удалось извлечь JSON из ответа модели.")
            print(f"      -> Ответ модели (первые 200 символов): {response_text[:200]}...")
            return None

        # 3. Валидация через Pydantic
        try:
            validated_obj = pydantic_model.model_validate_json(json_str)
            print("    - ✅ JSON-ответ успешно валидирован по Pydantic-модели.")
            return validated_obj
        except ValidationError as e:
            print("    - ❌ ОШИБКА ВАЛИДАЦИИ Pydantic: Ответ модели не соответствует схеме.")
            print(e)
            return None


