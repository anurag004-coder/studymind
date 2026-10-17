"""Unit and integration tests for Phase 6 frontend endpoints and assets."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_frontend_static_and_app_routes(client: AsyncClient) -> None:
    """Tests that the frontend index and static assets are served by FastAPI."""
    # Root / App route
    resp = await client.get("/app")
    assert resp.status_code == 200
    assert "StudyMind" in resp.text
    assert 'id="app-root"' in resp.text

    # Static CSS
    css_resp = await client.get("/static/index.css")
    assert css_resp.status_code == 200
    assert "--primary:" in css_resp.text

    # Static JS
    js_resp = await client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "renderBoundingBoxOverlay" in js_resp.text


@pytest.mark.asyncio
async def test_page_image_rendering_endpoint(client: AsyncClient) -> None:
    """Tests that GET /documents/{id}/pages/{n}/image renders a valid PNG."""
    # 1. Register & login
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "page_test_user@studymind.io", "password": "password1234"},
    )
    assert reg_resp.status_code == 201

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "page_test_user@studymind.io", "password": "password1234"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create workspace
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Page Image WS"},
        headers=headers,
    )
    ws_id = ws_resp.json()["id"]

    # 3. Upload a document
    file_bytes = b"Hello world! This is a test study text for page rendering."
    upload_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files={"file": ("notes.txt", file_bytes, "text/plain")},
        headers=headers,
    )
    assert upload_resp.status_code == 202
    doc_id = upload_resp.json()["document_id"]

    # Ingest document
    reprocess_resp = await client.post(
        f"/api/v1/documents/{doc_id}/reprocess",
        json={"force_vision_ocr": False},
        headers=headers,
    )
    assert reprocess_resp.status_code == 200

    # 4. Request Page 1 image render
    page_img_resp = await client.get(
        f"/api/v1/documents/{doc_id}/pages/1/image",
        headers=headers,
    )
    assert page_img_resp.status_code == 200
    assert page_img_resp.headers["content-type"] == "image/png"
    # PNG signature check: \x89PNG\r\n\x1a\n
    assert page_img_resp.content.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_workspace_conversations_listing(client: AsyncClient) -> None:
    """Tests that GET /workspaces/{id}/conversations lists user's conversations."""
    # Register & login
    await client.post(
        "/api/v1/auth/register",
        json={"email": "conv_list_user@studymind.io", "password": "password1234"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "conv_list_user@studymind.io", "password": "password1234"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Workspace
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Conversations WS"},
        headers=headers,
    )
    ws_id = ws_resp.json()["id"]

    # Create 2 conversations
    await client.post(
        f"/api/v1/workspaces/{ws_id}/conversations",
        json={"title": "Midterm Review"},
        headers=headers,
    )
    await client.post(
        f"/api/v1/workspaces/{ws_id}/conversations",
        json={"title": "Finals Prep"},
        headers=headers,
    )

    # List conversations
    list_resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/conversations",
        headers=headers,
    )
    assert list_resp.status_code == 200
    convs = list_resp.json()
    assert len(convs) == 2
    titles = [c["title"] for c in convs]
    assert "Midterm Review" in titles
    assert "Finals Prep" in titles
