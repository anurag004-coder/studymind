"""Quiz and Exam-Prep Engine ORM models per QUIZ_ASSESSMENT.md §7."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON list
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="topics")  # type: ignore[name-defined] # noqa: F821
    questions: Mapped[list["Question"]] = relationship("Question", back_populates="topic")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON list
    topic_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="SET NULL"), index=True, nullable=True
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # mcq, multi_select, true_false, fill_blank, short_answer, long_answer, numeric
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)  # 1-5
    bloom: Mapped[str] = mapped_column(
        String(50), default="remember", nullable=False
    )  # remember, understand, apply, analyze
    marks: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list for MCQ
    answer_key_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    rubric_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON for written questions
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    source_quotes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    validation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str] = mapped_column(
        String(50), default="question_gen_v1", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="active", index=True, nullable=False
    )  # active, flagged, retired
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    topic: Mapped["Topic | None"] = relationship("Topic", back_populates="questions")
    attempts: Mapped[list["Attempt"]] = relationship(
        "Attempt", back_populates="question", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_questions_ws_topic_diff", "workspace_id", "topic_id", "difficulty"),
    )


class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # quick, mock, drill, spaced, adaptive, countdown
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    attempts: Mapped[list["Attempt"]] = relationship(
        "Attempt", back_populates="session", cascade="all, delete-orphan"
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quiz_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_answer_json: Mapped[str] = mapped_column(Text, nullable=False)
    grade_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_s: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5 self rating
    graded_by: Mapped[str] = mapped_column(
        String(20), default="auto", nullable=False
    )  # auto, llm, self
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    session: Mapped["QuizSession"] = relationship("QuizSession", back_populates="attempts")
    question: Mapped["Question"] = relationship("Question", back_populates="attempts")


class TopicMastery(Base):
    __tablename__ = "topic_mastery"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )
    mastery: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_topic_mastery_user_topic", "user_id", "topic_id", unique=True),)


class ReviewSchedule(Base):
    __tablename__ = "review_schedule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    stability: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    ease: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_result: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (Index("ix_review_schedule_user_due", "user_id", "due_at"),)


class ExamGoal(Base):
    __tablename__ = "exam_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exam_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    topic_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON list
    target_score: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)


class QuestionReport(Base):
    __tablename__ = "question_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # wrong_key, not_in_material, unclear, typo
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
