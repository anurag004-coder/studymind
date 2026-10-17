"""Unit and integration tests for Phase 7 Study Tools.
Verifies:
1. Map-reduce Summary generation with verified key takeaways and quotes.
2. Grounded Flashcards generation where every card has a valid source chunk + quote.
3. Grounded Quiz generation with verified explanations and valid quotes.
4. Anki CSV/TSV and Markdown exports.
5. User isolation (multi-tenancy) across study items.
"""

import pytest
from httpx import AsyncClient


async def create_user_and_workspace_with_docs(
    client: AsyncClient, email: str
) -> tuple[dict[str, str], str, str]:
    """Helper to set up authenticated user, workspace, and an ingested document."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Biology Workspace"},
        headers=headers,
    )
    ws_id = ws_resp.json()["id"]

    # Ingest document
    bio_text = (
        "Mitochondria are membrane-bound cell organelles that generate chemical energy "
        "needed to power cellular reactions. Energy produced by the mitochondria "
        "is stored in a small molecule called adenosine triphosphate (ATP). "
        "Mitochondria contain their own chromosomes inherited only from the mother."
    )
    upload_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files={"file": ("cell_biology.txt", bio_text.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    doc_id = upload_resp.json()["document_id"]

    await client.post(
        f"/api/v1/documents/{doc_id}/reprocess",
        json={"force_vision_ocr": False},
        headers=headers,
    )

    return headers, ws_id, doc_id


@pytest.mark.asyncio
async def test_summary_map_reduce_generation(client: AsyncClient) -> None:
    """Tests map-reduce summary generation with verified chunk citations."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "summary_user@studymind.io"
    )

    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/study/summary",
        json={"document_ids": [doc_id], "length": "short"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["workspace_id"] == ws_id
    assert len(data["summary"]) > 0
    assert len(data["key_takeaways"]) > 0

    # DoD Check: Every takeaway must cite a valid chunk and quote
    for takeaway in data["key_takeaways"]:
        assert "source_chunk_id" in takeaway
        assert len(takeaway["source_chunk_id"]) > 0
        assert "quote" in takeaway
        assert len(takeaway["quote"]) > 0
        assert takeaway["document_id"] == doc_id


@pytest.mark.asyncio
async def test_flashcard_generation_and_quote_verification(client: AsyncClient) -> None:
    """Tests flashcard generation ensuring every card has a valid source chunk and quote."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "flashcard_user@studymind.io"
    )

    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/study/flashcards",
        json={"count": 3, "topic": "Mitochondria"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    cards = data["flashcards"]
    assert len(cards) > 0

    # DoD Check: Every generated item has valid source chunk + quote
    for card in cards:
        assert len(card["question"]) > 0
        assert len(card["answer"]) > 0
        assert len(card["source_chunk_id"]) > 0
        assert len(card["quote"]) > 0
        # Quote must contain actual material words
        assert any(
            term in card["quote"].lower() for term in ["mitochondria", "atp", "energy", "cell"]
        )


@pytest.mark.asyncio
async def test_quiz_generation_and_grounded_explanations(client: AsyncClient) -> None:
    """Tests grounded quiz question generation with verified explanations."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "quiz_user@studymind.io"
    )

    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/study/quiz",
        json={"count": 2, "difficulty": "medium"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    questions = data["questions"]
    assert len(questions) > 0

    # DoD Check: Every question must cite a chunk, have 4 options, and grounded quote
    for q in questions:
        assert len(q["stem"]) > 0
        assert len(q["options"]) == 4
        assert 0 <= q["correct_answer_index"] <= 3
        assert len(q["explanation"]) > 0
        assert len(q["quote"]) > 0
        assert len(q["source_chunk_id"]) > 0


@pytest.mark.asyncio
async def test_saved_study_items_and_export(client: AsyncClient) -> None:
    """Tests listing study items and exporting to Anki TSV and Markdown."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "export_user@studymind.io"
    )

    # 1. Generate flashcards and quiz to populate study items
    await client.post(
        f"/api/v1/workspaces/{ws_id}/study/flashcards",
        json={"count": 2},
        headers=headers,
    )
    await client.post(
        f"/api/v1/workspaces/{ws_id}/study/quiz",
        json={"count": 2},
        headers=headers,
    )

    # 2. List study items
    items_resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/study/items",
        headers=headers,
    )
    assert items_resp.status_code == 200
    items = items_resp.json()["items"]
    assert len(items) >= 4

    # 3. Export to Anki
    anki_resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/study/export/anki",
        headers=headers,
    )
    assert anki_resp.status_code == 200
    assert "text/tab-separated-values" in anki_resp.headers["content-type"]
    assert "studymind" in anki_resp.text
    # TSV should contain tab delimiters
    assert "\t" in anki_resp.text

    # 4. Export to Markdown Study Guide
    md_resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/study/export/markdown",
        headers=headers,
    )
    assert md_resp.status_code == 200
    assert "text/markdown" in md_resp.headers["content-type"]
    assert "# Study Guide:" in md_resp.text


@pytest.mark.asyncio
async def test_study_tools_user_isolation(client: AsyncClient) -> None:
    """Tests that User A cannot access or export User B's study items."""
    # User A setup
    headers_a, ws_a, doc_a = await create_user_and_workspace_with_docs(
        client, "isolated_user_a@studymind.io"
    )
    await client.post(
        f"/api/v1/workspaces/{ws_a}/study/flashcards",
        json={"count": 2},
        headers=headers_a,
    )

    # User B setup
    await client.post(
        "/api/v1/auth/register",
        json={"email": "isolated_user_b@studymind.io", "password": "password1234"},
    )
    login_b = await client.post(
        "/api/v1/auth/login",
        json={"email": "isolated_user_b@studymind.io", "password": "password1234"},
    )
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B trying to access User A's workspace study items -> 404
    forbidden_resp = await client.get(
        f"/api/v1/workspaces/{ws_a}/study/items",
        headers=headers_b,
    )
    assert forbidden_resp.status_code == 404
    assert (
        "unauthorized" in forbidden_resp.json()["error"]["message"].lower()
        or "not found" in forbidden_resp.json()["error"]["message"].lower()
    )

    # User B trying to export User A's workspace to Anki -> 404
    forbidden_export = await client.get(
        f"/api/v1/workspaces/{ws_a}/study/export/anki",
        headers=headers_b,
    )
    assert forbidden_export.status_code == 404


@pytest.mark.asyncio
async def test_flashcard_generation_prevents_duplicate_repetition(client: AsyncClient) -> None:
    """Tests that subsequent flashcard generations do not repeat identical questions."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "non_repeating_user@studymind.io"
    )

    # Batch 1
    resp1 = await client.post(
        f"/api/v1/workspaces/{ws_id}/study/flashcards",
        json={"count": 2},
        headers=headers,
    )
    assert resp1.status_code == 200
    cards1 = resp1.json()["flashcards"]
    assert len(cards1) > 0
    stems1 = {c["question"].strip().lower() for c in cards1}

    # Batch 2
    resp2 = await client.post(
        f"/api/v1/workspaces/{ws_id}/study/flashcards",
        json={"count": 2},
        headers=headers,
    )
    assert resp2.status_code == 200
    cards2 = resp2.json()["flashcards"]
    assert len(cards2) > 0

    # Ensure no exact overlap with previous questions
    for c2 in cards2:
        assert c2["question"].strip().lower() not in stems1


@pytest.mark.asyncio
async def test_summary_includes_important_areas_and_page_redirects(client: AsyncClient) -> None:
    """Tests summary response includes structured important areas and page redirects."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "summary_areas_user@studymind.io"
    )

    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/study/summary",
        json={"document_ids": [doc_id], "length": "medium"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "important_areas" in data
    assert "referenced_pages" in data
    assert len(data["important_areas"]) > 0
    assert len(data["referenced_pages"]) > 0

    first_area = data["important_areas"][0]
    assert len(first_area["area_title"]) > 0
    assert first_area["page"] >= 1
    assert first_area["document_id"] == doc_id
    assert len(first_area["summary"]) > 0

    first_page = data["referenced_pages"][0]
    assert first_page["page"] >= 1
    assert first_page["document_id"] == doc_id


@pytest.mark.asyncio
async def test_mark_based_chat_question_generation(client: AsyncClient) -> None:
    """Tests chat endpoint handling 1-mark and 3-mark question and answer generation."""
    headers, ws_id, doc_id = await create_user_and_workspace_with_docs(
        client, "marks_chat_user@studymind.io"
    )

    # Start a conversation
    conv_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/conversations",
        json={"title": "Marks Prep Chat"},
        headers=headers,
    )
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["id"]

    # Ask for 1-mark and 3-mark questions
    chat_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={
            "question": (
                "Generate questions and answers based on marks like 1 mark and 3 mark "
                "from the provided material"
            )
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200
    msg = chat_resp.json()
    assert msg["abstained"] is False
    assert len(msg["answer"]) > 0
    assert len(msg["citations"]) > 0

    combined_text = " ".join(s["text"] for s in msg["answer"])
    assert "1 Mark" in combined_text or "1-Mark" in combined_text or "Q1" in combined_text
    assert "3 Mark" in combined_text or "3-Mark" in combined_text or "Q3" in combined_text
