"""Tests verifying adapter contracts and implementations."""

import pytest
from pydantic import BaseModel

from app.adapters.base import ScoredChunk
from app.adapters.embeddings import MockEmbeddingAdapter
from app.adapters.llm import MockLLMAdapter
from app.adapters.reranker import MockRerankerAdapter
from app.adapters.storage import LocalStorageAdapter
from app.adapters.vectorstore import InMemoryVectorStoreAdapter


class SampleAnswerSchema(BaseModel):
    answer: str
    confidence: float


@pytest.mark.asyncio
async def test_llm_adapter_generate_and_structured() -> None:
    adapter = MockLLMAdapter(canned_response='{"answer": "Mitochondria", "confidence": 0.99}')
    resp = await adapter.generate([{"role": "user", "content": "What is the powerhouse?"}])
    assert "Mitochondria" in resp.text
    assert resp.model == "mock-llm"

    model_inst, structured_resp = await adapter.generate_structured(
        [{"role": "user", "content": "What is the powerhouse?"}],
        response_model=SampleAnswerSchema,
    )
    assert isinstance(model_inst, SampleAnswerSchema)
    assert model_inst.answer == "Mitochondria"
    assert model_inst.confidence == 0.99


@pytest.mark.asyncio
async def test_embedding_adapter_contract() -> None:
    embedder = MockEmbeddingAdapter(dimension=1024)
    assert embedder.dimension == 1024

    texts = ["First chunk of biology text.", "Second chunk of history notes."]
    vectors = await embedder.embed_texts(texts)
    assert len(vectors) == 2
    assert len(vectors[0]) == 1024
    assert len(vectors[1]) == 1024

    query_vec = await embedder.embed_query("biology")
    assert len(query_vec) == 1024


@pytest.mark.asyncio
async def test_reranker_adapter_contract() -> None:
    reranker = MockRerankerAdapter()
    candidates = [
        ScoredChunk(
            chunk_id="c1",
            document_id="d1",
            page_start=1,
            page_end=1,
            text="General remarks about science.",
            score=0.4,
        ),
        ScoredChunk(
            chunk_id="c2",
            document_id="d1",
            page_start=2,
            page_end=2,
            text="Photosynthesis converts light into chemical energy.",
            score=0.5,
        ),
    ]

    reranked = await reranker.rerank("photosynthesis", candidates, top_n=2)
    assert len(reranked) == 2
    # The chunk mentioning photosynthesis should be ranked first
    assert reranked[0].chunk_id == "c2"
    assert reranked[0].score > reranked[1].score


@pytest.mark.asyncio
async def test_vectorstore_user_isolation_contract() -> None:
    """CRITICAL PRODUCT RULE: Enforce user_id isolation in every vector search."""
    store = InMemoryVectorStoreAdapter()

    # Chunks for User A
    chunks_user_a = [
        {
            "chunk_id": "c_a1",
            "user_id": "user_a",
            "workspace_id": "ws_1",
            "document_id": "doc_1",
            "page_start": 1,
            "page_end": 1,
            "text": "Private notes belonging to User A",
        }
    ]
    vectors_user_a = [[0.8] * 10]

    # Chunks for User B
    chunks_user_b = [
        {
            "chunk_id": "c_b1",
            "user_id": "user_b",
            "workspace_id": "ws_2",
            "document_id": "doc_2",
            "page_start": 1,
            "page_end": 1,
            "text": "Secret exam answers belonging to User B",
        }
    ]
    vectors_user_b = [[0.9] * 10]

    await store.upsert(chunks_user_a, vectors_user_a)
    await store.upsert(chunks_user_b, vectors_user_b)

    # Search as User A -> MUST NOT find User B's chunks
    query_vector = [0.9] * 10
    results_user_a = await store.search(query_vector, user_id="user_a", workspace_id="ws_1")
    assert len(results_user_a) == 1
    assert results_user_a[0].chunk_id == "c_a1"

    # Search as User B
    results_user_b = await store.search(query_vector, user_id="user_b", workspace_id="ws_2")
    assert len(results_user_b) == 1
    assert results_user_b[0].chunk_id == "c_b1"

    # Purge user B
    await store.delete_by_user("user_b")
    results_user_b_after = await store.search(query_vector, user_id="user_b", workspace_id="ws_2")
    assert len(results_user_b_after) == 0


@pytest.mark.asyncio
async def test_storage_adapter_contract(tmp_path: pytest.TempPathFactory) -> None:
    storage = LocalStorageAdapter(base_dir=str(tmp_path))
    content = b"PDF dummy content byte stream"
    key = "documents/test_doc.pdf"

    saved_key = await storage.put_object(key, content, "application/pdf")
    assert saved_key == key

    retrieved = await storage.get_object(key)
    assert retrieved == content

    url = await storage.get_signed_url(key)
    assert "test_doc.pdf" in url

    await storage.delete_object(key)
    with pytest.raises(FileNotFoundError):
        await storage.get_object(key)
