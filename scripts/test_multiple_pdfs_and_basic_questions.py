"""Verification script testing multiple document uploads in a single subject
and answering basic questions related to the material/topic.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from httpx import AsyncClient, ASGITransport
from app.main import app

async def main():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Guest session
        auth_res = await client.post("/api/v1/auth/guest")
        assert auth_res.status_code == 200, auth_res.text
        data = auth_res.json()
        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"[1] Guest session created: {data['user']['email']}")

        # 2. Create Subject Workspace: "Natural Language Processing"
        ws_res = await client.post(
            "/api/v1/workspaces",
            headers=headers,
            json={"name": "Natural Language Processing (NLP)"},
        )
        assert ws_res.status_code == 201, ws_res.text
        ws = ws_res.json()
        ws_id = ws["id"]
        print(f"[2] Created Subject Workspace: '{ws['name']}' (id: {ws_id})")

        # 3. Upload 2-3 documents for the same subject
        doc1_text = (
            "Lab Practical 1: Word Tokenization Fundamentals.\n"
            "Word tokenization is the foundational process of segmenting continuous text into discrete lexical tokens or words.\n"
            "It is widely used across search engines, machine translation, and language modeling.\n"
            "Unlike simple whitespace splitting with text.split(), word tokenization handles punctuation marks and contractions by separating them as distinct tokens."
        )
        doc2_text = (
            "Lab Practical 2: Python NLTK and SpaCy Implementation.\n"
            "Practical Implementation in Python is typically achieved using the Natural Language Toolkit (NLTK) library.\n"
            "Code example: from nltk.tokenize import word_tokenize; tokens = word_tokenize(text).\n"
            "NLTK uses the TreebankWordTokenizer under the hood to preserve grammatical structure."
        )
        doc3_text = (
            "Lab Practical 3: Evaluation and Preprocessing Applications.\n"
            "Tokenization is an essential prerequisite step for text preprocessing, stemming, lemmatization, and stop-word removal.\n"
            "Common challenges include dealing with hyphenated words, URLs, abbreviations, and emoticons.\n"
            "Standard benchmark tokenizers maintain high precision across multilingual corpora."
        )

        for i, (name, content) in enumerate([
            ("word_tokenization_part1.txt", doc1_text),
            ("word_tokenization_part2_implementation.txt", doc2_text),
            ("word_tokenization_part3_preprocessing.txt", doc3_text),
        ], 1):
            files = {"file": (name, content.encode("utf-8"), "text/plain")}
            up_res = await client.post(f"/api/v1/workspaces/{ws_id}/documents", headers=headers, files=files)
            assert up_res.status_code in [201, 202], up_res.text
            d = up_res.json()
            doc_id = d["document_id"]
            # Trigger reprocessing
            await client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=headers, json={"force_vision_ocr": False})
            print(f"    Uploaded & indexed Doc {i}: '{name}' (id: {doc_id})")

        # 4. Create study conversation
        conv_res = await client.post(
            f"/api/v1/workspaces/{ws_id}/conversations",
            headers=headers,
            json={"title": "NLP Study Session"},
        )
        assert conv_res.status_code == 201
        conv_id = conv_res.json()["id"]

        # 5. Ask a variety of basic questions related to the provided material
        test_queries = [
            "What is word tokenization?",
            "How is word tokenization implemented in Python?",
            "What is the difference between word tokenization and simple whitespace splitting?",
            "What libraries are used in this practical?",
            "Explain how tokenization is used in preprocessing and what challenges exist.",
            "Can you give an overview of what this lab material teaches?",
        ]

        print("\n[3] Testing Question Answering across uploaded subject materials:")
        for q in test_queries:
            q_res = await client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                headers=headers,
                json={"question": q, "strict_mode": False},
            )
            assert q_res.status_code == 200, q_res.text
            ans = q_res.json()
            answer_text = " ".join(s["text"] for s in ans["answer"])
            citations_count = len(ans["citations"])
            print(f"\nQ: {q}")
            print(f"Abstained: {ans['abstained']} | Citations: {citations_count} | Confidence: {ans['confidence']}")
            print(f"A: {answer_text}")
            if ans["citations"]:
                for c in ans["citations"]:
                    print(f"   Citation [{c['n']}]: Page {c['page']} - \"{c['quote']}\"")
            assert not ans["abstained"], f"Unexpected abstention on query: {q}"
            assert citations_count > 0, f"Expected verified citations on query: {q}"

        print("\nAll subject queries answered and verified with citations!")

if __name__ == "__main__":
    asyncio.run(main())
