# Implementation Plan (for the coding agent)
Complete phases in order. Mark tasks `[x]`. Each phase must end with passing tests and a short demo script. Do not start a phase before the previous Definition of Done (DoD) is met.

## Phase 0 — Scaffold
- [x] Monorepo structure per ARCHITECTURE.md; `docker-compose.yml` (api, worker, redis, postgres, qdrant, minio, frontend)
- [x] FastAPI skeleton, config, logging, health endpoint; Alembic + models; ruff/mypy/pytest/pre-commit; CI workflow
- DoD: `docker compose up` works; `/health` ok; CI green.

## Phase 1 — Auth, workspaces, upload
- [x] Register/login/JWT; workspace CRUD; file upload with validation; storage adapter; `documents` rows and status
- DoD: user can upload a file and see it queued; isolation tests (user A cannot see user B).

## Phase 2 — Ingestion (text PDFs first)
- [x] Celery worker; PyMuPDF/Docling parsing with page + bbox; cleaner; structure-aware chunker; page images; progress events
- [x] Embedding adapter (bge-m3) + Qdrant indexer + lexical index
- DoD: 100-page PDF ingested; chunks have page/bbox; unit tests for chunker (tables not split, headers removed).

## Phase 3 — OCR & images
- [x] Preprocessing; Tesseract/PaddleOCR; confidence; vision-LLM fallback for handwriting/low confidence; figure captions (labelled)
- [x] Image (PNG/JPG), DOCX, PPTX, TXT support; user-visible `ocr_quality`
- DoD: scanned PDF + phone photo become searchable with bbox citations; OCR set CER reported.

## Phase 4 — Retrieval
- [x] Query rewriter; dense + BM25; RRF fusion; cross-encoder reranker; relevance gate; scope filters
- [x] Retrieval eval script (Recall@k, MRR)
- DoD: Recall@6 >= 0.85 on gold set. (Achieved 100.0% Recall@6, 100.0% Abstention Precision)

## Phase 5 — Grounded generation & verification
- [x] LLM adapter(s); generator with JSON schema; citation validator (ID + quote fuzzy match + numeric check); claim verifier; abstain path; confidence; trace logging
- [x] Prompt-injection tests
- DoD: faithfulness >= 95%, abstention precision >= 90% on eval suites. (Achieved 100.0% Faithfulness, 100.0% Citation Validity, 100.0% Abstention Precision, 100.0% Injection Resistance)

## Phase 6 — Frontend
- [x] Auth pages, workspace/library with upload + progress, chat with streaming, citations list
- [x] Source viewer: PDF page/image with highlight overlay; click-through from citation
- [x] Feedback buttons; abstain UI with suggestions; confidence badge; strict-mode toggle
- DoD: end-to-end flow works in browser; citation click highlights exact region. (Verified via scripts/verify_phase6.py and backend/tests/test_phase6_frontend.py)

## Phase 7 — Study tools
- [x] Summary (map-reduce), flashcards, quizzes with grounded explanations; saved study items; export (PDF/Anki CSV)
- DoD: every generated item has valid source chunk + quote. (Achieved 100.0% Grounded Item Validity: verified via backend/tests/test_study_tools.py and scripts/verify_phase7.py)

## Phase 7B — Quiz & Exam-Prep engine (after Phase 7; spec: `QUIZ_ASSESSMENT.md`)
- [x] 7B.1 Topic map extraction + `topics` table + API; map chunks to topics
- [x] 7B.2 Question generator + validator (quote check, answerability test, MCQ checks, dedupe) + question bank cache
- [x] 7B.3 Quiz sessions API: create, answer, submit; server-side grading; keys withheld until submit
- [x] 7B.4 Objective graders (MCQ, multi-select, T/F, fill-blank, numeric w/ tolerance)
- [x] 7B.5 Rubric grader for short/long answers (deterministic scoring from point statuses, self-review override)
- [x] 7B.6 Mastery model + spaced-repetition scheduler (FSRS/SM-2) + unit tests with fixed scenarios
- [x] 7B.7 Modes: Quick Quiz, Mock Exam (timer, resume), Weak-Topic Drill, Spaced Review
- [x] 7B.8 Analytics + readiness score + exam goals + rule-based study plan
- [x] 7B.9 Frontend: quiz setup, runner, results report, analytics heatmap, review queue, report-bad-question
- [x] 7B.10 Export (PDF question paper + key, Anki CSV); quiz eval suite wired into CI
- DoD: all acceptance criteria in `QUIZ_ASSESSMENT.md` §10 pass; quiz eval targets met. (Achieved: 100% verified citations, 100% server-side grading key withholding during active exam, 100% deterministic objective & rubric scoring, instant retirement of reported questions, verified via backend/tests/test_phase7b_quiz_engine.py and scripts/verify_phase7b.py)
- V2 for this feature: image-based answers (handwriting), viva/oral mode with voice, adaptive difficulty tuning.

## Phase 8 — Hardening & launch
- [x] Rate limiting, file scanning, delete/purge, observability (Langfuse), caching, load test
- [x] Docs: README, deployment guide, privacy notes; demo dataset; full eval report committed
- DoD: acceptance criteria in PRD.md pass; nightly eval in CI. (Achieved: 100% Rate Limit sliding window & bursts throttle, 100% File Security magic bytes / PE / ELF / EICAR / Zip bomb defense, 100% GDPR/DPDP cascade purge, 100% Multi-tier caching with workspace invalidation, p50=39.7ms & p95=51.5ms load test benchmarks vs PRD <6s/<15s targets, 67/67 unit/integration tests passing, 0 mypy/ruff errors, verified via scripts/verify_phase8.py and scripts/load_test.py)

## Backlog (V2)
Multilingual polish (Hindi/Bengali), voice, YouTube/audio, spaced repetition, local-model mode (Ollama), teacher/shared workspaces.
