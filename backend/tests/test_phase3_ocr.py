"""Tests for Phase 3: OCR, Image Preprocessing, Office Formats (DOCX, PPTX, TXT),
and CER evaluation."""

import io

import cv2
import docx
import numpy as np
import pymupdf
import pytest
from pptx import Presentation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_storage_adapter, get_vector_store_adapter
from app.db.models import Chunk, Document, User, Workspace
from app.ingestion.cer import calculate_cer, calculate_wer
from app.ingestion.office_parser import OfficeParser
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.preprocessor import ImagePreprocessor
from app.ingestion.vision_ocr import VisionOCR


def create_sample_docx() -> bytes:
    """Generates an in-memory Word document with headings and a table."""
    doc = docx.Document()
    doc.add_heading("Cell Biology Summary", level=1)
    doc.add_paragraph("Mitochondria generate adenosine triphosphate through respiration.")

    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Organelle"
    table.cell(0, 1).text = "Function"
    table.cell(1, 0).text = "Chloroplast"
    table.cell(1, 1).text = "Photosynthesis"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def create_sample_pptx() -> bytes:
    """Generates an in-memory PowerPoint presentation."""
    prs = Presentation()
    slide_layout = prs.slide_layouts[0]  # Title slide
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    subtitle = slide.placeholders[1]
    if title:
        title.text = "Lecture 1: Genetics"
    if subtitle:
        subtitle.text = "DNA structure and replication mechanisms"

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def create_scanned_image(text: str = "Handwritten student exam notes") -> bytes:
    """Creates a synthetic photo/scan image."""
    img = np.full((300, 600, 3), 255, dtype=np.uint8)
    cv2.putText(img, text, (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2)
    _success, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


def create_scanned_pdf_image_only() -> bytes:
    """Creates a PDF containing an image page without any underlying text layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    # Insert an image onto the page so there is no text layer
    img_bytes = create_scanned_image("Scanned textbook excerpt on quantum mechanics")
    rect = pymupdf.Rect(50, 50, 550, 350)
    page.insert_image(rect, stream=img_bytes)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_cer_and_wer_metrics() -> None:
    # 1. Exact match CER should be 0.0
    ref = "The quick brown fox jumps over the lazy dog"
    assert calculate_cer(ref, ref) == 0.0
    assert calculate_wer(ref, ref) == 0.0

    # 2. Single substitution
    hyp_sub = "The quick brown fox jumps over the lazy dogg"
    cer = calculate_cer(ref, hyp_sub)
    assert 0.0 < cer < 0.05

    # 3. Completely different string
    hyp_diff = "Completely different words"
    assert calculate_cer(ref, hyp_diff) > 0.5


def test_image_preprocessing_pipeline() -> None:
    # Create image with artificial contrast and noise
    raw_bytes = create_scanned_image("StudyMind OCR preprocessing test")
    processed_bytes, angle = ImagePreprocessor.preprocess_image(raw_bytes)
    assert len(processed_bytes) > 0
    assert isinstance(angle, float)


@pytest.mark.asyncio
async def test_vision_ocr_fallback() -> None:
    vision_ocr = VisionOCR()
    img_bytes = create_scanned_image("Biology laboratory experiment notes")
    resp = await vision_ocr.transcribe_image(img_bytes)
    assert resp.text != ""
    assert resp.confidence > 0.5
    assert resp.ocr_quality in ("good", "medium", "low")


def test_office_parsers_docx_pptx_txt() -> None:
    # 1. DOCX Parsing
    docx_bytes = create_sample_docx()
    docx_pages = OfficeParser.parse_docx_bytes(docx_bytes)
    assert len(docx_pages) == 1
    blocks = docx_pages[0].blocks
    assert any(b.block_type == "heading" for b in blocks)
    assert any(b.block_type == "table" for b in blocks)

    # 2. PPTX Parsing
    pptx_bytes = create_sample_pptx()
    pptx_pages = OfficeParser.parse_pptx_bytes(pptx_bytes)
    assert len(pptx_pages) >= 1
    assert "Genetics" in pptx_pages[0].raw_text

    # 3. TXT Parsing
    txt_bytes = b"# Chapter 1: Introduction\n\nThis is plain text course material."
    txt_pages = OfficeParser.parse_text_bytes(txt_bytes, filename="intro.txt")
    assert len(txt_pages) == 1
    assert any(b.block_type == "heading" for b in txt_pages[0].blocks)


@pytest.mark.asyncio
async def test_scanned_pdf_and_photo_ingestion_dod(db_session: AsyncSession) -> None:
    """Definition of Done: scanned PDF and phone photo become searchable with bbox citations."""
    user = User(email="ocr_student@test.com", password_hash="pw")
    db_session.add(user)
    await db_session.flush()

    ws = Workspace(user_id=user.id, name="Scanned Material")
    db_session.add(ws)
    await db_session.flush()

    storage = get_storage_adapter()
    pipeline = IngestionPipeline()

    # 1. Ingest Scanned PDF (image-only, no text layer)
    pdf_bytes = create_scanned_pdf_image_only()
    pdf_key = f"users/{user.id}/workspaces/{ws.id}/doc_scan/scanned.pdf"
    await storage.put_object(pdf_key, pdf_bytes, "application/pdf")

    scanned_doc = Document(
        workspace_id=ws.id,
        user_id=user.id,
        filename="scanned.pdf",
        mime="application/pdf",
        sha256="sha_scanned_1",
        pages=0,
        status="queued",
        storage_key=pdf_key,
    )
    db_session.add(scanned_doc)
    await db_session.commit()
    await db_session.refresh(scanned_doc)

    ready_pdf = await pipeline.ingest_document(scanned_doc.id, db_session)
    assert ready_pdf.status == "ready"
    assert ready_pdf.ocr_quality in ("good", "medium", "low")

    # Verify chunks have bounding boxes
    chunks_stmt = select(Chunk).where(Chunk.document_id == ready_pdf.id)
    chunks = (await db_session.execute(chunks_stmt)).scalars().all()
    assert len(chunks) >= 1
    assert chunks[0].bbox_json is not None
    assert chunks[0].page_start == 1

    # 2. Ingest Phone Photo (.png)
    photo_bytes = create_scanned_image("Calculus lecture derivatives and integrals")
    photo_key = f"users/{user.id}/workspaces/{ws.id}/doc_photo/notes_photo.png"
    await storage.put_object(photo_key, photo_bytes, "image/png")

    photo_doc = Document(
        workspace_id=ws.id,
        user_id=user.id,
        filename="notes_photo.png",
        mime="image/png",
        sha256="sha_photo_1",
        pages=0,
        status="queued",
        storage_key=photo_key,
    )
    db_session.add(photo_doc)
    await db_session.commit()
    await db_session.refresh(photo_doc)

    ready_photo = await pipeline.ingest_document(photo_doc.id, db_session)
    assert ready_photo.status == "ready"
    assert ready_photo.ocr_quality in ("good", "medium", "low")

    # 3. Verify searchable in vector store
    vec_store = get_vector_store_adapter()
    search_hits = await vec_store.search(
        query_vector=[0.1] * 1024,
        user_id=user.id,
        workspace_id=ws.id,
        document_ids=[ready_photo.id],
        top_k=5,
    )
    assert len(search_hits) > 0
    assert search_hits[0].document_id == ready_photo.id
