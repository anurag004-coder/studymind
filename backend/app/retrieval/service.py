"""Comprehensive hybrid retrieval pipeline service coordinating dense, lexical,
fusion, reranking, and gating.
"""

import json
import re
import time

from pydantic import BaseModel
from sqlalchemy import select

from app.adapters import (
    EmbeddingAdapter,
    RerankerAdapter,
    VectorStoreAdapter,
    get_embedding_adapter,
    get_reranker_adapter,
    get_vector_store_adapter,
)
from app.adapters.base import ScoredChunk
from app.adapters.observability import get_observability_adapter
from app.core.cache import app_cache
from app.core.config import settings
from app.core.logging import logger
from app.db.models import Chunk, Document
from app.db.session import AsyncSessionLocal
from app.ingestion.lexical_index import LexicalIndex, lexical_index
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.gate import GateDecision, RelevanceGate
from app.retrieval.query_rewrite import QueryRewriter


class RetrievalTrace(BaseModel):
    """Detailed trace metadata for observability and evaluation."""

    duration_ms: float
    query_rewrite_ms: float
    retrieval_ms: float
    rerank_ms: float
    original_query: str
    rewritten_queries: list[str]
    dense_candidates_count: int
    lexical_candidates_count: int
    fused_candidates_count: int
    reranked_chunks_count: int


class RetrievalResult(BaseModel):
    """Unified retrieval output returned to generator or API."""

    query: str
    rewritten_queries: list[str]
    chunks: list[ScoredChunk]
    gate_decision: GateDecision
    trace: RetrievalTrace


