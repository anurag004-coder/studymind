"""Pydantic v2 schemas for Quiz & Exam-Prep engine per QUIZ_ASSESSMENT.md."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------
# Topics
# ---------------------------------------------------------
class TopicItem(BaseModel):
    id: str
    workspace_id: str
    parent_id: str | None = None
    name: str
    chunk_count: int = 0
    question_count: int = 0
    mastery: float = 0.0
    created_at: datetime


class TopicTreeResponse(BaseModel):
    topics: list[TopicItem]
    total: int


class TopicRebuildResponse(BaseModel):
    status: str
    topics_created: int
    chunks_mapped: int


# ---------------------------------------------------------
# Questions & Question Bank
# ---------------------------------------------------------
class RubricPoint(BaseModel):
    id: str
    description: str
    quote: str
    marks: float = 1.0


class QuestionClientView(BaseModel):
    """View of question shown to student during active quiz session.
    CRITICAL: answer_key, rubric, and explanation quotes are strictly withheld!"""

    id: str
    topic_id: str | None = None
    type: str  # mcq, multi_select, true_false, fill_blank, numeric, short_answer, long_answer
    difficulty: int = 3
    bloom: str = "remember"
    marks: float = 1.0
    stem: str
    options: list[str] | None = None  # Populated for MCQ / multi_select (randomly arranged)


class QuestionFullView(BaseModel):
    """Complete question view for results review or question bank."""

    id: str
    workspace_id: str
    document_ids: list[str] = Field(default_factory=list)
    topic_id: str | None = None
    type: str
    difficulty: int
    bloom: str
    marks: float
    stem: str
    options: list[str] | None = None
    answer_key: Any
    rubric: list[RubricPoint] | None = None
    explanation: str
    source_chunk_ids: list[str]
    source_quotes: list[str]
    status: str
    created_at: datetime


# ---------------------------------------------------------
# Sessions & Answers
# ---------------------------------------------------------
class CreateQuizRequest(BaseModel):
    mode: str = "quick"  # quick, mock, drill, spaced, adaptive, countdown
    document_ids: list[str] | None = None
    topic_ids: list[str] | None = None
    count: int = Field(default=5, ge=1, le=50)
    difficulty: int = Field(default=3, ge=1, le=5)
    types: list[str] | None = None
    time_limit_s: int | None = None  # Required or optional for mock exam


class QuizSessionCreatedResponse(BaseModel):
    session_id: str
    workspace_id: str
    mode: str
    time_limit_s: int | None = None
    started_at: datetime
    questions: list[QuestionClientView]
    total_questions: int


class SubmitAnswerRequest(BaseModel):
    question_id: str
    user_answer: Any
    time_s: int = Field(default=0, ge=0)
    confidence: int | None = Field(default=None, ge=1, le=5)


class AnswerFeedbackResponse(BaseModel):
    attempt_id: str
    question_id: str
    is_correct: bool
    score: float
    max_score: float
    user_answer: Any
    correct_answer: Any | None = None
    explanation: str | None = None
    source_quotes: list[str] | None = None
    source_chunk_ids: list[str] | None = None
    needs_review: bool = False


class QuestionReviewItem(BaseModel):
    question_id: str
    stem: str
    type: str
    marks: float
    user_answer: Any
    score: float
    is_correct: bool
    correct_answer: Any
    explanation: str
    source_quotes: list[str]
    source_chunk_ids: list[str]
    rubric_evaluation: dict[str, Any] | None = None
    needs_review: bool = False


class TopicPerformance(BaseModel):
    topic_id: str
    topic_name: str
    questions_count: int
    score: float
    max_score: float
    percentage: float


class QuizReportResponse(BaseModel):
    session_id: str
    workspace_id: str
    mode: str
    started_at: datetime
    submitted_at: datetime
    duration_s: int
    score: float
    max_score: float
    percentage: float
    passed: bool
    per_topic: list[TopicPerformance]
    questions: list[QuestionReviewItem]
    encouraging_feedback: str
    readiness_score: float


# ---------------------------------------------------------
# Self-Review Override
# ---------------------------------------------------------
class OverrideScoreRequest(BaseModel):
    score: float
    comment: str | None = None


# ---------------------------------------------------------
# Spaced Repetition & Analytics
# ---------------------------------------------------------
class DueReviewItem(BaseModel):
    schedule_id: str
    question_id: str
    stem: str
    type: str
    difficulty: int
    due_at: datetime
    stability: float
    ease: float
    lapses: int


class DueReviewListResponse(BaseModel):
    due_items: list[DueReviewItem]
    total_due: int


class SubmitReviewResultRequest(BaseModel):
    quality: int = Field(ge=0, le=5)  # SM-2 grade 0-5 (0=blackout, 5=perfect)


class AnalyticsResponse(BaseModel):
    workspace_id: str
    overall_readiness_pct: float
    confidence_level: str  # high, medium, low
    total_attempts: int
    topics: list[TopicPerformance]
    weak_topics: list[str]
    strong_topics: list[str]
    average_accuracy_pct: float
    total_due_reviews: int


# ---------------------------------------------------------
# Exam Goals & Study Plan
# ---------------------------------------------------------
class CreateExamGoalRequest(BaseModel):
    name: str
    exam_date: datetime
    topic_ids: list[str] = Field(default_factory=list)
    target_score: float = Field(default=80.0, ge=0.0, le=100.0)


class ExamGoalResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    exam_date: datetime
    topic_ids: list[str]
    target_score: float
    days_remaining: int
    predicted_readiness_pct: float


class DailyTarget(BaseModel):
    day_number: int
    date: str
    focus_topic: str
    recommended_action: str
    estimated_time_minutes: int


class StudyPlanResponse(BaseModel):
    goal_id: str
    exam_name: str
    exam_date: datetime
    days_remaining: int
    current_readiness_pct: float
    target_score_pct: float
    daily_schedule: list[DailyTarget]


# ---------------------------------------------------------
# Question Reporting
# ---------------------------------------------------------
class QuestionReportRequest(BaseModel):
    reason: str = Field(description="wrong_key, not_in_material, unclear, typo")
    comment: str | None = None


class QuestionReportResponse(BaseModel):
    report_id: str
    question_id: str
    status: str
    message: str
