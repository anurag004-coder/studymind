"""Verification script for Phase 7 — Study Tools.
Validates:
1. Map-reduce Summary generation with verified key takeaways and quotes.
2. Grounded Flashcards generation where every card has a valid source chunk + quote.
3. Grounded Quiz generation with verified explanations, 4 options, and valid quotes.
4. Saved study items listing, metadata, and deletion.
5. Export to Anki TSV format and Markdown study guide compiler.
6. Multi-tenant user isolation across all study endpoints.
7. DoD Verification: 100% of generated items have valid source chunk + quote.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path("backend").resolve()
sys.path.insert(0, str(backend_dir))
os.chdir(str(backend_dir.parent))

from httpx import ASGITransport, AsyncClient
from rapidfuzz import fuzz


async def run_verification() -> bool:
    print("=" * 70)
    print("StudyMind Phase 7 — Study Tools Verification Harness")
    print("=" * 70)

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

    async def _override_get_db():
        async with session_factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: User A registration & authentication
        print("\n[Step 1] Registering and authenticating test user...")
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "phase7_tester@studymind.io", "password": "SecurePassword123!"},
        )
        assert reg_resp.status_code == 201, f"Failed register: {reg_resp.text}"
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "phase7_tester@studymind.io", "password": "SecurePassword123!"},
        )
        assert login_resp.status_code == 200, f"Failed login: {login_resp.text}"
        token_a = login_resp.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}
        print("  [PASS] User A authenticated successfully.")

        # Step 2: Create workspace
        print("\n[Step 2] Creating workspace...")
        ws_resp = await client.post(
            "/api/v1/workspaces",
            json={"name": "Biochemistry & Cellular Bio"},
            headers=headers_a,
        )
        assert ws_resp.status_code == 201, f"Failed workspace: {ws_resp.text}"
        ws_id = ws_resp.json()["id"]
        print(f"  [PASS] Workspace created: id={ws_id}")

        # Step 3: Ingest rich study material
        print("\n[Step 3] Uploading and processing study document...")
        bio_doc_text = (
            "Photosynthesis is the biological process by which autotrophic organisms convert "
            "light energy into chemical energy. In plant cells, this reaction takes place inside "
            "chloroplasts, specifically within the thylakoid membranes where chlorophyll pigments reside. "
            "The light-dependent reactions produce ATP and NADPH through photophosphorylation. "
            "\n\n"
            "The Calvin cycle, or light-independent reactions, occurs in the stroma of chloroplasts. "
            "Ribulose 1,5-bisphosphate carboxylase-oxygenase, commonly known as RuBisCO, catalyzes "
            "the fixation of carbon dioxide into 3-phosphoglycerate. This pathway converts CO2 "
            "into glyceraldehyde 3-phosphate (G3P) for subsequent glucose synthesis. "
            "\n\n"
            "Cellular respiration is the metabolic pathway that breaks down glucose to produce ATP. "
            "Glycolysis occurs in the cytoplasm and yields two pyruvate molecules, two net ATP, and two NADH. "
            "The citric acid cycle, also known as the Krebs cycle, operates in the mitochondrial matrix, "
            "oxidizing acetyl-CoA to CO2 while reducing NAD+ and FAD to NADH and FADH2."
        )

        up_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/documents",
            files={"file": ("cellular_energetics.txt", bio_doc_text.encode("utf-8"), "text/plain")},
            headers=headers_a,
        )
        assert up_resp.status_code in (200, 201, 202), f"Failed upload: {up_resp.text}"
        doc_id = up_resp.json()["document_id"]

        reproc_resp = await client.post(
            f"/api/v1/documents/{doc_id}/reprocess",
            json={"force_vision_ocr": False},
            headers=headers_a,
        )
        assert reproc_resp.status_code == 200, f"Failed reprocess: {reproc_resp.text}"
        print(f"  [PASS] Document ingested and indexed: doc_id={doc_id}")

        # Step 4: Map-Reduce Summary Generation
        print("\n[Step 4] Testing Map-Reduce Summary generation...")
        sum_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/study/summary",
            json={"document_ids": [doc_id], "length": "medium", "focus": "Energetics"},
            headers=headers_a,
        )
        assert sum_resp.status_code == 200, f"Summary failed: {sum_resp.text}"
        sum_data = sum_resp.json()
        assert len(sum_data["summary"]) > 50, "Summary too short"
        assert len(sum_data["key_takeaways"]) >= 1, "Missing key takeaways"
        print(f"  Generated Summary ({len(sum_data['summary'])} chars):")
        print(f"    Preview: {sum_data['summary'][:120]}...")
        print(f"  Key Takeaways ({len(sum_data['key_takeaways'])} items):")

        for idx, t in enumerate(sum_data["key_takeaways"], 1):
            assert t["source_chunk_id"], "Missing source_chunk_id in takeaway"
            assert t["quote"], "Missing quote in takeaway"
            # Fuzzy match quote against document text
            score = fuzz.partial_ratio(t["quote"].lower(), bio_doc_text.lower())
            assert score >= 70.0, f"Takeaway quote ungrounded: score={score}, quote={t['quote']}"
            print(f"    [{idx}] Point: {t['point'][:60]}... | Quote match: {score:.1f}%")
        print("  [PASS] Map-Reduce summary verified with grounded takeaways.")

        # Step 5: Grounded Flashcard Generation
        print("\n[Step 5] Testing Grounded Flashcards generation...")
        fc_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/study/flashcards",
            json={"count": 3, "topic": "Photosynthesis and Respiration"},
            headers=headers_a,
        )
        assert fc_resp.status_code == 200, f"Flashcards failed: {fc_resp.text}"
        fc_data = fc_resp.json()
        flashcards = fc_data["flashcards"]
        assert len(flashcards) >= 1, "No flashcards generated"
        print(f"  Generated {len(flashcards)} flashcards:")

        for idx, card in enumerate(flashcards, 1):
            assert card["question"], "Empty flashcard question"
            assert card["answer"], "Empty flashcard answer"
            assert card["source_chunk_id"], "Missing chunk ID on flashcard"
            assert card["quote"], "Missing quote on flashcard"
            score = fuzz.partial_ratio(card["quote"].lower(), bio_doc_text.lower())
            assert score >= 70.0, f"Flashcard quote ungrounded: score={score}, quote={card['quote']}"
            print(f"    Card {idx}: Q: {card['question'][:50]}... | Match: {score:.1f}%")
        print("  [PASS] Grounded flashcards verified with valid source chunks + quotes.")

        # Step 6: Grounded Quiz Generation
        print("\n[Step 6] Testing Grounded Quiz generation...")
        quiz_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/study/quiz",
            json={"count": 3, "difficulty": "medium", "topic": "Cellular Biology"},
            headers=headers_a,
        )
        assert quiz_resp.status_code == 200, f"Quiz generation failed: {quiz_resp.text}"
        quiz_data = quiz_resp.json()
        questions = quiz_data["questions"]
        assert len(questions) >= 1, "No quiz questions generated"
        print(f"  Generated {len(questions)} quiz questions:")

        for idx, q in enumerate(questions, 1):
            assert len(q["stem"]) > 0, "Empty stem"
            assert len(q["options"]) == 4, f"Expected 4 options, got {len(q['options'])}"
            assert 0 <= q["correct_answer_index"] <= 3, f"Invalid correct index: {q['correct_answer_index']}"
            assert len(q["explanation"]) > 0, "Missing explanation"
            assert q["source_chunk_id"], "Missing source_chunk_id on quiz question"
            assert q["quote"], "Missing quote on quiz question"
            score = fuzz.partial_ratio(q["quote"].lower(), bio_doc_text.lower())
            assert score >= 70.0, f"Quiz quote ungrounded: score={score}, quote={q['quote']}"
            print(f"    Q{idx}: {q['stem'][:50]}... | Correct: Opt {q['correct_answer_index']} | Match: {score:.1f}%")
        print("  [PASS] Grounded quiz questions verified with 4 options and verified quotes.")

        # Step 7: Saved Study Items & Management
        print("\n[Step 7] Testing Study Items listing and deletion...")
        items_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/study/items",
            headers=headers_a,
        )
        assert items_resp.status_code == 200, f"Failed listing items: {items_resp.text}"
        saved_items = items_resp.json()["items"]
        assert len(saved_items) >= 4, f"Expected >= 4 saved items, got {len(saved_items)}"

        types_found = {item["type"] for item in saved_items}
        print(f"  Saved items count: {len(saved_items)}, types found: {types_found}")
        assert "summary" in types_found or "flashcard" in types_found

        # Delete one item to test cleanup endpoint
        del_item_id = saved_items[0]["id"]
        del_resp = await client.delete(
            f"/api/v1/study/items/{del_item_id}",
            headers=headers_a,
        )
        assert del_resp.status_code in (200, 204), f"Failed delete item: {del_resp.text}"
        print(f"  [PASS] Deleted study item id={del_item_id}")

        # Step 8: Exporting to Anki TSV and Markdown
        print("\n[Step 8] Testing Anki TSV and Markdown exports...")
        anki_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/study/export/anki",
            headers=headers_a,
        )
        assert anki_resp.status_code == 200, f"Anki export failed: {anki_resp.text}"
        assert "text/tab-separated-values" in anki_resp.headers["content-type"]
        assert "attachment" in anki_resp.headers.get("content-disposition", "")
        anki_text = anki_resp.text
        assert "\t" in anki_text, "Anki export missing tab delimiters"
        print(f"  [PASS] Anki export verified ({len(anki_text)} bytes, valid TSV columns).")

        md_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/study/export/markdown",
            headers=headers_a,
        )
        assert md_resp.status_code == 200, f"Markdown export failed: {md_resp.text}"
        assert "text/markdown" in md_resp.headers["content-type"]
        md_text = md_resp.text
        assert "# Study Guide:" in md_text
        assert "Biochemistry & Cellular Bio" in md_text
        print(f"  [PASS] Markdown export verified ({len(md_text)} bytes, markdown headers present).")

        # Step 9: User Isolation & Security
        print("\n[Step 9] Verifying strict User Isolation across study endpoints...")
        reg_b = await client.post(
            "/api/v1/auth/register",
            json={"email": "phase7_intruder@studymind.io", "password": "SecurePassword123!"},
        )
        assert reg_b.status_code in (200, 201)
        login_b = await client.post(
            "/api/v1/auth/login",
            json={"email": "phase7_intruder@studymind.io", "password": "SecurePassword123!"},
        )
        token_b = login_b.json()["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User B trying to access User A's workspace study items
        leak_items = await client.get(
            f"/api/v1/workspaces/{ws_id}/study/items",
            headers=headers_b,
        )
        assert leak_items.status_code == 404, f"Security breach: items returned {leak_items.status_code}"

        # User B trying to export User A's workspace
        leak_anki = await client.get(
            f"/api/v1/workspaces/{ws_id}/study/export/anki",
            headers=headers_b,
        )
        assert leak_anki.status_code == 404, f"Security breach: export returned {leak_anki.status_code}"

        # User B trying to delete User A's study item
        if len(saved_items) > 1:
            leak_del = await client.delete(
                f"/api/v1/study/items/{saved_items[1]['id']}",
                headers=headers_b,
            )
            assert leak_del.status_code == 404, f"Security breach: delete returned {leak_del.status_code}"

        print("  [PASS] Multi-tenant isolation verified: unauthorized cross-workspace queries rejected with 404.")

        # Step 10: Definition of Done Evaluation Check
        print("\n" + "=" * 70)
        print("PHASE 7 DEFINITION OF DONE EVALUATION SUMMARY")
        print("=" * 70)
        total_items_checked = (
            len(sum_data["key_takeaways"]) + len(flashcards) + len(questions)
        )
        print(f"  Total Generated Study Items Evaluated: {total_items_checked}")
        print(f"  Takeaways with verified source chunk & quote: {len(sum_data['key_takeaways'])} / {len(sum_data['key_takeaways'])} (100.0%)")
        print(f"  Flashcards with verified source chunk & quote: {len(flashcards)} / {len(flashcards)} (100.0%)")
        print(f"  Quiz items with verified source chunk & quote: {len(questions)} / {len(questions)} (100.0%)")
        print("  Overall Grounded Item Validity Rate: 100.0% (Criterion: 100.0% required)")
        print("=" * 70)
        print("ALL PHASE 7 VERIFICATION CHECKS PASSED SUCCESSFULLY!\n")

    return True


if __name__ == "__main__":
    success = asyncio.run(run_verification())
    sys.exit(0 if success else 1)
