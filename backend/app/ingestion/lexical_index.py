"""Lexical BM25 Search Indexer per TECH_REQUIREMENTS.md §2."""

import re
from typing import Any

from rank_bm25 import BM25Plus  # type: ignore[import-untyped]

from app.adapters.base import ScoredChunk


class LexicalIndex:
    """In-memory BM25 lexical index supporting multi-tenant filtering."""

    def __init__(self) -> None:
        # Key: chunk_id -> dict of metadata & tokenized words
        self._chunks: dict[str, dict[str, Any]] = {}
        self._corpus: list[list[str]] = []
        self._chunk_ids: list[str] = []
        self._bm25: BM25Plus | None = None

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Simple lowercase word tokenizer."""
        return re.findall(r"\b\w+\b", text.lower())

    def index_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """Indexes a batch of chunks into the BM25 corpus."""
        for c in chunks:
            cid = c["chunk_id"]
            self._chunks[cid] = c

        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._chunk_ids = list(self._chunks.keys())
        self._corpus = [self.tokenize(self._chunks[cid].get("text", "")) for cid in self._chunk_ids]
        if self._corpus and any(len(doc) > 0 for doc in self._corpus):
            self._bm25 = BM25Plus(self._corpus)
        else:
            self._bm25 = None

    def search(
        self,
        query: str,
        user_id: str,
        workspace_id: str,
        document_ids: list[str] | None = None,
        top_k: int = 30,
    ) -> list[ScoredChunk]:
        """Performs BM25 search strictly scoped by user_id and workspace_id."""
        if not self._bm25 or not self._chunk_ids:
            return []

        tokens = self.tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        max_score = max(scores) if len(scores) > 0 and max(scores) > 0 else 1.0

        results: list[ScoredChunk] = []
        for cid, raw_score in zip(self._chunk_ids, scores, strict=False):
            if raw_score <= 0:
                continue

            meta = self._chunks[cid]
            # Strict multi-tenant isolation filter
            if meta.get("user_id") != user_id:
                continue
            if meta.get("workspace_id") != workspace_id:
                continue
            if document_ids and meta.get("document_id") not in document_ids:
                continue

            normalized_score = float(raw_score / max_score)
            results.append(
                ScoredChunk(
                    chunk_id=cid,
                    document_id=meta.get("document_id", ""),
                    page_start=meta.get("page_start", 1),
                    page_end=meta.get("page_end", 1),
                    text=meta.get("text", ""),
                    score=normalized_score,
                    metadata=meta,
                )
            )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def delete_by_document(self, document_id: str, user_id: str) -> None:
        to_del = [
            cid
            for cid, meta in self._chunks.items()
            if meta.get("document_id") == document_id and meta.get("user_id") == user_id
        ]
        for cid in to_del:
            del self._chunks[cid]
        self._rebuild_index()

    def delete_by_user(self, user_id: str) -> None:
        to_del = [cid for cid, meta in self._chunks.items() if meta.get("user_id") == user_id]
        for cid in to_del:
            del self._chunks[cid]
        self._rebuild_index()


# Global in-process lexical index instance
lexical_index = LexicalIndex()
