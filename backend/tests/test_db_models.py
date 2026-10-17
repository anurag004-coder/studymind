"""Tests for SQLAlchemy database models."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Attempt,
    Chunk,
    Conversation,
    Document,
    Feedback,
    Message,
    Page,
    Question,
    QuizSession,
    Topic,
    User,
    Workspace,
)


@pytest.mark.asyncio
async def test_create_user_and_workspace(db_session: AsyncSession) -> None:
    user = User(email="student@example.com", password_hash="hashed_pw")
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(user_id=user.id, name="Biology 101")
    db_session.add(workspace)
    await db_session.commit()

    # Query back
    stmt = select(Workspace).where(Workspace.id == workspace.id)
    res = await db_session.execute(stmt)
    saved_ws = res.scalar_one()

    assert saved_ws.name == "Biology 101"
    assert saved_ws.user_id == user.id


@pytest.mark.asyncio
async def test_document_page_and_chunks(db_session: AsyncSession) -> None:
    user = User(email="learner@example.com", password_hash="hashed_pw")
    db_session.add(user)
    await db_session.flush()

    ws = Workspace(user_id=user.id, name="Physics")
    db_session.add(ws)
    await db_session.flush()

    doc = Document(
        workspace_id=ws.id,
        user_id=user.id,
        filename="notes.pdf",
        mime="application/pdf",
        sha256="dummy_hash_12345",
        pages=2,
        status="ready",
        storage_key="docs/notes.pdf",
    )
    db_session.add(doc)
    await db_session.flush()

    page = Page(document_id=doc.id, page_no=1, has_text_layer=True, ocr_confidence=0.95)
    chunk = Chunk(
        document_id=doc.id,
        page_start=1,
        page_end=1,
        text="Newton's second law is F = ma.",
        token_count=10,
        source_type="text",
        chunk_index=0,
        embedding_model="BAAI/bge-m3",
    )
    db_session.add_all([page, chunk])
    await db_session.commit()

    stmt = select(Chunk).where(Chunk.document_id == doc.id)
    chunks_res = await db_session.execute(stmt)
    all_chunks = chunks_res.scalars().all()
    assert len(all_chunks) == 1
    assert "F = ma" in all_chunks[0].text


@pytest.mark.asyncio
async def test_conversation_and_messages(db_session: AsyncSession) -> None:
    user = User(email="talker@example.com", password_hash="hashed")
    db_session.add(user)
    await db_session.flush()

    ws = Workspace(user_id=user.id, name="General")
    db_session.add(ws)
    await db_session.flush()

    conv = Conversation(workspace_id=ws.id, user_id=user.id, title="Test Chat")
    db_session.add(conv)
    await db_session.flush()

    msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content="Here is the cited answer [1].",
        citations_json='[{"n": 1, "quote": "exact quote"}]',
        abstained=False,
    )
    db_session.add(msg)
    await db_session.flush()

    feedback = Feedback(message_id=msg.id, rating="up")
    db_session.add(feedback)
    await db_session.commit()

    stmt = select(Message).where(Message.conversation_id == conv.id)
    saved_msg = (await db_session.execute(stmt)).scalar_one()
    assert saved_msg.abstained is False


@pytest.mark.asyncio
async def test_quiz_models(db_session: AsyncSession) -> None:
    user = User(email="exam@example.com", password_hash="hashed")
    db_session.add(user)
    await db_session.flush()

    ws = Workspace(user_id=user.id, name="Chemistry")
    db_session.add(ws)
    await db_session.flush()

    topic = Topic(workspace_id=ws.id, name="Organic Chemistry")
    db_session.add(topic)
    await db_session.flush()

    question = Question(
        workspace_id=ws.id,
        topic_id=topic.id,
        type="mcq",
        stem="What is the functional group of alcohols?",
        options_json='["-OH", "-COOH", "-NH2", "-CHO"]',
        answer_key_json='{"answer": "-OH"}',
        explanation="Alcohols have an -OH hydroxyl group.",
        source_chunk_ids='["c1"]',
        source_quotes='["Alcohols contain a hydroxyl (-OH) group."]',
        prompt_version="v1",
        status="active",
    )
    db_session.add(question)
    await db_session.flush()

    session = QuizSession(
        user_id=user.id,
        workspace_id=ws.id,
        mode="quick",
        config_json="{}",
    )
    db_session.add(session)
    await db_session.flush()

    attempt = Attempt(
        session_id=session.id,
        question_id=question.id,
        user_answer_json='{"answer": "-OH"}',
        score=1.0,
        graded_by="auto",
    )
    db_session.add(attempt)
    await db_session.commit()

    stmt = select(Attempt).where(Attempt.session_id == session.id)
    saved_attempt = (await db_session.execute(stmt)).scalar_one()
    assert saved_attempt.score == 1.0
