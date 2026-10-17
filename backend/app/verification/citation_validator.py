"""Layer 3 deterministic citation validation verifying block IDs, quotes, and numbers."""

import re

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.adapters.base import ScoredChunk
from app.generation.generator import GroundedAnswerPayload, RawCitation


class ValidatedCitation(BaseModel):
    """Citation verified deterministically against source chunk text."""

    block_id: str
    chunk_id: str
    document_id: str
    page_start: int
    page_end: int
    quote: str
    fuzzy_ratio: float
    bbox: list[float] | None = None


class ValidatedSentence(BaseModel):
    """An answer sentence that successfully passed deterministic validation."""

    text: str
    citations: list[ValidatedCitation]


class CitationValidationResult(BaseModel):
    """Result of Layer 3 deterministic citation validation."""

    passed_sentences: list[ValidatedSentence]
    dropped_sentences: list[str]
    rejection_reasons: list[str]
    is_fully_grounded: bool


def find_quote_bbox_from_blocks(
    quote: str, chunk_text: str, bbox_list: list[list[float]] | None
) -> list[float] | None:
    """Finds bounding box corresponding to quote from chunk blocks."""
    if not bbox_list or not isinstance(bbox_list, list) or not quote:
        return None
    if len(bbox_list) == 1 and isinstance(bbox_list[0], list) and len(bbox_list[0]) == 4:
        return bbox_list[0]

    blocks_text = [b.strip() for b in chunk_text.split("\n\n") if b.strip()]
    if len(blocks_text) != len(bbox_list):
        blocks_text = [b.strip() for b in chunk_text.splitlines() if b.strip()]

    q_norm = " ".join(quote.lower().split())
    pairs: list[tuple[str, list[float]]] = []
    for i, b_box in enumerate(bbox_list):
        if isinstance(b_box, list) and len(b_box) == 4:
            b_text = blocks_text[i] if i < len(blocks_text) else ""
            pairs.append((b_text, b_box))

    if not pairs:
        return None

    matched_boxes: list[list[float]] = []
    for b_text, b_box in pairs:
        t_norm = " ".join(b_text.lower().split())
        if not t_norm:
            continue
        if len(t_norm) >= 5 and (q_norm in t_norm or t_norm in q_norm):
            matched_boxes.append(b_box)
        elif fuzz.partial_ratio(q_norm, t_norm) >= 80 and len(t_norm) >= 8:
            matched_boxes.append(b_box)

    if not matched_boxes:
        best_score = 0.0
        best_bbox: list[float] | None = None
        for b_text, b_box in pairs:
            t_norm = " ".join(b_text.lower().split())
            if len(t_norm) < 5:
                continue
            score = fuzz.token_set_ratio(q_norm, t_norm)
            if score > best_score:
                best_score = score
                best_bbox = b_box
        if best_score >= 60 and best_bbox:
            matched_boxes.append(best_bbox)

    if not matched_boxes:
        return pairs[0][1]

    min_x0 = min(b[0] for b in matched_boxes)
    min_y0 = min(b[1] for b in matched_boxes)
    max_x1 = max(b[2] for b in matched_boxes)
    max_y1 = max(b[3] for b in matched_boxes)
    return [round(min_x0, 2), round(min_y0, 2), round(max_x1, 2), round(max_y1, 2)]


