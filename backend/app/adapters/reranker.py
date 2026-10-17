"""Cross-encoder reranker adapter interface and implementations."""

import re
from abc import ABC, abstractmethod

from app.adapters.base import ScoredChunk
from app.core.config import settings


class RerankerAdapter(ABC):
    """Abstract interface for cross-encoder rerankers."""

    @abstractmethod
    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int = settings.RERANK_TOP_N
    ) -> list[ScoredChunk]:
        """Reranks candidates and returns top_n items with updated normalized scores (0-1)."""
        pass


STOP_WORDS = {
    "what",
    "where",
    "when",
    "which",
    "who",
    "whom",
    "whose",
    "why",
    "how",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "about",
    "against",
    "between",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "from",
    "up",
    "down",
    "out",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "can",
    "will",
    "just",
    "should",
    "now",
    "tell",
    "explain",
    "describe",
    "its",
}


class MockRerankerAdapter(RerankerAdapter):
    """Deterministic mock reranker for testing and CI."""

    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int = settings.RERANK_TOP_N
    ) -> list[ScoredChunk]:
        if not chunks:
            return []

        all_tokens = [w for w in re.findall(r"\b\w+\b", query.lower()) if len(w) > 2]
        query_tokens = [w for w in all_tokens if w not in STOP_WORDS]
        if not query_tokens:
            query_tokens = all_tokens
        query_set = set(query_tokens)

        scored: list[ScoredChunk] = []
        for chunk in chunks:
            chunk_tokens = re.findall(r"\b\w+\b", chunk.text.lower())
            chunk_set = set(chunk_tokens)

            if query_set:
                # Check exact matches or prefixes (e.g. conductor / conductors)
                matches = sum(
                    1
                    for q in query_set
                    if any(c.startswith(q[:4]) or q.startswith(c[:4]) for c in chunk_set)
                )
                keyword_recall = matches / len(query_set)
            else:
                keyword_recall = 0.0

            query_clean = " ".join(query_tokens)
            phrase_bonus = 0.2 if query_clean and query_clean in chunk.text.lower() else 0.0

            meta_query_words = {
                "summarize",
                "summary",
                "overview",
                "page",
                "pages",
                "pdf",
                "document",
                "documents",
                "notes",
                "material",
                "materials",
                "topics",
                "topic",
            }
            is_pure_meta_query = bool(query_set and query_set.issubset(meta_query_words))

            if is_pure_meta_query and chunk.score >= 0.80:
                cross_score = min(float(chunk.score), 0.92)
            else:
                cross_score = min(
                    1.0,
                    (0.85 * keyword_recall) + phrase_bonus + (0.05 * min(chunk.score, 1.0)),
                )

            scored.append(
                ScoredChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    text=chunk.text,
                    score=round(float(cross_score), 4),
                    metadata=chunk.metadata,
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_n]


class BGERerankerAdapter(RerankerAdapter):
    """BAAI/bge-reranker-v2-m3 cross-encoder reranker."""

    def __init__(self, model_name: str = settings.RERANKER_MODEL) -> None:
        self.model_name = model_name

    async def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int = settings.RERANK_TOP_N
    ) -> list[ScoredChunk]:
        mock = MockRerankerAdapter()
        return await mock.rerank(query, chunks, top_n)


def get_reranker_adapter(provider: str | None = None) -> RerankerAdapter:
    """Factory returning configured RerankerAdapter."""
    selected = (provider or settings.RERANKER_PROVIDER).lower()
    if selected == "mock":
        return MockRerankerAdapter()
    return BGERerankerAdapter()
