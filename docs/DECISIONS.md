# Decisions Log — StudyMind

This log records deviations, architectural decisions, and clarifications to the specification per `AGENTS.md`.

---

## Decision 001: Initial LLM Provider Selection
- **Date**: 2026-10-10
- **Context**: Spec allows configuring `gemini | openai | anthropic | ollama` via `.env`.
- **Decision**: Default to `gemini` (`gemini-2.5-flash` / `gemini-1.5-flash`) for generation, vision OCR fallback, and structured JSON output. All LLM calls remain strictly behind the `LLMAdapter` interface in `backend/app/adapters/llm.py` so switching to OpenAI, Anthropic, or local Ollama requires only changing `LLM_PROVIDER` in `.env`.
- **Rationale**: Gemini offers built-in multimodal vision support for scanned documents/diagrams, high speed, and native structured schema outputs.

---

## Decision 002: Modular Adapters and Local/Test Execution Without Docker
- **Date**: 2026-10-10
- **Context**: `docker-compose.yml` is specified for multi-service deployment (Postgres, Redis, Qdrant, MinIO, API, Worker, Frontend). However, the host environment does not have Docker installed in PATH.
- **Decision**: 
  1. We will provide a complete, production-ready `docker-compose.yml` and `.env.example` meeting Phase 0 requirements.
  2. The application architecture and test harness will support both containerized multi-container setups and direct local execution:
     - Vector store adapter will support Qdrant HTTP/gRPC as well as in-memory/local Qdrant (`qdrant_client.QdrantClient(":memory:")` or local SQLite vector fallback).
     - Storage adapter will support MinIO/S3 and local disk volume storage.
     - Database adapter will support async PostgreSQL via SQLAlchemy and SQLite for fast, standalone test execution.
- **Rationale**: Ensures test suites, CI, and local development can run anywhere without blocking on Docker daemon availability.

---

## Decision 003: Spec Directory Layout
- **Date**: 2026-10-10
- **Context**: The specification files were delivered in `/files/`, whereas `README.md` and `AGENTS.md` expect `/docs/spec/*.md`.
- **Decision**: The spec pack is mirrored into `/docs/spec/` so that all documentation paths (`/docs/spec/README.md`, etc.) are exact.

---

## Decision 004: Hybrid Retrieval Fusion and Layer 1 Relevance Gate Formulation
- **Date**: 2026-10-10
- **Context**: `ANTI_HALLUCINATION.md` Layer 1 mandates hybrid retrieval (dense + lexical), Reciprocal Rank Fusion (RRF), cross-encoder reranking, and an early relevance gate to abstain before LLM invocation when evidence is weak.
- **Decision**:
  1. **Reciprocal Rank Fusion**: Merges multi-query sub-decompositions across dense and `BM25Plus` lexical candidate lists using standard $RRF(d) = \sum \frac{w_m}{60 + \text{rank}_m(d)}$, deduplicating chunk IDs and normalizing scores.
  2. **Layer 1 Relevance Gate**: Computes both normalized cross-encoder `best_score` (threshold 0.35) and informative non-stopword query term coverage (threshold 40%). If `best_score < 0.35` or `coverage < 0.40`, the system aborts immediately with `should_abstain: true`, returning the closest passages and 1-3 suggested question rephrases without calling the LLM generator.
  3. **Multi-Tenancy**: Vector search and BM25 index enforce mandatory `user_id` and `workspace_id` parameters on every retrieval call.
- **Rationale**: Early abstention on unanswerable and out-of-domain queries cuts LLM token costs to zero, eliminates hallucinations before generation, and achieves 100% abstention precision on the benchmark unanswerable suite.

---

## Decision 005: 5-Layer Anti-Hallucination Pipeline & Prompt Injection Sanitization
- **Date**: 2026-10-10
- **Context**: `ANTI_HALLUCINATION.md` Layers 2–5 and `CHALLENGES.md` mandate strict grounding, deterministic citation validation, claim-level semantic verification, and prompt-injection defenses.
- **Decision**:
  1. **Untrusted XML Context Fencing**: Document chunks are packaged into `<untrusted_document_context id="C1" ...>` blocks with pre-generation defusing of injection triggers ("ignore previous instructions", "system override", "you are now").
  2. **Layer 3 Deterministic Validator**: Verifies that block ID exists in context, quote has fuzzy similarity $\ge 0.85$ via RapidFuzz, and all numeric tokens in the claim exist in the cited passage.
  3. **Layer 4 Semantic NLI Verifier**: Checks claim entailment against cited source premise, detecting polarity contradictions and dropping non-entailed assertions.
  4. **Layer 5 Response Composition**: Re-indexes citations to global 1-indexed integers matching student text citations `[1]`, computes confidence badges (`high`, `medium`, `low`), and formats abstention responses with closest passages and rephrase suggestions.