class CitationValidator:
    """Performs deterministic (non-LLM) verification of citations, quotes, and numerics."""

    def __init__(self, min_quote_similarity: float = 0.70) -> None:
        self.min_similarity = min_quote_similarity

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return " ".join(text.split()).strip()

    @staticmethod
    def extract_numeric_tokens(text: str) -> set[str]:
        """Extracts numbers and units from text, excluding structural formatting."""
        # Strip structural study markers like [1 Mark], [3 Marks], Q1, (1), Point 1, etc.
        cleaned = re.sub(r"\[?\b\d+\s*marks?\b\]?", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bQ\d+\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:point|step|item)\s*\d+\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\(\s*\d+\s*\)", "", cleaned)
        cleaned = re.sub(r"^\s*\d+\.\s*", "", cleaned)

        # Find integer/decimal numbers, percentages, and scientific notation
        nums = re.findall(r"\b\d+(?:[\.,]\d+)?%?\b", cleaned.lower())
        return set(nums)

    def verify_numeric_grounding(
        self, sentence_text: str, cited_chunk_text: str
    ) -> tuple[bool, list[str]]:
        """Verifies that all numbers/measurements in the answer sentence appear in the chunk."""
        sent_nums = self.extract_numeric_tokens(sentence_text)
        if not sent_nums:
            return True, []

        chunk_nums = self.extract_numeric_tokens(cited_chunk_text)
        unsupported = [n for n in sent_nums if n not in chunk_nums]
        if unsupported:
            return False, unsupported
        return True, []

    def _find_quote_bbox(self, quote: str, chunk: ScoredChunk) -> list[float] | None:
        """Finds bounding box corresponding to quote from chunk metadata."""
        if not chunk.metadata:
            return None
        if (
            "bbox" in chunk.metadata
            and isinstance(chunk.metadata["bbox"], list)
            and len(chunk.metadata["bbox"]) == 4
        ):
            return chunk.metadata["bbox"]
        bbox_list = chunk.metadata.get("bbox_list")
        return find_quote_bbox_from_blocks(quote, chunk.text, bbox_list)

    def verify_citation(
        self, citation: RawCitation, block_map: dict[str, ScoredChunk]
    ) -> tuple[ValidatedCitation | None, str | None]:
        """Validates that block ID exists, quote is found, and meets threshold."""
        block_id = citation.chunk_id.strip()
        if block_id not in block_map:
            return None, f"Block ID '{block_id}' does not exist in retrieved context set"

        chunk = block_map[block_id]
        chunk_clean = self._normalize_whitespace(chunk.text).lower()
        quote_clean = self._normalize_whitespace(citation.quote).lower()

        if not quote_clean:
            return None, f"Citation for {block_id} has an empty quote"

        # Check exact substring match first
        if quote_clean in chunk_clean:
            fuzzy_ratio = 1.0
        else:
            # Fuzzy match via rapidfuzz partial ratio
            partial = fuzz.partial_ratio(quote_clean, chunk_clean) / 100.0
            token_set = fuzz.token_set_ratio(quote_clean, chunk_clean) / 100.0
            fuzzy_ratio = max(partial, token_set)

        if fuzzy_ratio < self.min_similarity:
            q_prev = citation.quote[:25]
            err = (
                f"Quote '{q_prev}...' not found in {block_id} "
                f"(ratio: {fuzzy_ratio:.2f} < {self.min_similarity:.2f})"
            )
            return None, err

        bbox = self._find_quote_bbox(citation.quote, chunk)

        return (
            ValidatedCitation(
                block_id=block_id,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                quote=citation.quote,
                fuzzy_ratio=round(fuzzy_ratio, 4),
                bbox=bbox,
            ),
            None,
        )

    def validate_payload(
        self,
        payload: GroundedAnswerPayload,
        block_map: dict[str, ScoredChunk],
    ) -> CitationValidationResult:
        """Validates all answer sentences and drops unverified or hallucinated claims."""
        if not payload.answerable or not payload.answer_sentences:
            return CitationValidationResult(
                passed_sentences=[],
                dropped_sentences=[],
                rejection_reasons=["Payload marked unanswerable"],
                is_fully_grounded=False,
            )

        passed: list[ValidatedSentence] = []
        dropped: list[str] = []
        reasons: list[str] = []

        for sentence in payload.answer_sentences:
            sent_text = sentence.text.strip()
            if not sent_text:
                continue

            # Must have citations
            if not sentence.citations:
                dropped.append(sent_text)
                reasons.append(f"Sentence lacks citations: '{sent_text[:40]}...'")
                continue

            valid_citations: list[ValidatedCitation] = []
            combined_cited_text: list[str] = []

            for raw_cite in sentence.citations:
                val_cite, err = self.verify_citation(raw_cite, block_map)
                if val_cite:
                    valid_citations.append(val_cite)
                    chunk_obj = block_map.get(val_cite.block_id)
                    if chunk_obj:
                        combined_cited_text.append(chunk_obj.text)
                elif err:
                    reasons.append(err)

            # Must have at least 1 valid citation surviving
            if not valid_citations:
                dropped.append(sent_text)
                reasons.append(f"No valid citations remained for sentence: '{sent_text[:40]}...'")
                continue

            # Check numeric and entity consistency
            all_cited_text = " ".join(combined_cited_text)
            nums_ok, bad_nums = self.verify_numeric_grounding(sent_text, all_cited_text)
            if not nums_ok:
                dropped.append(sent_text)
                reasons.append(
                    f"Sentence contains ungrounded numbers/dates {bad_nums}: '{sent_text[:40]}...'"
                )
                continue

            passed.append(
                ValidatedSentence(
                    text=sent_text,
                    citations=valid_citations,
                )
            )

        is_fully_grounded = len(dropped) == 0 and len(passed) > 0

        return CitationValidationResult(
            passed_sentences=passed,
            dropped_sentences=dropped,
            rejection_reasons=reasons,
            is_fully_grounded=is_fully_grounded,
        )
