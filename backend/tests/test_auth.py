"""Tests for authentication and user registration endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_login_flow(client: AsyncClient) -> None:
    # 1. Register new user
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@university.edu", "password": "supersecretpassword123"},
    )
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["email"] == "alice@university.edu"
    assert "id" in user_data

    # 2. Duplicate registration should fail
    dup_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@university.edu", "password": "differentpassword"},
    )
    assert dup_resp.status_code == 400

    # 3. Login with correct password
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@university.edu", "password": "supersecretpassword123"},
    )
    assert login_resp.status_code == 200
    token_data = login_resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    token = token_data["access_token"]

    # 4. Verify /auth/me with Bearer token
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["id"] == user_data["id"]
    assert me_data["email"] == "alice@university.edu"


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    # Attempt login with non-existent email
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@university.edu", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_unauthorized(client: AsyncClient) -> None:
    # Without token
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)

    # With invalid token
    resp_invalid = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert resp_invalid.status_code == 401
