"""Reciprocal Rank Fusion (RRF) for hybrid multi-retriever search."""

from collections import defaultdict

from app.adapters.base import ScoredChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[ScoredChunk]],
    k: int = 60,
    weights: list[float] | None = None,
    top_n: int = 30,
) -> list[ScoredChunk]:
    """Combines multiple ranked lists using Reciprocal Rank Fusion (RRF).

    Formula:
        Score(d) = sum_{m in ranked_lists} (weight_m / (k + rank_m(d)))

    Args:
        ranked_lists: List of ranked candidate chunk lists (e.g., dense and BM25).
        k: Smoothing constant (standard IR default is 60).
        weights: Optional weights for each ranked list. Defaults to 1.0 for each.
        top_n: Maximum number of fused results to return.

    Returns:
        List of merged ScoredChunk objects ranked by descending RRF score.
    """
    if not ranked_lists:
        return []

    # Filter out empty lists
    valid_lists = [lst for lst in ranked_lists if lst]
    if not valid_lists:
        return []

    if weights is None:
        weights = [1.0] * len(valid_lists)
    elif len(weights) != len(valid_lists):
        # Fallback to uniform weights if length mismatch
        weights = [1.0] * len(valid_lists)

    scores: dict[str, float] = defaultdict(float)
    chunk_store: dict[str, ScoredChunk] = {}

    for list_idx, chunk_list in enumerate(valid_lists):
        weight = weights[list_idx]
        for rank, chunk in enumerate(chunk_list, start=1):
            scores[chunk.chunk_id] += weight / (k + rank)
            if chunk.chunk_id not in chunk_store:
                chunk_store[chunk.chunk_id] = chunk

    # Sort chunks by fused RRF score
    sorted_items = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    # Normalize scores so top item is scaled
    max_fused = sorted_items[0][1] if sorted_items else 1.0

    fused_chunks: list[ScoredChunk] = []
    for cid, rrf_score in sorted_items[:top_n]:
        base_chunk = chunk_store[cid]
        normalized_score = float(rrf_score / max_fused) if max_fused > 0 else 0.0

        fused_chunks.append(
            ScoredChunk(
                chunk_id=base_chunk.chunk_id,
                document_id=base_chunk.document_id,
                page_start=base_chunk.page_start,
                page_end=base_chunk.page_end,
                text=base_chunk.text,
                score=round(normalized_score, 4),
                metadata={
                    **base_chunk.metadata,
                    "rrf_raw_score": round(rrf_score, 6),
                },
            )
        )

    return fused_chunks
