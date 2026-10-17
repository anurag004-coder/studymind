import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.db.session import init_db, AsyncSessionLocal
from app.db.models.workspace import Workspace
from app.db.models.user import User
from app.db.models.document import Document
from app.adapters import get_storage_adapter
from app.ingestion.pipeline import IngestionPipeline
from app.generation.pipeline import GroundedGenerationPipeline
from sqlalchemy import select

async def main():
    await init_db()
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        if not user:
            print("No user found in DB")
            return
        ws = (await db.execute(select(Workspace).where(Workspace.user_id == user.id))).scalars().first()
        if not ws:
            print("No workspace found")
            return
        print(f"User: {user.email}, Workspace: {ws.id} ({ws.name})")

        sample_text = (
            "Lab Practical: Word Tokenization Implementation in Python\n\n"
            "Word tokenization is the process of breaking down a continuous stream of text into individual words or lexical units.\n"
            "In Natural Language Processing (NLP), word tokenization serves as the foundational preprocessing step before feature extraction, part-of-speech tagging, and syntactic parsing.\n\n"
            "Practical Implementation using Python and NLTK:\n"
            "from nltk.tokenize import word_tokenize\n"
            "text = 'Artificial Intelligence is transforming modern education.'\n"
            "tokens = word_tokenize(text)\n\n"
            "Execution Output:\n"
            "['Artificial', 'Intelligence', 'is', 'transforming', 'modern', 'education', '.']\n\n"
            "Key Difference:\n"
            "Unlike simple whitespace splitting with text.split(), word tokenization correctly handles punctuation marks and contractions by separating them as distinct tokens.\n"
        )
        file_bytes = sample_text.encode("utf-8")
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        filename = "word_tokenization_practical.txt"

        doc = Document(
            workspace_id=ws.id,
            user_id=user.id,
            filename=filename,
            mime="text/plain",
            sha256=sha256,
            storage_key=f"users/{user.id}/workspaces/{ws.id}/test_token/{filename}",
            status="queued"
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        storage = get_storage_adapter()
        await storage.put_object(doc.storage_key, file_bytes, doc.mime)

        ingestion = IngestionPipeline()
        ingested_doc = await ingestion.ingest_document(document_id=doc.id, db=db)
        print(f"Ingested doc {ingested_doc.id} with status '{ingested_doc.status}', pages: {ingested_doc.pages}")

        pipeline = GroundedGenerationPipeline()
        questions = [
            "What is word tokenization?",
            "How is word tokenization implemented in Python?",
            "What is the difference between word tokenization and simple whitespace splitting?",
        ]

        for q in questions:
            print(f"\n==========================================")
            print(f"QUESTION: {q}")
            ans = await pipeline.answer_question(
                question=q,
                user_id=user.id,
                workspace_id=ws.id
            )
            print(f"Abstained: {ans.abstained}")
            print(f"Confidence: {ans.confidence}")
            answer_text = ' '.join(s.text for s in ans.answer)
            print(f"Answer: {answer_text}")
            print(f"Citations ({len(ans.citations)}):")
            for c in ans.citations:
                print(f"  [{c.n}] Page {c.page}: \"{c.quote}\"")

if __name__ == "__main__":
    asyncio.run(main())
