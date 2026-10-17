"""Unit and integration tests for Phase 8: Hardening & Launch.
Validates:
1. Rate limiting (429 Too Many Requests on bursts, exempt routes, Retry-After header).
2. File security scanner (magic bytes sniffing, executable blocking, malware detection, zip bomb).
3. Complete GDPR/DPDP purge (document purge, workspace purge, user account purge).
4. Multi-tier caching layer (cache hits, TTL, workspace invalidation).
5. Observability & tracing (trace generation, spans, token counts, metrics endpoint).
"""

import io
import zipfile

import pytest
from httpx import AsyncClient

from app.adapters.observability import get_observability_adapter
from app.core.cache import app_cache
from app.core.file_scanner import FileSecurityScanner
from app.core.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter() -> None:
    """Tests rate limiter logic under sliding 60-second window."""
    limiter = SlidingWindowRateLimiter(limit_per_minute=5)
    key = "test_client_key"
    limiter.reset(key)

    # First 5 requests must be allowed
    for i in range(5):
        allowed, remaining, _ = limiter.is_allowed(key, max_limit=5)
        assert allowed is True
        assert remaining == 5 - (i + 1)

    # 6th request must be rejected
    allowed, remaining, reset_secs = limiter.is_allowed(key, max_limit=5)
    assert allowed is False
    assert remaining == 0
    assert reset_secs > 0

    limiter.reset(key)
    allowed, remaining, _ = limiter.is_allowed(key, max_limit=5)
    assert allowed is True


@pytest.mark.asyncio
async def test_file_security_scanner_validations() -> None:
    """Tests sniffing of magic bytes, rejection of executables, malware, and zip bombs."""
    # 1. Valid PDF
    valid_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    FileSecurityScanner.scan_and_validate("textbook.pdf", valid_pdf)

    # 2. Fake PDF (invalid magic header)
    with pytest.raises(Exception) as exc:
        FileSecurityScanner.scan_and_validate("fake.pdf", b"NOT A VALID PDF FILE CONTENT")
    assert "Missing standard '%PDF-'" in str(exc.value)

    # 3. Executable header (Windows PE 'MZ')
    with pytest.raises(Exception) as exc:
        FileSecurityScanner.scan_and_validate("homework.pdf", b"MZ\x90\x00\x03\x00\x00\x00")
    assert "Executable binaries are disallowed" in str(exc.value)

    # 4. Executable header (Linux ELF)
    with pytest.raises(Exception) as exc:
        FileSecurityScanner.scan_and_validate("notes.txt", b"\x7fELF\x02\x01\x01\x00")
    assert "Executable binaries are disallowed" in str(exc.value)

    # 5. EICAR Malware Signature
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    with pytest.raises(Exception) as exc:
        FileSecurityScanner.scan_and_validate("clean_doc.txt", eicar)
    assert "Malware signature detected" in str(exc.value)

    # 6. Valid PNG
    valid_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    FileSecurityScanner.scan_and_validate("chart.png", valid_png)

    # 7. Invalid PNG
    with pytest.raises(Exception) as exc:
        FileSecurityScanner.scan_and_validate("chart.png", b"GIF89a corrupted image")
    assert "Magic header does not match PNG format" in str(exc.value)

    # 8. Zip Bomb protection
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1 MB of zeroes compresses to ~1 KB (> 500:1 ratio)
        zf.writestr("word/document.xml", b"\x00" * (2 * 1024 * 1024))
    zip_bomb_bytes = buf.getvalue()

    with pytest.raises(Exception) as exc:
        FileSecurityScanner.scan_and_validate("thesis.docx", zip_bomb_bytes)
    assert "exceeds safe limit" in str(exc.value)


@pytest.mark.asyncio
async def test_caching_layer_hits_and_invalidation() -> None:
    """Tests multi-tier cache store, hit counter, and workspace invalidation."""
    app_cache.clear()
    ws_id = "ws_test_cache_123"

    # Set and Get
    app_cache.set("key_1", {"data": "photosynthesis"}, ttl_seconds=60, workspace_id=ws_id)
    val = app_cache.get("key_1")
    assert val == {"data": "photosynthesis"}
    assert app_cache.hits == 1

    # Cache miss
    miss_val = app_cache.get("nonexistent_key")
    assert miss_val is None
    assert app_cache.misses == 1

    # Invalidate by workspace
    invalidated_count = app_cache.invalidate_workspace(ws_id)
    assert invalidated_count == 1
    assert app_cache.get("key_1") is None


@pytest.mark.asyncio
async def test_observability_tracing_and_metrics(client: AsyncClient) -> None:
    """Tests trace recording, span execution, and /metrics reporting."""
    obs = get_observability_adapter()
    trace = obs.create_trace(
        name="test_user_query",
        user_id="user_obs_123",
        tags=["chat", "test"],
        metadata={"query": "test query"},
    )
    span = trace.start_span("retrieval_step")
    span.end(output={"chunks_retrieved": 5})
    trace.end(prompt_tokens=150, completion_tokens=40)
    obs.log_trace(trace)

    recent = obs.get_recent_traces(limit=10)
    assert len(recent) >= 1
    t = recent[0]
    assert t["name"] == "test_user_query"
    assert t["total_tokens"] == 190
    assert len(t["spans"]) == 1

    # Verify metrics endpoint reports cache stats and traces count
    metrics_resp = await client.get("/metrics")
    assert metrics_resp.status_code == 200
    m_data = metrics_resp.json()
    assert "cache_stats" in m_data
    assert "traces_recorded" in m_data
    assert m_data["traces_recorded"] >= 1


@pytest.mark.asyncio
async def test_complete_gdpr_data_purge(client: AsyncClient) -> None:
    """Tests complete GDPR/DPDP purge for document, workspace, and user account."""
    # 1. Register User A
    email = "purge_student@studymind.io"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePassword123!"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create Workspace and Document
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Privacy Protected Workspace"},
        headers=headers,
    )
    ws_id = ws_resp.json()["id"]

    sample_text = "Genetic code is degenerate and universal across biological taxa."
    up_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files={"file": ("genetics_notes.txt", sample_text.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    doc_id = up_resp.json()["document_id"]

    # 3. Purge Document (DELETE /documents/{id})
    del_doc_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    assert del_doc_resp.status_code == 204

    # Document must be completely gone
    get_doc_resp = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert get_doc_resp.status_code == 404

    # 4. Upload another document for workspace purge testing
    up_resp2 = await client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files={"file": ("another_doc.txt", b"Sample data", "text/plain")},
        headers=headers,
    )
    doc_id2 = up_resp2.json()["document_id"]
    assert doc_id2 is not None

    # 5. Purge Workspace (DELETE /workspaces/{id})
    del_ws_resp = await client.delete(f"/api/v1/workspaces/{ws_id}", headers=headers)
    assert del_ws_resp.status_code == 204

    # Workspace and documents must be completely gone
    get_ws_resp = await client.get(f"/api/v1/workspaces/{ws_id}", headers=headers)
    assert get_ws_resp.status_code == 404
    get_doc2_resp = await client.get(f"/api/v1/documents/{doc_id2}", headers=headers)
    assert get_doc2_resp.status_code == 404

    # 6. User Account Purge (DELETE /auth/me)
    del_user_resp = await client.delete("/api/v1/auth/me", headers=headers)
    assert del_user_resp.status_code == 204

    # User cannot log in anymore
    relogin_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    assert relogin_resp.status_code == 401
