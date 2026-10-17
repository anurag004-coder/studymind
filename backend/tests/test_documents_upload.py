"""Tests for document upload, validation, storage, and retrieval."""

import pytest
from httpx import AsyncClient


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
