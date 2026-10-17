"""Documents API router for uploading, listing, viewing, and deleting documents."""

import hashlib
import io
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from PIL import Image, ImageDraw
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_storage_adapter, get_vector_store_adapter
from app.api.deps import get_current_user
from app.core.cache import app_cache
from app.core.file_scanner import FileSecurityScanner
from app.db.models import Chunk, Document, Job, Page, User, Workspace
from app.db.models.quiz import Question
from app.db.session import get_db

router = APIRouter(tags=["Documents"])

# Allowed extensions per PRD §4
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
}


class DocumentResponse(BaseModel):
    id: str
    workspace_id: str
    filename: str
    mime: str
    sha256: str
    pages: int
    status: str
    ocr_quality: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    filename: str
    pages: int
    ocr_quality: str | None


class DocumentDetailResponse(BaseModel):
    id: str
    workspace_id: str
    filename: str
    mime: str
    pages: int
    status: str
    ocr_quality: str | None
    error: str | None
    created_at: datetime
    current_stage: str | None
    progress: float | None


async def _background_ingest(document_id: str) -> None:
    from app.core.logging import logger
    from app.db.session import AsyncSessionLocal
    from app.ingestion.pipeline import IngestionPipeline

    try:
        async with AsyncSessionLocal() as session:
            pipeline = IngestionPipeline()
            await pipeline.ingest_document(document_id=document_id, db=session)
    except Exception as exc:
        logger.warning("Background ingestion failed for %s: %s", document_id, exc)


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    workspace_id: str,
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> DocumentUploadResponse:
    """Uploads a study material file (PDF, image, docx, pptx, txt)."""
    # 1. Verify workspace ownership
    stmt = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.user_id == current_user.id,
    )
    workspace = (await db.execute(stmt)).scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # 2. Validate filename and extension
    filename = file.filename or "uploaded_file"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed_list = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {allowed_list}",
        )

    # 3. Read and check file size & security scan
    file_bytes = await file.read()
    # Sniff magic bytes, disallow masquerading executables, verify zip bombs & malware
    FileSecurityScanner.scan_and_validate(filename, file_bytes, file.content_type or "")

    # 4. Compute SHA-256 for integrity and deduplication
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # 5. Store file using Storage Adapter
    storage = get_storage_adapter()
    mime = file.content_type or "application/octet-stream"
    temp_doc = Document(
        workspace_id=workspace_id,
        user_id=current_user.id,
        filename=filename,
        mime=mime,
        sha256=sha256_hash,
        pages=0,
        status="queued",
        storage_key="placeholder",
    )
    db.add(temp_doc)
    await db.flush()  # Generates temp_doc.id

    storage_key = f"users/{current_user.id}/workspaces/{workspace_id}/{temp_doc.id}/{filename}"
    await storage.put_object(storage_key, file_bytes, mime)
    temp_doc.storage_key = storage_key

    # 6. Create initial tracking job row
    job = Job(
        document_id=temp_doc.id,
        stage="upload",
        status="queued",
        progress=0.0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(temp_doc)

    background_tasks.add_task(_background_ingest, temp_doc.id)

    return DocumentUploadResponse(
        document_id=temp_doc.id,
        status=temp_doc.status,
        filename=temp_doc.filename,
        pages=temp_doc.pages,
        ocr_quality=temp_doc.ocr_quality,
    )


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_workspace_documents(
    workspace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DocumentResponse]:
    """Lists all documents within a workspace owned by the current user."""
    # Verify workspace
    ws_stmt = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.user_id == current_user.id,
    )
    if not (await db.execute(ws_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    stmt = (
        select(Document)
        .where(
            Document.workspace_id == workspace_id,
            Document.user_id == current_user.id,
        )
        .order_by(Document.created_at.desc())
    )
    docs = (await db.execute(stmt)).scalars().all()
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentDetailResponse:
    """Retrieves document details and ingestion progress."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == current_user.id,
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Get latest job
    job_stmt = select(Job).where(Job.document_id == document_id).order_by(Job.updated_at.desc())
    latest_job = (await db.execute(job_stmt)).scalars().first()

    return DocumentDetailResponse(
        id=doc.id,
        workspace_id=doc.workspace_id,
        filename=doc.filename,
        mime=doc.mime,
        pages=doc.pages,
        status=doc.status,
        ocr_quality=doc.ocr_quality,
        error=doc.error,
        created_at=doc.created_at,
        current_stage=latest_job.stage if latest_job else None,
        progress=latest_job.progress if latest_job else None,
    )


@router.get("/documents/{document_id}/events")
async def document_progress_events(
    document_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Streams server-sent events (SSE) for document ingestion progress."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == current_user.id,
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    job_stmt = select(Job).where(Job.document_id == document_id).order_by(Job.updated_at.desc())
    latest_job = (await db.execute(job_stmt)).scalars().first()
    stage = latest_job.stage if latest_job else "queued"
    progress = latest_job.progress if latest_job else 0.0

    sse_data = f'data: {{"status": "{doc.status}", "stage": "{stage}", "progress": {progress}}}\n\n'
    return Response(content=sse_data, media_type="text/event-stream")


@router.get("/documents/{document_id}/pages/{page_no}/image")
async def get_page_image(
    document_id: str,
    page_no: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Returns rendered image for a specific document page."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == current_user.id,
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # 1. Check for Page record and pre-rendered image in storage
    page_stmt = select(Page).where(
        Page.document_id == document_id,
        Page.page_no == page_no,
    )
    page_record = (await db.execute(page_stmt)).scalars().first()
    storage = get_storage_adapter()

    if page_record and page_record.image_key:
        try:
            content = await storage.get_object(page_record.image_key)
            return Response(content=content, media_type="image/png")
        except FileNotFoundError:
            pass

    # 2. Fallback: if document is image, return original image bytes
    if doc.mime.startswith("image/"):
        try:
            content = await storage.get_object(doc.storage_key)
            return Response(content=content, media_type=doc.mime)
        except FileNotFoundError:
            pass

    # 3. Fallback: if document is PDF, render page on-the-fly with PyMuPDF
    if doc.mime == "application/pdf":
        try:
            doc_bytes = await storage.get_object(doc.storage_key)
            import fitz  # type: ignore[import-untyped,import-not-found]

            pdf_doc = fitz.open(stream=doc_bytes, filetype="pdf")
            if 1 <= page_no <= len(pdf_doc):
                pdf_page = pdf_doc[page_no - 1]
                pix = pdf_page.get_pixmap(dpi=150)
                png_bytes = pix.tobytes("png")
                # Cache it in storage
                cache_key = (
                    f"users/{doc.user_id}/workspaces/{doc.workspace_id}/"
                    f"{doc.id}/pages/{page_no}.png"
                )
                await storage.put_object(cache_key, png_bytes, "image/png")
                if page_record:
                    page_record.image_key = cache_key
                    await db.commit()
                return Response(content=png_bytes, media_type="image/png")
        except Exception:
            pass

    # 3. Fallback: if document is image itself and page_no == 1
    if doc.mime.startswith("image/") and page_no == 1:
        try:
            content = await storage.get_object(doc.storage_key)
            return Response(content=content, media_type=doc.mime)
        except Exception:
            pass

    # 4. Fallback: render a clean document canvas sheet for text/docx/pptx pages
    img = Image.new("RGB", (800, 1050), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 790, 1040], outline=(203, 213, 225), width=2)
    draw.rectangle([10, 10, 790, 60], fill=(241, 245, 249))
    draw.text((30, 25), f"{doc.filename} — Page {page_no}", fill=(30, 41, 59))
    draw.line([(10, 60), (790, 60)], fill=(203, 213, 225), width=2)

    chunk_stmt = select(Chunk).where(
        Chunk.document_id == document_id,
        Chunk.page_start <= page_no,
        Chunk.page_end >= page_no,
    )
    chunks = (await db.execute(chunk_stmt)).scalars().all()
    y = 80
    if chunks:
        for chunk in chunks:
            if y > 980:
                break
            for line in chunk.text.split("\n"):
                if y > 980:
                    break
                draw.text((40, y), line[:85], fill=(51, 65, 85))
                y += 24
            y += 16
    else:
        draw.text((40, y), f"Page {page_no} content preview", fill=(100, 116, 139))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Streams original document content back to user."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == current_user.id,
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    storage = get_storage_adapter()
    try:
        content = await storage.get_object(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored document file not found",
        ) from None

    return Response(
        content=content,
        media_type=doc.mime,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Purges a document, its file in storage, and its vectors."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == current_user.id,
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # 1. Purge from storage
    storage = get_storage_adapter()
    try:
        await storage.delete_object(doc.storage_key)
    except Exception:
        pass

    # 2. Purge from vector store
    vector_store = get_vector_store_adapter()
    await vector_store.delete_by_document(document_id, current_user.id)

    # 3. Purge derived questions referencing this document
    del_q_stmt = select(Question).where(
        Question.workspace_id == doc.workspace_id,
        Question.document_ids.like(f"%{document_id}%"),
    )
    matching_qs = (await db.execute(del_q_stmt)).scalars().all()
    for mq in matching_qs:
        await db.delete(mq)

    # 4. Invalidate workspace cache
    app_cache.invalidate_workspace(doc.workspace_id)

    # 5. Delete from DB (cascades pages, chunks, jobs)
    await db.delete(doc)
    await db.commit()


class ReprocessRequest(BaseModel):
    force_vision_ocr: bool = False


@router.post("/documents/{document_id}/reprocess")
async def reprocess_document(
    document_id: str,
    payload: ReprocessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentUploadResponse:
    """Reprocesses a document, optionally forcing Vision-LLM OCR."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.user_id == current_user.id,
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    from app.ingestion.pipeline import IngestionPipeline

    pipeline = IngestionPipeline()
    reprocessed = await pipeline.ingest_document(
        document_id=doc.id, db=db, force_vision_ocr=payload.force_vision_ocr
    )

    return DocumentUploadResponse(
        document_id=reprocessed.id,
        status=reprocessed.status,
        filename=reprocessed.filename,
        pages=reprocessed.pages,
        ocr_quality=reprocessed.ocr_quality,
    )
