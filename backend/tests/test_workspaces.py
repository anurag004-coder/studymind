"""Tests for Workspace CRUD endpoints."""

import pytest
from httpx import AsyncClient


async def get_auth_token(client: AsyncClient, email: str = "student1@test.com") -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_workspace_crud(client: AsyncClient) -> None:
    token = await get_auth_token(client, "workspace_user@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create workspace
    create_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Neuroscience Semester 2"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    ws = create_resp.json()
    assert ws["name"] == "Neuroscience Semester 2"
    ws_id = ws["id"]

    # 2. List workspaces
    list_resp = await client.get("/api/v1/workspaces", headers=headers)
    assert list_resp.status_code == 200
    workspaces = list_resp.json()
    assert len(workspaces) == 1
    assert workspaces[0]["id"] == ws_id

    # 3. Get single workspace
    get_resp = await client.get(f"/api/v1/workspaces/{ws_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Neuroscience Semester 2"

    # 4. Delete workspace
    del_resp = await client.delete(f"/api/v1/workspaces/{ws_id}", headers=headers)
    assert del_resp.status_code == 204

    # 5. Verify deleted
    get_after = await client.get(f"/api/v1/workspaces/{ws_id}", headers=headers)
    assert get_after.status_code == 404
