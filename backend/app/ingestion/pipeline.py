"""End-to-end ingestion pipeline coordinator."""

import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import (
    get_embedding_adapter,
    get_storage_adapter,
    get_vector_store_adapter,
)
from app.core.logging import logger
from app.db.models import Chunk, Document, Job, Page
from app.ingestion.chunker import StructureAwareChunker
from app.ingestion.cleaner import TextCleaner
from app.ingestion.lexical_index import lexical_index
from app.ingestion.router import DocumentParserRouter


class IngestionPipeline:
    """Asynchronous ingestion pipeline: parse -> clean -> chunk -> embed -> index."""

    def __init__(self) -> None:
        self.chunker = StructureAwareChunker()
        self.storage = get_storage_adapter()
        self.vector_store = get_vector_store_adapter()
        self.embedder = get_embedding_adapter()
        self.router = DocumentParserRouter()

    async def ingest_document(
        self,
        document_id: str,
        db: AsyncSession,
        force_vision_ocr: bool = False,
    ) -> Document:
        """Runs the complete ingestion pipeline for a queued document."""
        # 1. Fetch document record
        stmt = select(Document).where(Document.id == document_id)
        doc = (await db.execute(stmt)).scalar_one_or_none()
        if not doc:
            raise ValueError(f"Document not found: {document_id}")

        # Update initial job
        job_stmt = select(Job).where(Job.document_id == document_id).order_by(Job.updated_at.desc())
        job = (await db.execute(job_stmt)).scalars().first()

        async def update_progress(stage: str, progress: float) -> None:
            if job:
                job.stage = stage
                job.status = "processing"
                job.progress = progress
                await db.commit()

        try:
            # 2. Retrieve file content
            await update_progress("parsing", 0.1)
            file_bytes = await self.storage.get_object(doc.storage_key)

            # 3. Route to layout parser or OCR engine
            raw_pages = await self.router.parse_document(
                file_bytes=file_bytes,
                filename=doc.filename,
                mime=doc.mime,
                force_vision_ocr=force_vision_ocr,
            )
            if not raw_pages:
                raise ValueError("No pages extracted from document")

            # 4. Clean text and strip repeated headers/footers
            await update_progress("cleaning", 0.3)
            cleaned_pages = TextCleaner.detect_and_strip_repeated_headers_footers(raw_pages)

            # 5. Clean up previous pages and chunks for idempotency
            await db.execute(delete(Page).where(Page.document_id == doc.id))
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            await db.flush()

            # Store Page records and image previews
            doc.pages = len(cleaned_pages)
            for page in cleaned_pages:
                image_key: str | None = None
                if page.image_bytes:
                    image_key = (
                        f"users/{doc.user_id}/workspaces/{doc.workspace_id}/"
                        f"{doc.id}/pages/{page.page_no}.png"
                    )
                    await self.storage.put_object(image_key, page.image_bytes, "image/png")

                page_row = Page(
                    document_id=doc.id,
                    page_no=page.page_no,
                    image_key=image_key,
                    has_text_layer=page.has_text_layer,
                    ocr_confidence=page.ocr_confidence or 1.0,
                )
                db.add(page_row)

            await db.flush()

            # 6. Structure-aware chunking
            await update_progress("chunking", 0.5)
            chunks = self.chunker.chunk_pages(
                pages=cleaned_pages,
                document_id=doc.id,
                workspace_id=doc.workspace_id,
                user_id=doc.user_id,
                embedding_model=self.embedder.__class__.__name__,
            )

            if not chunks:
                logger.warning(f"No text chunks created for document {doc.id}")

            # 7. Persist chunks in Database
            chunk_payloads: list[dict] = []
            for c in chunks:
                chunk_row = Chunk(
                    id=c.chunk_id,
                    document_id=doc.id,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    section_path=c.section_path,
                    text=c.text,
                    token_count=c.token_count,
                    source_type=c.source_type,
                    bbox_json=json.dumps(c.bbox_list),
                    parent_id=c.parent_id,
                    chunk_index=c.chunk_index,
                    embedding_model=c.embedding_model,
                )
                db.add(chunk_row)

                chunk_payloads.append(
                    {
                        "chunk_id": c.chunk_id,
                        "document_id": doc.id,
                        "workspace_id": doc.workspace_id,
                        "user_id": doc.user_id,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "section_path": c.section_path,
                        "text": c.text,
                        "source_type": c.source_type,
                        "bbox_list": c.bbox_list,
                    }
                )

            await db.flush()

            # 8. Embeddings & Indexing into Qdrant and BM25
            await update_progress("indexing", 0.7)
            if chunks:
                texts = [c.text for c in chunks]
                dense_vectors = await self.embedder.embed_texts(texts)

                # Qdrant Dense Indexing
                await self.vector_store.upsert(chunks=chunk_payloads, vectors=dense_vectors)

                # Lexical BM25 Indexing
                lexical_index.index_chunks(chunk_payloads)

            # 9. Mark Document & Job completed
            doc.status = "ready"
            confidences = [p.ocr_confidence for p in cleaned_pages if p.ocr_confidence is not None]
            min_conf = min(confidences) if confidences else 1.0
            if min_conf >= 0.85:
                doc.ocr_quality = "good"
            elif min_conf >= 0.65:
                doc.ocr_quality = "medium"
            else:
                doc.ocr_quality = "low"

            if job:
                job.stage = "completed"
                job.status = "completed"
                job.progress = 1.0

            await db.commit()
            await db.refresh(doc)
            return doc

        except Exception as e:
            logger.exception(f"Ingestion failed for document {document_id}: {e}")
            doc.status = "error"
            doc.error = str(e)
            if job:
                job.status = "failed"
                job.error = str(e)
            await db.commit()
            raise
