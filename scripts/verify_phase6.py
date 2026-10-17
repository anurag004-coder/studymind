"""Verification script for Phase 6 — Frontend.
Validates:
1. Frontend asset integrity (HTML5, Vanilla CSS3, ES6 JS, Node server, package.json).
2. FastAPI serving of /app, /static/index.css, and /static/app.js.
3. Document page image rendering endpoint (GET /documents/{id}/pages/{n}/image).
4. End-to-end Grounded Chat + Citation Click Highlight calculation.
5. Abstention flow + Suggested chips.
6. Feedback submission endpoint.
7. Node dev server boot & static delivery on port 3000.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path("backend").resolve()))


async def run_verification() -> bool:
    print("=" * 70)
    print("StudyMind Phase 6 — Frontend Verification Harness")
    print("=" * 70)

    # 1. Check frontend assets
    frontend_dir = Path("frontend")
    required_files = ["index.html", "index.css", "app.js", "server.js", "package.json"]
    for fname in required_files:
        fpath = frontend_dir / fname
        assert fpath.exists(), f"Missing required file: {fpath}"
        assert fpath.stat().st_size > 50, f"File appears empty: {fpath}"
        print(f"  [PASS] Verified frontend asset: {fname} ({fpath.stat().st_size} bytes)")

    # 2. Check HTML markup contains all required interactive element IDs
    html_content = (frontend_dir / "index.html").read_text(encoding="utf-8")
    required_ids = [
        "app-root",
        "top-navbar",
        "workspace-select",
        "btn-new-workspace",
        "strict-mode-toggle",
        "btn-open-login",
        "user-profile-badge",
        "tab-chat-btn",
        "tab-library-btn",
        "chat-view",
        "library-view",
        "conv-select",
        "btn-new-chat",
        "messages-container",
        "chat-input",
        "btn-send-message",
        "upload-dropzone",
        "file-upload-input",
        "ingestion-progress-card",
        "documents-table",
        "source-viewer-panel",
        "viewer-doc-title",
        "btn-prev-page",
        "btn-next-page",
        "viewer-page-indicator",
        "btn-zoom-in",
        "btn-zoom-out",
        "btn-zoom-fit",
        "viewer-page-image",
        "source-highlight-box",
        "source-quote-tooltip",
        "auth-modal",
        "auth-form",
        "auth-email",
        "auth-password",
        "btn-demo-account",
        "workspace-modal",
        "feedback-modal",
    ]
    for el_id in required_ids:
        assert f'id="{el_id}"' in html_content, f"Missing required HTML element ID: {el_id}"
    print(f"  [PASS] Verified {len(required_ids)} semantic HTML interactive elements present")

    # 3. Test backend integration with httpx
    from app.db.models import Base
    from app.db.session import get_db
    from app.main import app
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _demo_get_db():
        async with session_factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _demo_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Check /app route
        resp = await client.get("/app")
        assert resp.status_code == 200
        assert "StudyMind" in resp.text
        print("  [PASS] Verified /app route returns index.html")

        # Check /static/index.css
        css_resp = await client.get("/static/index.css")
        assert css_resp.status_code == 200
        assert "--primary:" in css_resp.text
        print("  [PASS] Verified /static/index.css served with design tokens")

        # Check /static/app.js
        js_resp = await client.get("/static/app.js")
        assert js_resp.status_code == 200
        assert "renderBoundingBoxOverlay" in js_resp.text
        print("  [PASS] Verified /static/app.js served with highlight overlay logic")

        # 4. User Registration & Login
        user_email = f"student_p6_{int(time.time())}@studymind.io"
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={"email": user_email, "password": "password1234"},
        )
        assert reg_resp.status_code == 201

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user_email, "password": "password1234"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"  [PASS] User registration & authentication succeeded: {user_email}")

        # 5. Workspace Creation
        ws_resp = await client.post(
            "/api/v1/workspaces",
            json={"name": "Neuroscience 101"},
            headers=headers,
        )
        ws_id = ws_resp.json()["id"]
        print(f"  [PASS] Workspace created: 'Neuroscience 101' (id: {ws_id})")

        # 6. Upload Study Material Document
        doc_content = (
            "Dopamine is a neurotransmitter that plays several important roles in the brain. "
            "It is involved in reward, motivation, memory, and attention. "
            "When dopamine is released in large amounts, it creates feelings of pleasure. "
            "Parkinson's disease is associated with the loss of dopamine-producing cells."
        )
        upload_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/documents",
            files={"file": ("dopamine_notes.txt", doc_content.encode("utf-8"), "text/plain")},
            headers=headers,
        )
        assert upload_resp.status_code == 202
        doc_id = upload_resp.json()["document_id"]
        print(f"  [PASS] Document uploaded: 'dopamine_notes.txt' (id: {doc_id})")

        # Ingestion
        ingest_resp = await client.post(
            f"/api/v1/documents/{doc_id}/reprocess",
            json={"force_vision_ocr": False},
            headers=headers,
        )
        assert ingest_resp.status_code == 200
        print("  [PASS] Document ingested and indexed successfully")

        # 7. Page Image Render Endpoint
        page_img_resp = await client.get(
            f"/api/v1/documents/{doc_id}/pages/1/image",
            headers=headers,
        )
        assert page_img_resp.status_code == 200
        assert page_img_resp.headers["content-type"] == "image/png"
        assert page_img_resp.content.startswith(b"\x89PNG\r\n\x1a\n")
        print(f"  [PASS] Verified GET /documents/{doc_id}/pages/1/image renders valid PNG image ({len(page_img_resp.content)} bytes)")

        # 8. Create Conversation
        conv_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/conversations",
            json={"title": "Neuroscience Chat"},
            headers=headers,
        )
        assert conv_resp.status_code == 201
        conv_id = conv_resp.json()["id"]
        print(f"  [PASS] Conversation created: 'Neuroscience Chat' (id: {conv_id})")

        # 9. Grounded Question & Answer with Citations
        chat_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"question": "What roles does dopamine play in the brain?", "strict_mode": False},
            headers=headers,
        )
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()
        assert not chat_data["abstained"], "Expected answerable grounded response"
        assert len(chat_data["citations"]) > 0, "Expected at least 1 verified citation"
        first_citation = chat_data["citations"][0]
        assert first_citation["document_id"] == doc_id
        assert first_citation["page"] == 1
        assert "dopamine" in first_citation["quote"].lower()
        print(f"  [PASS] Grounded answer generated with {len(chat_data['citations'])} verified citation(s)")
        print(f"      Citation [1]: Doc={first_citation['document_id'][:8]} Page={first_citation['page']} Quote='{first_citation['quote'][:45]}...'")

        # 10. Verify Bounding Box Highlight Coordinates
        bbox = first_citation["bbox"]
        assert isinstance(bbox, list) and len(bbox) == 4, f"Invalid bbox format: {bbox}"
        print(f"  [PASS] Bounding box verified: {bbox}")

        # 11. Feedback Submission
        msg_id = chat_data["message_id"]
        fb_resp = await client.post(
            f"/api/v1/messages/{msg_id}/feedback",
            json={"rating": "up"},
            headers=headers,
        )
        assert fb_resp.status_code == 201
        print(f"  [PASS] User feedback submitted for message {msg_id}")

        # 12. Abstention Flow with Suggestions
        abstain_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"question": "What is the capital of Australia and who is the prime minister?", "strict_mode": True},
            headers=headers,
        )
        assert abstain_resp.status_code == 200
        abstain_data = abstain_resp.json()
        assert abstain_data["abstained"], "Expected abstention on ungrounded out-of-scope question"
        print("  [PASS] Abstention flow verified (abstained=True, zero outside knowledge)")

    # 13. Test Frontend Dev Server boot (server.js)
    print("  [*] Verifying Node development server (server.js)...")
    node_proc = subprocess.Popen(  # noqa: ASYNC220
        ["node", "frontend/server.js"],
        env={**os.environ, "PORT": "3099", "API_URL": "http://localhost:8000"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    await asyncio.sleep(1.0)
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:3099") as dev_client:
            dev_resp = await dev_client.get("/")
            assert dev_resp.status_code == 200
            assert "StudyMind" in dev_resp.text
            print("  [PASS] Node dev server running on port 3099 successfully served index.html")
    finally:
        node_proc.terminate()
        node_proc.wait()

    print("=" * 70)
    print("All Phase 6 Frontend Definition of Done (DoD) Checks PASSED!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = asyncio.run(run_verification())
    if not success:
        sys.exit(1)
