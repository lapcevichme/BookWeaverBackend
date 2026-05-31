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
    "xiaomi/mimo-v2-flash:free" : {"input": 0.0, "output": 0.0}
}

class LLMService:
    """
    Централизованный класс для работы с LLM (Google Gemini или OpenRouter) с ленивой инициализацией.
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

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0

        logger.info(
            f"Сервис LLMService сконфигурирован: провайдер '{self.provider}', модель '{self.model_name}' (ленивая загрузка).")

    @property
    def model(self):
        if self.provider == "google":
            return self._init_google_model()
        elif self.provider == "openrouter":
            return self._init_openrouter_client()
        return None

    def _init_google_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    import google.generativeai as genai
                    api_key = self.api_key or os.getenv("GOOGLE_API_KEY")
                    if api_key:
                        genai.configure(api_key=api_key)
                    self._model = genai.GenerativeModel(self.model_name)
        return self._model

    def _init_openrouter_client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from openai import OpenAI
                    api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")
                    self._client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        return self._client

    @property
    def generation_config(self):
        if self.provider != "google": return None
        if self._config is None:
            from google.generativeai.types import GenerationConfig
            gen_config_args = {"temperature": self.temperature}
            if "gemma" not in self.model_name.lower():
                gen_config_args["response_mime_type"] = "application/json"
            self._config = GenerationConfig(**gen_config_args)
        return self._config

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
            if self.provider == "openrouter":
                response_text, usage = self._raw_call_openrouter(prompt)
            else:
                response_text, usage = self._raw_call_google(prompt)
            
            if not response_text:
                status = "api_error"
            else:
                result = self._process_response_text(response_text, pydantic_model)
                if not result:
                    status = "json_error"
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

    def _raw_call_google(self, prompt: str) -> Tuple[Optional[str], Tuple[int, int]]:
        from google.api_core import exceptions
        from google.generativeai.types import RequestOptions
        
        max_retries = 3
        for attempt in range(max_retries):
            if attempt > 0: metrics_collector.increment("api_retries")
            try:
                response = self.model.generate_content(
                    prompt, 
                    generation_config=self.generation_config,
                    request_options=RequestOptions(timeout=120)
                )
                if not response.candidates: return None, (0, 0)
                
                usage = (0, 0)
                if hasattr(response, 'usage_metadata'):
                    usage = (response.usage_metadata.prompt_token_count, response.usage_metadata.candidates_token_count)
                    self._track_usage(*usage)
                
                return response.text, usage
            except exceptions.ResourceExhausted:
                time.sleep(5)
            except Exception:
                time.sleep(2)
        return None, (0, 0)

    def _raw_call_openrouter(self, prompt: str) -> Tuple[Optional[str], Tuple[int, int]]:
        max_retries = 3
        for attempt in range(max_retries):
            if attempt > 0: metrics_collector.increment("api_retries")
            try:
                completion = self.model.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    response_format={"type": "json_object"}
                )
                usage = (0, 0)
                if completion.usage:
                    usage = (completion.usage.prompt_tokens, completion.usage.completion_tokens)
                    self._track_usage(*usage)
                return completion.choices[0].message.content, usage
            except Exception:
                time.sleep(2)
        return None, (0, 0)

    def _process_response_text(self, text: str, pydantic_model: Type[PydanticModel]) -> Optional[PydanticModel]:
        # Очистка JSON
        text = re.sub(r'[\x00-\x1F]', '', text)
        match = re.search(r'```json\s*(\{.*}|\[.*])\s*```', text, re.DOTALL) or re.search(r'(\{.*}|\[.*])', text, re.DOTALL)
        if not match: return None
        try:
            return pydantic_model.model_validate_json(match.group(1).strip())
        except ValidationError:
            return None
