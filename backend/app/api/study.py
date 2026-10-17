"""Study Tools API router for summaries, flashcards, quizzes, and exports."""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import StudyItem, User, Workspace
from app.db.session import get_db
from app.study.export_service import ExportService
from app.study.flashcard_service import FlashcardService
from app.study.quiz_service import QuizService
from app.study.schemas import (
    FlashcardListResponse,
    FlashcardRequest,
    QuizListResponse,
    QuizRequest,
    StudyItemResponse,
    StudyItemsListResponse,
    SummaryRequest,
    SummaryResponse,
)
from app.study.summary_service import SummaryService

router = APIRouter(tags=["Study Tools"])


async def _verify_workspace_ownership(
    workspace_id: str, user_id: str, db: AsyncSession
) -> Workspace:
    """Helper to verify workspace exists and is owned by the user."""
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


@router.post("/workspaces/{workspace_id}/study/summary", response_model=SummaryResponse)
async def generate_summary(
    workspace_id: str,
    payload: SummaryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SummaryResponse:
    """Generates a hierarchical map-reduce grounded summary."""
    await _verify_workspace_ownership(workspace_id, current_user.id, db)
    service = SummaryService()
    return await service.generate_summary(
        workspace_id=workspace_id,
        user_id=current_user.id,
        db=db,
        document_ids=payload.document_ids,
        length=payload.length,
    )


@router.post("/workspaces/{workspace_id}/study/flashcards", response_model=FlashcardListResponse)
async def generate_flashcards(
    workspace_id: str,
    payload: FlashcardRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FlashcardListResponse:
    """Generates verified flashcards with exact source chunk IDs and quotes."""
    await _verify_workspace_ownership(workspace_id, current_user.id, db)
    service = FlashcardService()
    return await service.generate_flashcards(
        workspace_id=workspace_id,
        user_id=current_user.id,
        db=db,
        document_ids=payload.document_ids,
        count=payload.count,
        topic=payload.topic,
    )


@router.post("/workspaces/{workspace_id}/study/quiz", response_model=QuizListResponse)
async def generate_quiz(
    workspace_id: str,
    payload: QuizRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuizListResponse:
    """Generates multiple-choice quiz questions with grounded explanations."""
    await _verify_workspace_ownership(workspace_id, current_user.id, db)
    service = QuizService()
    return await service.generate_quiz(
        workspace_id=workspace_id,
        user_id=current_user.id,
        db=db,
        document_ids=payload.document_ids,
        count=payload.count,
        difficulty=payload.difficulty,
        topic=payload.topic,
    )


@router.get("/workspaces/{workspace_id}/study/items", response_model=StudyItemsListResponse)
async def list_study_items(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    type: Literal["summary", "flashcard", "quiz"] | None = Query(default=None),
) -> StudyItemsListResponse:
    """Lists saved study items in a workspace."""
    await _verify_workspace_ownership(workspace_id, current_user.id, db)

    stmt = select(StudyItem).where(StudyItem.workspace_id == workspace_id)
    if type:
        stmt = stmt.where(StudyItem.type == type)
    stmt = stmt.order_by(StudyItem.created_at.desc())

    items = (await db.execute(stmt)).scalars().all()
    results: list[StudyItemResponse] = []
    for it in items:
        try:
            payload_dict = json.loads(it.payload_json)
        except Exception:
            payload_dict = {}

        try:
            chunk_ids = json.loads(it.source_chunk_ids)
        except Exception:
            chunk_ids = []

        results.append(
            StudyItemResponse(
                id=it.id,
                workspace_id=it.workspace_id,
                type=it.type,
                payload=payload_dict,
                source_chunk_ids=chunk_ids,
                created_at=it.created_at,
            )
        )

    return StudyItemsListResponse(items=results, total=len(results))


@router.delete("/study/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_study_item(
    item_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Deletes a study item with multi-tenant ownership check."""
    stmt = (
        select(StudyItem)
        .join(Workspace, StudyItem.workspace_id == Workspace.id)
        .where(
            StudyItem.id == item_id,
            Workspace.user_id == current_user.id,
        )
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Study item not found or unauthorized",
        )

    await db.delete(item)
    await db.commit()


@router.get("/workspaces/{workspace_id}/study/export/anki")
async def export_anki(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Exports flashcards and quiz questions as Anki-compatible TSV."""
    await _verify_workspace_ownership(workspace_id, current_user.id, db)

    stmt = (
        select(StudyItem)
        .where(
            StudyItem.workspace_id == workspace_id,
            StudyItem.type.in_(["flashcard", "quiz"]),
        )
        .order_by(StudyItem.created_at.asc())
    )
    items = (await db.execute(stmt)).scalars().all()
    tsv_content = ExportService.export_anki_tsv(list(items))

    return Response(
        content=tsv_content,
        media_type="text/tab-separated-values; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="studymind_flashcards.tsv"'},
    )


@router.get("/workspaces/{workspace_id}/study/export/markdown")
async def export_study_guide_markdown(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Exports all study items as a formatted Markdown study guide."""
    ws = await _verify_workspace_ownership(workspace_id, current_user.id, db)

    stmt = (
        select(StudyItem)
        .where(StudyItem.workspace_id == workspace_id)
        .order_by(StudyItem.created_at.asc())
    )
    items = (await db.execute(stmt)).scalars().all()
    md_content = ExportService.export_study_guide_markdown(list(items), workspace_name=ws.name)

    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{ws.name}_study_guide.md"'},
    )
