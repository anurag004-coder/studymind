"""Authentication endpoints (register, login, me)."""

import secrets
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.models import User, Workspace
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password at least 6 characters")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class GuestResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    workspace_id: str
    is_guest: bool = True


@router.post("/guest", response_model=GuestResponse)
async def create_guest_session(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GuestResponse:
    """Creates an anonymous guest user and default workspace without requiring registration."""
    guest_tag = uuid.uuid4().hex[:8]
    guest_email = f"guest_{guest_tag}@studymind.local"
    guest_user = User(
        email=guest_email,
        password_hash=get_password_hash(secrets.token_hex(16)),
    )
    db.add(guest_user)
    await db.flush()

    workspace = Workspace(
        user_id=guest_user.id,
        name="Guest Study Workspace",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(guest_user)
    await db.refresh(workspace)

    token = create_access_token(subject=guest_user.id)
    return GuestResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(guest_user),
        workspace_id=workspace.id,
        is_guest=True,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Registers a new student user."""
    # Check if email is already registered
    stmt = select(User).where(User.email == payload.email.lower())
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=payload.email.lower(),
        password_hash=get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticates a user and issues a JWT access token."""
    stmt = select(User).where(User.email == payload.email.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(subject=user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Returns the currently authenticated user."""
    return UserResponse.model_validate(current_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """GDPR/DPDP-compliant full user account and data purge.

    Purges all user documents from storage, vector store, and database.
    """
    from app.adapters import get_storage_adapter, get_vector_store_adapter
    from app.core.cache import app_cache
    from app.db.models import Document, Workspace

    # 1. Find all documents belonging to user
    doc_stmt = select(Document).where(Document.user_id == current_user.id)
    docs = (await db.execute(doc_stmt)).scalars().all()

    storage = get_storage_adapter()
    for doc in docs:
        try:
            await storage.delete_object(doc.storage_key)
        except Exception:
            pass

    # 2. Purge all vectors for this user
    vector_store = get_vector_store_adapter()
    await vector_store.delete_by_user(current_user.id)

    # 3. Find and invalidate all user workspace caches
    ws_stmt = select(Workspace).where(Workspace.user_id == current_user.id)
    workspaces = (await db.execute(ws_stmt)).scalars().all()
    for ws in workspaces:
        app_cache.invalidate_workspace(ws.id)

    # 4. Cascade delete user and all associated records from DB
    await db.delete(current_user)
    await db.commit()
