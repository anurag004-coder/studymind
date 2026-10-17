# Technical Requirements

## 1. Languages & runtimes
- Python 3.11+ (backend, workers) · Node 20+ (frontend) · Docker + Docker Compose

## 2. Backend
| Concern | Choice | Notes |
|---|---|---|
| API | FastAPI + Pydantic v2 | async, OpenAPI docs |
| Task queue | Celery + Redis (or RQ/Arq) | ingestion, re-index, quiz generation |
| DB | PostgreSQL 16 + SQLAlchemy 2 + Alembic | users, docs, chunks metadata, chats |
| Vector store | **Qdrant** (primary) — alt: pgvector for simplest deploy | payload filter by user_id/workspace_id/doc_id |
| Lexical search | Postgres FTS or `rank_bm25` / OpenSearch | hybrid retrieval |
| Object storage | Local volume (dev) / S3-compatible (MinIO, R2) | original files + page images |
| Auth | JWT (FastAPI-Users) or Supabase Auth | |
| Config | pydantic-settings, `.env` | |

## 3. Ingestion / parsing
- PDF: `PyMuPDF` (text, blocks, page render), `pdfplumber` (tables), **Docling** (layout-aware, tables, reading order) as primary advanced parser
- OCR: `PaddleOCR` or `Tesseract` (+ `ocrmypdf`) for scans; **vision-LLM fallback** (Gemini/GPT/Claude vision) for handwriting, diagrams, formulas
- Image preprocessing: `OpenCV`, `Pillow` (deskew, denoise, contrast)
- Office: `python-docx`, `python-pptx`; text/markdown direct
- Optional: `faster-whisper` (audio), `youtube-transcript-api`
- Language detect: `langdetect`/`fasttext`
- Chunking: custom structure-aware splitter (heading/paragraph/table aware) + token counting with `tiktoken`

## 4. AI components (all behind adapter interfaces)
| Role | Default | Alternatives |
|---|---|---|
| Embeddings | `BAAI/bge-m3` (multilingual, local) | OpenAI `text-embedding-3-small`, Gemini embeddings |
| Reranker | `BAAI/bge-reranker-v2-m3` (cross-encoder) | Cohere Rerank |
| Generator LLM | Gemini / Claude / GPT (config) | Ollama local (Llama/Qwen) |
| Verifier | small fast LLM or NLI model (`cross-encoder/nli-deberta-v3-base`) | same LLM with verifier prompt |
| Vision/OCR LLM | Gemini Flash / GPT-4o-mini vision | |
- Orchestration: plain Python pipeline (preferred, debuggable). LangChain/LlamaIndex allowed only for loaders/utilities — **do not hide the grounding logic inside framework magic**.
- Structured output: JSON schema / function calling with Pydantic validation, retry on invalid.

## 5. Frontend
- Next.js (App Router) + React + TypeScript + Tailwind + shadcn/ui
- `react-pdf` / PDF.js for viewer with highlight overlay; image viewer with bounding boxes
- Streaming responses (SSE), TanStack Query, Zustand
- Pages: Login, Workspaces, Upload/Library, Chat, Source Viewer, Study tools (flashcards/quiz), Settings

## 6. Observability & quality
- Langfuse (or OpenTelemetry + Grafana) for traces of retrieval/generation
- `pytest`, `pytest-asyncio`, `httpx`; `RAGAS` / `DeepEval` for eval; `ruff`, `mypy`, `pre-commit`
- GitHub Actions CI: lint, unit tests, eval smoke test

## 7. Infra
- `docker-compose.yml`: api, worker, redis, postgres, qdrant, minio, frontend
- Deploy: Frontend → Vercel; Backend → Render/Railway/Fly/VM; GPU optional (only for local embeddings/reranker at scale)
- Min dev machine: 16 GB RAM (CPU embeddings OK); GPU speeds OCR/embeddings

## 8. Environment variables (`.env.example`)
```
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
S3_ENDPOINT=... S3_BUCKET=... S3_ACCESS_KEY=... S3_SECRET_KEY=...
JWT_SECRET=...
LLM_PROVIDER=gemini|openai|anthropic|ollama
LLM_MODEL=...
LLM_API_KEY=...
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
VERIFIER_MODEL=...
RETRIEVAL_TOP_K=30
RERANK_TOP_N=6
MIN_RELEVANCE_SCORE=0.35
MAX_UPLOAD_MB=50
MAX_PAGES=500
ENABLE_OUTSIDE_KNOWLEDGE=false
```

## 9. Security requirements
- Per-user data isolation enforced in **every** DB and vector query
- File type allowlist + MIME sniffing + size limits; parse in worker, not API process
- Rate limiting, CORS allowlist, secrets only via env
- Treat document text as untrusted (prompt injection guard)
- Delete endpoint purges files, chunks, vectors, caches, traces
