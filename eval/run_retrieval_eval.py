"""Retrieval Evaluation Script measuring Recall@k, MRR, and Abstention Precision per EVALUATION.md."""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure backend app is in PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.adapters import (
    InMemoryVectorStoreAdapter,
    MockEmbeddingAdapter,
    MockRerankerAdapter,
)
from app.ingestion.lexical_index import LexicalIndex
from app.retrieval.gate import RelevanceGate
from app.retrieval.query_rewrite import QueryRewriter
from app.retrieval.service import RetrievalService

DATASETS_DIR = REPO_ROOT / "eval" / "datasets"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


async def setup_eval_corpus(
    vector_store: InMemoryVectorStoreAdapter,
    lexical: LexicalIndex,
    embedder: MockEmbeddingAdapter,
    user_id: str,
    workspace_id: str,
    gold_data: list[dict],
) -> None:
    """Indexes unique chunks from the gold dataset into isolated stores."""
    chunks_to_index: list[dict] = []
    texts_to_embed: list[str] = []

    seen_cids = set()
    for item in gold_data:
        cid = item["gold_chunk_ids"][0]
        if cid in seen_cids:
            continue
        seen_cids.add(cid)

        chunk_payload = {
            "chunk_id": cid,
            "document_id": item["doc_id"],
            "workspace_id": workspace_id,
            "user_id": user_id,
            "page_start": item["gold_page"],
            "page_end": item["gold_page"],
            "text": item["text"],
            "section_path": ["StudyMaterial", item.get("type", "fact")],
            "block_type": "paragraph",
        }
        chunks_to_index.append(chunk_payload)
        texts_to_embed.append(item["text"])

    vectors = await embedder.embed_texts(texts_to_embed)
    await vector_store.upsert(chunks_to_index, vectors)
    lexical.index_chunks(chunks_to_index)


