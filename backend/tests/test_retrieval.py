"""Tests for Phase 4 Retrieval: query rewrite, RRF fusion, gate, service, isolation, and DoD."""

import pytest
from eval.run_retrieval_eval import run_retrieval_evaluation
from httpx import AsyncClient

from app.adapters import (
    InMemoryVectorStoreAdapter,
    MockEmbeddingAdapter,
    MockRerankerAdapter,
)
from app.adapters.base import ScoredChunk
from app.ingestion.lexical_index import LexicalIndex
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.gate import RelevanceGate
from app.retrieval.query_rewrite import QueryRewriter
from app.retrieval.service import RetrievalService


@pytest.mark.asyncio
async def test_query_rewriter_standalone_and_decomposition() -> None:
    rewriter = QueryRewriter()

    # 1. Single standalone query without history
    single = await rewriter.rewrite("What is photosynthesis?")
    assert single.original_query == "What is photosynthesis?"
    assert len(single.queries) == 1
    assert single.queries[0] == "What is photosynthesis?"

    # 2. Multi-part question decomposition
    multi = await rewriter.rewrite(
        "What is photosynthesis and also why does chlorophyll absorb light?"
    )
    assert len(multi.queries) >= 2


@pytest.mark.asyncio
async def test_query_rewriter_chat_history_resolution() -> None:
    rewriter = QueryRewriter()
    history = [
        {"role": "user", "content": "Tell me about the mitochondrion."},
        {"role": "assistant", "content": "Mitochondria are the powerhouses of eukaryotic cells."},
    ]

    # Query with pronoun "it"
    resolved = await rewriter.rewrite("What is its primary function?", chat_history=history)
    assert len(resolved.queries) >= 1
    assert any("mitochondri" in q.lower() for q in resolved.queries)


def test_reciprocal_rank_fusion_logic() -> None:
    c1 = ScoredChunk(
        chunk_id="c1", document_id="d1", page_start=1, page_end=1, text="Chunk 1", score=0.9
    )
    c2 = ScoredChunk(
        chunk_id="c2", document_id="d1", page_start=2, page_end=2, text="Chunk 2", score=0.8
    )
    c3 = ScoredChunk(
        chunk_id="c3", document_id="d1", page_start=3, page_end=3, text="Chunk 3", score=0.7
    )

    # Dense ranked list: [c1, c2]
    # Lexical ranked list: [c2, c3]
    dense_list = [c1, c2]
    lexical_list = [c2, c3]

    fused = reciprocal_rank_fusion([dense_list, lexical_list], k=60)
    assert len(fused) == 3

    # c2 appears in both lists (#2 in dense, #1 in lexical),
    # so its combined RRF score should be highest!
    assert fused[0].chunk_id == "c2"
    assert fused[0].score == 1.0  # normalized max
    assert "rrf_raw_score" in fused[0].metadata


def test_relevance_gate_abstains_on_empty_and_low_score() -> None:
    gate = RelevanceGate(min_relevance_score=0.35)

    # 1. Empty results
    empty_decision = gate.evaluate("What is dark matter?", [])
    assert empty_decision.should_abstain is True
    assert empty_decision.reason == "no_results"
    assert len(empty_decision.suggested_rephrases) > 0

    # 2. Low relevance score below threshold
    weak_chunk = ScoredChunk(
        chunk_id="c_weak",
        document_id="d1",
        page_start=1,
        page_end=1,
        text="Random unrelated text mentioning general things.",
        score=0.20,
    )
    low_decision = gate.evaluate("Explain quantum entanglement", [weak_chunk])
    assert low_decision.should_abstain is True
    assert low_decision.reason == "insufficient_evidence"

    # 3. High score and good coverage passes
    strong_chunk = ScoredChunk(
        chunk_id="c_strong",
        document_id="d1",
        page_start=1,
        page_end=1,
        text="Quantum entanglement is a physical phenomenon where pairs of particles interact.",
        score=0.85,
    )
    high_decision = gate.evaluate("Explain quantum entanglement", [strong_chunk])
    assert high_decision.should_abstain is False
    assert high_decision.reason == "passed"


