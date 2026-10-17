# PRD — StudyMind

## 1. Problem
Students use generic chatbots that invent facts. They need an assistant that answers strictly from their own
notes/books/slides/handwritten pages and shows exactly where each answer came from.

## 2. Target users
- College/school students (primary), exam-prep learners, self-learners.
- Secondary: researchers/professionals querying their own document sets.

## 3. Core user stories
- U1: Upload PDF / image / DOCX / PPTX / TXT / (later) YouTube transcript or audio.
- U2: Ask a question; get an answer with inline citations `[1]`, click → opens page with the source text highlighted.
- U3: If the answer is not in my material, the app clearly says so (no guessing).
- U4: Generate summary, key points, flashcards, and MCQ quiz **from my material only**, with citations.
- U5: Scope a chat to one document, a folder ("workspace"), or everything.
- U6: See processing status (uploaded → parsed → OCR → indexed) and fix bad OCR.
- U7: Delete my files and all derived data (privacy).
- U8: Be quizzed on my own material (MCQ, short/long answer, numerical, diagram-based) with instant grading and source-cited explanations.
- U9: Take a timed mock exam and get a report: score, per-topic breakdown, weak areas.
- U10: Set an exam date and syllabus; get a readiness score, spaced-repetition reviews and a daily study plan.
- U11: Report a bad/wrong question so it is removed immediately.

## 4. Features
### MVP (must)
- Auth (email/password or OAuth), workspaces
- Upload: PDF (text + scanned), images (PNG/JPG), DOCX, PPTX, TXT/MD
- Parsing + OCR + chunking + indexing pipeline (async)
- Hybrid retrieval (dense + BM25) + reranker
- Grounded Q&A with citations + verification + abstention
- Citation viewer (PDF page + highlight; image with bounding box)
- Chat history per workspace
- Summary + flashcards generation (grounded)
- **Quiz & Exam-Prep engine** (see `QUIZ_ASSESSMENT.md`): quick quiz, mock exam, weak-topic drill, grading, mastery tracking, spaced review, readiness score

### V2 (should)
- Handwriting OCR via vision LLM, tables/formulas (LaTeX) support
- Multilingual (Hindi, Bengali, English minimum)
- Voice input/output, YouTube/audio transcripts (Whisper)
- Spaced repetition for flashcards, export to Anki/PDF
- "Strict mode" toggle: refuse anything not directly quoted

### Out of scope (v1)
- Web search / outside knowledge (explicitly disabled; optional labelled "outside source" mode later)
- Real-time collaboration, mobile native apps

## 5. Non-functional requirements
- Answer latency: p50 < 6 s, p95 < 15 s (excluding ingestion)
- Ingestion: 100-page text PDF < 90 s; scanned < 5 min
- Faithfulness (see EVALUATION.md) >= 95% on gold set; abstention precision >= 90%
- Data isolation per user (row-level + vector payload filter by `user_id`)
- Max upload 50 MB / file, 500 pages / file (configurable)
- GDPR/DPDP-style delete: full purge within 24 h

## 6. Success metrics
- % answers with >=1 valid citation (target 100% for non-abstained)
- Citation validity (quote actually exists in cited chunk): >= 98%
- User thumbs-up rate, "answer was wrong" report rate < 3%

## 7. Acceptance criteria (MVP done when)
0. Quiz engine meets all criteria in `QUIZ_ASSESSMENT.md` §10.
1. Upload a 50-page textbook PDF → ask 20 questions from gold set → >= 95% faithful.
2. Ask 10 out-of-scope questions → >= 9 abstentions ("not found in your material").
3. Scanned page photo uploaded → searchable and cited with bounding-box highlight.
4. Every citation click opens the exact page/region.
5. All tests in `EVALUATION.md` run in CI via one command.
