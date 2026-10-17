"""Chat endpoints managing conversations, grounded message generation, and feedback."""

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.chat import Conversation, Feedback, Message
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db
from app.generation.composer import FinalChatResponse
from app.generation.pipeline import GroundedGenerationPipeline

router = APIRouter(tags=["Chat"])


class CreateConversationRequest(BaseModel):
    """Payload to initiate a new conversation."""

    title: str = Field(default="Study Chat", max_length=255)
    scope: dict[str, Any] | None = Field(
        default=None,
        description="Optional scope object e.g. {'document_ids': ['...']}",
    )


class SendMessageRequest(BaseModel):
    """Payload to ask a question within a conversation."""

    question: str = Field(..., min_length=1, description="Question asked by the student")
    strict_mode: bool = Field(
        default=False,
        description="If true, any unverified detail triggers complete abstention",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="Optional list of specific document IDs to restrict search to",
    )
    page: int | None = Field(
        default=None,
        description="Optional specific page number to query or summarize",
    )


class FeedbackRequest(BaseModel):
    """Payload to rate and review an assistant answer."""

    rating: Literal["up", "down"]
    reason: Literal["wrong", "not_in_source", "incomplete", "other"] | None = None
    comment: str | None = None


@router.post("/workspaces/{workspace_id}/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    workspace_id: str,
    payload: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Creates a new conversation scoped to user and workspace."""
    # Enforce workspace ownership
    ws_stmt = (
        select(Workspace)
        .where(Workspace.id == workspace_id)
        .where(Workspace.user_id == current_user.id)
    )
    ws = (await db.execute(ws_stmt)).scalar_one_or_none()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or unauthorized",
        )

    scope_str = json.dumps(payload.scope) if payload.scope else None
    conv = Conversation(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        user_id=current_user.id,
        title=payload.title,
        scope_json=scope_str,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return {
        "id": conv.id,
        "workspace_id": conv.workspace_id,
        "title": conv.title,
        "scope": payload.scope,
        "created_at": conv.created_at.isoformat(),
    }


@router.get("/workspaces/{workspace_id}/conversations")
async def list_conversations(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Lists all conversations within a workspace belonging to user."""
    ws_stmt = (
        select(Workspace)
        .where(Workspace.id == workspace_id)
        .where(Workspace.user_id == current_user.id)
    )
    ws = (await db.execute(ws_stmt)).scalar_one_or_none()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or unauthorized",
        )

    stmt = (
        select(Conversation)
        .where(Conversation.workspace_id == workspace_id)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    convs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": c.id,
            "workspace_id": c.workspace_id,
            "title": c.title,
            "scope": json.loads(c.scope_json) if c.scope_json else None,
            "created_at": c.created_at.isoformat(),
        }
        for c in convs
    ]


@router.post("/conversations/{conversation_id}/messages", response_model=FinalChatResponse)
async def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FinalChatResponse:
    """Answers a question strictly using user's material and verified citations."""
    # 1. Enforce conversation ownership & isolation
    conv_stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == current_user.id)
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or unauthorized",
        )

    # 2. Record student's user message
    user_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        role="user",
        content=payload.question,
    )
    db.add(user_msg)
    await db.commit()

    # 3. Retrieve recent chat history for reference resolution
    hist_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    all_msgs = (await db.execute(hist_stmt)).scalars().all()
    chat_history: list[dict[str, str]] = [
        {"role": m.role, "content": m.content}
        for m in all_msgs[:-1]  # Exclude current question
    ]

    # 4. Extract document scope if specified
    doc_ids = payload.document_ids
    if not doc_ids and conv.scope_json:
        try:
            scope_dict = json.loads(conv.scope_json)
            doc_ids = scope_dict.get("document_ids")
        except Exception:
            doc_ids = None

    # 5. Execute 5-layer Grounded Generation Pipeline
    pipeline = GroundedGenerationPipeline()
    response = await pipeline.answer_question(
        question=payload.question,
        user_id=current_user.id,
        workspace_id=conv.workspace_id,
        document_ids=doc_ids,
        chat_history=chat_history,
        strict_mode=payload.strict_mode,
        page=payload.page,
    )

    # 6. Persist assistant message in DB
    ans_text = "\n".join(s.text for s in response.answer)
    assistant_msg = Message(
        id=response.message_id,
        conversation_id=conversation_id,
        role="assistant",
        content=ans_text,
        citations_json=json.dumps([c.model_dump() for c in response.citations]),
        verification_json=json.dumps(
            {
                "confidence": response.confidence,
                "dropped_claims": response.dropped_claims,
                "missing_info": response.missing_info,
            }
        ),
        abstained=response.abstained,
    )
    db.add(assistant_msg)
    await db.commit()

    return response


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieves all messages in a conversation."""
    conv_stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == current_user.id)
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or unauthorized",
        )

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = (await db.execute(stmt)).scalars().all()

    results: list[dict[str, Any]] = []
    for m in messages:
        citations = json.loads(m.citations_json) if m.citations_json else []
        verification = json.loads(m.verification_json) if m.verification_json else {}
        results.append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "citations": citations,
                "verification": verification,
                "abstained": m.abstained,
                "created_at": m.created_at.isoformat(),
            }
        )

    return results


@router.post("/messages/{message_id}/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    message_id: str,
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Records user feedback on an answer."""
    # Verify message exists and user owns the enclosing conversation
    msg_stmt = (
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == message_id)
        .where(Conversation.user_id == current_user.id)
    )
    msg = (await db.execute(msg_stmt)).scalar_one_or_none()
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found or unauthorized",
        )

    fb = Feedback(
        id=str(uuid.uuid4()),
        message_id=message_id,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
    )
    db.add(fb)
    await db.commit()

    return {"status": "success", "id": fb.id}
