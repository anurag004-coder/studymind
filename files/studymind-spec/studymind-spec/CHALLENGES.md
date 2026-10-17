# Challenges & Mitigations

## A. Hallucination & grounding
| Challenge | Why it happens | Mitigation |
|---|---|---|
| Model answers from its own knowledge | LLM prior overrides context | Strict system prompt, "context only" rule, temperature 0, output must be JSON with citations, verifier pass |
| Fabricated citations | Model invents page numbers | Citations are **chunk IDs we gave it**; backend validates IDs exist and quote is a substring (fuzzy) of chunk |
| Partially supported claims | Model blends 2 chunks into a false claim | Sentence-level claim extraction + entailment check per claim |
| Answering when nothing relevant retrieved | Model tries to be helpful | Retrieval score threshold + "insufficient evidence" abstain path *before* calling generator |
| Conflicting info across documents | Different editions/notes | Surface both with sources; never silently merge |
| Question outside the docs (general knowledge) | User expectation mismatch | Explicit message + optional clearly-labelled "outside source" mode (off by default) |

## B. Document ingestion
- **Scanned PDFs / photos**: skew, blur, low light → preprocess (deskew, denoise, binarize), OCR with confidence per word; flag low-confidence regions to user.
- **Handwriting**: classic OCR fails → vision-LLM transcription with confidence + keep original image for citation.
- **Multi-column layouts, headers/footers, footnotes**: naive extraction scrambles order → layout-aware parser (Docling / PyMuPDF blocks), strip repeated headers/footers.
- **Tables**: flatten badly → extract to Markdown/HTML table chunks, keep table as one chunk with caption.
- **Math/formulas/code**: lost in OCR → keep as LaTeX where possible, vision model fallback, never "fix" formulas by guessing.
- **Diagrams/figures**: no text → caption via vision model, mark as `generated_caption` (lower trust, shown labelled).
- **Large files**: memory/time → streaming, page-wise processing, background workers, resumable jobs.
- **Password-protected / corrupt files**: detect and return clear error.
- **Non-English / mixed script (Hindi/Bengali)**: use multilingual OCR + multilingual embeddings (bge-m3).
- **Malicious files**: virus/zip bombs/prompt injection inside docs → size limits, MIME sniffing, sandboxed parsing, treat document text as **untrusted data**.

## C. Retrieval quality
- Chunks too small lose context; too large dilute → structure-aware chunking (by heading/section), ~300-600 tokens, 10-15% overlap, parent-child retrieval.
- Pure vector search misses exact terms (formula names, numbers) → hybrid dense + BM25 with RRF fusion.
- Vague questions ("explain this") → query rewriting using chat history, ask clarifying question if ambiguous.
- Multi-hop questions → query decomposition, retrieve per sub-question.
- Summaries of whole documents don't fit "top-k" → hierarchical summarization (map-reduce) with citations to sections.
- Embedding drift when model changes → store embedding model name/version, re-index tool.

## D. Prompt injection (security)
Documents may contain "ignore previous instructions…". Mitigate: delimit context, label as untrusted, system prompt priority, strip/flag instruction-like text, no tool access for generator, output schema validation.

## E. Cost & latency
- Embedding + LLM + reranker + verifier = multiple calls → cache embeddings by content hash, cache answers by (query, doc-version), use small model for verification, batch embeddings, stream the answer (verify after / progressive).
- Free-tier rate limits → provider abstraction, retries with backoff, queue.

## F. Privacy & compliance
- Student data and possibly copyrighted books → per-user isolation, encryption at rest, delete-everything endpoint, no training on user data, clear ToS; user is responsible for upload rights.
- API providers receive content → document this; offer local-model mode (Ollama) for privacy.

## G. UX
- Users trust fluent text → show citations prominently, confidence indicator, "show source" always one click.
- Abstention feels unhelpful → on abstain, suggest closest related passages and rephrasings.
- Slow ingestion → progress bar, allow chatting on already-indexed pages.

## H. Evaluation
- No ground truth → build gold set (questions + expected answer + source page), adversarial/unanswerable set, regression in CI. Use RAGAS/DeepEval metrics + human spot checks.

## I. Engineering
- Provider lock-in → LLM/embedding/vector adapters behind interfaces.
- Reproducibility → pin versions, Docker, seed configs.
- Observability → trace every query: retrieved chunks, scores, prompts, verifier result (Langfuse / OpenTelemetry).
