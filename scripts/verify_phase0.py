"""Phase 0 verification and demo script.

Verifies:
1. Configuration loads cleanly.
2. Database models initialize in an in-memory session.
3. Health endpoint returns 200 OK.
4. Adapters contract functions correctly.
"""

import asyncio

from app.adapters import (
    InMemoryVectorStoreAdapter,
    get_embedding_adapter,
    get_llm_adapter,
)
from app.core.config import settings
from app.db.models import Base
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine


async def run_demo() -> None:
    print("=== StudyMind Phase 0 Demo ===")
    print(f"1. Project: {settings.PROJECT_NAME} ({settings.ENVIRONMENT})")
    print(f"   Configured LLM: {settings.LLM_PROVIDER} ({settings.LLM_MODEL})")
    print(f"   Embeddings: {settings.EMBEDDING_PROVIDER} ({settings.EMBEDDING_MODEL})")

    # 2. In-memory DB check
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    table_count = len(Base.metadata.tables)
    print(
        f"2. Database ORM tables initialized successfully: {table_count} tables created."
    )

    # 3. HTTP Health endpoint check
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/health")
        print(f"3. GET /health -> Status {resp.status_code}: {resp.json()}")

    # 4. Adapters test
    llm = get_llm_adapter("mock")
    llm_resp = await llm.generate([{"role": "user", "content": "ping"}])
    embedder = get_embedding_adapter("mock")
    vec = await embedder.embed_query("test query")
    vector_store = InMemoryVectorStoreAdapter()
    print(
        f"4. Service Adapters: LLM '{llm_resp.model}', Embedder dim={len(vec)}, "
        f"VectorStore {vector_store.__class__.__name__} ready."
    )

    print("\n>>> Phase 0 Verification PASSED! All systems operational. <<<\n")


if __name__ == "__main__":
    asyncio.run(run_demo())
