# Kickoff prompt — paste into Antigravity

You are the lead engineer building **StudyMind**, a grounded study assistant: users upload PDFs, images and study material, then ask questions and generate summaries/flashcards/quizzes. Answers must come only from the user's material, with verified citations, or the app must abstain.

Before writing code:
1. Read `/docs/spec/README.md`, then `PRD.md`, `CHALLENGES.md`, `TECH_REQUIREMENTS.md`, `ARCHITECTURE.md`, `ANTI_HALLUCINATION.md`, `API_SPEC.md`, `PROMPTS.md`, `EVALUATION.md`, `QUIZ_ASSESSMENT.md`, `IMPLEMENTATION_PLAN.md`, and follow `AGENTS.md`.
2. Produce a short plan restating the architecture, risks, and any assumptions or spec conflicts. Wait for my approval.

Then:
- Execute **Phase 0 only**, run its tests, show me a summary and the DoD checklist.
- After my approval, continue phase by phase. Never skip the evaluation harness (Phase 4–5) — I want measured faithfulness and abstention numbers.
- Use an LLM provider configurable via `.env` (start with: <Gemini / OpenAI / Claude / Ollama — choose>). Use local `bge-m3` embeddings and a cross-encoder reranker unless I say otherwise.
- Where the spec is ambiguous, pick the simplest option, log it in `/docs/DECISIONS.md`, and tell me.

Priorities: correctness and groundedness > citations/UX > speed > extra features.
