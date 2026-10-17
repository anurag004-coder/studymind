# Implementation Plan (for the coding agent)
Complete phases in order. Mark tasks `[x]`. Each phase must end with passing tests and a short demo script. Do not start a phase before the previous Definition of Done (DoD) is met.

## Phase 0 — Scaffold
- [ ] Monorepo structure per ARCHITECTURE.md; `docker-compose.yml` (api, worker, redis, postgres, qdrant, minio, frontend)
- [ ] FastAPI skeleton, config, logging, health endpoint; Alembic + models; ruff/mypy/pytest/pre-commit; CI workflow
- DoD: `docker compose up` works; `/health` ok; CI green.

## Phase 1 — Auth, workspaces, upload
- [ ] Register/login/JWT; workspace CRUD; file upload with validation; storage adapter; `documents` rows and status
- DoD: user can upload a file and see it queued; isolation tests (user A cannot see user B).

## Phase 2 — Ingestion (text PDFs first)
- [ ] Celery worker; PyMuPDF/Docling parsing with page + bbox; cleaner; structure-aware chunker; page images; progress events
- [ ] Embedding adapter (bge-m3) + Qdrant indexer + lexical index
- DoD: 100-page PDF ingested; chunks have page/bbox; unit tests for chunker (tables not split, headers removed).

## Phase 3 — OCR & images
- [ ] Preprocessing; Tesseract/PaddleOCR; confidence; vision-LLM fallback for handwriting/low confidence; figure captions (labelled)
- [ ] Image (PNG/JPG), DOCX, PPTX, TXT support; user-visible `ocr_quality`
- DoD: scanned PDF + phone photo become searchable with bbox citations; OCR set CER reported.

## Phase 4 — Retrieval
- [ ] Query rewriter; dense + BM25; RRF fusion; cross-encoder reranker; relevance gate; scope filters
- [ ] Retrieval eval script (Recall@k, MRR)
- DoD: Recall@6 >= 0.85 on gold set.

## Phase 5 — Grounded generation & verification
- [ ] LLM adapter(s); generator with JSON schema; citation validator (ID + quote fuzzy match + numeric check); claim verifier; abstain path; confidence; trace logging
- [ ] Prompt-injection tests
- DoD: faithfulness >= 95%, abstention precision >= 90% on eval suites.

## Phase 6 — Frontend
- [ ] Auth pages, workspace/library with upload + progress, chat with streaming, citations list
- [ ] Source viewer: PDF page/image with highlight overlay; click-through from citation
- [ ] Feedback buttons; abstain UI with suggestions; confidence badge; strict-mode toggle
- DoD: end-to-end flow works in browser; citation click highlights exact region.

## Phase 7 — Study tools
- [ ] Summary (map-reduce), flashcards, quizzes with grounded explanations; saved study items; export (PDF/Anki CSV)
- DoD: every generated item has valid source chunk + quote.

## Phase 7B — Quiz & Exam-Prep engine (after Phase 7; spec: `QUIZ_ASSESSMENT.md`)
- [ ] 7B.1 Topic map extraction + `topics` table + API; map chunks to topics
- [ ] 7B.2 Question generator + validator (quote check, answerability test, MCQ checks, dedupe) + question bank cache
- [ ] 7B.3 Quiz sessions API: create, answer, submit; server-side grading; keys withheld until submit
- [ ] 7B.4 Objective graders (MCQ, multi-select, T/F, fill-blank, numeric w/ tolerance)
- [ ] 7B.5 Rubric grader for short/long answers (deterministic scoring from point statuses, self-review override)
- [ ] 7B.6 Mastery model + spaced-repetition scheduler (FSRS/SM-2) + unit tests with fixed scenarios
- [ ] 7B.7 Modes: Quick Quiz, Mock Exam (timer, resume), Weak-Topic Drill, Spaced Review
- [ ] 7B.8 Analytics + readiness score + exam goals + rule-based study plan
- [ ] 7B.9 Frontend: quiz setup, runner, results report, analytics heatmap, review queue, report-bad-question
- [ ] 7B.10 Export (PDF question paper + key, Anki CSV); quiz eval suite wired into CI
- DoD: all acceptance criteria in `QUIZ_ASSESSMENT.md` §10 pass; quiz eval targets met.
- V2 for this feature: image-based answers (handwriting), viva/oral mode with voice, adaptive difficulty tuning.

## Phase 8 — Hardening & launch
- [ ] Rate limiting, file scanning, delete/purge, observability (Langfuse), caching, load test
- [ ] Docs: README, deployment guide, privacy notes; demo dataset; full eval report committed
- DoD: acceptance criteria in PRD.md pass; nightly eval in CI.

## Backlog (V2)
Multilingual polish (Hindi/Bengali), voice, YouTube/audio, spaced repetition, local-model mode (Ollama), teacher/shared workspaces.
