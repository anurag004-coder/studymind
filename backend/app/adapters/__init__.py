"""Adapters package exporting all interfaces and factories."""

from app.adapters.base import LLMResponse, ScoredChunk
from app.adapters.embeddings import (
    BGEM3EmbeddingAdapter,
    EmbeddingAdapter,
    MockEmbeddingAdapter,
    get_embedding_adapter,
)
from app.adapters.llm import GeminiLLMAdapter, LLMAdapter, MockLLMAdapter, get_llm_adapter
from app.adapters.reranker import (
    BGERerankerAdapter,
    MockRerankerAdapter,
    RerankerAdapter,
    get_reranker_adapter,
)
from app.adapters.storage import (
    LocalStorageAdapter,
    S3StorageAdapter,
    StorageAdapter,
    get_storage_adapter,
)
from app.adapters.vectorstore import (
    InMemoryVectorStoreAdapter,
    QdrantVectorStoreAdapter,
    VectorStoreAdapter,
    get_vector_store_adapter,
)

__all__ = [
    "LLMResponse",
    "ScoredChunk",
    "LLMAdapter",
    "MockLLMAdapter",
    "GeminiLLMAdapter",
    "get_llm_adapter",
    "EmbeddingAdapter",
    "MockEmbeddingAdapter",
    "BGEM3EmbeddingAdapter",
    "get_embedding_adapter",
    "RerankerAdapter",
    "MockRerankerAdapter",
    "BGERerankerAdapter",
    "get_reranker_adapter",
    "VectorStoreAdapter",
    "InMemoryVectorStoreAdapter",
    "QdrantVectorStoreAdapter",
    "get_vector_store_adapter",
    "StorageAdapter",
    "LocalStorageAdapter",
    "S3StorageAdapter",
    "get_storage_adapter",
]
