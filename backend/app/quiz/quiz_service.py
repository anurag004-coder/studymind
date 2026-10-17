"""Quiz session orchestrator and examination manager per QUIZ_ASSESSMENT.md."""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import get_llm_adapter
from app.db.models.quiz import (
    Attempt,
    Question,
    QuestionReport,
    QuizSession,
    ReviewSchedule,
    Topic,
    TopicMastery,
)
from app.quiz.graders import ObjectiveGrader, RubricGrader
from app.quiz.mastery_service import MasteryService
from app.quiz.question_generator import QuestionGenerator
from app.quiz.schemas import (
    AnswerFeedbackResponse,
    CreateQuizRequest,
    QuestionClientView,
    QuestionReviewItem,
    QuizReportResponse,
    QuizSessionCreatedResponse,
    SubmitAnswerRequest,
    TopicPerformance,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class QuizService:
    """Manages active quiz sessions, server-side grading, and exam submissions."""

    def __init__(self) -> None:
        self.generator = QuestionGenerator()
        self.rubric_grader = RubricGrader()
        self.llm = get_llm_adapter()
        self.feedback_prompt = (PROMPTS_DIR / "feedback_writer_v1.txt").read_text(encoding="utf-8")

    async def create_quiz_session(
        self,
        user_id: str,
        workspace_id: str,
        req: CreateQuizRequest,
        db: AsyncSession,
    ) -> QuizSessionCreatedResponse:
        """Creates a quiz session with server-side withheld answer keys."""
        # 1. Fetch available active questions
        stmt = select(Question).where(
            Question.workspace_id == workspace_id,
            Question.status == "active",
        )
        if req.topic_ids:
            stmt = stmt.where(Question.topic_id.in_(req.topic_ids))
        if req.types:
            stmt = stmt.where(Question.type.in_(req.types))

        raw_questions = (await db.execute(stmt)).scalars().all()

        # Sanitize and retire any incomplete legacy questions on the fly
        questions: list[Question] = []
        for q in raw_questions:
            stem = (q.stem or "").strip()
            if (
                len(stem) < 25
                or stem.endswith((":", ","))
                or "regarding include:" in stem
                or "Threats,." in stem
                or "Secure." in stem
            ):
                q.status = "retired"
                continue

            if q.type == "mcq":
                try:
                    opts = json.loads(q.options_json) if q.options_json else []
                    if (
                        not isinstance(opts, list)
                        or len(opts) != 4
                        or any(len(str(o).strip()) < 5 for o in opts)
                    ):
                        q.status = "retired"
                        continue
                except Exception:
                    q.status = "retired"
                    continue

            questions.append(q)

        # Mode-specific question filtering
        if req.mode == "spaced":
            now = datetime.now(timezone.utc)
            due_stmt = select(ReviewSchedule.question_id).where(
                ReviewSchedule.user_id == user_id,
                ReviewSchedule.due_at <= now,
            )
            due_ids = set((await db.execute(due_stmt)).scalars().all())
            due_qs = [q for q in questions if q.id in due_ids]
            if len(due_qs) >= 2:
                questions = due_qs

        elif req.mode == "drill":
            weak_stmt = select(TopicMastery.topic_id).where(
                TopicMastery.user_id == user_id,
                TopicMastery.mastery < 0.6,
            )
            weak_ids = set((await db.execute(weak_stmt)).scalars().all())
            drill_qs = [q for q in questions if q.topic_id in weak_ids]
            if len(drill_qs) >= 2:
                questions = drill_qs

        # 2. If not enough questions, generate new grounded questions
        if len(questions) < req.count:
            needed = req.count - len(questions)
            new_qs = await self.generator.generate_and_store_questions(
                workspace_id=workspace_id,
                document_ids=req.document_ids,
                topic_ids=req.topic_ids,
                count=needed,
                difficulty=req.difficulty,
                types=req.types,
                db=db,
            )
            questions = list(questions) + new_qs

        selected = questions[: req.count]
        if not selected:
            # Fallback attempt: generate directly
            selected = await self.generator.generate_and_store_questions(
                workspace_id=workspace_id,
                document_ids=req.document_ids,
                topic_ids=req.topic_ids,
                count=req.count,
                difficulty=req.difficulty,
                types=req.types,
                db=db,
            )

        # 3. Create Session
        session_id = str(uuid.uuid4())
        session = QuizSession(
            id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            mode=req.mode,
            config_json=json.dumps(req.model_dump()),
            started_at=datetime.now(timezone.utc),
            duration_s=req.time_limit_s,
        )
        db.add(session)

        client_questions: list[QuestionClientView] = []
        for q in selected:
            # Record initial empty attempt
            attempt = Attempt(
                id=str(uuid.uuid4()),
                session_id=session_id,
                question_id=q.id,
                user_answer_json=json.dumps(None),
                score=None,
                time_s=0,
            )
            db.add(attempt)

            # Build strictly sanitized client view (NO ANSWER KEYS OR QUOTES)
            opts = json.loads(q.options_json) if q.options_json else None
            client_questions.append(
                QuestionClientView(
                    id=q.id,
                    topic_id=q.topic_id,
                    type=q.type,
                    difficulty=q.difficulty,
                    bloom=q.bloom,
                    marks=q.marks,
                    stem=q.stem,
                    options=opts,
                )
            )

        await db.commit()

        return QuizSessionCreatedResponse(
            session_id=session_id,
            workspace_id=workspace_id,
            mode=req.mode,
            time_limit_s=req.time_limit_s,
            started_at=session.started_at,
            questions=client_questions,
            total_questions=len(client_questions),
        )

    async def record_answer(
        self,
        session_id: str,
        user_id: str,
        req: SubmitAnswerRequest,
        db: AsyncSession,
    ) -> AnswerFeedbackResponse:
        """Records student answer with server-side grading."""
        # 1. Verify session ownership
        sess_stmt = select(QuizSession).where(
            QuizSession.id == session_id,
            QuizSession.user_id == user_id,
        )
        session = (await db.execute(sess_stmt)).scalar_one_or_none()
        if not session or session.submitted_at:
            raise ValueError("Quiz session not found or already submitted")

        # 2. Find attempt and question
        att_stmt = select(Attempt).where(
            Attempt.session_id == session_id,
            Attempt.question_id == req.question_id,
        )
        attempt = (await db.execute(att_stmt)).scalar_one_or_none()
        if not attempt:
            raise ValueError(f"Question {req.question_id} not part of this session")

        q_stmt = select(Question).where(Question.id == req.question_id)
        question = (await db.execute(q_stmt)).scalar_one_or_none()
        if not question:
            raise ValueError("Question not found")

        # 3. Grade answer
        score, is_correct, grade_info, needs_review = await self._grade_single_question(
            question, req.user_answer
        )

        attempt.user_answer_json = json.dumps(req.user_answer)
        attempt.grade_json = json.dumps(grade_info)
        attempt.score = score
        attempt.time_s = req.time_s
        attempt.confidence = req.confidence
        attempt.graded_by = "llm" if question.type in ("short_answer", "long_answer") else "auto"

        await db.commit()

        # In Mock Exam mode, suppress answer key until final submission!
        if session.mode == "mock":
            return AnswerFeedbackResponse(
                attempt_id=attempt.id,
                question_id=question.id,
                is_correct=False,
                score=0.0,
                max_score=question.marks,
                user_answer=req.user_answer,
                correct_answer=None,  # Withheld
                explanation=None,  # Withheld
                source_quotes=None,  # Withheld
                source_chunk_ids=None,
                needs_review=False,
            )

        # In Practice / Quick modes, provide instant feedback & source citation
        key_val = json.loads(question.answer_key_json)
        quotes = json.loads(question.source_quotes)
        chunk_ids = json.loads(question.source_chunk_ids)

        return AnswerFeedbackResponse(
            attempt_id=attempt.id,
            question_id=question.id,
            is_correct=is_correct,
            score=score,
            max_score=question.marks,
            user_answer=req.user_answer,
            correct_answer=key_val,
            explanation=question.explanation,
            source_quotes=quotes,
            source_chunk_ids=chunk_ids,
            needs_review=needs_review,
        )

    async def submit_quiz_session(
        self,
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> QuizReportResponse:
        """Submits quiz session and compiles comprehensive results report."""
        sess_stmt = select(QuizSession).where(
            QuizSession.id == session_id,
            QuizSession.user_id == user_id,
        )
        session = (await db.execute(sess_stmt)).scalar_one_or_none()
        if not session:
            raise ValueError("Session not found")

        # Fetch all attempts
        att_stmt = (
            select(Attempt, Question)
            .join(Question, Attempt.question_id == Question.id)
            .where(Attempt.session_id == session_id)
        )
        rows = (await db.execute(att_stmt)).all()

        total_score = 0.0
        max_possible = 0.0
        topic_scores: dict[str, dict[str, Any]] = {}
        reviews: list[QuestionReviewItem] = []

        now = datetime.now(timezone.utc)
        start_dt = session.started_at
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        duration = int((now - start_dt).total_seconds())

        for attempt, question in rows:
            max_possible += question.marks
            u_ans = json.loads(attempt.user_answer_json) if attempt.user_answer_json else None

            # If attempt wasn't graded yet, grade now
            if attempt.score is None:
                score, is_correct, grade_info, needs_review = await self._grade_single_question(
                    question, u_ans
                )
                attempt.score = score
                attempt.grade_json = json.dumps(grade_info)
            else:
                score = attempt.score
                is_correct = score >= (question.marks * 0.85)
                grade_info = json.loads(attempt.grade_json) if attempt.grade_json else {}
                needs_review = False

            total_score += score

            # Update Topic Mastery and Spaced Repetition (SM-2)
            await MasteryService.update_topic_mastery(
                user_id=user_id,
                topic_id=question.topic_id,
                score=score,
                max_score=question.marks,
                difficulty=question.difficulty,
                db=db,
            )

            # SM-2 quality grade (0 to 5)
            q_quality = 5 if is_correct else 1
            await MasteryService.update_review_schedule(
                user_id=user_id,
                question_id=question.id,
                quality=q_quality,
                db=db,
            )

            # Aggregate per topic
            top_id = question.topic_id or "general"
            if top_id not in topic_scores:
                top_name = "General"
                if question.topic_id:
                    t_stmt = select(Topic).where(Topic.id == question.topic_id)
                    t_row = (await db.execute(t_stmt)).scalar_one_or_none()
                    if t_row:
                        top_name = t_row.name
                topic_scores[top_id] = {
                    "id": top_id,
                    "name": top_name,
                    "score": 0.0,
                    "max": 0.0,
                    "count": 0,
                }
            topic_scores[top_id]["score"] += score
            topic_scores[top_id]["max"] += question.marks
            topic_scores[top_id]["count"] += 1

            reviews.append(
                QuestionReviewItem(
                    question_id=question.id,
                    stem=question.stem,
                    type=question.type,
                    marks=question.marks,
                    user_answer=u_ans,
                    score=score,
                    is_correct=is_correct,
                    correct_answer=json.loads(question.answer_key_json),
                    explanation=question.explanation,
                    source_quotes=json.loads(question.source_quotes),
                    source_chunk_ids=json.loads(question.source_chunk_ids),
                    rubric_evaluation=grade_info,
                    needs_review=needs_review,
                )
            )

        percentage = round((total_score / max_possible * 100.0), 1) if max_possible > 0 else 0.0
        passed = percentage >= 60.0

        session.submitted_at = now
        session.duration_s = duration
        session.score = round(total_score, 2)
        session.max_score = round(max_possible, 2)

        # Build topic breakdowns
        per_topic = []
        for t_data in topic_scores.values():
            pct = round((t_data["score"] / t_data["max"] * 100.0), 1) if t_data["max"] > 0 else 0.0
            per_topic.append(
                TopicPerformance(
                    topic_id=t_data["id"],
                    topic_name=t_data["name"],
                    questions_count=t_data["count"],
                    score=round(t_data["score"], 2),
                    max_score=round(t_data["max"], 2),
                    percentage=pct,
                )
            )

        # Overall readiness
        readiness, _, _ = await MasteryService.compute_readiness(session.workspace_id, user_id, db)

        encourage_note = (
            "Excellent understanding of the core material!"
            if passed
            else "Good effort! Review the cited weak topics."
        )
        feedback_text = (
            f"You scored {percentage}% ({total_score}/{max_possible} marks). {encourage_note}"
        )

        await db.commit()

        return QuizReportResponse(
            session_id=session.id,
            workspace_id=session.workspace_id,
            mode=session.mode,
            started_at=session.started_at,
            submitted_at=now,
            duration_s=duration,
            score=round(total_score, 2),
            max_score=round(max_possible, 2),
            percentage=percentage,
            passed=passed,
            per_topic=per_topic,
            questions=reviews,
            encouraging_feedback=feedback_text,
            readiness_score=readiness,
        )

    async def report_bad_question(
        self,
        question_id: str,
        user_id: str,
        reason: str,
        comment: str | None,
        db: AsyncSession,
    ) -> QuestionReport:
        """Instantly disables reported question per QUIZ_ASSESSMENT.md §3."""
        q_stmt = select(Question).where(Question.id == question_id)
        question = (await db.execute(q_stmt)).scalar_one_or_none()
        if not question:
            raise ValueError("Question not found")

        # Disable immediately
        question.status = "flagged"

        report = QuestionReport(
            id=str(uuid.uuid4()),
            question_id=question_id,
            user_id=user_id,
            reason=reason,
            comment=comment,
        )
        db.add(report)
        await db.commit()
        return report

    async def _grade_single_question(
        self, question: Question, user_answer: Any
    ) -> tuple[float, bool, dict[str, Any], bool]:
        """Routes question to appropriate objective or rubric grader."""
        if user_answer is None or str(user_answer).strip() == "":
            return 0.0, False, {"comment": "Unanswered"}, False

        key = json.loads(question.answer_key_json)

        if question.type == "mcq":
            score, is_corr = ObjectiveGrader.grade_mcq(user_answer, key, question.marks)
            return score, is_corr, {"type": "mcq"}, False

        if question.type == "multi_select":
            score, is_corr = ObjectiveGrader.grade_multi_select(user_answer, key, question.marks)
            return score, is_corr, {"type": "multi_select"}, False

        if question.type == "true_false":
            score, is_corr = ObjectiveGrader.grade_true_false(user_answer, key, question.marks)
            return score, is_corr, {"type": "true_false"}, False

        if question.type == "fill_blank":
            score, is_corr = ObjectiveGrader.grade_fill_blank(user_answer, key, question.marks)
            return score, is_corr, {"type": "fill_blank"}, False

        if question.type == "numeric":
            score, is_corr = ObjectiveGrader.grade_numeric(user_answer, key, 0.05, question.marks)
            return score, is_corr, {"type": "numeric"}, False

        # Written question with rubric
        rubric = json.loads(question.rubric_json) if question.rubric_json else []
        return await self.rubric_grader.grade(
            question.stem, str(user_answer), rubric, question.marks
        )
