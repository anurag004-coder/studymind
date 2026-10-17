"""Base types and schemas for adapters."""

from typing import Any

from pydantic import BaseModel, Field


class ScoredChunk(BaseModel):
    chunk_id: str
    document_id: str
    page_start: int
    page_end: int
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    text: str
    structured_json: dict[str, Any] | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str
