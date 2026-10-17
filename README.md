# StudyMind

Grounded study assistant with verified citations and anti-hallucination guarantees.

StudyMind is an AI-powered study assistant designed for students and researchers. It allows users to upload course materials—including textbooks, lecture slides, research papers, and handwritten notes—and ask questions through an interactive chat interface. 

Unlike conventional conversational chatbots, StudyMind enforces strict grounding: every factual statement in an answer must be directly backed by retrieved context with verified citations and verbatim quotes. If the source material does not contain enough evidence to answer a question, the system explicitly abstains rather than speculating.

---

## Capabilities

### Grounded Question Answering
- Strict evidence rule: Every sentence in an answer includes an explicit citation linked to an uploaded source chunk and an exact verbatim quote.
- Multi-layer anti-hallucination pipeline:
  - Layer 1: Hybrid retrieval (Reciprocal Rank Fusion of dense and lexical search) with an early relevance gate to filter out-of-domain queries.
  - Layer 2: Untrusted context fencing to protect against prompt injection in user documents.
  - Layer 3: Deterministic citation verification using quote matching and numeric validation.
  - Layer 4: Natural language inference (NLI) claim verification to reject unsupported statements.
  - Layer 5: Global citation composition with confidence indicators (high, medium, low).
- Clean abstention: When evidence is insufficient, StudyMind declines to answer and suggests related questions that the uploaded documents can answer.

### Synchronized Source Viewer
- Interactive citations: Clicking a citation pill in the chat immediately opens the relevant document page in the split-pane viewer.
- Precision highlighting: Calculates relative bounding boxes to scroll to and highlight the exact source passage on the page.

### Study and Exam Preparation
- Summarization: Generates structured overviews and key takeaways with source citations.
- Flashcards: Interactive 3D flip-cards with quote verification tooltips.
- Exam and quiz engine:
  - Hierarchical syllabus topic extraction.
  - Four-stage question validation (citation check, single-chunk answerability, distractor plausibility, deduplication).
  - Server-side grading security: Answer keys and rubrics are withheld from clients during active exams.
  - Deterministic scoring: Objective questions (MCQ, multi-select, numeric tolerances) and rubric grading with server-computed scores.
  - Spaced repetition: Bayesian topic mastery tracking paired with the SuperMemo-2 (SM-2) scheduling algorithm.
  - One-click retirement: User-reported questions are removed from the active bank immediately.
  - Export formats: Anki TSV files, printable Markdown exam sheets, and study guides.

### Security and Hardening
- Tenant isolation: User and workspace boundaries enforced in every database query and vector lookup.
- File scanner: Inspects file headers and magic bytes to reject executables, scripts, corrupted files, and zip bombs before processing.
- Rate limiting: Sliding-window limiter (60 requests per minute per user) with HTTP 429 status and retry headers.
- Multi-tier caching: In-memory LRU and TTL caching with workspace-level invalidation.
- GDPR and DPDP compliance: Cascading deletion of documents, embeddings, and accounts upon request.

---

## Technical Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy 2.0 (asyncpg / aiosqlite), Alembic, Pydantic v2
- Retrieval: Dense embeddings, lexical BM25 index, cross-encoder reranker, reciprocal rank fusion
- Storage: PostgreSQL / SQLite, local disk / S3-compatible object storage, Qdrant vector database
- Frontend: HTML5, modern CSS3, ES6 JavaScript (zero build step required)
- Dev Server: Node.js HTTP server with API proxying

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+ (for local frontend dev server)
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/anurag004-coder/studymind.git
cd studymind
```

### 2. Environment Configuration

Copy the example configuration to create your local `.env`:

```bash
cp .env.example .env
```

Review `.env` and set your preferred AI provider credentials (such as `GEMINI_API_KEY`) and database URL. By default, the project runs locally using SQLite and mock adapters for instant zero-dependency testing.

### 3. Backend Setup

Create and activate a Python virtual environment:

```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On Linux/macOS:
source .venv/bin/activate
```

Install backend dependencies:

```bash
pip install -e backend
pip install -r backend/requirements.txt  # or install optional dev dependencies
```

Apply database migrations:

```bash
cd backend
alembic upgrade head
cd ..
```

Start the FastAPI backend server:

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

The interactive API documentation is available at `http://127.0.0.1:8000/docs`.

### 4. Frontend Setup

In a separate terminal, start the frontend development server:

```bash
cd frontend
npm start
```

Open `http://localhost:3000` in your browser. 

Alternatively, the FastAPI backend also serves the frontend directly at `http://127.0.0.1:8000/app`.

---

## Docker Deployment

To launch the complete containerized stack:

```bash
docker compose up -d --build
```

This starts the FastAPI backend, Qdrant vector database, PostgreSQL, Redis, and the frontend web proxy.

---

## Frontend Deployment (Vercel)

The frontend is a lightweight, zero-build client that can be deployed to Vercel:

1. Deploy the `frontend/` directory using the Vercel CLI:
   ```bash
   npx vercel deploy ./frontend
   ```
2. When deployed separately from the backend, configure the backend API endpoint by either:
   - Appending `?api=https://your-backend-url.com` to the URL.
   - Setting `localStorage.setItem('studymind_api_base', 'https://your-backend-url.com')` in the browser console.

---

## Running Tests and Verification

All backend code is typed, linted, and verified with automated test suites:

```bash
# Run all unit and integration tests (70 tests)
python -m pytest backend

# Check code formatting with Ruff
python -m ruff format --check backend

# Run Ruff linter
python -m ruff check backend

# Run strict static type checking with MyPy
python -m mypy backend

# Run frontend end-to-end verification harness
python scripts/verify_phase6.py

# Run quiz engine verification suite
python scripts/verify_phase7b.py

# Run security, file scanner, and rate limiter verification
python scripts/verify_phase8.py
```

---

## Project Structure

```text
studymind/
├── backend/
│   ├── app/
│   │   ├── adapters/          # LLM, embeddings, reranker, vector store, and storage adapters
│   │   ├── api/               # FastAPI route controllers (auth, chat, documents, workspaces, quiz)
│   │   ├── core/              # Config, security, rate limiting, cache, file scanning
│   │   ├── db/                # SQLAlchemy database models and async session management
│   │   ├── generation/        # Anti-hallucination generation pipeline and citation verification
│   │   ├── ingestion/         # Document parsing, OCR, chunking, and lexical indexing
│   │   ├── retrieval/         # Query rewriting, hybrid fusion (RRF), and relevance gating
│   │   └── study/             # Exam generator, question validation, and grading engines
│   ├── alembic/               # Database migration scripts
│   └── tests/                 # Unit, integration, and security test suite
├── frontend/
│   ├── index.html             # Single-page application markup
│   ├── index.css              # Custom design tokens, themes, and responsive layouts
│   ├── app.js                 # Frontend application logic, chat state, and source overlay
│   ├── server.js              # Lightweight Node static server and API proxy
│   └── vercel.json            # Vercel routing configuration
├── eval/                      # Benchmark datasets and evaluation scripts
├── scripts/                   # Phase verification, stress test, and utility scripts
├── docs/                      # Architectural specifications and design decisions
├── docker-compose.yml         # Container composition for production deployments
├── .env.example               # Environment variables template
└── .gitignore                 # Git ignore rules protecting secrets and local databases
```

---

## License

This project is licensed under the MIT License.
