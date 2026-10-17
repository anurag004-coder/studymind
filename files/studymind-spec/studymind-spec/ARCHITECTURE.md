# Architecture

## 1. High-level components
```
[Next.js Frontend] <-> [FastAPI API] <-> [Postgres]
                            |  \-> [Qdrant (vectors)]
                            |  \-> [Object storage (files, page images)]
                            v
                       [Redis queue] -> [Ingestion Workers]
                                          parse -> OCR -> clean -> chunk -> embed -> index
                            |
                            v
                  [LLM / Embedding / Reranker / Verifier adapters]
```

## 2. Ingestion pipeline (async worker)
1. **Receive**: validate type/size, store original, hash (SHA-256) → dedupe, create `document` row `status=queued`.
2. **Detect**: per page, is there a text layer? If not → OCR path.
3. **Parse**: Docling/PyMuPDF → blocks with `{page, bbox, type(heading|para|table|figure|formula), text, reading_order}`.
4. **OCR** (scanned/images): preprocess → PaddleOCR/Tesseract → word confidences. Low confidence (< 0.80) or handwriting → vision-LLM transcription; store both, flag `ocr_quality`.
5. **Clean**: remove repeated headers/footers, fix hyphenation, normalize unicode; **never rewrite content semantically**.
6. **Figures**: optional vision caption, stored with `source_type=generated_caption`.
7. **Chunk**: structure-aware, 300-600 tokens, overlap 10-15%, tables as single chunks; each chunk keeps `page_start/page_end`, `bbox_list`, `section_path`, `doc_id`, `chunk_index`, `parent_id`.
8. **Embed + index**: dense vectors to Qdrant (payload: user_id, workspace_id, doc_id, page, chunk_id, source_type); text to lexical index.
9. **Finalize**: `status=ready`, emit progress events (SSE/websocket).
Idempotent + resumable per page; failures recorded per page.

## 3. Query pipeline (summary — details in ANTI_HALLUCINATION.md)
`question → rewrite (use chat history) → hybrid retrieve (dense+BM25, filtered by user/workspace) → RRF fuse → cross-encoder rerank → relevance gate (abstain?) → context pack with chunk IDs → generator (JSON w/ citations) → citation validation → claim verification → compose final answer or abstain → log trace`.

## 4. Database schema (Postgres)
```
users(id, email, password_hash, created_at)
workspaces(id, user_id, name, created_at)
documents(id, workspace_id, user_id, filename, mime, sha256, pages, status, ocr_quality, error, storage_key, created_at)
pages(id, document_id, page_no, image_key, has_text_layer, ocr_confidence)
chunks(id, document_id, page_start, page_end, section_path, text, token_count, source_type, bbox_json, parent_id, chunk_index, embedding_model)
conversations(id, workspace_id, user_id, title, scope_json, created_at)
messages(id, conversation_id, role, content, citations_json, verification_json, abstained bool, trace_id, created_at)
feedback(id, message_id, rating, reason, created_at)
study_items(id, workspace_id, type(flashcard|quiz|summary), payload_json, source_chunk_ids, created_at)
jobs(id, document_id, stage, status, progress, error, updated_at)
```
Qdrant collection `chunks`: vector (bge-m3 dim 1024), payload `{chunk_id, user_id, workspace_id, document_id, page_start, page_end, source_type}`; index payload fields `user_id`, `workspace_id`, `document_id`.

## 5. Folder structure
```
studymind/
├── AGENTS.md
├── docs/spec/*.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/ (config, security, logging)
│   │   ├── api/ (auth, workspaces, documents, chat, study, feedback)
│   │   ├── db/ (models, session, migrations)
│   │   ├── ingestion/ (router, pdf_parser, ocr, vision_ocr, cleaner, chunker, indexer)
│   │   ├── retrieval/ (query_rewrite, dense, lexical, fusion, reranker, gate)
│   │   ├── generation/ (prompts, generator, schema)
│   │   ├── verification/ (citation_check, claim_extract, nli_verify, abstain)
│   │   ├── study/ (summary, flashcards, quiz)
│   │   ├── adapters/ (llm_*, embed_*, rerank_*, vectorstore_*, storage_*)
│   │   └── workers/ (celery_app, tasks)
│   ├── tests/ (unit, integration, eval)
│   └── pyproject.toml
├── frontend/ (Next.js app)
├── eval/ (datasets, run_eval.py, reports/)
└── scripts/
```

## 6. Design principles
- Adapters for every external model/service (swap providers by config).
- Pipelines are plain, typed Python functions — each stage unit-testable.
- Every answer stores a full trace (retrieved chunks, scores, prompt version, verifier output).
- Prompts are versioned files in `generation/prompts/`.

## 7. Quiz & Exam-Prep addition
New modules: `backend/app/quiz/` (`topic_map.py`, `selector.py`, `generator.py`, `validator.py`, `grader.py`, `mastery.py`, `scheduler.py`, `planner.py`, `export.py`) and routers `api/quiz.py`, `api/analytics.py`, `api/review.py`.
New tables: topics, questions, quiz_sessions, attempts, topic_mastery, review_schedule, exam_goals, question_reports (full DDL in `QUIZ_ASSESSMENT.md` §7).
Flow: ingestion → topic map → (background) question-bank generation + validation → quiz session picks validated questions → server-side grading → mastery/schedule update → analytics.
Frontend: `/quiz/new`, `/quiz/[id]` (runner), `/quiz/[id]/report`, `/analytics`, `/review`, `/exam-goals`.
