"""Tests for Phase 2: Ingestion pipeline, PDF parser, cleaner, chunker, and lexical index."""

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_storage_adapter, get_vector_store_adapter
from app.db.models import Chunk, Document, Page, User, Workspace
from app.ingestion.chunker import StructureAwareChunker
from app.ingestion.cleaner import TextCleaner
from app.ingestion.lexical_index import LexicalIndex
from app.ingestion.models import ExtractedBlock, ParsedPage
from app.ingestion.pipeline import IngestionPipeline


def create_synthetic_pdf(num_pages: int = 5) -> bytes:
    """Creates an in-memory synthetic PDF with headings, paragraphs, and tables."""
    doc = pymupdf.open()
    for page_num in range(1, num_pages + 1):
        page = doc.new_page()

        # Running header (repeated across pages)
        page.insert_text((50, 30), "StudyMind University - Physics 101", fontsize=8)

        # Chapter / Section heading
        heading = f"Chapter {page_num}: Thermodynamics Fundamentals"
        page.insert_text((50, 70), heading, fontsize=16)

        # Body paragraphs with hyphenation
        body1 = (
            f"On page {page_num}, we investigate the fundamen-\ntal principles of heat "
            "and energy transfer. The first law of thermodynamics states that energy "
            "cannot be created or destroyed, only transformed from one state to another. "
            "This principle forms the foundation for all modern mechanical engineering systems."
        )
        page.insert_text((50, 100), body1, fontsize=11)

        # On every 5th page, add a table
        if page_num % 5 == 0:
            table_text = (
                "Parameter | Symbol | SI Unit\n"
                "Temperature | T | Kelvin\n"
                "Pressure | P | Pascal\n"
                "Volume | V | Cubic Meter"
            )
            page.insert_text((50, 200), table_text, fontsize=10)

        # Running footer with page number
        page.insert_text((250, 780), f"Page {page_num}", fontsize=8)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_cleaner_repeated_headers_and_hyphenation() -> None:
    # 1. Test hyphenation repair
    text_with_hyphen = "The fundamen-\ntal principles of hydro-\ndynamics."
    cleaned_hyphen = TextCleaner.normalize_text(text_with_hyphen)
    assert "fundamental" in cleaned_hyphen
    assert "hydrodynamics" in cleaned_hyphen

    # 2. Test repeated header and footer removal
    page1 = ParsedPage(
        page_no=1,
        has_text_layer=True,
        blocks=[
            ExtractedBlock(
                page_no=1,
                bbox=[50, 20, 200, 35],
                block_type="header",
                text="Physics 101 - Running Header",
                reading_order=0,
            ),
            ExtractedBlock(
                page_no=1,
                bbox=[50, 60, 400, 150],
                block_type="paragraph",
                text="Unique content on kinematics.",
                reading_order=1,
            ),
            ExtractedBlock(
                page_no=1,
                bbox=[50, 780, 100, 790],
                block_type="footer",
                text="Page 1",
                reading_order=2,
            ),
        ],
        raw_text="",
    )

    page2 = ParsedPage(
        page_no=2,
        has_text_layer=True,
        blocks=[
            ExtractedBlock(
                page_no=2,
                bbox=[50, 20, 200, 35],
                block_type="header",
                text="Physics 101 - Running Header",
                reading_order=0,
            ),
            ExtractedBlock(
                page_no=2,
                bbox=[50, 60, 400, 150],
                block_type="paragraph",
                text="Unique content on dynamics.",
                reading_order=1,
            ),
            ExtractedBlock(
                page_no=2,
                bbox=[50, 780, 100, 790],
                block_type="footer",
                text="Page 2",
                reading_order=2,
            ),
        ],
        raw_text="",
    )

    cleaned_pages = TextCleaner.detect_and_strip_repeated_headers_footers([page1, page2])
    assert len(cleaned_pages) == 2
    # Only the unique paragraph should remain on each page
    assert len(cleaned_pages[0].blocks) == 1
    assert "Unique content on kinematics" in cleaned_pages[0].blocks[0].text
    assert len(cleaned_pages[1].blocks) == 1
    assert "Unique content on dynamics" in cleaned_pages[1].blocks[0].text


