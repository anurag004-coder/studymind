"""FastAPI routes for Quiz & Exam-Prep engine per QUIZ_ASSESSMENT.md §8."""

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models.quiz import (
    Attempt,
    ExamGoal,
    Question,
    QuizSession,
    ReviewSchedule,
    Topic,
    TopicMastery,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db
from app.quiz.mastery_service import MasteryService
from app.quiz.quiz_service import QuizService
from app.quiz.schemas import (
    AnalyticsResponse,
    AnswerFeedbackResponse,
    CreateExamGoalRequest,
    CreateQuizRequest,
    DailyTarget,
    DueReviewItem,
    DueReviewListResponse,
    ExamGoalResponse,
    OverrideScoreRequest,
    QuestionClientView,
    QuestionReportRequest,
    QuestionReportResponse,
    QuizReportResponse,
    QuizSessionCreatedResponse,
    StudyPlanResponse,
    SubmitAnswerRequest,
    SubmitReviewResultRequest,
    TopicPerformance,
    TopicRebuildResponse,
    TopicTreeResponse,
)
from app.quiz.topic_service import TopicService

router = APIRouter(tags=["quizzes"])
topic_svc = TopicService()
quiz_svc = QuizService()


async def verify_workspace_owner(workspace_id: str, user_id: str, db: AsyncSession) -> Workspace:
    """Verifies that workspace belongs to user (multi-tenant isolation)."""
    stmt = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.user_id == user_id,
    )
    ws = (await db.execute(stmt)).scalar_one_or_none()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or unauthorized",
        )
    return ws


