"""Pydantic schemas for study tools (summaries, flashcards, quizzes, exports)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SummaryRequest(BaseModel):
    """Payload to request a grounded summary."""

    document_ids: list[str] | None = Field(
        default=None,
        description="Optional list of document IDs to scope the summary",
    )
    length: Literal["short", "medium", "detailed"] = Field(
        default="medium",
        description="Target length of the summary",
    )


class KeyTakeawayItem(BaseModel):
    """Single key takeaway with source grounding."""

    point: str
    source_chunk_id: str
    quote: str
    document_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None


class RawMapSummary(BaseModel):
    """Map-step summary of a document section."""

    section_id: str
    summary_bullets: list[str]
    source_chunk_id: str
    quote: str


class RawMapOutput(BaseModel):
    """LLM output for Map step."""

    sections: list[RawMapSummary]


class RawReduceOutput(BaseModel):
    """LLM output for Reduce step."""

    title: str
    overview: str
    takeaways: list[KeyTakeawayItem]


class ImportantAreaItem(BaseModel):
    """An important concept/area covered in the document with page reference."""

    area_title: str
    summary: str
    page: int = 1
    document_id: str | None = None
    quote: str = ""
    bbox: list[float] | None = None


class ReferencedPageItem(BaseModel):
    """Page reference mapping for fast jumping from summary to exact source viewer."""

    page: int
    document_id: str
    title: str = ""


class SummaryResponse(BaseModel):
    """Response containing the generated grounded summary."""

    id: str
    workspace_id: str
    title: str
    summary: str
    key_takeaways: list[KeyTakeawayItem]
    important_areas: list[ImportantAreaItem] = Field(default_factory=list)
    referenced_pages: list[ReferencedPageItem] = Field(default_factory=list)
    source_chunk_ids: list[str]
    created_at: datetime


class FlashcardRequest(BaseModel):
    """Payload to generate grounded flashcards."""

    document_ids: list[str] | None = None
    count: int = Field(default=5, ge=1, le=30)
    topic: str | None = None


class RawFlashcardItem(BaseModel):
    """Raw flashcard emitted by LLM."""

    question: str
    answer: str
    source_chunk_id: str
    quote: str


class RawFlashcardsOutput(BaseModel):
    """LLM output containing list of flashcards."""

    flashcards: list[RawFlashcardItem]


class FlashcardItem(BaseModel):
    """Validated student-facing flashcard."""

    id: str
    question: str
    answer: str
    source_chunk_id: str
    quote: str
    document_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None


class FlashcardListResponse(BaseModel):
    """List of generated and validated flashcards."""

    flashcards: list[FlashcardItem]
    saved_count: int


class QuizRequest(BaseModel):
    """Payload to generate grounded multiple-choice questions."""

    document_ids: list[str] | None = None
    count: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    topic: str | None = None


class RawQuizQuestion(BaseModel):
    """Raw quiz question emitted by LLM."""

    stem: str
    options: list[str]
    correct_answer_index: int
    explanation: str
    source_chunk_id: str
    quote: str


class RawQuizOutput(BaseModel):
    """LLM output containing list of quiz questions."""

    questions: list[RawQuizQuestion]


class QuizQuestionItem(BaseModel):
    """Validated quiz question with grounded explanation."""

    id: str
    stem: str
    options: list[str]
    correct_answer_index: int
    explanation: str
    source_chunk_id: str
    quote: str
    difficulty: str
    document_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None


class QuizListResponse(BaseModel):
    """List of validated grounded quiz questions."""

    questions: list[QuizQuestionItem]
    saved_count: int


class StudyItemResponse(BaseModel):
    """Persisted study item response."""

    id: str
    workspace_id: str
    type: str
    payload: dict[str, Any]
    source_chunk_ids: list[str]
    created_at: datetime


class StudyItemsListResponse(BaseModel):
    """List of saved study items."""

    items: list[StudyItemResponse]
    total: int
