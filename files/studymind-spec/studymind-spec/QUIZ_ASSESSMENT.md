# Feature Spec — Quiz & Exam-Prep Engine ("Test Me")

The app quizzes the user from **their own PDFs/images**, grades them, finds weak topics, and drives them toward exam readiness.
Same rule as the rest of the product: **every question, answer key and explanation must be grounded in the user's material and cite it.**

## 1. Modes
| Mode | Description |
|---|---|
| Quick Quiz | 5–20 questions on selected docs/topics, instant feedback after each answer |
| Mock Exam | Timed, no feedback until the end, mixed question types, configurable marks (e.g. 20 MCQ + 5 short + 2 long), full report at the end |
| Weak-Topic Drill | Auto-selects topics where mastery is low or answers were wrong recently |
| Spaced Review | Resurfaces previously missed questions/flashcards on a schedule (FSRS or SM-2) |
| Adaptive Practice | Difficulty rises/falls with the user's performance per topic |
| Exam Countdown | User sets exam date + syllabus (docs/topics) → daily plan of quizzes + readiness score |
| Viva / Oral (V2) | Chat-style follow-up questions, user answers by text/voice, graded against source |

## 2. Question types
- MCQ (single), multi-select, true/false (with justification), fill-in-the-blank
- Short answer (1–3 sentences), long answer / essay (rubric graded)
- Numerical / formula problems (answer checked with tolerance; steps shown only if present in source)
- Match-the-following, ordering/sequence
- Image-based: label a diagram, identify a region (uses bounding boxes from image/page)
Each question carries: `topic_id`, `difficulty (1–5)`, `bloom_level (remember|understand|apply|analyze)`, `marks`, `source_chunk_ids`, `source_quotes`, `answer_key`, `rubric`, `explanation`.

## 3. Question generation pipeline (grounding is critical)
1. **Topic map**: after ingestion, extract topics/subtopics from headings + chunk clustering (LLM names clusters). Each chunk maps to topic(s). Stored in `topics` table.
2. **Coverage-aware selection**: choose chunks so questions cover the syllabus evenly (not only the first pages); weight by topic importance (heading level, repeated terms, user-flagged "important").
3. **Generate** (LLM, temp 0.3, JSON schema): question + key + explanation + quote + chunk ID, from the selected chunks only. Skip chunks that are low-OCR-quality, boilerplate, or captions with `source_type=generated_caption` (unless user allows).
4. **Validate (all must pass, else discard)**:
   - a. *Deterministic*: chunk ID exists; quote found in chunk (fuzzy ≥ 0.9); answer key text/numbers appear in chunk.
   - b. *Answerability test*: a separate LLM call answers the question using ONLY the cited chunk(s); its answer must match the key (exact for MCQ, semantic ≥ threshold for text). Mismatch → discard.
   - c. *MCQ checks*: exactly one correct option; distractors are plausible but contradicted or unsupported by the context; no "all/none of the above" unless asked; no length/position bias (shuffle).
   - d. *Quality*: not ambiguous, not trivially answered by the question text, not a duplicate (embedding similarity > 0.9 with existing questions in bank).
5. **Store** in question bank (cache by chunk hash + prompt version) so repeat sessions are fast and cheap; regenerate if source doc changes.
6. **User flag**: "Report bad question" (wrong key / not in my material / unclear) → question disabled immediately, added to regression set.

## 4. Grading
- **Objective types**: deterministic (exact / set equality / numeric tolerance / normalized string with synonyms list from key).
- **Short/long answers**: rubric grading.
  - At generation time create a rubric: list of *key points* (each cited to a chunk) + marks per point.
  - Grader LLM checks which key points the user's answer covers (per point: `covered | partial | missing`) and returns JSON — it may NOT invent extra criteria or use outside knowledge.
  - Score = deterministic sum from point statuses (the LLM does not output the final number).
  - Feedback shows: points earned/missed, the model answer built from the source, and citations to open the page.
  - Low-confidence grading (borderline/ambiguous) → mark "needs self-review" and show the source; let the user override (self-grade) — never silently fail them.
- **Image/handwritten answers (V2)**: user uploads photo of written answer → vision transcription (show transcript for user to confirm) → rubric grading.
- Always show the source passage for every wrong answer. Never reveal the key before the user submits (Mock Exam: only at the end).

## 5. Learner model & analytics
- Per-topic **mastery** (0–1): Bayesian/Elo-style update after each attempt, weighted by difficulty and recency decay.
- **Readiness score** per exam = coverage-weighted mastery across the syllabus (%), with confidence level (low if few attempts).
- **Spaced repetition**: wrong or hesitant answers scheduled with FSRS/SM-2 (`due_at`, `stability`, `ease`).
- Track time per question, confidence self-rating (optional "how sure are you?"), common error patterns (e.g., confuses X with Y — only from actual wrong-option choices).
- Dashboard: topic heatmap, accuracy trend, weak/strong topics, time management, questions due today, predicted readiness at exam date (simple trend, labelled as an estimate).
- Study plan: daily targets from exam date + mastery gaps ("Today: 15 min drill on Thermodynamics, 10 reviews"). Plan is rule-based, not LLM-invented.