# ---------------------------------------------------------
# Topics
# ---------------------------------------------------------
@router.post(
    "/workspaces/{workspace_id}/topics/rebuild",
    response_model=TopicRebuildResponse,
)
async def rebuild_topics(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TopicRebuildResponse:
    """Rebuilds topic outline and chunk mappings for the workspace."""
    await verify_workspace_owner(workspace_id, current_user.id, db)
    created, mapped = await topic_svc.rebuild_topics(workspace_id, db)
    return TopicRebuildResponse(
        status="success",
        topics_created=created,
        chunks_mapped=mapped,
    )


@router.get(
    "/workspaces/{workspace_id}/topics",
    response_model=TopicTreeResponse,
)
async def get_topics(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TopicTreeResponse:
    """Lists topic outline with mastery and question statistics."""
    await verify_workspace_owner(workspace_id, current_user.id, db)
    items = await topic_svc.get_topics_for_workspace(workspace_id, current_user.id, db)
    return TopicTreeResponse(topics=items, total=len(items))


# ---------------------------------------------------------
# Quiz Sessions
# ---------------------------------------------------------
@router.post(
    "/workspaces/{workspace_id}/quizzes",
    response_model=QuizSessionCreatedResponse,
)
async def create_quiz(
    workspace_id: str,
    req: CreateQuizRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuizSessionCreatedResponse:
    """Creates a new quiz session with answer keys strictly withheld."""
    await verify_workspace_owner(workspace_id, current_user.id, db)
    return await quiz_svc.create_quiz_session(current_user.id, workspace_id, req, db)


@router.get("/quizzes/{session_id}")
async def get_quiz_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Resumes an active session (keys withheld) or returns full report if submitted."""
    stmt = select(QuizSession).where(
        QuizSession.id == session_id,
        QuizSession.user_id == current_user.id,
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Quiz session not found")

    if session.submitted_at:
        return await quiz_svc.submit_quiz_session(session_id, current_user.id, db)

    # Active session: return client views
    att_stmt = (
        select(Attempt, Question)
        .join(Question, Attempt.question_id == Question.id)
        .where(Attempt.session_id == session_id)
    )
    rows = (await db.execute(att_stmt)).all()

    client_qs = []
    answers_so_far = {}
    for att, q in rows:
        client_qs.append(
            QuestionClientView(
                id=q.id,
                topic_id=q.topic_id,
                type=q.type,
                difficulty=q.difficulty,
                bloom=q.bloom,
                marks=q.marks,
                stem=q.stem,
                options=json.loads(q.options_json) if q.options_json else None,
            )
        )
        if att.user_answer_json:
            answers_so_far[q.id] = json.loads(att.user_answer_json)

    return {
        "session_id": session.id,
        "workspace_id": session.workspace_id,
        "mode": session.mode,
        "started_at": session.started_at,
        "time_limit_s": session.duration_s,
        "questions": client_qs,
        "saved_answers": answers_so_far,
    }


@router.post(
    "/quizzes/{session_id}/answers",
    response_model=AnswerFeedbackResponse,
)
async def submit_answer(
    session_id: str,
    req: SubmitAnswerRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnswerFeedbackResponse:
    """Submits answer for a single question with server-side grading."""
    try:
        return await quiz_svc.record_answer(session_id, current_user.id, req, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/quizzes/{session_id}/submit",
    response_model=QuizReportResponse,
)
async def submit_quiz(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuizReportResponse:
    """Submits the complete quiz session and generates results report."""
    try:
        return await quiz_svc.submit_quiz_session(session_id, current_user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/quizzes/attempts/{attempt_id}/override")
async def override_attempt_score(
    attempt_id: str,
    req: OverrideScoreRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Allows student to override score for written questions flagged as needs_review."""
    stmt = (
        select(Attempt)
        .join(QuizSession, Attempt.session_id == QuizSession.id)
        .where(
            Attempt.id == attempt_id,
            QuizSession.user_id == current_user.id,
        )
    )
    attempt = (await db.execute(stmt)).scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt.score = req.score
    attempt.graded_by = "self"
    grade_data = json.loads(attempt.grade_json) if attempt.grade_json else {}
    grade_data["self_override"] = True
    grade_data["self_comment"] = req.comment
    attempt.grade_json = json.dumps(grade_data)

    await db.commit()
    return {"status": "success", "new_score": attempt.score}


# ---------------------------------------------------------
# Analytics & Spaced Repetition
# ---------------------------------------------------------
@router.get(
    "/workspaces/{workspace_id}/analytics",
    response_model=AnalyticsResponse,
)
async def get_analytics(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnalyticsResponse:
    """Retrieves mastery heatmap, syllabus readiness, and accuracy trends."""
    await verify_workspace_owner(workspace_id, current_user.id, db)

    readiness, confidence, total_attempts = await MasteryService.compute_readiness(
        workspace_id, current_user.id, db
    )

    # Topics breakdown
    topics = await topic_svc.get_topics_for_workspace(workspace_id, current_user.id, db)
    weak = [t.name for t in topics if t.mastery < 0.6]
    strong = [t.name for t in topics if t.mastery >= 0.8]

    # Overall accuracy
    att_stmt = (
        select(func.sum(Attempt.score), func.count(Attempt.id))
        .join(QuizSession, Attempt.session_id == QuizSession.id)
        .where(
            QuizSession.workspace_id == workspace_id,
            QuizSession.user_id == current_user.id,
            Attempt.score.isnot(None),
        )
    )
    tot_score, tot_count = (await db.execute(att_stmt)).one()
    avg_acc = (
        round((float(tot_score or 0) / max(1, tot_count or 1)) * 100.0, 1) if tot_count else 0.0
    )

    # Due reviews count
    now = datetime.now(timezone.utc)
    due_stmt = (
        select(func.count(ReviewSchedule.id))
        .join(Question, ReviewSchedule.question_id == Question.id)
        .where(
            ReviewSchedule.user_id == current_user.id,
            Question.workspace_id == workspace_id,
            ReviewSchedule.due_at <= now,
        )
    )
    due_count = (await db.execute(due_stmt)).scalar() or 0

    topic_perfs = [
        TopicPerformance(
            topic_id=t.id,
            topic_name=t.name,
            questions_count=t.question_count,
            score=round(t.mastery * 10, 1),
            max_score=10.0,
            percentage=round(t.mastery * 100.0, 1),
        )
        for t in topics
    ]

    return AnalyticsResponse(
        workspace_id=workspace_id,
        overall_readiness_pct=readiness,
        confidence_level=confidence,
        total_attempts=total_attempts,
        topics=topic_perfs,
        weak_topics=weak,
        strong_topics=strong,
        average_accuracy_pct=min(100.0, avg_acc),
        total_due_reviews=due_count,
    )


@router.get("/review/due", response_model=DueReviewListResponse)
async def get_due_reviews(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DueReviewListResponse:
    """Lists questions currently due for spaced repetition review."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(ReviewSchedule, Question)
        .join(Question, ReviewSchedule.question_id == Question.id)
        .where(
            ReviewSchedule.user_id == current_user.id,
            ReviewSchedule.due_at <= now,
        )
        .order_by(ReviewSchedule.due_at)
    )
    rows = (await db.execute(stmt)).all()

    items = [
        DueReviewItem(
            schedule_id=sched.id,
            question_id=q.id,
            stem=q.stem,
            type=q.type,
            difficulty=q.difficulty,
            due_at=sched.due_at,
            stability=sched.stability,
            ease=sched.ease,
            lapses=sched.lapses,
        )
        for sched, q in rows
    ]
    return DueReviewListResponse(due_items=items, total_due=len(items))


@router.post("/review/{question_id}/result")
async def record_review_result(
    question_id: str,
    req: SubmitReviewResultRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Records spaced repetition rating (0-5) and updates next due date."""
    sched = await MasteryService.update_review_schedule(
        user_id=current_user.id,
        question_id=question_id,
        quality=req.quality,
        db=db,
    )
    await db.commit()
    return {
        "status": "success",
        "question_id": question_id,
        "due_at": sched.due_at,
        "ease": sched.ease,
    }


# ---------------------------------------------------------
# Exam Goals & Study Plan
# ---------------------------------------------------------
@router.post(
    "/workspaces/{workspace_id}/exam-goals",
    response_model=ExamGoalResponse,
)
async def create_exam_goal(
    workspace_id: str,
    req: CreateExamGoalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExamGoalResponse:
    """Sets target exam date and syllabus goal."""
    await verify_workspace_owner(workspace_id, current_user.id, db)
    now = datetime.now(timezone.utc)
    target_dt = req.exam_date
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
    days_rem = max(1, (target_dt - now).days)

    goal = ExamGoal(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        workspace_id=workspace_id,
        name=req.name,
        exam_date=req.exam_date,
        topic_ids=json.dumps(req.topic_ids),
        target_score=req.target_score,
    )
    db.add(goal)
    await db.commit()

    readiness, _, _ = await MasteryService.compute_readiness(workspace_id, current_user.id, db)

    return ExamGoalResponse(
        id=goal.id,
        workspace_id=goal.workspace_id,
        name=goal.name,
        exam_date=goal.exam_date,
        topic_ids=req.topic_ids,
        target_score=goal.target_score,
        days_remaining=days_rem,
        predicted_readiness_pct=readiness,
    )


@router.get("/exam-goals/{goal_id}/plan", response_model=StudyPlanResponse)
async def get_study_plan(
    goal_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudyPlanResponse:
    """Generates rule-based daily study plan for exam goal."""
    stmt = select(ExamGoal).where(
        ExamGoal.id == goal_id,
        ExamGoal.user_id == current_user.id,
    )
    goal = (await db.execute(stmt)).scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Exam goal not found")

    topics_stmt = select(Topic).where(Topic.workspace_id == goal.workspace_id)
    topics = (await db.execute(topics_stmt)).scalars().all()
    if not topics:
        await topic_svc.rebuild_topics(goal.workspace_id, db)
        topics = (await db.execute(topics_stmt)).scalars().all()

    # Mastery map
    m_stmt = select(TopicMastery).where(TopicMastery.user_id == current_user.id)
    m_rows = (await db.execute(m_stmt)).scalars().all()
    m_map = {m.topic_id: m.mastery for m in m_rows}

    plan = MasteryService.generate_study_plan(
        exam_name=goal.name,
        exam_date=goal.exam_date,
        topics=list(topics),
        mastery_map=m_map,
        target_score=goal.target_score,
    )

    now = datetime.now(timezone.utc)
    target_dt = goal.exam_date
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
    days_rem = max(1, (target_dt - now).days)
    readiness, _, _ = await MasteryService.compute_readiness(goal.workspace_id, current_user.id, db)

    return StudyPlanResponse(
        goal_id=goal.id,
        exam_name=goal.name,
        exam_date=goal.exam_date,
        days_remaining=days_rem,
        current_readiness_pct=readiness,
        target_score_pct=goal.target_score,
        daily_schedule=[
            DailyTarget(
                day_number=d["day_number"],
                date=d["date"],
                focus_topic=d["focus_topic"],
                recommended_action=d["recommended_action"],
                estimated_time_minutes=d["estimated_time_minutes"],
            )
            for d in plan
        ],
    )


# ---------------------------------------------------------
# Question Reporting
# ---------------------------------------------------------
@router.post(
    "/questions/{question_id}/report",
    response_model=QuestionReportResponse,
)
async def report_question(
    question_id: str,
    req: QuestionReportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuestionReportResponse:
    """Flags a bad question, instantly disabling it from future quizzes."""
    try:
        report = await quiz_svc.report_bad_question(
            question_id=question_id,
            user_id=current_user.id,
            reason=req.reason,
            comment=req.comment,
            db=db,
        )
        return QuestionReportResponse(
            report_id=report.id,
            question_id=question_id,
            status="flagged",
            message="Question reported and retired from active quizzes.",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---------------------------------------------------------
# Export (PDF Printable / Anki CSV)
# ---------------------------------------------------------
@router.get("/quizzes/{session_id}/export")
async def export_quiz_session(
    session_id: str,
    format: str = Query("anki", pattern="^(anki|pdf|markdown)$"),
    current_user: Annotated[User, Depends(get_current_user)] = None,  # type: ignore[assignment]
    db: Annotated[AsyncSession, Depends(get_db)] = None,  # type: ignore[assignment]
) -> Response:
    """Exports quiz questions as Anki TSV or printable Markdown study guide."""
    stmt = (
        select(Attempt, Question)
        .join(Question, Attempt.question_id == Question.id)
        .join(QuizSession, Attempt.session_id == QuizSession.id)
        .where(
            QuizSession.id == session_id,
            QuizSession.user_id == current_user.id,
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Quiz session not found")

    if format == "anki":
        lines = []
        for _, q in rows:
            front = q.stem
            opts = json.loads(q.options_json) if q.options_json else None
            if opts:
                front += "<br>" + "<br>".join(f"• {opt}" for opt in opts)
            back = f"<b>Answer:</b> {q.answer_key_json}<br><br><b>Explanation:</b> {q.explanation}"
            quotes = json.loads(q.source_quotes)
            if quotes:
                back += f"<br><br><i>Source: {quotes[0]}</i>"
            tags = f"studymind quiz {q.type}"
            lines.append(f"{front}\t{back}\t{tags}")

        tsv_data = "\n".join(lines)
        return Response(
            content=tsv_data,
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": f'attachment; filename="quiz_{session_id}.tsv"'},
        )

    # Markdown / printable question paper with answer key at the end
    md_lines = [
        f"# StudyMind Exam Paper: Session {session_id[:8]}",
        f"Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n",
        "## Part 1: Questions\n",
    ]
    for idx, (_, q) in enumerate(rows, 1):
        md_lines.append(f"**Q{idx}. [{q.marks} Marks]** {q.stem}")
        opts = json.loads(q.options_json) if q.options_json else None
        if opts:
            for opt_idx, opt in enumerate(opts):
                md_lines.append(f"   ({chr(65 + opt_idx)}) {opt}")
        md_lines.append("")

    md_lines.append("\n---\n## Part 2: Answer Key & Verified Explanations\n")
    for idx, (_, q) in enumerate(rows, 1):
        md_lines.append(f"**Q{idx} Answer:** {q.answer_key_json}")
        md_lines.append(f"- **Explanation:** {q.explanation}")
        quotes = json.loads(q.source_quotes)
        if quotes:
            md_lines.append(f'- **Cited Quote:** "{quotes[0]}"')
        md_lines.append("")

    return Response(
        content="\n".join(md_lines),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="quiz_{session_id}.md"'},
    )
