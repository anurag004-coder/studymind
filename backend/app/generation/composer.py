"""Layer 5 response composer linking inline citations, calculating confidence,
and formatting abstain messages.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.retrieval.gate import GateDecision
from app.verification.citation_validator import ValidatedSentence


class FormattedCitation(BaseModel):
    """Citation object returned in API payload per API_SPEC.md §Chat."""

    n: int = Field(..., description="1-indexed citation number matching answer text [n]")
    document_id: str
    page: int
    quote: str
    chunk_id: str
    bbox: list[float] | None = None


class AnswerSentenceItem(BaseModel):
    """Sentence item with referencing citation indices."""

    text: str
    citations: list[int]


class FinalChatResponse(BaseModel):
    """Final grounded chat response matching API_SPEC.md §Chat."""

    message_id: str
    abstained: bool
    confidence: Literal["high", "medium", "low"]
    answer: list[AnswerSentenceItem]
    citations: list[FormattedCitation]
    dropped_claims: int = 0
    missing_info: str | None = None
    suggestions: list[str] = Field(default_factory=list)


class ResponseComposer:
    """Composes the final student-facing grounded message or abstain notification."""

    @staticmethod
    def compose_abstain_response(
        gate_decision: GateDecision,
        missing_info: str | None = None,
        dropped_claims: int = 0,
    ) -> FinalChatResponse:
        """Formats the official abstention payload when evidence is weak
        or claims fail verification.
        """
        suggestions = gate_decision.suggested_rephrases or []
        if not suggestions:
            suggestions = [
                "Try asking about topics explicitly covered in your uploaded notes.",
                "Verify that the relevant lecture slide or PDF page has been uploaded.",
            ]

        msg_id = str(uuid.uuid4())
        abstain_text = (
            "I couldn't find sufficient evidence for this in your uploaded study material."
        )
        if missing_info:
            abstain_text += f" ({missing_info})"

        return FinalChatResponse(
            message_id=msg_id,
            abstained=True,
            confidence="low",
            answer=[AnswerSentenceItem(text=abstain_text, citations=[])],
            citations=[],
            dropped_claims=dropped_claims,
            missing_info=missing_info or "Insufficient source evidence in workspace.",
            suggestions=suggestions[:3],
        )

    @staticmethod
    def compose_grounded_response(
        sentences: list[ValidatedSentence],
        best_score: float,
        dropped_claims: int = 0,
        missing_info: str | None = None,
    ) -> FinalChatResponse:
        """Composes verified grounded sentences and builds globally numbered citations."""
        msg_id = str(uuid.uuid4())

        citations_list: list[FormattedCitation] = []
        citation_map: dict[str, int] = {}  # (chunk_id, quote) -> n

        formatted_sentences: list[AnswerSentenceItem] = []

        for sent in sentences:
            sentence_cite_indices: list[int] = []

            for cite in sent.citations:
                key = f"{cite.chunk_id}::{cite.quote.strip().lower()}"
                if key not in citation_map:
                    n = len(citations_list) + 1
                    citation_map[key] = n
                    citations_list.append(
                        FormattedCitation(
                            n=n,
                            document_id=cite.document_id,
                            page=cite.page_start,
                            quote=cite.quote,
                            chunk_id=cite.chunk_id,
                            bbox=cite.bbox,
                        )
                    )
                else:
                    n = citation_map[key]

                if n not in sentence_cite_indices:
                    sentence_cite_indices.append(n)

            formatted_sentences.append(
                AnswerSentenceItem(
                    text=sent.text,
                    citations=sentence_cite_indices,
                )
            )

        # Compute confidence badge per ANTI_HALLUCINATION.md Layer 5
        if dropped_claims == 0 and best_score >= 0.50:
            confidence: Literal["high", "medium", "low"] = "high"
        elif dropped_claims <= 1 and best_score >= 0.35:
            confidence = "medium"
        else:
            confidence = "low"

        return FinalChatResponse(
            message_id=msg_id,
            abstained=False,
            confidence=confidence,
            answer=formatted_sentences,
            citations=citations_list,
            dropped_claims=dropped_claims,
            missing_info=missing_info,
            suggestions=[],
        )
