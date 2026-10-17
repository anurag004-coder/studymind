"""Tests for document upload, validation, storage, and retrieval."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def get_auth_token_and_workspace(
    client: AsyncClient, email: str = "uploader@test.com"
) -> tuple[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    token = login_resp.json()["access_token"]
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Upload Workspace"},
        headers={"Authorization": f"Bearer {token}"},
    )
    ws_id = ws_resp.json()["id"]
    return token, ws_id


@pytest.mark.asyncio
async def test_upload_valid_pdf_and_retrieve(client: AsyncClient) -> None:
    token, ws_id = await get_auth_token_and_workspace(client, "valid_pdf_user@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Upload valid PDF
    pdf_content = b"%PDF-1.4 dummy textbook file content"
    files = {"file": ("calculus_chapter1.pdf", pdf_content, "application/pdf")}

    upload_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files=files,
        headers=headers,
    )
    assert upload_resp.status_code == 202
    doc_info = upload_resp.json()
    assert "document_id" in doc_info
    assert doc_info["status"] == "queued"
    assert doc_info["filename"] == "calculus_chapter1.pdf"
    doc_id = doc_info["document_id"]

    # List documents in workspace
    list_resp = await client.get(f"/api/v1/workspaces/{ws_id}/documents", headers=headers)
    assert list_resp.status_code == 200
    docs = list_resp.json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id
    assert docs[0]["status"] == "queued"

    # Get document metadata
    detail_resp = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == doc_id
    assert detail["status"] == "queued"
    assert detail["current_stage"] == "upload"

    # Download original file
    file_resp = await client.get(f"/api/v1/documents/{doc_id}/file", headers=headers)
    assert file_resp.status_code == 200
    assert file_resp.content == pdf_content

    # Delete document
    del_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    assert del_resp.status_code == 204

    # Confirm deleted
    detail_after = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert detail_after.status_code == 404


@pytest.mark.asyncio
async def test_upload_disallowed_file_type(client: AsyncClient) -> None:
    token, ws_id = await get_auth_token_and_workspace(client, "bad_file_user@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Upload .exe or .bin file
    exe_content = b"MZ executable binary"
    files = {"file": ("malicious.exe", exe_content, "application/x-dosexec")}

    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_upload_empty_file(client: AsyncClient) -> None:
    token, ws_id = await get_auth_token_and_workspace(client, "empty_file_user@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    files = {"file": ("empty.txt", b"", "text/plain")}
    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_delete_document_purges_lexical_index_and_study_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import json

    from sqlalchemy import select

    from app.db.models import Chunk, StudyItem
    from app.ingestion.lexical_index import lexical_index

    token, ws_id = await get_auth_token_and_workspace(client, "purge_test_user@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Upload document
    pdf_content = b"%PDF-1.4 dummy textbook file content"
    files = {"file": ("purge_subject.pdf", pdf_content, "application/pdf")}
    upload_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files=files,
        headers=headers,
    )
    assert upload_resp.status_code == 202
    doc_id = upload_resp.json()["document_id"]

    # Get user_id from token/profile
    me_resp = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me_resp.json()["id"]

    # Index test chunk into BM25 index
    chunk_id = f"chunk-{doc_id}-1"
    lexical_index.index_chunks(
        [
            {
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "workspace_id": ws_id,
                "user_id": user_id,
                "text": "UniqueMitochondriaATPConceptForPurgeTest",
            }
        ]
    )

    # Verify BM25 finds it before deletion
    results_before = lexical_index.search(
        "UniqueMitochondriaATPConceptForPurgeTest", user_id=user_id, workspace_id=ws_id
    )
    assert len(results_before) > 0
    assert results_before[0].chunk_id == chunk_id

    # Create a Chunk and StudyItem referencing this doc in the test session
    chunk = Chunk(
        id=chunk_id,
        document_id=doc_id,
        page_start=1,
        page_end=1,
        chunk_index=0,
        text="UniqueMitochondriaATPConceptForPurgeTest",
        token_count=10,
        embedding_model="text-embedding-3-small",
    )
    db_session.add(chunk)
    study_item = StudyItem(
        workspace_id=ws_id,
        type="flashcard",
        payload_json=json.dumps(
            {"front": "What is ATP?", "back": "Energy carrier", "document_id": doc_id}
        ),
        source_chunk_ids=json.dumps([chunk_id]),
    )
    db_session.add(study_item)
    await db_session.commit()

    # Delete the document via API
    del_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    assert del_resp.status_code == 204

    # Verify lexical index purged chunks for this document
    results_after = lexical_index.search(
        "UniqueMitochondriaATPConceptForPurgeTest", user_id=user_id, workspace_id=ws_id
    )
    assert len(results_after) == 0

    # Verify StudyItem referencing this document was purged
    res = await db_session.execute(select(StudyItem).where(StudyItem.workspace_id == ws_id))
    items = res.scalars().all()
    assert len(items) == 0
