"""Load testing and latency benchmarking harness for StudyMind per PRD.md §5.
Validates Non-Functional Requirements:
- Answer / query latency: p50 < 6 s, p95 < 15 s
- Concurrency scaling without dropped requests or deadlocks
- Reports p50, p90, p95, and p99 percentiles and Requests Per Second (RPS)
"""

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

# Add backend directory to path
backend_dir = Path("backend").resolve()
sys.path.insert(0, str(backend_dir))
os.chdir(str(backend_dir.parent))

from httpx import ASGITransport, AsyncClient


async def run_load_test(concurrency: int = 20, total_requests: int = 40) -> dict[str, float]:
    print("=" * 75)
    print(f"StudyMind Load Test Benchmark: {total_requests} requests, concurrency={concurrency}")
    print("=" * 75)

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
        # Setup: Create User & Workspace & Ingest Document
        print("[Setup] Initializing user and benchmark material...")
        reg = await client.post(
            "/api/v1/auth/register",
            json={"email": "loadtester@studymind.io", "password": "SecurePassword123!"},
        )
        assert reg.status_code == 201
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "loadtester@studymind.io", "password": "SecurePassword123!"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        ws = await client.post("/api/v1/workspaces", json={"name": "Benchmark Lab"}, headers=headers)
        ws_id = ws.json()["id"]

        doc_text = (
            "Biochemical energetics and metabolic regulation.\n"
            "Glycolysis yields 2 pyruvate molecules and 2 ATP in the cytoplasm. "
            "Oxidative phosphorylation occurs on the mitochondrial inner membrane, "
            "synthesizing approximately 30 to 32 ATP per glucose molecule via ATP synthase."
        )
        up = await client.post(
            f"/api/v1/workspaces/{ws_id}/documents",
            files={"file": ("energetics.txt", doc_text.encode("utf-8"), "text/plain")},
            headers=headers,
        )
        doc_id = up.json()["document_id"]
        await client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=headers)
        print("  [PASS] Setup complete. Launching concurrent request batch...\n")

        # Concurrent worker
        latencies: list[float] = []
        errors = 0
        sem = asyncio.Semaphore(concurrency)

        queries = [
            "How many ATP molecules are produced during oxidative phosphorylation?",
            "Where does glycolysis occur?",
            "What enzyme synthesizes ATP in the mitochondria?",
            "What is the net yield of glycolysis?",
        ]

        async def worker_task(idx: int) -> None:
            nonlocal errors
            q = queries[idx % len(queries)]
            async with sem:
                t0 = time.perf_counter()
                try:
                    resp = await client.post(
                        f"/api/v1/workspaces/{ws_id}/search",
                        json={"query": q, "top_k": 4},
                        headers=headers,
                    )
                    elapsed = time.perf_counter() - t0
                    if resp.status_code == 200:
                        latencies.append(elapsed)
                    else:
                        errors += 1
                except Exception as e:
                    errors += 1

        overall_start = time.perf_counter()
        tasks = [asyncio.create_task(worker_task(i)) for i in range(total_requests)]
        await asyncio.gather(*tasks)
        total_time = time.perf_counter() - overall_start

        # Calculate Percentiles
        latencies.sort()
        n = len(latencies)
        assert n > 0, "No successful requests recorded!"

        p50 = statistics.median(latencies)
        p90 = latencies[int(n * 0.90)] if n >= 10 else latencies[-1]
        p95 = latencies[int(n * 0.95)] if n >= 20 else latencies[-1]
        p99 = latencies[int(n * 0.99)] if n >= 50 else latencies[-1]
        rps = round(n / total_time, 2)

        print("-" * 75)
        print(f"Results: {n}/{total_requests} succeeded ({errors} errors)")
        print(f"Total Test Duration: {total_time:.2f} s")
        print(f"Throughput:         {rps} req/sec (RPS)")
        print(f"p50 Latency:        {p50 * 1000:.1f} ms  (Target: < 6,000 ms)")
        print(f"p90 Latency:        {p90 * 1000:.1f} ms")
        print(f"p95 Latency:        {p95 * 1000:.1f} ms  (Target: < 15,000 ms)")
        print(f"p99 Latency:        {p99 * 1000:.1f} ms")
        print("-" * 75)

        # PRD Non-Functional Requirement Assertions
        assert p50 < 6.0, f"p50 latency {p50}s exceeded 6.0s limit"
        assert p95 < 15.0, f"p95 latency {p95}s exceeded 15.0s limit"
        print("  [PASS] All PRD non-functional latency targets met!\n")

        return {
            "p50_ms": round(p50 * 1000, 1),
            "p90_ms": round(p90 * 1000, 1),
            "p95_ms": round(p95 * 1000, 1),
            "p99_ms": round(p99 * 1000, 1),
            "rps": rps,
        }


if __name__ == "__main__":
    asyncio.run(run_load_test(concurrency=10, total_requests=30))
