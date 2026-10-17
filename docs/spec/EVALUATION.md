# Evaluation Plan

"No hallucination" must be **measured**. Build this before polishing the UI.

## 1. Datasets (`/eval/datasets/`)
| Set | Size (min) | Content |
|---|---|---|
| `gold_answerable.jsonl` | 100 | question, reference answer, source doc+page, type (fact, definition, table, formula, multi-hop, summary) |
| `unanswerable.jsonl` | 50 | plausible questions NOT in docs (should abstain) |
| `adversarial.jsonl` | 30 | prompt-injection text in docs, misleading near-duplicates, contradictory docs, false-premise questions |
| `ocr_set/` | 30 pages | scanned, skewed, handwritten, Hindi/Bengali pages |
| `multi_doc.jsonl` | 20 | questions needing 2+ docs |
Use public textbooks (open-licensed, e.g. OpenStax), the user's own notes, and synthetic questions reviewed by a human.

## 2. Metrics
**Retrieval**: Recall@k (k=6,30), MRR, nDCG, page-hit rate.
**Generation**:
- Faithfulness (claims entailed by cited context) — target >= 95%
- Answer correctness vs reference — target >= 85%
- Citation validity (ID exists + quote found) — target >= 98%
- Citation precision/recall (right pages cited)
- Abstention precision on `unanswerable` — target >= 90%; false-abstain rate on answerable <= 10%
- Injection resistance — target 100% (never follows doc instructions)
**System**: p50/p95 latency, cost per query, ingestion time/page, OCR character error rate (CER) on OCR set.

## 3. Tooling
- `eval/run_eval.py --suite all` → writes `eval/reports/<timestamp>.md/json`
- RAGAS / DeepEval for faithfulness & relevancy; LLM-judge (different model than generator) + 10% human audit
- CI: run a 20-question smoke subset on every PR; full suite nightly; fail build if faithfulness < threshold

## 4. Tuning loop
1. Run eval → inspect failures by category.
2. Tune: chunk size, top-k, fusion weights, reranker n, relevance threshold, prompts.
3. Re-run; record in `eval/CHANGELOG.md`. Never tune on the test split — keep 30% held out.

## 5. Production monitoring
- Log every query trace; sample 5% for review.
- Track thumbs-down rate, "not in source" reports, abstain rate (sudden shift => regression).
- Failed cases are auto-added to the regression set.

## 6. Quiz & Exam-Prep evaluation
| Check | Method | Target |
|---|---|---|
| Question groundedness | deterministic quote + chunk check on all generated questions | 100% |
| Key correctness & answerability | human audit of 100 sampled questions + automated answerability test | >= 95% |
| Distractor validity (MCQ has exactly one correct option) | LLM-judge + human spot check | >= 97% |
| Duplicate rate (20-question quiz) | embedding similarity > 0.9 | < 5% |
| Topic coverage | % of syllabus topics hit by a 30-question mock exam | >= 80% |
| Objective grading accuracy | unit tests | 100% |
| Rubric grader vs human | 50 answers, 2 human graders, Cohen's kappa | >= 0.7, agreement >= 85% |
| Mastery/scheduler correctness | fixed-scenario unit tests | all pass |
| Key leakage | API test: no key/rubric in responses before submit | 0 leaks |
Store datasets in `eval/datasets/quiz_*.jsonl`; run with `run_eval.py --suite quiz`.