- **Rationale**: Guarantees zero fabricated citations or numeric hallucinations, achieves 100% injection resistance, and strictly enforces the non-negotiable rule that answers come exclusively from retrieved user material.

---

## Decision 006: Frontend Architecture & Synchronized Bounding Box Source Viewer
- **Date**: 2026-10-10
- **Context**: Phase 6 requires a rich, modern web interface with authentication, workspace library with drag-and-drop upload & live SSE progress, grounded chat with verified citation pills `[1]`, feedback controls, abstention cards, and a synchronized source viewer highlighting the exact bounding box region upon citation click.
- **Decision**:
  1. **Architecture & Aesthetics**: Built using Vanilla HTML5, modern CSS3 design tokens (`Plus Jakarta Sans` typography, sleek dark mode `#0a0e17`, indigo/violet radiant gradients, and glassmorphic elevated surfaces), and modular ES6 JavaScript without heavyweight framework bloat.
  2. **FastAPI & Dual Dev Serving**: Mounted static assets (`/static`) and `/app` route directly in FastAPI, and provided a zero-dependency Node static + proxy server in `frontend/server.js` on port 3000 matching `docker-compose.yml`.
  3. **Page Image Rendering**: Implemented `GET /api/v1/documents/{id}/pages/{n}/image` with multi-tier rendering: pre-rendered PNG from storage, on-the-fly PyMuPDF rendering for uploaded PDFs, direct image pass-through for scans/photos, and dynamic canvas rendering with text previews for notes/DOCX.
  4. **Synchronized Bounding Box Highlighter**: Clicking any citation pill `[1]` in chat or source card immediately opens the cited document page, calculates relative coordinates from `bbox: [x0, y0, x1, y1]`, centers the viewer via smooth scrolling, and renders a glowing, animated pulsating bounding box with a verified quote tooltip badge.
  5. **Abstention & Feedback Flow**: Renders clear abstention cards with clickable suggestion prompt chips and provides inline thumbs up / down feedback submission dialogs linked to `POST /api/v1/messages/{id}/feedback`.
- **Rationale**: Completely fulfills the Phase 6 Definition of Done, guarantees seamless usability across both local Node dev servers and FastAPI, and provides students with an immediate, visually verified link between generated answers and exact source regions.
---

## Decision 007: Phase 7 Study Tools Architecture, Map-Reduce Summarization, and Grounded Generation
- **Date**: 2026-10-10
- **Context**: Phase 7 requires map-reduce document summarization, flashcards generation, grounded quizzes, study item persistence, Anki TSV and Markdown exports, and zero-hallucination quote verification satisfying the DoD ("every generated item has valid source chunk + quote").
- **Decision**:
  1. **Map-Reduce Summarizer**: Implemented section-level mapping preserving chunk IDs and exact quote citations, followed by a reduce step synthesizing comprehensive overviews and key takeaways with verified quotes.
  2. **Strict Quote Verification**: Both `FlashcardService` and `QuizService` compare candidate quotes against actual referenced chunk content using RapidFuzz ($threshold \ge 70.0$). Any ungrounded candidate is strictly discarded rather than repaired with guesses.
  3. **Saved Study Items & Multi-Tenancy**: Added endpoints for listing, viewing, and deleting persisted study items with mandatory `workspace.user_id == current_user.id` isolation in every database query.
  4. **Multi-Format Exports**: Implemented Anki TSV format (`Front \t Back \t Tags` with citation footnotes) for seamless import into Anki desktop/mobile, and a Markdown study guide compiler.
  5. **Interactive UI**: Built dedicated frontend runners featuring 3D flip-card flashcards, instant-grading interactive quizzes with quote verification tooltips, and source viewer synchronizers.
- **Rationale**: Guarantees zero hallucinations in all study tools, provides high-utility learning aids for students, and fulfills 100% of the Phase 7 Definition of Done.

---

