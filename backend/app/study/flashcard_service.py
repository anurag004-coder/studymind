"""Grounded Flashcards Generation Service per PROMPTS.md §6 and ANTI_HALLUCINATION.md Layer 6."""

import json
import uuid
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_llm_adapter
from app.adapters.llm import LLMAdapter
from app.db.models import Chunk, Document, StudyItem
from app.study.schemas import (
    FlashcardItem,
    FlashcardListResponse,
    RawFlashcardsOutput,
)
from app.verification.citation_validator import find_quote_bbox_from_blocks


class FlashcardService:
    """Generates grounded flashcards where every card has a verified chunk ID + quote."""

    def __init__(self, llm_adapter: LLMAdapter | None = None) -> None:
        self.llm = llm_adapter or get_llm_adapter()

    async def generate_flashcards(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
        document_ids: list[str] | None = None,
        count: int = 5,
        topic: str | None = None,
    ) -> FlashcardListResponse:
        """Generates, verifies, and persists study flashcards."""
        # 1. Fetch chunks for this workspace
        query = (
            select(Chunk, Document.filename)
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Document.workspace_id == workspace_id,
                Document.user_id == user_id,
            )
        )
        if document_ids:
            query = query.where(Document.id.in_(document_ids))
        query = query.order_by(Chunk.page_start.asc())

        results = (await db.execute(query)).all()
        if not results:
            return FlashcardListResponse(flashcards=[], saved_count=0)

        chunks_map: dict[str, Chunk] = {c.id: c for c, _ in results}
        chunk_list = [c for c, _ in results]

        # Filter chunks if topic is specified
        if topic:
            filtered = [
                c
                for c in chunk_list
                if topic.lower() in (c.section_path or "").lower()
                or topic.lower() in c.text.lower()
            ]
            if filtered:
                chunk_list = filtered

        # 2. Query existing flashcard items for this workspace to prevent repetition
        existing_items_stmt = select(StudyItem).where(
            StudyItem.workspace_id == workspace_id,
            StudyItem.type == "flashcard",
        )
        existing_rows = (await db.execute(existing_items_stmt)).scalars().all()
        existing_questions: list[str] = []
        used_chunk_ids: set[str] = set()
        for row in existing_rows:
            try:
                p = json.loads(row.payload_json)
                q_text = p.get("question", "")
                if q_text:
                    existing_questions.append(q_text)
                c_id = p.get("source_chunk_id", "")
                if c_id:
                    used_chunk_ids.add(c_id)
            except Exception:
                pass

        # 3. Intelligent coverage-aware chunk selection (avoid always picking chunk 0..7)
        unused_chunks = [c for c in chunk_list if c.id not in used_chunk_ids]
        candidate_pool = unused_chunks if len(unused_chunks) >= min(count, 3) else chunk_list

        # Distribute selection across whole document
        if len(candidate_pool) > 10:
            stride = max(1, len(candidate_pool) // 10)
            selected_chunks = candidate_pool[::stride][:10]
        else:
            selected_chunks = candidate_pool[: min(10, len(candidate_pool))]

        context_blocks = "\n\n".join(
            f"[CHUNK_ID: {c.id} | Page: {c.page_start}]\n{c.text}" for c in selected_chunks
        )

        dedup_clause = ""
        if existing_questions:
            recent_stems = "\n".join(f"- {q}" for q in existing_questions[-12:])
            dedup_clause = (
                f"\nCRITICAL DEDUPLICATION RULE:\n"
                f"Do NOT duplicate questions similar to existing ones:\n{recent_stems}\n"
                f"Choose distinct concepts, definitions, formulas, or details from the context."
            )

        prompt = (
            f"You are a strict study assistant. From the CONTEXT only, create {count} flashcards.\n"
            f"For each card:\n"
            f"- question: Clear, focused question testing a concept\n"
            f"- answer: Concise explanation (<= 2 sentences)\n"
            f"- source_chunk_id: The exact CHUNK_ID that provides the proof\n"
            f"- quote: Exact supporting quote found in that chunk text\n\n"
            f"RULES: Skip anything not explicitly stated in the context.\n"
            f"{dedup_clause}\n"
            f"Return JSON adhering to RawFlashcardsOutput."
            f"\n\nCONTEXT:\n{context_blocks}"
        )

        try:
            output, _ = await self.llm.generate_structured(
                messages=[
                    {"role": "system", "content": "You are a grounded study flashcard generator."},
                    {"role": "user", "content": prompt},
                ],
                response_model=RawFlashcardsOutput,
                temperature=0.2,
            )
            raw_cards = output.flashcards if isinstance(output, RawFlashcardsOutput) else []
        except Exception:
            raw_cards = []

        # Deterministic fallback extraction if LLM returned empty or failed
        if not raw_cards:
            candidate_sentences: list[tuple[Any, str]] = []
            for c in candidate_pool:
                for sent in c.text.split(". "):
                    s_clean = sent.strip().rstrip(".").replace("\n", " ")
                    if len(s_clean) >= 20 and not s_clean.endswith("?"):
                        # Skip if already tested in existing questions
                        is_repeat = any(
                            fuzz.partial_ratio(s_clean.lower()[:35], eq.lower()) > 85.0
                            for eq in existing_questions
                        )
                        if not is_repeat:
                            candidate_sentences.append((c, s_clean))

            # If unused candidate sentences are fewer than requested count,
            # cycle available sentences with alternative question phrasings
            if len(candidate_sentences) < count:
                for c in candidate_pool:
                    for sent in c.text.split(". "):
                        s_clean = sent.strip().rstrip(".").replace("\n", " ")
                        if len(s_clean) >= 20 and not s_clean.endswith("?"):
                            if not any(s == s_clean for _, s in candidate_sentences):
                                candidate_sentences.append((c, s_clean))

            stem_templates = [
                "What key concept regarding '{phrase}' is stated in the material?",
                "According to the source, how is '{phrase}' defined or explained?",
                "What does the course material outline regarding '{phrase}'?",
                "What critical function or role does '{phrase}' perform?",
                "Based on the notes, what are the characteristics of '{phrase}'?",
                "Explain the significance of '{phrase}' as described in the notes:",
                "In relation to '{phrase}', what does the text highlight?",
            ]

            offset = len(existing_questions)
            for idx, (chunk, sentence) in enumerate(candidate_sentences[:count]):
                words = sentence.split()
                phrase = " ".join(words[: min(6, len(words))])
                tpl = stem_templates[(offset + idx) % len(stem_templates)]
                q_text = tpl.format(phrase=phrase)
                raw_cards.append(
                    type(
                        "RawCard",
                        (),
                        {
                            "question": q_text,
                            "answer": sentence + ".",
                            "source_chunk_id": chunk.id,
                            "quote": sentence,
                        },
                    )()  # type: ignore[call-arg]
                )

        # 4. Strict Grounding & Deduplication Verification (DoD Requirement)
        validated_cards: list[FlashcardItem] = []

        for card in raw_cards:
            if len(validated_cards) >= count:
                break

            # Deduplication against already saved questions and newly validated cards
            cand_q = card.question.strip()
            if not cand_q:
                continue

            is_dup = False
            for prev_q in existing_questions + [vc.question for vc in validated_cards]:
                if (
                    cand_q.lower() == prev_q.lower()
                    or fuzz.ratio(cand_q.lower(), prev_q.lower()) > 88.0
                ):
                    is_dup = True
                    break
            if is_dup:
                continue

            chunk = chunks_map.get(card.source_chunk_id)
            if not chunk and chunk_list:
                for cand in chunk_list:
                    if card.quote.lower() in cand.text.lower():
                        chunk = cand
                        break

            if not chunk:
                continue

            # Verify quote against chunk text
            quote_sim = fuzz.partial_ratio(card.quote.lower(), chunk.text.lower())
            if quote_sim < 70.0 and card.quote.lower() not in chunk.text.lower():
                continue

            card_id = str(uuid.uuid4())
            b_list = json.loads(chunk.bbox_json) if chunk.bbox_json else None
            card_bbox = find_quote_bbox_from_blocks(card.quote, chunk.text, b_list)

            valid_card = FlashcardItem(
                id=card_id,
                question=cand_q,
                answer=card.answer,
                source_chunk_id=chunk.id,
                quote=card.quote if len(card.quote) <= 300 else card.quote[:300],
                document_id=chunk.document_id,
                page=chunk.page_start,
                bbox=card_bbox,
            )
            validated_cards.append(valid_card)

            # Persist to study_items table
            study_row = StudyItem(
                id=card_id,
                workspace_id=workspace_id,
                type="flashcard",
                payload_json=json.dumps(valid_card.model_dump()),
                source_chunk_ids=json.dumps([chunk.id]),
            )
            db.add(study_row)

        await db.commit()

        return FlashcardListResponse(
            flashcards=validated_cards,
            saved_count=len(validated_cards),
        )