## 6. UX requirements
- Start screen: choose scope (documents/topics), mode, count, difficulty, timer, question types.
- During quiz: progress bar, timer (mock), flag-for-review, navigation (mock), keyboard shortcuts.
- After each answer (practice mode): correct/incorrect, explanation, "Show in source" (opens page + highlight), "Ask AI about this" (opens grounded chat prefilled with the question).
- Results: score, per-topic breakdown, time analysis, list of missed questions → "Drill these" and "Add to flashcards".
- Export: quiz as PDF (question paper + answer key), Anki CSV.
- Accessibility: keyboard navigable, readable math (KaTeX).

## 7. Data model additions (Postgres)
```
topics(id, workspace_id, parent_id, name, chunk_ids[], created_at)
questions(id, workspace_id, document_ids[], topic_id, type, difficulty, bloom, marks, stem, options_json, answer_key_json,
          rubric_json, explanation, source_chunk_ids[], source_quotes[], validation_json, prompt_version, status(active|flagged|retired), created_at)
quiz_sessions(id, user_id, workspace_id, mode, config_json, started_at, submitted_at, duration_s, score, max_score)
attempts(id, session_id, question_id, user_answer_json, grade_json, score, time_s, confidence, graded_by(auto|llm|self), created_at)
topic_mastery(user_id, topic_id, mastery, attempts_count, last_attempt_at)
review_schedule(user_id, question_id, due_at, stability, ease, lapses, last_result)
exam_goals(id, user_id, workspace_id, name, exam_date, topic_ids[], target_score)
question_reports(id, question_id, user_id, reason, comment, created_at)
```
Indexes on `(user_id, due_at)`, `(workspace_id, topic_id, difficulty)`.

## 8. API additions (prefix `/api/v1`)
- `POST /workspaces/{wid}/topics/rebuild` · `GET /workspaces/{wid}/topics`
- `POST /workspaces/{wid}/quizzes` {mode, document_ids?, topic_ids?, count, difficulty, types[], time_limit_s?} → `{session_id, questions[]}` (answer keys NOT included)
- `GET /quizzes/{sid}` (resume) · `POST /quizzes/{sid}/answers` {question_id, answer, time_s, confidence?} → graded result (practice) or ack (mock)
- `POST /quizzes/{sid}/submit` → full report `{score, per_topic[], missed[], time_stats, readiness_delta}`
- `GET /workspaces/{wid}/analytics` → mastery heatmap, trends, readiness
- `GET /review/due` · `POST /review/{qid}/result`
- `POST /workspaces/{wid}/exam-goals` · `GET /exam-goals/{id}/plan`
- `POST /questions/{id}/report` {reason, comment}
- `GET /quizzes/{sid}/export?format=pdf|anki`
Security: never send `answer_key`/`rubric` to the client before submission; grade server-side.

## 9. Challenges specific to this feature (and mitigations)
| Challenge | Mitigation |
|---|---|
| Wrong answer key (hallucinated or OCR error) | Answerability test + quote check + skip low-OCR chunks + report button + auto-retire flagged questions |
| Trivial / ambiguous / duplicate questions | Quality validator, dedupe by embeddings, Bloom-level mix |
| Poor distractors | Generate distractors from same-topic terms in the material; validator ensures they're wrong per context |
| Subjective grading of long answers | Rubric of cited key points, deterministic scoring, self-review override, grader eval vs human labels |
| Uneven syllabus coverage | Topic map + coverage-aware sampling |
| Over-trusting readiness score | Show confidence, minimum attempts, label as estimate |
| Cost of many LLM calls | Question bank cache, batch generation at ingestion time, cheaper model for validation |
| Cheating/answer leakage | Server-side grading, keys withheld, randomized option order |
| User answers in other language / typos | Normalize, semantic matching for short text, accept synonyms from key |
| Math/formula grading | Numeric tolerance, unit handling, symbolic check via `sympy` where possible |
| Stress/demotivation | Encouraging feedback tone, streaks, "review not fail" framing |

## 10. Acceptance criteria
1. 100% of served questions have valid citations (chunk + quote verified).
2. Human audit of 100 generated questions: >= 95% have a correct key and are answerable from the cited text.
3. Objective grading accuracy 100%; rubric grader agreement with human >= 85% (Cohen's kappa >= 0.7) on 50 sampled answers.
4. Duplicate rate within a 20-question quiz < 5%.
5. Mock exam works with a timer, resumes after refresh, shows full report; keys never exposed in network responses before submit.
6. Mastery + due-review scheduling update correctly after attempts (unit tests with fixed scenarios).
7. A flagged question is removed from future quizzes immediately.
