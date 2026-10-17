# StudyMind — Grounded Study Assistant (Spec Pack)

Working name: **StudyMind**. Upload PDFs, images, notes, slides → ask questions, get summaries, flashcards, quizzes
→ every answer is **grounded in the user's own material, cited, and verified**, or the app says "not found in your material".

## Honest goal
"Zero hallucination" is not achievable by any LLM system. The goal here is:
1. Answers come ONLY from retrieved user content.
2. Every claim carries a citation (doc, page, highlighted region).
3. A verification step checks claims against sources before display.
4. When evidence is weak, the system **abstains**.
5. Quality is measured with an evaluation set, not assumed.

## Files in this pack (read in this order)
| # | File | Purpose |
|---|------|---------|
| 1 | `PRD.md` | What we are building, users, features, scope, acceptance criteria |
| 2 | `CHALLENGES.md` | Everything that can go wrong + mitigation |
| 3 | `TECH_REQUIREMENTS.md` | Stack, libraries, infra, versions, env vars |
| 4 | `ARCHITECTURE.md` | Components, data flow, DB schema, folder structure |
| 5 | `ANTI_HALLUCINATION.md` | The grounding + verification pipeline in detail |
| 6 | `API_SPEC.md` | REST endpoints and payloads |
| 7 | `PROMPTS.md` | LLM prompts (answer, verify, OCR cleanup, quiz) |
| 8 | `EVALUATION.md` | Test sets, metrics, pass thresholds |
| 9 | `IMPLEMENTATION_PLAN.md` | Phased, checkable task list for the agent |
| 10 | `QUIZ_ASSESSMENT.md` | Quiz / mock exam / adaptive practice / readiness engine (grounded) |
| 11 | `AGENTS.md` | Rules the coding agent must follow (copy to repo root) |
| 12 | `ANTIGRAVITY_KICKOFF_PROMPT.md` | Paste this first into Antigravity |

## How to use with Antigravity
1. Create an empty repo folder, copy this whole pack into `/docs/spec/`, and copy `AGENTS.md` to the repo root.
2. Open the folder in Antigravity, paste `ANTIGRAVITY_KICKOFF_PROMPT.md`.
3. Have the agent finish one phase at a time from `IMPLEMENTATION_PLAN.md`; review and run tests after each phase.
4. Do not skip `EVALUATION.md` — it is what proves the "no hallucination" claim.
