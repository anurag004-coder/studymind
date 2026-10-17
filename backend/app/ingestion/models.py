"""Ingestion data models and schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedBlock(BaseModel):
    page_no: int
    bbox: list[float] = Field(..., description="[x0, y0, x1, y1] coordinates")
    block_type: Literal["heading", "paragraph", "table", "formula", "code", "header", "footer"]
    text: str
    reading_order: int
    font_size: float | None = None
    is_bold: bool = False


class ParsedPage(BaseModel):
    page_no: int
    has_text_layer: bool
    blocks: list[ExtractedBlock]
    raw_text: str
    ocr_confidence: float | None = None
    image_bytes: bytes | None = None


class IngestionChunk(BaseModel):
    chunk_id: str
    document_id: str
    workspace_id: str
    user_id: str
    page_start: int
    page_end: int
    section_path: str | None = None
    text: str
    token_count: int
    source_type: Literal["text", "ocr", "generated_caption", "table", "formula"] = "text"
    bbox_list: list[list[float]] = Field(default_factory=list)
    chunk_index: int
    parent_id: str | None = None
    embedding_model: str = "BAAI/bge-m3"