async def run_retrieval_evaluation(verbose: bool = True) -> dict:
    """Executes the complete retrieval evaluation suite."""
    gold_file = DATASETS_DIR / "gold_answerable.jsonl"
    unanswerable_file = DATASETS_DIR / "unanswerable.jsonl"

    if not gold_file.exists():
        raise FileNotFoundError(f"Missing gold dataset: {gold_file}")

    gold_data = [
        json.loads(line)
        for line in gold_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    unanswerable_data = (
        [
            json.loads(line)
            for line in unanswerable_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if unanswerable_file.exists()
        else []
    )

    eval_user_id = "eval_user_001"
    eval_workspace_id = "eval_workspace_001"

    # Dedicated in-memory components for pure, isolated benchmark
    vector_store = InMemoryVectorStoreAdapter(shared=False)
    lexical = LexicalIndex()
    embedder = MockEmbeddingAdapter()
    reranker = MockRerankerAdapter()
    query_rewriter = QueryRewriter()
    gate = RelevanceGate(min_relevance_score=0.35)

    await setup_eval_corpus(
        vector_store=vector_store,
        lexical=lexical,
        embedder=embedder,
        user_id=eval_user_id,
        workspace_id=eval_workspace_id,
        gold_data=gold_data,
    )

    retrieval_service = RetrievalService(
        vector_store=vector_store,
        embedder=embedder,
        lexical=lexical,
        reranker=reranker,
        query_rewriter=query_rewriter,
        gate=gate,
    )

    # 1. Evaluate Gold Answerable Questions
    hits_at_6 = 0
    hits_at_30 = 0
    page_hits_at_6 = 0
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    false_abstains = 0

    per_query_results = []

    for item in gold_data:
        q_id = item["id"]
        question = item["question"]
        gold_chunk_ids = set(item["gold_chunk_ids"])
        gold_page = item["gold_page"]

        start = time.perf_counter()
        res = await retrieval_service.retrieve(
            query=question,
            user_id=eval_user_id,
            workspace_id=eval_workspace_id,
            top_k=6,
            top_candidates=30,
        )
        duration_ms = (time.perf_counter() - start) * 1000
        latencies.append(duration_ms)

        retrieved_cids = [c.chunk_id for c in res.chunks]
        retrieved_pages = [c.page_start for c in res.chunks]

        # Calculate rank of first relevant chunk
        rr = 0.0
        for rank, cid in enumerate(retrieved_cids, start=1):
            if cid in gold_chunk_ids:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

        is_hit_6 = any(cid in gold_chunk_ids for cid in retrieved_cids[:6])
        is_hit_30 = any(cid in gold_chunk_ids for cid in retrieved_cids)
        is_page_hit = gold_page in retrieved_pages[:6]

        if is_hit_6:
            hits_at_6 += 1
        if is_hit_30:
            hits_at_30 += 1
        if is_page_hit:
            page_hits_at_6 += 1

        if res.gate_decision.should_abstain:
            false_abstains += 1

        per_query_results.append(
            {
                "id": q_id,
                "question": question,
                "type": item.get("type", "fact"),
                "hit_at_6": is_hit_6,
                "reciprocal_rank": round(rr, 4),
                "best_score": res.gate_decision.best_score,
                "abstained": res.gate_decision.should_abstain,
                "latency_ms": round(duration_ms, 2),
            }
        )

    # 2. Evaluate Unanswerable Questions
    correct_abstains = 0
    unanswerable_results = []

    for item in unanswerable_data:
        u_id = item["id"]
        question = item["question"]
        res = await retrieval_service.retrieve(
            query=question,
            user_id=eval_user_id,
            workspace_id=eval_workspace_id,
            top_k=6,
            top_candidates=30,
        )

        should_abstain = res.gate_decision.should_abstain
        if should_abstain:
            correct_abstains += 1

        unanswerable_results.append(
            {
                "id": u_id,
                "question": question,
                "category": item.get("category", "general"),
                "best_score": res.gate_decision.best_score,
                "abstained_correctly": should_abstain,
                "reason": res.gate_decision.reason,
            }
        )

    total_gold = len(gold_data)
    total_unans = len(unanswerable_data)

    recall_at_6 = float(hits_at_6 / total_gold) if total_gold > 0 else 0.0
    recall_at_30 = float(hits_at_30 / total_gold) if total_gold > 0 else 0.0
    page_hit_rate = float(page_hits_at_6 / total_gold) if total_gold > 0 else 0.0
    mrr = float(sum(reciprocal_ranks) / total_gold) if total_gold > 0 else 0.0
    false_abstain_rate = float(false_abstains / total_gold) if total_gold > 0 else 0.0
    abstention_precision = (
        float(correct_abstains / total_unans) if total_unans > 0 else 1.0
    )

    latencies.sort()
    p50_latency = latencies[len(latencies) // 2] if latencies else 0.0
    p95_latency = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "summary": {
            "total_gold_queries": total_gold,
            "total_unanswerable_queries": total_unans,
            "recall_at_6": round(recall_at_6, 4),
            "recall_at_30": round(recall_at_30, 4),
            "page_hit_rate_at_6": round(page_hit_rate, 4),
            "mrr": round(mrr, 4),
            "abstention_precision": round(abstention_precision, 4),
            "false_abstain_rate": round(false_abstain_rate, 4),
            "latency_p50_ms": round(p50_latency, 2),
            "latency_p95_ms": round(p95_latency, 2),
            "recall_target_met": recall_at_6 >= 0.85,
            "abstention_target_met": abstention_precision >= 0.90,
        },
        "per_query_results": per_query_results,
        "unanswerable_results": unanswerable_results,
    }

    # Write JSON and Markdown reports
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_slug = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_json_path = REPORTS_DIR / f"retrieval_eval_{timestamp_slug}.json"
    report_md_path = REPORTS_DIR / f"retrieval_eval_{timestamp_slug}.md"

    report_json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_content = f"""# Retrieval Evaluation Report ({report["timestamp"]})

## Summary Metrics
- **Recall@6**: {recall_at_6:.2%} (Target: >= 85.0%) -> **{"PASS" if recall_at_6 >= 0.85 else "FAIL"}**
- **Recall@30**: {recall_at_30:.2%}
- **MRR (Mean Reciprocal Rank)**: {mrr:.4f}
- **Page Hit Rate@6**: {page_hit_rate:.2%}
- **Abstention Precision**: {abstention_precision:.2%} (Target: >= 90.0%) -> **{"PASS" if abstention_precision >= 0.90 else "FAIL"}**
- **False Abstain Rate**: {false_abstain_rate:.2%} (Target: <= 10.0%)
- **Latency**: p50 = {p50_latency:.1f}ms, p95 = {p95_latency:.1f}ms

## Gold Set Query Breakdown
| ID | Type | Hit@6 | MRR | Score | Abstained |
|---|---|---|---|---|---|
"""
    for r in per_query_results:
        md_content += f"| {r['id']} | {r['type']} | {'Yes' if r['hit_at_6'] else 'No'} | {r['reciprocal_rank']} | {r['best_score']} | {'Yes' if r['abstained'] else 'No'} |\n"

    md_content += """
## Unanswerable Query Breakdown
| ID | Category | Best Score | Abstained Correctly | Reason |
|---|---|---|---|---|
"""
    for u in unanswerable_results:
        md_content += f"| {u['id']} | {u['category']} | {u['best_score']} | {'Yes' if u['abstained_correctly'] else 'No'} | {u['reason']} |\n"

    report_md_path.write_text(md_content, encoding="utf-8")

    if verbose:
        print("\n" + "=" * 50)
        print("StudyMind Phase 4 Retrieval Evaluation Results")
        print("=" * 50)
        print(f"Total Gold Queries:        {total_gold}")
        print(f"Recall@6:                  {recall_at_6:.2%} (Target >= 85%)")
        print(f"Recall@30:                 {recall_at_30:.2%}")
        print(f"MRR:                       {mrr:.4f}")
        print(f"Page Hit Rate@6:           {page_hit_rate:.2%}")
        print(f"Abstention Precision:      {abstention_precision:.2%} (Target >= 90%)")
        print(f"False Abstain Rate:        {false_abstain_rate:.2%}")
        print(f"Latency (p50 / p95):       {p50_latency:.1f}ms / {p95_latency:.1f}ms")
        print(f"Report saved to:           {report_json_path}")
        print("=" * 50)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run StudyMind Retrieval Evaluation Suite"
    )
    parser.add_argument(
        "--verbose", action="store_true", default=True, help="Print summary to stdout"
    )
    args = parser.parse_args()

    report = asyncio.run(run_retrieval_evaluation(verbose=args.verbose))
    if not report["summary"]["recall_target_met"]:
        print(
            "ERROR: Recall@6 did not meet the Definition of Done threshold (>= 0.85)!",
            file=sys.stderr,
        )
        sys.exit(1)
    if not report["summary"]["abstention_target_met"]:
        print(
            "ERROR: Abstention precision did not meet the target (>= 0.90)!",
            file=sys.stderr,
        )
        sys.exit(1)

    print("SUCCESS: Phase 4 Retrieval Definition of Done achieved!")
    sys.exit(0)
