"""Topic extraction and syllabus mapping service per QUIZ_ASSESSMENT.md §3."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import get_llm_adapter
from app.db.models.document import Chunk, Document
from app.db.models.quiz import Question, Topic, TopicMastery
from app.quiz.schemas import TopicItem

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class TopicService:
    """Extracts topic hierarchies and maintains chunk-to-topic mappings."""

    def __init__(self) -> None:
        self.llm = get_llm_adapter()
        self.prompt_template = (PROMPTS_DIR / "topic_extraction_v1.txt").read_text(encoding="utf-8")

    async def rebuild_topics(
        self,
        workspace_id: str,
        db: AsyncSession,
    ) -> tuple[int, int]:
        """Rebuilds the workspace topic map from ingested document chunks."""
        # 1. Fetch chunks for this workspace
        stmt = (
            select(Chunk, Document.filename)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.id, Chunk.chunk_index)
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return 0, 0

        chunks_data = [
            {
                "id": c.id,
                "text": c.text,
                "filename": fname,
                "page": c.page_start,
            }
            for c, fname in rows
        ]

        # 2. Extract topics using LLM or structured heuristic
        raw_topics = await self._extract_topics_llm_or_heuristic(chunks_data)

        # 3. Clean up old topics for this workspace
        await db.execute(delete(Topic).where(Topic.workspace_id == workspace_id))
        await db.flush()

        # 4. Insert new topics
        name_to_id: dict[str, str] = {}
        created_count = 0
        chunks_mapped = set()

        # First pass: parent topics
        for item in raw_topics:
            parent_name = item.get("parent_name")
            if not parent_name:
                t_id = str(uuid.uuid4())
                name = item["name"]
                c_ids = item.get("chunk_ids", [])
                for cid in c_ids:
                    chunks_mapped.add(cid)

                name_to_id[name.lower()] = t_id
                topic = Topic(
                    id=t_id,
                    workspace_id=workspace_id,
                    parent_id=None,
                    name=name,
                    chunk_ids=json.dumps(c_ids),
                )
                db.add(topic)
                created_count += 1

        await db.flush()

        # Second pass: subtopics
        for item in raw_topics:
            parent_name = item.get("parent_name")
            if parent_name:
                t_id = str(uuid.uuid4())
                name = item["name"]
                parent_id = name_to_id.get(parent_name.lower())
                c_ids = item.get("chunk_ids", [])
                for cid in c_ids:
                    chunks_mapped.add(cid)

                name_to_id[name.lower()] = t_id
                topic = Topic(
                    id=t_id,
                    workspace_id=workspace_id,
                    parent_id=parent_id,
                    name=name,
                    chunk_ids=json.dumps(c_ids),
                )
                db.add(topic)
                created_count += 1

        await db.commit()
        return created_count, len(chunks_mapped)

    async def get_topics_for_workspace(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> list[TopicItem]:
        """Lists all topics in the workspace with chunk count, question count, and mastery."""
        stmt = select(Topic).where(Topic.workspace_id == workspace_id).order_by(Topic.name)
        topics = (await db.execute(stmt)).scalars().all()

        results: list[TopicItem] = []
        for t in topics:
            c_list = json.loads(t.chunk_ids) if t.chunk_ids else []

            # Count questions
            q_count_stmt = select(func.count(Question.id)).where(
                Question.topic_id == t.id,
                Question.status == "active",
            )
            q_count = (await db.execute(q_count_stmt)).scalar() or 0

            # Get user mastery
            mastery_stmt = select(TopicMastery.mastery).where(
                TopicMastery.user_id == user_id,
                TopicMastery.topic_id == t.id,
            )
            mastery = (await db.execute(mastery_stmt)).scalar() or 0.0

            results.append(
                TopicItem(
                    id=t.id,
                    workspace_id=t.workspace_id,
                    parent_id=t.parent_id,
                    name=t.name,
                    chunk_count=len(c_list),
                    question_count=q_count,
                    mastery=round(float(mastery), 3),
                    created_at=t.created_at,
                )
            )

        return results

    async def _extract_topics_llm_or_heuristic(
        self, chunks_data: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Invokes LLM for topic clustering or falls back to robust syntactic clustering."""
        # Build prompt excerpt summary
        excerpts = []
        for c in chunks_data[:30]:  # Up to 30 chunks for topic clustering
            text_preview = c["text"][:160].replace("\n", " ").strip()
            prefix = f"[{c['id']}] (File: {c['filename']}, Page {c['page']}):"
            excerpts.append(f"{prefix} {text_preview}")

        user_content = "CHUNKS:\n" + "\n".join(excerpts)
        try:
            prompt_text = f"{self.prompt_template}\n\n{user_content}"
            raw_response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt_text}],
                temperature=0.2,
                max_tokens=1000,
            )
            # Try parsing JSON array
            text = raw_response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning("LLM topic extraction fallback triggered: %s", e)

        # Robust heuristic fallback: group by document filename and keywords
        doc_groups: dict[str, list[str]] = {}
        for c in chunks_data:
            base_name = Path(c["filename"]).stem.replace("_", " ").title()
            doc_groups.setdefault(base_name, []).append(c["id"])

        topics: list[dict[str, Any]] = []
        for doc_title, c_ids in doc_groups.items():
            topics.append({"name": doc_title, "parent_name": None, "chunk_ids": c_ids})
            # Subtopics based on chunks if many
            if len(c_ids) > 2:
                mid = len(c_ids) // 2
                topics.append(
                    {
                        "name": f"{doc_title} - Part 1",
                        "parent_name": doc_title,
                        "chunk_ids": c_ids[:mid],
                    }
                )
                topics.append(
                    {
                        "name": f"{doc_title} - Part 2",
                        "parent_name": doc_title,
                        "chunk_ids": c_ids[mid:],
                    }
                )

        return topics