@pytest.mark.asyncio
async def test_retrieval_user_isolation_and_scope_filters() -> None:
    user_a = "user_alpha"
    user_b = "user_beta"
    ws_a = "workspace_alpha"
    ws_b = "workspace_beta"

    vector_store = InMemoryVectorStoreAdapter(shared=False)
    lexical = LexicalIndex()
    embedder = MockEmbeddingAdapter()
    reranker = MockRerankerAdapter()
    gate = RelevanceGate(min_relevance_score=0.35)

    # Index confidential document for User B
    b_chunks = [
        {
            "chunk_id": "b_chunk_secret",
            "document_id": "doc_b_classified",
            "workspace_id": ws_b,
            "user_id": user_b,
            "page_start": 1,
            "page_end": 1,
            "text": "Classified financial revenue data for User B: $10,000,000 net profit.",
            "section_path": ["Confidential"],
            "block_type": "paragraph",
        }
    ]
    b_vectors = await embedder.embed_texts([str(b_chunks[0]["text"])])
    await vector_store.upsert(b_chunks, b_vectors)
    lexical.index_chunks(b_chunks)

    # Index open document for User A
    a_chunks = [
        {
            "chunk_id": "a_chunk_study",
            "document_id": "doc_a_bio",
            "workspace_id": ws_a,
            "user_id": user_a,
            "page_start": 1,
            "page_end": 1,
            "text": "Biology chapter 1: Cell division and cellular metabolism overview.",
            "section_path": ["Biology"],
            "block_type": "paragraph",
        }
    ]
    a_vectors = await embedder.embed_texts([str(a_chunks[0]["text"])])
    await vector_store.upsert(a_chunks, a_vectors)
    lexical.index_chunks(a_chunks)

    service = RetrievalService(
        vector_store=vector_store,
        embedder=embedder,
        lexical=lexical,
        reranker=reranker,
        gate=gate,
    )

    # User A tries to query User B's exact classified text
    res = await service.retrieve(
        query="What is the net profit classified data?",
        user_id=user_a,
        workspace_id=ws_a,
    )

    # STRICT MULTI-TENANT ISOLATION: User A must NEVER see User B's chunk!
    for chunk in res.chunks:
        assert chunk.chunk_id != "b_chunk_secret"
        assert "Classified" not in chunk.text


@pytest.mark.asyncio
async def test_retrieval_api_endpoint(client: AsyncClient) -> None:
    # Register and login a test student
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "retrieval_student@test.com", "password": "SecurePassword123!"},
    )
    assert reg.status_code == 201

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "retrieval_student@test.com", "password": "SecurePassword123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create workspace
    ws_res = await client.post(
        "/api/v1/workspaces", json={"name": "Physics Revision"}, headers=headers
    )
    assert ws_res.status_code == 201
    ws_id = ws_res.json()["id"]

    # Search workspace endpoint
    search_res = await client.post(
        f"/api/v1/workspaces/{ws_id}/search",
        json={"query": "What is Newton's law of motion?", "top_k": 5},
        headers=headers,
    )
    assert search_res.status_code == 200
    data = search_res.json()
    assert "query" in data
    assert "chunks" in data
    assert "gate_decision" in data
    assert "trace" in data


@pytest.mark.asyncio
async def test_phase4_retrieval_dod_evaluation_benchmark() -> None:
    """DoD: Recall@6 >= 0.85 on gold set."""
    report = await run_retrieval_evaluation(verbose=False)
    summary = report["summary"]

    assert summary["recall_at_6"] >= 0.85, (
        f"Recall@6 was {summary['recall_at_6']}, expected >= 0.85"
    )
    assert summary["abstention_precision"] >= 0.90, (
        f"Abstention precision was {summary['abstention_precision']}, expected >= 0.90"
    )
    assert summary["false_abstain_rate"] <= 0.10, (
        f"False abstain rate was {summary['false_abstain_rate']}, expected <= 0.10"
    )