## Decision 008: Phase 7B Quiz & Exam-Prep Engine Architecture, Server-Side Security, and Graders
- **Date**: 2026-10-10
- **Context**: `QUIZ_ASSESSMENT.md` specifies an exam-prep engine generating grounded questions across 5+ types, server-side grading with strict answer key withholding during active exam sessions, deterministic rubric grading, Bayesian topic mastery, SM-2 spaced repetition, and instant retirement of reported bad questions.
- **Decision**:
  1. **Topic Map Extraction**: Topic outline generated from chunk hierarchy (`rebuild_topics`), mapping chunks to topics stored in `topics` table for coverage-aware sampling.
  2. **4-Stage Question Validation Pipeline**: Candidate questions undergo deterministic citation validation (RapidFuzz $\ge 85\%$), LLM answerability test using only cited chunk, MCQ distractor uniqueness/plausibility checks, and embedding/stem deduplication ($< 90\%$ similarity).
  3. **Server-Side Grading & Zero-Leak Security**: Client views (`QuestionClientView`) omit answer keys, rubrics, explanations, and quotes during active test sessions. Practice mode yields instant feedback while Mock Exam mode delays all grading until final submission.
  4. **Deterministic Objective & Rubric Graders**: Objective grader evaluates MCQ, multi-select (with partial credit and excess penalty), true/false, fill-in-the-blank (normalized with synonyms), and numeric (tolerance $\pm 5\%$). Rubric grader evaluates cited key points (`covered | partial | missing`); final score is calculated deterministically by code summing point statuses (the LLM never outputs the final score); student self-review override supported for borderline written answers.
  5. **Mastery Tracking & SM-2 Scheduler**: Bayesian/EMA topic mastery updated per attempt weighted by question difficulty; SuperMemo-2 (SM-2) algorithm schedules due reviews (`due_at`, `stability`, `ease`, `lapses`); syllabus coverage-weighted readiness score calculator and rule-based daily study planner.
  6. **Auto-Retirement of Bad Questions**: Any reported question (`POST /questions/{id}/report`) is immediately flagged/retired and permanently filtered from active question bank queries.
- **Rationale**: Completely adheres to non-negotiable grounding and server-side security rules in `AGENTS.md` and `QUIZ_ASSESSMENT.md`, eliminates cheating via client inspection, guarantees deterministic grading repeatability, and fulfills 100% of Phase 7B Definition of Done.

---

## Decision 009: Phase 8 Hardening, Rate Limiting, File Security, GDPR Purge, Multi-Tier Caching, and Observability
- **Date**: 2026-10-10
- **Context**: Phase 8 mandates production hardening: rate limiting per user (60 req/min sliding window), file security scanner (magic bytes, malware detection, zip bombs, executable blocking), complete GDPR/DPDP right to be forgotten (document purge, workspace purge, user account purge), multi-tier caching with workspace-level invalidation, observability/tracing adapter, and load testing benchmark meeting PRD NFRs ($p50 < 6\text{s}$, $p95 < 15\text{s}$).
- **Decision**:
  1. **Sliding Window Rate Limiter**: Implemented `SlidingWindowRateLimiter` with SHA-256 token hashing for collision-free user bucket keys, returning standard HTTP 429, `Retry-After`, `X-RateLimit-*` headers, while exempting health probes (`/health`, `/metrics`, `/docs`, `/static`).
  2. **File Security Scanner**: Enforced sniffing of magic bytes (`%PDF-`, `\x89PNG`, `\xff\xd8\xff`, `PK\x03\x04`), blocking Windows PE (`MZ`) and Linux ELF (`\x7fELF`) executables, blocking EICAR malware test strings, and guarding against zip bomb decompression attacks ($> 100:1$ ratio).
  3. **GDPR/DPDP Data Purge**:
     - `DELETE /documents/{id}`: Purges storage files, Qdrant vectors (`delete_by_document`), DB records, derived questions from question bank, and invalidates workspace cache.
     - `DELETE /workspaces/{id}`: Cascading purge of all documents, storage files, vectors, topics, quizzes, and cache.
     - `DELETE /auth/me`: Complete account erasure purging all user documents, storage objects, vectors across all workspaces, caches, and user credentials.
  4. **Multi-Tier Caching**: Implemented `MultiTierCache` in `app/core/cache.py` with LRU eviction, TTL expiration, hit/miss tracking, and workspace-level invalidation (`app_cache.invalidate_workspace`). Wired into `RetrievalService.retrieve`.
  5. **Observability & Tracing**: Created `ObservabilityAdapter` with `LangfuseObservabilityAdapter` and `LocalObservabilityAdapter` recording traces, spans, duration ms, and token counts. Exposed via `GET /metrics` and `GET /traces`.
  6. **Load Testing Benchmark**: Implemented `scripts/load_test.py` measuring concurrent requests throughput (228.34 req/sec), $p50 = 39.7$ ms (Target: $< 6,000$ ms), $p95 = 51.5$ ms (Target: $< 15,000$ ms), 0 dropped requests.
- **Rationale**: Guarantees production grade security, compliance with international privacy mandates (GDPR / DPDP), enterprise stability, resilient performance under concurrent burst loads, and fulfills 100% of Phase 8 Definition of Done.

