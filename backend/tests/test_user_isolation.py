"""Comprehensive Multi-Tenant User Isolation Tests.

Verifies Non-Negotiable Product Rule #5:
Enforce user_id isolation in every DB query and vector search.
User A must never be able to access, view, modify, or delete User B's resources.
"""

import pytest
from httpx import AsyncClient


async def create_user_and_token(
    client: AsyncClient, email: str, password: str = "securepassword123"
) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_user_a_cannot_see_user_b_resources(client: AsyncClient) -> None:
    # 1. Setup User A
    token_a = await create_user_and_token(client, "alice@study.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # User A creates Workspace A
    ws_a_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Alice Private Workspace"},
        headers=headers_a,
    )
    assert ws_a_resp.status_code == 201
    ws_a_id = ws_a_resp.json()["id"]

    # User A uploads Document A
    doc_a_resp = await client.post(
        f"/api/v1/workspaces/{ws_a_id}/documents",
        files={
            "file": (
                "alice_notes.pdf",
                b"%PDF-1.4 Alice confidential study notes",
                "application/pdf",
            )
        },
        headers=headers_a,
    )
    assert doc_a_resp.status_code == 202
    doc_a_id = doc_a_resp.json()["document_id"]

    # 2. Setup User B
    token_b = await create_user_and_token(client, "bob@study.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B creates Workspace B
    ws_b_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Bob Workspace"},
        headers=headers_b,
    )
    assert ws_b_resp.status_code == 201

    # 3. Isolation Checks: User B attempting to access User A's Workspace A
    # User B listing workspaces -> MUST NOT contain Workspace A
    b_list_ws = await client.get("/api/v1/workspaces", headers=headers_b)
    assert b_list_ws.status_code == 200
    b_workspaces = b_list_ws.json()
    assert len(b_workspaces) == 1
    assert b_workspaces[0]["name"] == "Bob Workspace"
    assert not any(w["id"] == ws_a_id for w in b_workspaces)

    # User B accessing Workspace A directly -> MUST return 404
    b_get_ws_a = await client.get(f"/api/v1/workspaces/{ws_a_id}", headers=headers_b)
    assert b_get_ws_a.status_code == 404

    # User B attempting to delete Workspace A -> MUST return 404
    b_del_ws_a = await client.delete(f"/api/v1/workspaces/{ws_a_id}", headers=headers_b)
    assert b_del_ws_a.status_code == 404

    # 4. Isolation Checks: User B attempting to access User A's Documents
    # User B listing documents in Workspace A -> MUST return 404
    b_list_docs = await client.get(f"/api/v1/workspaces/{ws_a_id}/documents", headers=headers_b)
    assert b_list_docs.status_code == 404

    # User B attempting to upload into User A's Workspace A -> MUST return 404
    b_upload_to_a = await client.post(
        f"/api/v1/workspaces/{ws_a_id}/documents",
        files={"file": ("intruder.pdf", b"Unauthorized content", "application/pdf")},
        headers=headers_b,
    )
    assert b_upload_to_a.status_code == 404

    # User B fetching metadata of Doc A -> MUST return 404
    b_get_doc_a = await client.get(f"/api/v1/documents/{doc_a_id}", headers=headers_b)
    assert b_get_doc_a.status_code == 404

    # User B downloading file content of Doc A -> MUST return 404
    b_file_doc_a = await client.get(f"/api/v1/documents/{doc_a_id}/file", headers=headers_b)
    assert b_file_doc_a.status_code == 404

    # User B attempting to delete Doc A -> MUST return 404
    b_del_doc_a = await client.delete(f"/api/v1/documents/{doc_a_id}", headers=headers_b)
    assert b_del_doc_a.status_code == 404

    # 5. Verify User A's Workspace A and Doc A are completely intact
    a_get_doc = await client.get(f"/api/v1/documents/{doc_a_id}", headers=headers_a)
    assert a_get_doc.status_code == 200
    assert a_get_doc.json()["filename"] == "alice_notes.pdf"
