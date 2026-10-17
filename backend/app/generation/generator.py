"""Constrained grounded answer generator enforcing citation block IDs and verbatim quotes."""

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.adapters import LLMAdapter, get_llm_adapter
from app.adapters.base import ScoredChunk
from app.core.logging import logger

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class RawCitation(BaseModel):
    """Raw citation referencing a context block ID and quote."""

    chunk_id: str = Field(..., description="Context block identifier e.g. C1")
    quote: str = Field(..., description="Short exact supporting quote from the cited chunk")


class RawAnswerSentence(BaseModel):
    """An individual sentence in the grounded answer."""

    text: str = Field(..., description="Sentence text directly supported by the citations")
    citations: list[RawCitation] = Field(
        default_factory=list,
        description="At least one citation supporting this sentence",
    )


class GroundedAnswerPayload(BaseModel):
    """Structured JSON schema output per ANTI_HALLUCINATION.md Layer 2."""

    answerable: bool = Field(
        default=True,
        description="Whether the question can be answered from the provided context",
    )
    answer_sentences: list[RawAnswerSentence] = Field(
        default_factory=list,
        description="List of verified answer sentences with citations",
    )
    missing_info: str | None = Field(
        default=None,
        description="Explanation of what is missing if question is unanswerable or partial",
    )


def extract_clean_sentences(text: str) -> list[str]:
    """Extracts coherent, non-fragmented sentences from potentially wrapped OCR or raw text."""
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    sentences: list[str] = []
    dangling_words = {
        "of",
        "and",
        "or",
        "to",
        "in",
        "with",
        "the",
        "a",
        "an",
        "for",
        "from",
        "by",
        "is",
        "are",
        "at",
        "as",
        "into",
        "their",
        "its",
        "which",
    }
    for p in paragraphs:
        lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
        merged_para_parts: list[str] = []
        for ln in lines:
            if not merged_para_parts:
                merged_para_parts.append(ln)
            else:
                prev = merged_para_parts[-1]
                last_word = prev.split()[-1].lower().strip(".,;:?!") if prev.split() else ""
                if prev.endswith("-"):
                    merged_para_parts[-1] = prev[:-1] + ln
                elif not re.search(r"[.!?:]$", prev) or last_word in dangling_words:
                    merged_para_parts[-1] = prev + " " + ln
                elif ln and ln[0].islower():
                    merged_para_parts[-1] = prev + " " + ln
                else:
                    merged_para_parts.append(ln)
        merged_para = " ".join(merged_para_parts)

        # Split on sentence terminators followed by space
        sents = re.split(r"(?<=[.!?])\s+", merged_para)
        for s in sents:
            s_clean = s.strip().lstrip("•-* \t0123456789.)")
            if len(s_clean) >= 15:
                sentences.append(s_clean)
    return sentences


def format_1mark_qa(sent: str) -> tuple[str, str]:
    """Generates an objective 1-mark question prompt and factual answer from a sentence."""
    s = sent.strip().rstrip(".")
    # Pattern 1: Term : Description
    m_col = re.match(r"^([A-Za-z0-9\s\(\)/\-]{3,40}):\s*(.+)$", s)
    if m_col:
        topic = m_col.group(1).strip()
        desc = m_col.group(2).strip()
        stem = f"What is defined as **{topic}** according to the material?"
        ans = f"{topic}: {desc}."
        return stem, ans

    # Pattern 2: Term - / – Description
    m_dash = re.match(r"^([0-9\.\s]*)([A-Za-z0-9\s]{3,35})\s*[–\-]\s*(.+)$", s)
    if m_dash:
        topic = m_dash.group(2).strip()
        desc = m_dash.group(3).strip()
        stem = f"What is the function of **{topic}** as stated in the notes?"
        ans = f"{topic} – {desc}."
        return stem, ans

    # Pattern 3: Subject is / are Description
    m_is = re.match(r"^([A-Za-z0-9\s]{3,35})\s+(?:is|are)\s+(.+)$", s, re.IGNORECASE)
    if m_is and not m_is.group(1).lower().startswith(
        ("what", "why", "how", "this", "that", "these", "there", "it", "which", "where")
    ):
        topic = m_is.group(1).strip()
        stem = f"How is **{topic}** defined in the provided study material?"
        ans = f"{s}."
        return stem, ans

    # Pattern 4: Informative noun extraction
    words = [
        w
        for w in re.findall(r"\b[A-Za-z]{3,}\b", s)
        if w.lower()
        not in {
            "the",
            "all",
            "these",
            "this",
            "that",
            "with",
            "from",
            "have",
            "been",
            "which",
            "what",
            "answer",
            "question",
            "explain",
            "describe",
            "define",
        }
    ]
    topic = words[0].capitalize() if words else "the concept"
    stem = f"What key detail is stated regarding **{topic}** in the material?"
    ans = f"{s}."
    return stem, ans


