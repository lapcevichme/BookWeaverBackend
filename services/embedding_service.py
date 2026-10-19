import os
import math
import logging
from typing import List, Optional, Tuple, Any, Dict
from threading import Lock
from dotenv import load_dotenv

import config

load_dotenv()
logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Легковесный сервис для генерации и сравнения текстовых эмбеддингов через OpenRouter / OpenAI API.
    Используется для дедупликации персонажей и семантического поиска.
    """

    def __init__(self, model_name: str = "openai/text-embedding-3-small"):
        self.model_name = model_name
        self._client = None
        self._lock = Lock()
        self._cache: Dict[str, List[float]] = {}

    @property
    def client(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from openai import OpenAI
                    provider = getattr(config, "LLM_PROVIDER", "openrouter").lower()
                    if provider == "openrouter":
                        api_key = getattr(config, "OPENROUTER_API_KEY", None) or os.getenv("OPENROUTER_API_KEY")
                        base_url = "https://openrouter.ai/api/v1"
                    else:
                        api_key = getattr(config, "GOOGLE_API_KEY", None) or os.getenv("GOOGLE_API_KEY")
                        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                    
                    self._client = OpenAI(base_url=base_url, api_key=api_key)
        return self._client

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Возвращает нормализованный вектор для строки текста."""
        clean_text = text.strip()
        if not clean_text:
            return None

        if clean_text in self._cache:
            return self._cache[clean_text]

        results = self.get_embeddings([clean_text])
        if results and results[0]:
            return results[0]
        return None

    def get_embeddings(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Пакетное получение эмбеддингов для списка текстов."""
        if not texts:
            return []

        clean_texts = [t.strip() for t in texts]
        results: List[Optional[List[float]]] = [None] * len(clean_texts)
        uncached_indices = []
        uncached_texts = []

        for idx, text in enumerate(clean_texts):
            if not text:
                continue
            if text in self._cache:
                results[idx] = self._cache[text]
            else:
                uncached_indices.append(idx)
                uncached_texts.append(text)

        if uncached_texts:
            try:
                response = self.client.embeddings.create(
                    model=self.model_name,
                    input=uncached_texts
                )
                for i, item in enumerate(response.data):
                    vec = item.embedding
                    orig_idx = uncached_indices[i]
                    results[orig_idx] = vec
                    self._cache[uncached_texts[i]] = vec
            except Exception as e:
                logger.error(f"Ошибка получения эмбеддингов через {self.model_name}: {e}", exc_info=True)

        return results

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Вычисляет косинусное сходство между двумя векторами (значение от -1.0 до 1.0)."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def find_most_similar(
        self,
        target_vec: List[float],
        candidates: List[Tuple[Any, List[float]]],
        threshold: float = 0.75
    ) -> Optional[Tuple[Any, float]]:
        """
        Ищет наилучшее совпадение для target_vec среди списка пар (entity, vector).
        Возвращает (entity, similarity) если сходство >= threshold, иначе None.
        """
        best_match = None
        best_score = -1.0

        for entity, vec in candidates:
            if not vec:
                continue
            score = self.cosine_similarity(target_vec, vec)
            if score > best_score:
                best_score = score
                best_match = entity

        if best_score >= threshold:
            return best_match, best_score
        return None
