"""Workspace model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="workspaces")  # type: ignore[name-defined] # noqa: F821
    documents: Mapped[list["Document"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Document", back_populates="workspace", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Conversation", back_populates="workspace", cascade="all, delete-orphan"
    )
    study_items: Mapped[list["StudyItem"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "StudyItem", back_populates="workspace", cascade="all, delete-orphan"
    )
    topics: Mapped[list["Topic"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Topic", back_populates="workspace", cascade="all, delete-orphan"
    )