class GroundedGenerator:
    """Generates grounded answers strictly from retrieved context blocks."""

    def __init__(
        self,
        llm: LLMAdapter | None = None,
        prompt_version: str = "answer_v1.txt",
    ) -> None:
        self.llm = llm or get_llm_adapter()
        self.prompt_file = PROMPTS_DIR / prompt_version
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        if self.prompt_file.exists():
            return self.prompt_file.read_text(encoding="utf-8").strip()
        return (
            "You are a study assistant that answers ONLY from the provided CONTEXT blocks. "
            "Never use outside knowledge. Every sentence must cite at least one block ID and "
            "quote. Output valid JSON matching the schema."
        )

    @staticmethod
    def _sanitize_untrusted_text(text: str) -> str:
        """Sanitizes document text to prevent prompt injection attempts."""
        pattern = (
            r"(?i)\b(ignore previous instructions|system override|"
            r"you are now|disregard all rules)\b"
        )
        sanitized = re.sub(pattern, "[DEFUSED_DIRECTIVE]", text)
        return sanitized

    def format_context_blocks(
        self, chunks: list[ScoredChunk]
    ) -> tuple[str, dict[str, ScoredChunk]]:
        """Formats context blocks as numbered, securely tagged untrusted containers."""
        formatted_blocks: list[str] = []
        block_map: dict[str, ScoredChunk] = {}

        for idx, chunk in enumerate(chunks, start=1):
            block_id = f"C{idx}"
            block_map[block_id] = chunk

            sanitized_text = self._sanitize_untrusted_text(chunk.text)
            doc_id = chunk.document_id or "doc"
            page = chunk.page_start

            block_str = (
                f'<untrusted_document_context id="{block_id}" doc="{doc_id}" page="{page}">\n'
                f"{sanitized_text}\n"
                f"</untrusted_document_context>"
            )
            formatted_blocks.append(block_str)

        return "\n\n".join(formatted_blocks), block_map

    async def generate_answer(
        self,
        question: str,
        chunks: list[ScoredChunk],
        chat_history: list[dict[str, str]] | None = None,
    ) -> tuple[GroundedAnswerPayload, dict[str, ScoredChunk]]:
        """Invokes structured LLM generation with untrusted context wrapping."""
        if not chunks:
            return (
                GroundedAnswerPayload(
                    answerable=False,
                    answer_sentences=[],
                    missing_info="No relevant study material was retrieved for this question.",
                ),
                {},
            )

        context_str, block_map = self.format_context_blocks(chunks)

        history_str = ""
        if chat_history:
            history_lines = [
                f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                for m in chat_history[-4:]
            ]
            history_str = (
                "CHAT HISTORY (for reference resolution only, not a source of facts):\n"
                + "\n".join(history_lines)
                + "\n\n"
            )

        q_lower = question.lower()
        is_marks_query = bool(
            re.search(r"\b(?:1|2|3|5|10)\s*[- ]?marks?\b", q_lower)
            or re.search(
                r"\bmarks?\s*(?:based|allocation|distribution|like|wise|questions?)\b", q_lower
            )
            or any(
                k in q_lower
                for k in [
                    "1 mark",
                    "3 mark",
                    "1-mark",
                    "3-mark",
                    "based on marks",
                    "by marks",
                    "marks like",
                    "mark questions",
                    "marks q&a",
                    "marks questions",
                    "questions and answers",
                    "questions with answers",
                    "q&a based on marks",
                ]
            )
        )

        marks_instruction = ""
        if is_marks_query:
            marks_instruction = (
                "\n\nSPECIAL INSTRUCTION: Generate questions and answers by marks "
                "(1 mark and 3 mark) based strictly on the provided material.\n"
                "- Provide 1-mark questions (definitions, single facts, objective recall).\n"
                "- Provide 3-mark questions (topics requiring structured 3-point explanation).\n"
                "- Every sentence in every answer MUST cite the exact block ID and quote."
            )

        user_content = (
            f"CONTEXT:\n{context_str}\n\n{history_str}QUESTION: {question}{marks_instruction}"
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            parsed, raw_resp = await self.llm.generate_structured(
                messages=messages,
                response_model=GroundedAnswerPayload,
                temperature=0.0,
            )

            if isinstance(parsed, GroundedAnswerPayload):
                payload = parsed
            else:
                payload = GroundedAnswerPayload.model_validate(parsed)

            # Fallback for mock LLM or empty model construction
            if not payload.answer_sentences and payload.answerable:
                # Specialized synthesis for 1-mark and 3-mark Q&A
                if is_marks_query:
                    marks_sentences: list[RawAnswerSentence] = []
                    # Collect all clean sentences across blocks using extract_clean_sentences
                    usable_facts: list[tuple[str, str, str]] = []  # (block_id, sentence, quote)
                    for b_id, chunk in block_map.items():
                        if not chunk or not chunk.text:
                            continue
                        clean_lines = extract_clean_sentences(chunk.text)
                        for sent in clean_lines:
                            words = sent.split()
                            quote = " ".join(words[: min(7, len(words))])
                            usable_facts.append((b_id, sent, quote))

                    if usable_facts:
                        # 1-Mark Q&A 1
                        b_id1, sent1, q1 = usable_facts[0]
                        stem1, ans1 = format_1mark_qa(sent1)
                        marks_sentences.append(
                            RawAnswerSentence(
                                text=f"🎯 **[1 Mark] Q1:** {stem1} **Ans:** {ans1}",
                                citations=[RawCitation(chunk_id=b_id1, quote=q1)],
                            )
                        )

                        # 1-Mark Q&A 2 (if second fact exists)
                        if len(usable_facts) > 1:
                            b_id2, sent2, q2 = usable_facts[1]
                            stem2, ans2 = format_1mark_qa(sent2)
                            marks_sentences.append(
                                RawAnswerSentence(
                                    text=f"🎯 **[1 Mark] Q2:** {stem2} **Ans:** {ans2}",
                                    citations=[RawCitation(chunk_id=b_id2, quote=q2)],
                                )
                            )

                        # 3-Mark Q&A with structured 3 points
                        p_pool = usable_facts[2:6] if len(usable_facts) >= 5 else usable_facts[:3]
                        b_id3, sent3, q3 = p_pool[0]
                        words3 = [
                            w
                            for w in re.findall(r"\b[A-Za-z]{3,}\b", sent3)
                            if w.lower()
                            not in {
                                "the",
                                "all",
                                "these",
                                "this",
                                "that",
                                "with",
                                "from",
                                "which",
                                "what",
                            }
                        ]
                        topic3 = words3[0].capitalize() if words3 else "the subject"
                        points_str = " ".join(
                            f"({p_idx}) {p_sent.rstrip('.')}."
                            for p_idx, (_, p_sent, _) in enumerate(p_pool[:3], start=1)
                        )
                        marks_sentences.append(
                            RawAnswerSentence(
                                text=(
                                    f"📑 **[3 Marks] Q3:** Explain the key aspects of **{topic3}** "
                                    f"as described in the notes. **Ans:** {points_str}"
                                ),
                                citations=[RawCitation(chunk_id=b_id3, quote=q3)],
                            )
                        )

                        return GroundedAnswerPayload(
                            answerable=True,
                            answer_sentences=marks_sentences,
                        ), block_map

                # Standard synthesis fallback
                q_words = set(re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", q_lower))

                # Collect all candidate sentences from all retrieved blocks
                candidates: list[dict[str, Any]] = []

                for b_id, chunk in block_map.items():
                    if not chunk or not chunk.text:
                        continue
                    # Split into candidate sentences
                    raw_sentences = extract_clean_sentences(chunk.text)
                    for s in raw_sentences:
                        s_lower = s.lower()
                        s_words = set(re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", s_lower))
                        overlap = len(q_words.intersection(s_words))
                        score = float(overlap)

                        # Bonus for definition or explanatory markers
                        if any(
                            p in s_lower
                            for p in [
                                " is ",
                                " are ",
                                " refers to ",
                                " process of ",
                                " defined as ",
                                " meaning ",
                                " ensures ",
                                " allows ",
                                " prevents ",
                                " verifies ",
                                " provides ",
                                " guarantees ",
                            ]
                        ):
                            score += 2.0

                        # Penalize questions / question headers as answer statements
                        if s.strip().endswith("?") or s.strip().lower().startswith(
                            ("what is ", "why is ", "how is ", "who is ", "answer:", "q.", "q:")
                        ):
                            score -= 4.0

                        # Bonus for query keyword presence
                        for qw in q_words:
                            if qw in s_lower:
                                score += 0.5

                        # Penalize document titles/headings when other informative sentences exist
                        if (
                            s.strip()
                            .lower()
                            .startswith(
                                (
                                    "lab practical:",
                                    "experiment:",
                                    "lab experiment:",
                                    "chapter ",
                                    "section ",
                                )
                            )
                        ):
                            score -= 2.0

                        # Bonus for implementation details when query asks how/implement/code
                        if any(
                            k in q_lower
                            for k in ["how", "implement", "code", "python", "library", "function"]
                        ):
                            if any(
                                k in s_lower
                                for k in [
                                    "import",
                                    "from ",
                                    "tokenize",
                                    "nltk",
                                    "practical implementation",
                                    "using python",
                                    "code",
                                    "def ",
                                ]
                            ):
                                score += 2.5

                        # Bonus for contrast/differences
                        if any(
                            k in q_lower
                            for k in ["difference", "unlike", "contrast", "vs", "split"]
                        ):
                            if any(
                                k in s_lower
                                for k in [
                                    "unlike",
                                    "difference",
                                    "split",
                                    "instead",
                                    "whereas",
                                    "handles",
                                ]
                            ):
                                score += 2.5

                        # Check if query is summary or topic overview
                        is_summary_query = any(
                            p in q_lower
                            for p in [
                                "summar",
                                "overview",
                                "topic",
                                "main point",
                                "key point",
                                "page",
                                "pdf",
                                "document",
                                "notes",
                                "what is this",
                                "tell me about",
                            ]
                        )
                        if is_summary_query:
                            score += 1.0
                            if any(k in s for k in [":", "-", "•", "(", ")", "="]):
                                score += 2.0
                            if any(
                                k in s_lower
                                for k in [
                                    "component",
                                    "system",
                                    "input",
                                    "error",
                                    "control",
                                    "detector",
                                    "element",
                                    "process",
                                    "function",
                                    "unit",
                                ]
                            ):
                                score += 1.5

                        # Bonus for general questions/summary/overview
                        if any(
                            k in q_lower
                            for k in [
                                "what",
                                "explain",
                                "summar",
                                "overview",
                                "about",
                                "concept",
                                "main",
                                "material",
                                "notes",
                            ]
                        ):
                            if any(
                                k in s_lower
                                for k in [
                                    "process",
                                    "used",
                                    "important",
                                    "allows",
                                    "key",
                                    "result",
                                    "involves",
                                ]
                            ):
                                score += 1.0

                        if b_id == "C1":
                            score += 0.2

                        candidates.append(
                            {
                                "sentence": s,
                                "block_id": b_id,
                                "score": score,
                                "words": s_words,
                            }
                        )

                # Sort candidates by score descending
                candidates.sort(key=lambda c: c["score"], reverse=True)

                is_summary_query = any(
                    p in q_lower
                    for p in [
                        "summar",
                        "overview",
                        "topic",
                        "main point",
                        "key point",
                        "page",
                        "pdf",
                        "document",
                        "notes",
                        "what is this",
                        "tell me about",
                    ]
                )

                selected_sentences: list[RawAnswerSentence] = []
                used_words: set[str] = set()

                for cand in candidates:
                    if cand["score"] <= 0 and selected_sentences and not is_summary_query:
                        break
                    # Avoid near-duplicate sentences
                    cand_words = cand["words"]
                    if (
                        used_words
                        and len(cand_words.intersection(used_words)) / max(1, len(cand_words))
                        > 0.65
                    ):
                        continue

                    sentence_text = cand["sentence"]
                    if (
                        is_summary_query
                        and not sentence_text.startswith("- ")
                        and not sentence_text.startswith("• ")
                    ):
                        sentence_text = f"- {sentence_text}"
                    words = cand["sentence"].split()
                    quote = " ".join(words[: min(7, len(words))])
                    selected_sentences.append(
                        RawAnswerSentence(
                            text=sentence_text,
                            citations=[RawCitation(chunk_id=cand["block_id"], quote=quote)],
                        )
                    )
                    used_words.update(cand_words)

                    max_limit = 5 if is_summary_query else 2
                    if len(selected_sentences) >= max_limit:
                        break

                if not selected_sentences:
                    top_chunk = block_map.get("C1")
                    if top_chunk and top_chunk.text:
                        sents = [
                            s.strip() for s in re.split(r"[.!?]\s+", top_chunk.text) if s.strip()
                        ]
                        fallback_sent = sents[0] if sents else top_chunk.text
                        words = fallback_sent.split()
                        quote = " ".join(words[: min(7, len(words))])
                        selected_sentences.append(
                            RawAnswerSentence(
                                text=fallback_sent,
                                citations=[RawCitation(chunk_id="C1", quote=quote)],
                            )
                        )

                payload = GroundedAnswerPayload(
                    answerable=True,
                    answer_sentences=selected_sentences,
                )

            return payload, block_map

        except Exception as exc:
            logger.warning("Grounded generation call failed: %s. Returning unanswerable.", exc)
            return (
                GroundedAnswerPayload(
                    answerable=False,
                    answer_sentences=[],
                    missing_info="Failed to generate verified response from context.",
                ),
                block_map,
            )
