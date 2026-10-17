"""Study tools item model (flashcards, summaries, quick quizzes)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StudyItem(Base):
    __tablename__ = "study_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # flashcard, quiz, summary
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of chunk IDs
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="study_items")  # type: ignore[name-defined] # noqa: F821
