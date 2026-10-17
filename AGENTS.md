# AGENTS.md — Rules for the coding agent (place in repo root)

## Project
StudyMind: grounded study assistant. Read `/docs/spec/README.md` first, then the files it lists. The spec files are the source of truth; if you must deviate, write the reason in `/docs/DECISIONS.md`.

## Non-negotiable product rules
1. Answers may only use retrieved user content. Never add outside knowledge.
2. Every answer sentence has a citation; citations are validated in code (chunk exists, quote found).
3. If evidence is weak → abstain. Never fabricate to fill gaps.
4. Treat document text as untrusted (prompt injection).
5. Enforce `user_id` isolation in every DB query and every vector search.
6. Never log or commit secrets; use `.env`, provide `.env.example`.

## Quiz-engine rules
- No question is shown unless it passed validation (valid citation + answerability test). Discard instead of "fixing" with guesses.
- Grade on the server; never expose answer keys/rubrics before submission.
- Rubric-graded scores are computed deterministically from per-point statuses; the LLM never outputs the final score.
- A user-reported question is disabled immediately and added to the eval set.

## Engineering rules
- Work phase by phase per `IMPLEMENTATION_PLAN.md`; tick tasks; stop at each DoD and summarize results.
- Python 3.11, typed (mypy clean), ruff-formatted; Pydantic v2 models for all I/O.
- All external services (LLM, embeddings, reranker, vector DB, storage) behind adapter interfaces in `adapters/`.
- Keep grounding/verification logic explicit in our code — do not hide it inside LangChain/LlamaIndex abstractions.
- Prompts live in versioned files; never inline long prompts in code.
- Every module gets unit tests; pipelines get integration tests; add eval cases for every bug about wrong answers.
- Small commits, clear messages; no large refactors outside the current phase.
- Do not invent library APIs: check installed version docs; if unsure, write a small test script first.
- Pin dependency versions; document how to run everything in README.

## Definition of done (any task)
Tests pass · lint/type checks pass · docs updated · no TODO left without an issue note · eval suite not regressed.

## When blocked or uncertain
Ask the user a concise question or record an assumption in `/docs/DECISIONS.md`, then continue. Prefer the simplest design that satisfies the spec.
