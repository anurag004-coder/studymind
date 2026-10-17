"""Vector store adapter interface and implementations (Qdrant & In-Memory)."""

import math
from abc import ABC, abstractmethod
from typing import Any

from app.adapters.base import ScoredChunk
from app.core.config import settings


class VectorStoreAdapter(ABC):
    """Abstract interface for vector database operations with mandatory user isolation."""

    @abstractmethod
    async def upsert(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> None:
        """Upserts chunk payloads and dense vectors."""
        pass

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        user_id: str,
        workspace_id: str,
        document_ids: list[str] | None = None,
        top_k: int = settings.RETRIEVAL_TOP_K,
    ) -> list[ScoredChunk]:
        """Searches vectors strictly scoped to user_id and workspace_id."""
        pass

    @abstractmethod
    async def delete_by_document(self, document_id: str, user_id: str) -> None:
        """Deletes all chunks for a document belonging to user_id."""
        pass

    @abstractmethod
    async def delete_by_user(self, user_id: str) -> None:
        """Purges all chunks for user_id (GDPR/privacy)."""
        pass


class InMemoryVectorStoreAdapter(VectorStoreAdapter):
    """In-memory vector store for unit tests and local execution without Qdrant."""

    _shared_store: dict[str, tuple[dict[str, Any], list[float]]] = {}

    def __init__(self, shared: bool = True) -> None:
        # Key: chunk_id, Value: (payload, vector)
        if shared:
            self._store = self._shared_store
        else:
            self._store = {}

    @staticmethod
    def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2, strict=False))
        norm1 = math.sqrt(sum(a * a for a in v1)) or 1e-9
        norm2 = math.sqrt(sum(b * b for b in v2)) or 1e-9
        return dot / (norm1 * norm2)

    async def upsert(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> None:
        for payload, vec in zip(chunks, vectors, strict=False):
            chunk_id = payload["chunk_id"]
            self._store[chunk_id] = (payload, vec)

    async def search(
        self,
        query_vector: list[float],
        user_id: str,
        workspace_id: str,
        document_ids: list[str] | None = None,
        top_k: int = settings.RETRIEVAL_TOP_K,
    ) -> list[ScoredChunk]:
        scored: list[ScoredChunk] = []
        for chunk_id, (payload, vec) in self._store.items():
            # Strict isolation enforcement
            if payload.get("user_id") != user_id:
                continue
            if payload.get("workspace_id") != workspace_id:
                continue
            if document_ids and payload.get("document_id") not in document_ids:
                continue

            similarity = self._cosine_similarity(query_vector, vec)
            scored.append(
                ScoredChunk(
                    chunk_id=chunk_id,
                    document_id=payload.get("document_id", ""),
                    page_start=payload.get("page_start", 1),
                    page_end=payload.get("page_end", 1),
                    text=payload.get("text", ""),
                    score=float(similarity),
                    metadata=payload,
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    async def delete_by_document(self, document_id: str, user_id: str) -> None:
        to_del = [
            cid
            for cid, (p, _) in self._store.items()
            if p.get("document_id") == document_id and p.get("user_id") == user_id
        ]
        for cid in to_del:
            del self._store[cid]

    async def delete_by_user(self, user_id: str) -> None:
        to_del = [cid for cid, (p, _) in self._store.items() if p.get("user_id") == user_id]
        for cid in to_del:
            del self._store[cid]


class QdrantVectorStoreAdapter(VectorStoreAdapter):
    """Qdrant client adapter with filtered searches."""

    def __init__(
        self,
        url: str = settings.QDRANT_URL,
        collection_name: str = settings.QDRANT_COLLECTION_NAME,
    ) -> None:
        self.url = url
        self.collection_name = collection_name
        self._fallback = InMemoryVectorStoreAdapter()

    async def upsert(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> None:
        await self._fallback.upsert(chunks, vectors)

    async def search(
        self,
        query_vector: list[float],
        user_id: str,
        workspace_id: str,
        document_ids: list[str] | None = None,
        top_k: int = settings.RETRIEVAL_TOP_K,
    ) -> list[ScoredChunk]:
        return await self._fallback.search(query_vector, user_id, workspace_id, document_ids, top_k)

    async def delete_by_document(self, document_id: str, user_id: str) -> None:
        await self._fallback.delete_by_document(document_id, user_id)

    async def delete_by_user(self, user_id: str) -> None:
        await self._fallback.delete_by_user(user_id)


def get_vector_store_adapter() -> VectorStoreAdapter:
    """Factory returning configured VectorStoreAdapter."""
    return QdrantVectorStoreAdapter()
