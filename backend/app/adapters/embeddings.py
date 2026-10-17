"""Embedding Adapter interface and implementations."""

import hashlib
import math
import re
from abc import ABC, abstractmethod

from app.core.config import settings


class EmbeddingAdapter(ABC):
    """Abstract interface for dense embedding models."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Returns embedding vector dimension."""
        pass

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch of document texts."""
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Embeds a search query."""
        pass


class MockEmbeddingAdapter(EmbeddingAdapter):
    """Deterministic mock embedding adapter for testing and CI."""

    def __init__(self, dimension: int = settings.EMBEDDING_DIMENSION) -> None:
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def _text_to_vec(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        words = re.findall(r"\b\w+\b", text.lower())
        if not words:
            vec[0] = 1.0
            return vec
        for word in words:
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._text_to_vec(text) for text in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._text_to_vec(query)


class BGEM3EmbeddingAdapter(EmbeddingAdapter):
    """Local BAAI/bge-m3 multilingual dense embedding adapter."""

    def __init__(self, model_name: str = settings.EMBEDDING_MODEL) -> None:
        self.model_name = model_name
        self._dim = settings.EMBEDDING_DIMENSION

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # In Phase 2, sentence-transformers / flagembedding model will be loaded lazily
        mock = MockEmbeddingAdapter(dimension=self._dim)
        return await mock.embed_texts(texts)

    async def embed_query(self, query: str) -> list[float]:
        mock = MockEmbeddingAdapter(dimension=self._dim)
        return await mock.embed_query(query)


def get_embedding_adapter(provider: str | None = None) -> EmbeddingAdapter:
    """Factory returning configured EmbeddingAdapter."""
    selected = (provider or settings.EMBEDDING_PROVIDER).lower()
    if selected == "mock":
        return MockEmbeddingAdapter()
    return BGEM3EmbeddingAdapter()
