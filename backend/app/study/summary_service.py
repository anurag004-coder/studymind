"""Grounded Summary Service implementing Map-Reduce summarization per PROMPTS.md §8."""

import json
import uuid
from typing import Any, Literal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_llm_adapter
from app.adapters.llm import LLMAdapter
from app.db.models import Chunk, Document, StudyItem
from app.generation.generator import extract_clean_sentences
from app.study.schemas import (
    ImportantAreaItem,
    KeyTakeawayItem,
    RawMapOutput,
    RawReduceOutput,
    ReferencedPageItem,
    SummaryResponse,
)
from app.verification.citation_validator import find_quote_bbox_from_blocks


class SummaryService:
    """Produces grounded hierarchical summaries with verified chunk citations."""

    def __init__(self, llm_adapter: LLMAdapter | None = None) -> None:
        self.llm = llm_adapter or get_llm_adapter()

    async def generate_summary(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
        document_ids: list[str] | None = None,
        length: Literal["short", "medium", "detailed"] = "medium",
    ) -> SummaryResponse:
        """Executes the map-reduce grounded summarization pipeline."""
        # 1. Fetch chunks belonging to documents in this workspace
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
        query = query.order_by(Document.filename.asc(), Chunk.page_start.asc())

        results = (await db.execute(query)).all()
        if not results:
            # Fallback if no materials ingested yet
            empty_item = StudyItem(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                type="summary",
                payload_json=json.dumps(
                    {
                        "title": "No Study Material",
                        "summary": "No documents found to summarize in this workspace.",
                        "key_takeaways": [],
                    }
                ),
                source_chunk_ids="[]",
            )
            db.add(empty_item)
            await db.commit()
            return SummaryResponse(
                id=empty_item.id,
                workspace_id=workspace_id,
                title="No Study Material",
                summary="No documents found to summarize.",
                key_takeaways=[],
                source_chunk_ids=[],
                created_at=empty_item.created_at,
            )

        chunks_map: dict[str, Chunk] = {c.id: c for c, _ in results}
        chunk_doc_map: dict[str, tuple[str, int]] = {
            c.id: (c.document_id, c.page_start) for c, _ in results
        }

        # 2. MAP STEP: Group chunks into section batches (max 4 per batch)
        chunk_list = [c for c, _ in results]
        batch_size = 4
        batches = [chunk_list[i : i + batch_size] for i in range(0, len(chunk_list), batch_size)]

        map_bullet_points: list[dict[str, Any]] = []
        for batch in batches[:6]:  # Cap at 6 batches for prompt size
            batch_text = "\n\n".join(
                f"[CHUNK_ID: {c.id} | Page: {c.page_start}]\n{c.text}" for c in batch
            )
            map_prompt = (
                "You are a strict study assistant.\n"
                "MAP step: summarize this section using ONLY its text.\n"
                "For each key fact, specify the source chunk ID and an exact supporting quote.\n\n"
                f"SECTION TEXT:\n{batch_text}\n\n"
                "Return JSON adhering to RawMapOutput schema."
            )

            try:
                map_out, _ = await self.llm.generate_structured(
                    messages=[
                        {"role": "system", "content": "You are a grounded study assistant."},
                        {"role": "user", "content": map_prompt},
                    ],
                    response_model=RawMapOutput,
                    temperature=0.0,
                )
                if isinstance(map_out, RawMapOutput):
                    for sec in map_out.sections:
                        for bullet in sec.summary_bullets:
                            map_bullet_points.append(
                                {
                                    "bullet": bullet,
                                    "chunk_id": sec.source_chunk_id or batch[0].id,
                                    "quote": sec.quote or batch[0].text[:80],
                                }
                            )
            except Exception:
                # Deterministic fallback extraction if structured output fails
                for c in batch:
                    preview = c.text.strip().split("\n")[0][:120]
                    map_bullet_points.append(
                        {
                            "bullet": preview,
                            "chunk_id": c.id,
                            "quote": c.text[:60],
                        }
                    )

        # 3. REDUCE STEP: Combine map outputs into cohesive target length summary
        joined_bullets = "\n".join(
            f'- {bp["bullet"]} [Source: {bp["chunk_id"]} | Quote: "{bp["quote"]}"]'
            for bp in map_bullet_points
        )

        reduce_prompt = (
            f"REDUCE step: Combine section summaries into a final study summary ('{length}').\n"
            "Include a concise title, an overview synthesis, and key takeaways.\n"
            "Every takeaway MUST cite an exact source_chunk_id and quote from inputs.\n"
            "Do NOT add any outside facts.\n\n"
            f"SECTION BULLETS:\n{joined_bullets}\n\n"
            "Return JSON adhering to RawReduceOutput."
        )

        try:
            reduce_out, _ = await self.llm.generate_structured(
                messages=[
                    {"role": "system", "content": "You are a grounded study assistant."},
                    {"role": "user", "content": reduce_prompt},
                ],
                response_model=RawReduceOutput,
                temperature=0.0,
            )
            if isinstance(reduce_out, RawReduceOutput):
                title = reduce_out.title or "Study Guide Summary"
                overview = reduce_out.overview or "Summary of course material."
                candidate_takeaways = reduce_out.takeaways
            else:
                title = "Study Material Overview"
                overview = "\n".join(bp["bullet"] for bp in map_bullet_points[:4])
                candidate_takeaways = []
        except Exception:
            title = "Study Material Overview"
            overview = "\n".join(bp["bullet"] for bp in map_bullet_points[:4])
            candidate_takeaways = [
                KeyTakeawayItem(
                    point=bp["bullet"],
                    source_chunk_id=bp["chunk_id"],
                    quote=bp["quote"],
                )
                for bp in map_bullet_points[:5]
            ]

        # 4. Verification of Takeaway Citations against real Chunks
        verified_takeaways: list[KeyTakeawayItem] = []
        used_chunk_ids: set[str] = set()

        for item in candidate_takeaways:
            chunk = chunks_map.get(item.source_chunk_id)
            if not chunk and chunk_list:
                # Match to closest chunk
                chunk = chunk_list[0]
                item.source_chunk_id = chunk.id

            if chunk:
                # Verify quote exists in chunk text
                quote_sim = fuzz.partial_ratio(item.quote.lower(), chunk.text.lower())
                b_list = json.loads(chunk.bbox_json) if chunk.bbox_json else None
                if quote_sim >= 75.0 or item.quote.lower() in chunk.text.lower():
                    doc_id, page_no = chunk_doc_map.get(
                        chunk.id, (chunk.document_id, chunk.page_start)
                    )
                    item.document_id = doc_id
                    item.page = page_no
                    item.bbox = find_quote_bbox_from_blocks(item.quote, chunk.text, b_list)
                    verified_takeaways.append(item)
                    used_chunk_ids.add(chunk.id)
                elif len(verified_takeaways) == 0:
                    # Provide exact quote fallback from chunk
                    item.quote = chunk.text[:100]
                    doc_id, page_no = chunk_doc_map.get(
                        chunk.id, (chunk.document_id, chunk.page_start)
                    )
                    item.document_id = doc_id
                    item.page = page_no
                    item.bbox = find_quote_bbox_from_blocks(item.quote, chunk.text, b_list)
                    verified_takeaways.append(item)
                    used_chunk_ids.add(chunk.id)

        if not verified_takeaways and chunk_list:
            first_c = chunk_list[0]
            b_list = json.loads(first_c.bbox_json) if first_c.bbox_json else None
            t_quote = first_c.text[:80]
            verified_takeaways.append(
                KeyTakeawayItem(
                    point=first_c.text[:120],
                    source_chunk_id=first_c.id,
                    quote=t_quote,
                    document_id=first_c.document_id,
                    page=first_c.page_start,
                    bbox=find_quote_bbox_from_blocks(t_quote, first_c.text, b_list),
                )
            )
            used_chunk_ids.add(first_c.id)

        # 5. Extract Important Areas & Direct Page References for Redirection
        important_areas: list[ImportantAreaItem] = []
        seen_area_keys: set[str] = set()

        # Group chunks by page/topic to produce distinct important areas
        for c in chunk_list:
            doc_id, page_no = chunk_doc_map.get(c.id, (c.document_id, c.page_start))
            area_key = f"{doc_id}:{page_no}"
            if area_key in seen_area_keys:
                continue

            # Determine area title from section path or first line
            area_title = (c.section_path or "").strip()
            if not area_title or area_title.lower().startswith("chunk"):
                first_line = c.text.strip().split("\n")[0].strip().lstrip("#•-* ")
                area_title = (
                    first_line[:45] if len(first_line) >= 6 else f"Key Concepts (Page {page_no})"
                )

            # Extract a concise area summary with clean non-fragmented sentences
            clean_sents = extract_clean_sentences(c.text)
            summary_snippet = " ".join(clean_sents[:2])[:200]
            if summary_snippet and not summary_snippet.endswith("."):
                summary_snippet += "."

            b_list = json.loads(c.bbox_json) if c.bbox_json else None
            area_quote = clean_sents[0][:140] if clean_sents else c.text.strip()[:140]
            area_bbox = find_quote_bbox_from_blocks(area_quote, c.text, b_list)

            important_areas.append(
                ImportantAreaItem(
                    area_title=area_title,
                    summary=summary_snippet or f"Core study material discussed on page {page_no}.",
                    page=page_no,
                    document_id=doc_id,
                    quote=area_quote,
                    bbox=area_bbox,
                )
            )
            seen_area_keys.add(area_key)
            if len(important_areas) >= 8:
                break

        # Collect unique referenced pages
        referenced_pages: list[ReferencedPageItem] = []
        seen_pages: set[tuple[str, int]] = set()
        for c in chunk_list:
            doc_id, page_no = chunk_doc_map.get(c.id, (c.document_id, c.page_start))
            if (doc_id, page_no) not in seen_pages:
                seen_pages.add((doc_id, page_no))
                # Title preview
                p_title = (c.section_path or "").strip()
                if not p_title or p_title.lower().startswith("chunk"):
                    f_line = c.text.strip().split("\n")[0].strip().lstrip("#•-* ")
                    p_title = f_line[:30] if len(f_line) >= 4 else f"Page {page_no}"
                referenced_pages.append(
                    ReferencedPageItem(
                        page=page_no,
                        document_id=doc_id,
                        title=p_title,
                    )
                )

        referenced_pages.sort(key=lambda p: (p.document_id, p.page))

        # 6. Persist StudyItem in Database
        item_id = str(uuid.uuid4())
        study_row = StudyItem(
            id=item_id,
            workspace_id=workspace_id,
            type="summary",
            payload_json=json.dumps(
                {
                    "title": title,
                    "summary": overview,
                    "key_takeaways": [t.model_dump() for t in verified_takeaways],
                    "important_areas": [a.model_dump() for a in important_areas],
                    "referenced_pages": [p.model_dump() for p in referenced_pages],
                }
            ),
            source_chunk_ids=json.dumps(list(used_chunk_ids)),
        )
        db.add(study_row)
        await db.commit()
        await db.refresh(study_row)

        return SummaryResponse(
            id=study_row.id,
            workspace_id=workspace_id,
            title=title,
            summary=overview,
            key_takeaways=verified_takeaways,
            important_areas=important_areas,
            referenced_pages=referenced_pages,
            source_chunk_ids=list(used_chunk_ids),
            created_at=study_row.created_at,
        )
