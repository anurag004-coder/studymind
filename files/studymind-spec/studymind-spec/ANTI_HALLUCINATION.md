# Anti-Hallucination Pipeline

> Principle: **the model is a reader and writer, not a source of facts.** All facts must come from retrieved chunks.

## Layer 0 — Good data in
- Correct reading order, tables preserved, OCR confidence tracked.
- Low-quality OCR text is flagged; answers based on it show a "low-confidence source" badge.

## Layer 1 — Retrieval gate (before the LLM)
1. Hybrid retrieval (top 30) → rerank (top 6).
2. Compute `best_score` (reranker, normalized 0-1) and `coverage` (how many of the question's key terms/entities appear in top chunks).
3. If `best_score < MIN_RELEVANCE_SCORE` → **abstain immediately**; return closest passages + rephrase suggestions. The LLM is never called.
4. Tune the threshold on the unanswerable set in EVALUATION.md.

## Layer 2 — Constrained generation
- System prompt forbids outside knowledge (see PROMPTS.md).
- Context is passed as numbered blocks: `[C1] (doc, p.12) text...`
- Temperature 0–0.2.
- Output **JSON schema**:
```json
{
  "answerable": true,
  "answer_sentences": [
    {"text": "...", "citations": [{"chunk_id": "C1", "quote": "exact supporting words from the chunk"}]}
  ],
  "missing_info": "what the material doesn't cover (if partial)"
}
```
- Every sentence MUST have >= 1 citation, else it is dropped.
- Context is wrapped as untrusted data (prompt-injection guard).

## Layer 3 — Deterministic citation validation (no LLM)
For every citation:
- `chunk_id` must be in the provided context set (else reject sentence).
- `quote` must appear in the chunk text (normalized whitespace; fuzzy ratio >= 0.9 via `rapidfuzz`).
- Sentence numbers/dates/units must also appear in the cited chunks (regex check for numerics and named entities).

## Layer 4 — Semantic verification (claim-level)
- For each answer sentence: premise = cited chunk text(s), hypothesis = sentence.
- Use NLI model (`deberta-v3` NLI) or a verifier LLM prompt → label `entailed | neutral | contradicted`.
- Keep only `entailed`. If all dropped → abstain. If some dropped → show remaining + note "some details could not be verified".
- Optionally a second-pass "self-consistency" check: regenerate with different seed; low agreement lowers confidence.

## Layer 5 — Response composition
- Display answer with inline `[1][2]` linked to source viewer (page + highlighted bbox).
- Confidence badge: High (all sentences entailed, best_score high) / Medium / Low.
- Abstain message template: *"I couldn't find this in your uploaded material. Closest passages: … Try asking: …"*
- Optional "Outside source" mode (off by default) must be visibly labelled **not from your material**.

## Layer 6 — Study tools (flashcards/quiz/summary)
- Generate from selected chunks only; each item stores `source_chunk_ids`.
- Quiz answers/explanations pass the same Layer 3–4 verification.
- Distractors may be invented but the **correct answer and explanation** must be grounded.

## Layer 7 — Feedback loop
- 👍/👎 + "wrong/not in source/missing" reasons → stored; failing cases added to the regression eval set.
- Weekly review of low-confidence + downvoted traces.

## Failure policy
When unsure → abstain. A refused answer is better than a wrong one. Never "fill the gaps" with plausible text.
