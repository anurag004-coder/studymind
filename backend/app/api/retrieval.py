"""Retrieval search endpoints strictly scoped to authenticated user and workspace."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User, Workspace
from app.db.session import get_db
from app.retrieval.service import RetrievalResult, RetrievalService

router = APIRouter(tags=["Retrieval"])


class SearchRequest(BaseModel):
    """Payload for workspace hybrid search."""

    query: str = Field(..., min_length=1, description="Search question or query")
    document_ids: list[str] | None = Field(
        default=None, description="Optional list of document IDs to scope search"
    )
    chat_history: list[dict[str, str]] | None = Field(
        default=None, description="Optional chat history for pronoun resolution"
    )
    top_k: int = Field(default=6, ge=1, le=30, description="Number of reranked chunks to return")
    custom_threshold: float | None = Field(
        default=None, description="Optional custom minimum relevance score threshold"
    )


@router.post("/workspaces/{workspace_id}/search", response_model=RetrievalResult)
@router.post("/workspaces/{workspace_id}/retrieval", response_model=RetrievalResult)
async def search_workspace(
    workspace_id: str,
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RetrievalResult:
    """Executes hybrid dense+BM25 retrieval, RRF fusion, cross-encoder rerank, and gate."""
    # 1. Enforce workspace ownership & multi-tenant isolation
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

    # 2. Invoke retrieval service with strict user_id isolation
    retrieval_service = RetrievalService()
    result = await retrieval_service.retrieve(
        query=payload.query,
        user_id=current_user.id,
        workspace_id=workspace_id,
        document_ids=payload.document_ids,
        chat_history=payload.chat_history,
        top_k=payload.top_k,
        custom_threshold=payload.custom_threshold,
    )
    return result
