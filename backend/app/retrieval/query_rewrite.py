"""Query rewriter module resolving pronouns and decomposing multi-part questions
per PROMPTS.md §2.
"""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.adapters import get_llm_adapter
from app.core.logging import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "generation" / "prompts"


class QueryRewriteResponse(BaseModel):
    """Pydantic schema for structured LLM query rewriting response."""

    queries: list[str] = Field(
        default_factory=list,
        description="List of 1 to 3 standalone rewritten queries",
    )


class QueryRewriteResult(BaseModel):
    """Result of query rewriting pipeline."""

    original_query: str
    standalone_query: str
    queries: list[str]


class QueryRewriter:
    """Rewrites conversational queries using chat history and decomposes multi-part questions."""

    def __init__(self, prompt_version: str = "query_rewrite_v1.txt") -> None:
        self.prompt_file = PROMPTS_DIR / prompt_version
        self.system_prompt = self._load_prompt()
        self.llm = get_llm_adapter()

    def _load_prompt(self) -> str:
        if self.prompt_file.exists():
            return self.prompt_file.read_text(encoding="utf-8").strip()
        return (
            "Rewrite the final user question into a standalone search query using the "
            "chat history to resolve pronouns. Do not add facts. If the question has multiple "
            'parts, output up to 3 sub-queries. Return JSON: {"queries": ["..."]}'
        )

    @staticmethod
    def _format_chat_history(chat_history: list[dict[str, str]]) -> str:
        formatted_lines: list[str] = []
        for msg in chat_history[-6:]:  # Keep recent context
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "").strip()
            if content:
                formatted_lines.append(f"{role}: {content}")
        return "\n".join(formatted_lines)

    @staticmethod
    def _heuristic_pronoun_rewrite(query: str, chat_history: list[dict[str, str]]) -> str:
        """Lightweight heuristic fallback to resolve simple pronouns (it, this, that)."""
        lower = query.lower()
        pronouns = [
            r"\bit\b",
            r"\bits\b",
            r"\bthis\b",
            r"\bthat\b",
            r"\bthese\b",
            r"\bthose\b",
            r"\bthey\b",
            r"\btheir\b",
        ]
        has_pronoun = any(re.search(p, lower) for p in pronouns)
        if not has_pronoun or not chat_history:
            return query

        ignored = {
            "tell",
            "about",
            "what",
            "where",
            "when",
            "which",
            "who",
            "whom",
            "why",
            "how",
            "give",
            "show",
            "explain",
            "describe",
            "with",
            "from",
            "into",
            "that",
            "this",
            "there",
            "here",
            "user",
            "assistant",
            "please",
            "help",
            "know",
            "think",
        }

        # Search backward for the most recent user topic
        last_topic = ""
        for msg in reversed(chat_history):
            content = msg.get("content", "")
            words = [
                w
                for w in re.findall(r"\b[A-Za-z0-9_-]+\b", content)
                if len(w) > 3 and w.lower() not in ignored
            ]
            if words:
                last_topic = words[0]
                break

        if last_topic:
            return f"{query} ({last_topic})"
        return query

    async def rewrite(
        self,
        query: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> QueryRewriteResult:
        """Rewrites the input query using chat history."""
        clean_query = query.strip()
        if not clean_query:
            return QueryRewriteResult(
                original_query="",
                standalone_query="",
                queries=[],
            )

        if not chat_history:
            # Check for multiple questions joined by and/also
            sub_parts = [
                p.strip()
                for p in re.split(
                    r"\b(?:and also|and what is|and why does)\b", clean_query, flags=re.I
                )
                if p.strip()
            ]
            queries = sub_parts if len(sub_parts) > 1 else [clean_query]
            return QueryRewriteResult(
                original_query=clean_query,
                standalone_query=clean_query,
                queries=queries[:3],
            )

        history_str = self._format_chat_history(chat_history)
        user_prompt = (
            f"CHAT HISTORY (for reference resolution only, not a source of facts):\n"
            f"{history_str}\n\n"
            f"QUESTION: {clean_query}"
        )

        try:
            parsed, _ = await self.llm.generate_structured(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=QueryRewriteResponse,
                temperature=0.0,
            )
            response_model = (
                parsed
                if isinstance(parsed, QueryRewriteResponse)
                else QueryRewriteResponse.model_validate(parsed)
            )

            generated_queries = [q.strip() for q in response_model.queries if q and q.strip()]
            if not generated_queries:
                fallback = self._heuristic_pronoun_rewrite(clean_query, chat_history)
                generated_queries = [fallback]

            return QueryRewriteResult(
                original_query=clean_query,
                standalone_query=generated_queries[0],
                queries=generated_queries[:3],
            )
        except Exception as exc:
            logger.warning("Query rewrite LLM call failed: %s. Using heuristic fallback.", exc)
            fallback = self._heuristic_pronoun_rewrite(clean_query, chat_history)
            return QueryRewriteResult(
                original_query=clean_query,
                standalone_query=fallback,
                queries=[fallback],
            )
