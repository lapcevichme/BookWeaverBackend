import time
import re
import logging
import os
from typing import Type, TypeVar, Optional, Tuple
from threading import Lock
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError
from utils.metrics import metrics_collector, LLMMetrics

load_dotenv()
logger = logging.getLogger(__name__)

PydanticModel = TypeVar("PydanticModel", bound=BaseModel)

PRICING_REGISTRY = {
    "xiaomi/mimo-v2-flash:free": {"input": 0.0, "output": 0.0}
}


class LLMService:
    """
    Централизованный класс для работы с LLM (Google Gemini или OpenRouter) через единый клиент OpenAI SDK.
    """

    def __init__(self, model_name: str, temperature: float = 0.5, provider: str = "google", api_key: str = None):
        self.model_name = model_name
        self.temperature = temperature
        self.provider = provider.lower()
        self.api_key = api_key
        self._client = None
        self._lock = Lock()

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0

        logger.info(
            f"Сервис LLMService сконфигурирован: провайдер '{self.provider}', модель '{self.model_name}'."
        )

    @property
    def client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from openai import OpenAI
                    if self.provider == "google":
                        api_key = self.api_key or os.getenv("GOOGLE_API_KEY")
                        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                    else:
                        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")
                        base_url = "https://openrouter.ai/api/v1"

                    self._client = OpenAI(base_url=base_url, api_key=api_key)
        return self._client

    def _track_usage(self, input_tokens: int, output_tokens: int):
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        price_info = PRICING_REGISTRY.get(self.model_name)
        if price_info:
            cost = (input_tokens / 1_000_000) * price_info["input"] + (output_tokens / 1_000_000) * price_info["output"]
            self.total_cost += cost

    def call_for_pydantic(self, pydantic_model: Type[PydanticModel], prompt: str, prompt_type: str = "unknown") -> Optional[PydanticModel]:
        start_time = time.time()
        response_text, usage = None, (0, 0)
        status = "success"
        error_msg = None

        try:
            response_text, usage = self._raw_call_llm(prompt)
            if not response_text:
                status = "api_error"
            else:
                result = self._process_response_text(response_text, pydantic_model)
                if not result:
                    status = "json_error"
                    logger.error(f"❌ JSON/Validation Error for {prompt_type}. Raw response: {response_text[:1000]}...")
                else:
                    return result
        except Exception as e:
            status = "api_error"
            error_msg = str(e)
            logger.error(f"LLM Call Error: {e}", exc_info=True)
        finally:
            latency_ms = (time.time() - start_time) * 1000
            metrics_collector.log_llm_call(LLMMetrics(
                prompt_type=prompt_type,
                model_name=self.model_name,
                input_tokens=usage[0],
                output_tokens=usage[1],
                latency_ms=latency_ms,
                status=status,
                error_message=error_msg
            ))
        return None

    def _raw_call_llm(self, prompt: str) -> Tuple[Optional[str], Tuple[int, int]]:
        max_retries = 3
        for attempt in range(max_retries):
            if attempt > 0:
                metrics_collector.increment("api_retries")
            try:
                kwargs = {
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                }
                if "gemma" not in self.model_name.lower():
                    kwargs["response_format"] = {"type": "json_object"}

                completion = self.client.chat.completions.create(**kwargs)
                usage = (0, 0)
                if completion.usage:
                    usage = (completion.usage.prompt_tokens, completion.usage.completion_tokens)
                    self._track_usage(*usage)

                content = completion.choices[0].message.content if completion.choices else None
                return content, usage
            except Exception as e:
                logger.warning(f"LLM API Call attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        return None, (0, 0)

    def _process_response_text(self, text: str, pydantic_model: Type[PydanticModel]) -> Optional[PydanticModel]:
        text = re.sub(r'[\x00-\x1F]', '', text)
        match = re.search(r'```json\s*(\{.*}|\[.*])\s*```', text, re.DOTALL) or re.search(r'(\{.*}|\[.*])', text, re.DOTALL)
        if not match:
            return None
        try:
            return pydantic_model.model_validate_json(match.group(1).strip())
        except ValidationError as ve:
            logger.error(f"❌ Pydantic Validation Error for {pydantic_model.__name__}: {ve}")
            return None
        except Exception as e:
            logger.error(f"❌ JSON Parsing Error: {e}")
            return None