def test_chunker_table_preservation_and_token_limits() -> None:
    chunker = StructureAwareChunker(min_tokens=20, max_tokens=100)

    table_block = ExtractedBlock(
        page_no=1,
        bbox=[50, 150, 300, 250],
        block_type="table",
        text="| Element | Atomic Number |\n| H | 1 |\n| He | 2 |",
        reading_order=1,
    )
    para_block = ExtractedBlock(
        page_no=1,
        bbox=[50, 50, 300, 120],
        block_type="paragraph",
        text="The periodic table organizes all chemical elements by atomic number.",
        reading_order=0,
    )

    page = ParsedPage(
        page_no=1,
        has_text_layer=True,
        blocks=[para_block, table_block],
        raw_text="",
    )

    chunks = chunker.chunk_pages(
        [page],
        document_id="doc_1",
        workspace_id="ws_1",
        user_id="user_1",
    )

    # Chunker MUST keep the table as an independent chunk without splitting
    assert len(chunks) == 2
    table_chunk = next(c for c in chunks if c.source_type == "table")
    assert "Atomic Number" in table_chunk.text
    assert len(table_chunk.bbox_list) == 1


def test_lexical_bm25_index() -> None:
    idx = LexicalIndex()
    chunks = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "workspace_id": "w1",
            "user_id": "u1",
            "page_start": 1,
            "page_end": 1,
            "text": "Mitochondria are organelles that produce cellular energy via ATP synthesis.",
        },
        {
            "chunk_id": "c2",
            "document_id": "d1",
            "workspace_id": "w1",
            "user_id": "u1",
            "page_start": 2,
            "page_end": 2,
            "text": "The Golgi apparatus packages proteins for secretion.",
        },
    ]
    idx.index_chunks(chunks)

    results = idx.search("mitochondria ATP", user_id="u1", workspace_id="w1")
    assert len(results) > 0
    assert results[0].chunk_id == "c1"

    # Isolation check: user2 searching must return empty
    iso_res = idx.search("mitochondria", user_id="u2", workspace_id="w1")
    assert len(iso_res) == 0


@pytest.mark.asyncio
async def test_100_page_pdf_ingestion_dod(db_session: AsyncSession) -> None:
    """Definition of Done (DoD) test: 100-page PDF ingested with chunks, page/bbox tracking."""
    # 1. Setup user & workspace
    user = User(email="100page_student@test.com", password_hash="pw")
    db_session.add(user)
    await db_session.flush()

    ws = Workspace(user_id=user.id, name="Physics 100 Pages")
    db_session.add(ws)
    await db_session.flush()

    # 2. Generate 100-page synthetic textbook PDF
    pdf_bytes = create_synthetic_pdf(num_pages=100)
    assert len(pdf_bytes) > 0

    storage = get_storage_adapter()
    key = f"users/{user.id}/workspaces/{ws.id}/doc_100/textbook.pdf"
    await storage.put_object(key, pdf_bytes, "application/pdf")

    doc = Document(
        workspace_id=ws.id,
        user_id=user.id,
        filename="textbook.pdf",
        mime="application/pdf",
        sha256="dummy_100_hash",
        pages=0,
        status="queued",
        storage_key=key,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    # 3. Execute Ingestion Pipeline
    pipeline = IngestionPipeline()
    ready_doc = await pipeline.ingest_document(doc.id, db_session)

    # 4. Verify Document Status
    assert ready_doc.status == "ready"
    assert ready_doc.pages == 100
    assert ready_doc.ocr_quality == "good"

    # 5. Verify Page rows
    page_stmt = select(Page).where(Page.document_id == doc.id)
    pages = (await db_session.execute(page_stmt)).scalars().all()
    assert len(pages) == 100
    assert pages[0].page_no == 1
    assert pages[99].page_no == 100

    # 6. Verify Chunks have page and bounding box tracking
    chunk_stmt = select(Chunk).where(Chunk.document_id == doc.id)
    chunks = (await db_session.execute(chunk_stmt)).scalars().all()
    assert len(chunks) >= 100
    for ch in chunks:
        assert ch.page_start >= 1
        assert ch.page_end <= 100
        assert ch.token_count > 0
        assert ch.bbox_json is not None
        assert len(ch.text) > 0

    # 7. Verify Vector Store and Lexical BM25 Search
    vector_store = get_vector_store_adapter()
    vec_results = await vector_store.search(
        query_vector=[0.1] * 1024,
        user_id=user.id,
        workspace_id=ws.id,
        document_ids=[doc.id],
        top_k=5,
    )
    assert len(vec_results) > 0
    assert vec_results[0].document_id == doc.id
