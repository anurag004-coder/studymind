import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "backend"))

import sqlite3
conn = sqlite3.connect("studymind.db")
c = conn.cursor()
c.execute("SELECT user_id, workspace_id FROM documents WHERE id = ?", ("a63ccd60-4bab-4670-a849-4b443f7bcf7e",))
row = c.fetchone()
if not row:
    print("Document not found")
    sys.exit(1)
user_id, ws_id = row
print(f"Testing for user: {user_id}, workspace: {ws_id}")

from app.generation.pipeline import GroundedGenerationPipeline

async def test_summary():
    pipeline = GroundedGenerationPipeline()
    for q in ["summarize the topics", "summarize page 1", "what are the main components on this page?"]:
        print(f"\n==========================================")
        print(f"QUESTION: {q}")
        res = await pipeline.answer_question(
            question=q,
            user_id=user_id,
            workspace_id=ws_id,
            document_ids=["a63ccd60-4bab-4670-a849-4b443f7bcf7e"],
            strict_mode=False
        )
        print(f"Abstained: {res.abstained} | Confidence: {res.confidence}")
        for i, s in enumerate(res.answer, 1):
            print(f"[{i}] {s.text}")
        for cit in res.citations:
            print(f"   Citation [{cit.n}] page {cit.page}: \"{cit.quote}\"")

if __name__ == "__main__":
    asyncio.run(test_summary())
