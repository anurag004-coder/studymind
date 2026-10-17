"""Workspaces API router."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_storage_adapter, get_vector_store_adapter
from app.api.deps import get_current_user
from app.core.cache import app_cache
from app.db.models import Document, User, Workspace
from app.db.session import get_db

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceResponse(BaseModel):
    id: str
    user_id: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    """Creates a new workspace scoped to the authenticated user."""
    workspace = Workspace(
        user_id=current_user.id,
        name=payload.name.strip(),
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkspaceResponse]:
    """Lists all workspaces belonging to the authenticated user."""
    stmt = (
        select(Workspace)
        .where(Workspace.user_id == current_user.id)
        .order_by(Workspace.created_at.desc())
    )
    result = await db.execute(stmt)
    workspaces = result.scalars().all()
    return [WorkspaceResponse.model_validate(w) for w in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    """Gets a specific workspace, strictly isolated to the owner."""
    stmt = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return WorkspaceResponse.model_validate(workspace)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Deletes a workspace, purging all files, chunks, vectors, and cache entries."""
    stmt = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # 1. Find all documents in this workspace
    doc_stmt = select(Document).where(Document.workspace_id == workspace_id)
    docs = (await db.execute(doc_stmt)).scalars().all()

    storage = get_storage_adapter()
    vector_store = get_vector_store_adapter()

    # 2. Purge files from storage and vectors from Qdrant and lexical BM25
    from app.ingestion.lexical_index import lexical_index

    for doc in docs:
        try:
            await storage.delete_object(doc.storage_key)
        except Exception:
            pass
        await vector_store.delete_by_document(doc.id, current_user.id)
        lexical_index.delete_by_document(doc.id, current_user.id)

    # 3. Invalidate cache
    app_cache.invalidate_workspace(workspace_id)

    # 4. Cascade delete from DB
    await db.delete(workspace)
    await db.commit()