class RetrievalService:
    """Orchestrates multi-query hybrid retrieval with RRF fusion,
    cross-encoder reranking, and gating.
    """

    def __init__(
        self,
        vector_store: VectorStoreAdapter | None = None,
        embedder: EmbeddingAdapter | None = None,
        lexical: LexicalIndex | None = None,
        reranker: RerankerAdapter | None = None,
        query_rewriter: QueryRewriter | None = None,
        gate: RelevanceGate | None = None,
    ) -> None:
        self.vector_store = vector_store or get_vector_store_adapter()
        self.embedder = embedder or get_embedding_adapter()
        self.lexical = lexical or lexical_index
        self.reranker = reranker or get_reranker_adapter()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.gate = gate or RelevanceGate()

    async def retrieve(
        self,
        query: str,
        user_id: str,
        workspace_id: str,
        document_ids: list[str] | None = None,
        chat_history: list[dict[str, str]] | None = None,
        top_k: int = settings.RERANK_TOP_N,
        top_candidates: int = settings.RETRIEVAL_TOP_K,
        custom_threshold: float | None = None,
        page: int | None = None,
    ) -> RetrievalResult:
        """Executes full retrieval pipeline strictly isolated to user_id and workspace_id."""
        cache_key = f"retrieval:{workspace_id}:{user_id}:{query}:{document_ids}:{top_k}"
        cached = app_cache.get(cache_key)
        if cached:
            return cached  # type: ignore[no-any-return]

        start_time = time.perf_counter()

        # Step 1: Query Rewrite & Expansion
        t0 = time.perf_counter()
        rewrite_res = await self.query_rewriter.rewrite(query, chat_history)
        search_queries = rewrite_res.queries or [query]
        query_rewrite_ms = (time.perf_counter() - t0) * 1000

        # Step 2: Multi-Query Dense + Lexical Retrieval
        t1 = time.perf_counter()
        dense_results: list[list[ScoredChunk]] = []
        lexical_results: list[list[ScoredChunk]] = []

        total_dense_count = 0
        total_lexical_count = 0

        for sq in search_queries:
            # Dense retrieval
            q_vec = await self.embedder.embed_query(sq)
            dense_chunks = await self.vector_store.search(
                query_vector=q_vec,
                user_id=user_id,
                workspace_id=workspace_id,
                document_ids=document_ids,
                top_k=top_candidates,
            )
            dense_results.append(dense_chunks)
            total_dense_count += len(dense_chunks)

            # Lexical BM25 retrieval
            bm25_chunks = self.lexical.search(
                query=sq,
                user_id=user_id,
                workspace_id=workspace_id,
                document_ids=document_ids,
                top_k=top_candidates,
            )
            lexical_results.append(bm25_chunks)
            total_lexical_count += len(bm25_chunks)

        retrieval_ms = (time.perf_counter() - t1) * 1000

        # Step 3: Reciprocal Rank Fusion (RRF)
        all_candidate_lists = dense_results + lexical_results
        fused_candidates = reciprocal_rank_fusion(
            ranked_lists=all_candidate_lists,
            k=60,
            top_n=top_candidates,
        )

        # Handle page/pdf summary and study generation queries where query words are meta terms
        primary_query = search_queries[0]
        q_lower = primary_query.lower()
        is_summary_query = any(
            p in q_lower
            for p in [
                "summar",
                "overview",
                "topic",
                "main point",
                "key point",
                "page",
                "pdf",
                "document",
                "notes",
                "material",
                "what is this",
                "tell me about",
                "generate question",
                "question and answer",
                "questions and answers",
                "1 mark",
                "3 mark",
                "marks",
                "quiz",
                "flashcard",
                "test me",
            ]
        )

        target_page: int | None = page
        if target_page is None:
            page_match = re.search(r"\bpage\s*(\d+)\b", q_lower)
            if page_match:
                target_page = int(page_match.group(1))
            elif "first page" in q_lower or "1st page" in q_lower:
                target_page = 1
            elif "second page" in q_lower or "2nd page" in q_lower:
                target_page = 2
            elif "third page" in q_lower or "3rd page" in q_lower:
                target_page = 3

        if is_summary_query and (
            target_page is not None
            or not fused_candidates
            or all(c.score < 0.25 for c in fused_candidates)
        ):
            try:
                async with AsyncSessionLocal() as db_session:
                    chunk_stmt = (
                        select(Chunk)
                        .join(Document, Chunk.document_id == Document.id)
                        .where(Document.workspace_id == workspace_id)
                        .where(Document.user_id == user_id)
                        .where(Document.status == "ready")
                    )
                    if document_ids:
                        chunk_stmt = chunk_stmt.where(Chunk.document_id.in_(document_ids))

                    if target_page is not None:
                        chunk_stmt = chunk_stmt.where(
                            (Chunk.page_start <= target_page) & (Chunk.page_end >= target_page)
                        )

                    chunk_stmt = chunk_stmt.order_by(Chunk.chunk_index.asc()).limit(top_candidates)
                    db_chunks = (await db_session.execute(chunk_stmt)).scalars().all()

                    page_candidates = [
                        ScoredChunk(
                            chunk_id=ch.id,
                            document_id=ch.document_id,
                            page_start=ch.page_start,
                            page_end=ch.page_end,
                            text=ch.text,
                            score=0.92 if target_page is not None else 0.88,
                            metadata={
                                "chunk_id": ch.id,
                                "document_id": ch.document_id,
                                "page_start": ch.page_start,
                                "page_end": ch.page_end,
                                "bbox_list": json.loads(ch.bbox_json) if ch.bbox_json else [],
                            },
                        )
                        for ch in db_chunks
                    ]
                    if target_page is not None and page_candidates:
                        fused_candidates = page_candidates + fused_candidates
                    else:
                        fused_candidates.extend(page_candidates)
            except Exception as exc:
                logger.warning("Failed to fetch workspace chunks for summary query: %s", exc)

        # Step 4: Cross-Encoder Reranking
        t2 = time.perf_counter()
        primary_query = search_queries[0]
        reranked_chunks = await self.reranker.rerank(
            query=primary_query,
            chunks=fused_candidates,
            top_n=top_k,
        )
        rerank_ms = (time.perf_counter() - t2) * 1000

        # Step 5: Relevance Gate Evaluation
        gate_decision = self.gate.evaluate(
            query=primary_query,
            reranked_chunks=reranked_chunks,
            custom_threshold=custom_threshold,
        )

        total_duration_ms = (time.perf_counter() - start_time) * 1000

        trace = RetrievalTrace(
            duration_ms=round(total_duration_ms, 2),
            query_rewrite_ms=round(query_rewrite_ms, 2),
            retrieval_ms=round(retrieval_ms, 2),
            rerank_ms=round(rerank_ms, 2),
            original_query=query,
            rewritten_queries=search_queries,
            dense_candidates_count=total_dense_count,
            lexical_candidates_count=total_lexical_count,
            fused_candidates_count=len(fused_candidates),
            reranked_chunks_count=len(reranked_chunks),
        )

        logger.info(
            "Retrieval executed for user %s: %d chunks found (Gate decision: %s, Best score: %.3f)",
            user_id,
            len(reranked_chunks),
            gate_decision.reason,
            gate_decision.best_score,
        )

        res = RetrievalResult(
            query=query,
            rewritten_queries=search_queries,
            chunks=reranked_chunks,
            gate_decision=gate_decision,
            trace=trace,
        )
        app_cache.set(
            cache_key,
            res,
            ttl_seconds=settings.CACHE_TTL_SECONDS,
            workspace_id=workspace_id,
        )

        obs = get_observability_adapter()
        obs_trace = obs.create_trace(
            name="retrieval_pipeline",
            user_id=user_id,
            tags=["retrieval", "hybrid_rrf"],
            metadata={"query": query, "workspace_id": workspace_id, "gate": gate_decision.reason},
        )
        obs_trace.duration_ms = trace.duration_ms
        obs.log_trace(obs_trace)

        return res
