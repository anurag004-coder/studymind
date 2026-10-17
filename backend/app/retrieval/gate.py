"""Relevance gate deciding whether to proceed with LLM generation or abstain immediately."""

import re
from collections import Counter

from pydantic import BaseModel, Field

from app.adapters.base import ScoredChunk
from app.core.config import settings

STOP_WORDS = {
    "what",
    "where",
    "when",
    "which",
    "who",
    "whom",
    "whose",
    "why",
    "how",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "about",
    "against",
    "between",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "from",
    "up",
    "down",
    "out",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "can",
    "will",
    "just",
    "should",
    "now",
    "tell",
    "explain",
    "describe",
    "generate",
    "generates",
    "generating",
    "question",
    "questions",
    "answer",
    "answers",
    "mark",
    "marks",
    "based",
    "provided",
    "material",
    "materials",
    "create",
    "give",
    "write",
    "test",
    "quiz",
}


class GateDecision(BaseModel):
    """Decision made by the relevance gate before invoking generation."""

    should_abstain: bool = Field(
        ..., description="Whether the system must abstain due to insufficient evidence"
    )
    best_score: float = Field(
        ..., description="Highest reranker relevance score among retrieved chunks"
    )
    coverage: float = Field(
        ..., description="Ratio of key query terms found in top retrieved chunks"
    )
    threshold: float = Field(..., description="Configured minimum relevance score threshold")
    reason: str = Field(
        ..., description="Decision reason: 'passed', 'insufficient_evidence', or 'no_results'"
    )
    closest_chunks: list[ScoredChunk] = Field(
        default_factory=list,
        description="Top 1-3 closest passages returned when abstaining",
    )
    suggested_rephrases: list[str] = Field(
        default_factory=list,
        description="Suggested alternative questions based on closest available passages",
    )


class RelevanceGate:
    """Evaluates retrieved chunks to guard against generating ungrounded answers."""

    def __init__(self, min_relevance_score: float = settings.MIN_RELEVANCE_SCORE) -> None:
        self.threshold = min_relevance_score

    @staticmethod
    def extract_key_tokens(query: str) -> list[str]:
        """Extracts non-stopword alphanumeric terms from the query."""
        tokens = re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", query.lower())
        return [t for t in tokens if t not in STOP_WORDS]

    def compute_coverage(self, key_tokens: list[str], chunks: list[ScoredChunk]) -> float:
        """Computes proportion of key query tokens present in the retrieved chunks."""
        if not key_tokens:
            return 1.0
        if not chunks:
            return 0.0

        combined_text = " ".join(c.text.lower() for c in chunks)
        found = sum(1 for token in key_tokens if token in combined_text)
        return float(found / len(key_tokens))

    def generate_suggestions(self, query: str, closest_chunks: list[ScoredChunk]) -> list[str]:
        """Generates 1 to 3 query rephrase suggestions from closest candidate passages."""
        if not closest_chunks:
            return [
                "Try asking about topics covered in your uploaded documents.",
                "Ensure the relevant document has finished processing.",
            ]

        # Extract frequent informative words from closest chunk texts
        candidate_words: list[str] = []
        for c in closest_chunks:
            words = re.findall(r"\b[a-zA-Z]{4,}\b", c.text.lower())
            candidate_words.extend([w for w in words if w not in STOP_WORDS])

        common = [word for word, count in Counter(candidate_words).most_common(3)]
        suggestions: list[str] = []
        for term in common:
            suggestions.append(f"What does the material explain about {term}?")

        if not suggestions:
            suggestions.append("Try rephrasing with specific terminology from your study notes.")

        return suggestions[:3]

    def evaluate(
        self,
        query: str,
        reranked_chunks: list[ScoredChunk],
        custom_threshold: float | None = None,
    ) -> GateDecision:
        # Check if query is asking for summary, overview, or study item generation from material
        is_summary_query = any(
            p in query.lower()
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
                "material",
                "generate question",
                "question and answer",
                "questions and answers",
                "1 mark",
                "3 mark",
                "marks",
                "quiz",
                "flashcard",
                "test me",
            ]
        )

        if custom_threshold is not None:
            threshold = custom_threshold
        elif is_summary_query:
            threshold = 0.15
        else:
            threshold = self.threshold

        if not reranked_chunks:
            return GateDecision(
                should_abstain=True,
                best_score=0.0,
                coverage=0.0,
                threshold=threshold,
                reason="no_results",
                closest_chunks=[],
                suggested_rephrases=self.generate_suggestions(query, []),
            )

        best_score = float(reranked_chunks[0].score)
        key_tokens = self.extract_key_tokens(query)
        coverage = self.compute_coverage(key_tokens, reranked_chunks[:3])
        closest = reranked_chunks[:3]

        # Gate logic per ANTI_HALLUCINATION.md Layer 1
        if best_score < threshold:
            return GateDecision(
                should_abstain=True,
                best_score=round(best_score, 4),
                coverage=round(coverage, 4),
                threshold=threshold,
                reason="insufficient_evidence",
                closest_chunks=closest,
                suggested_rephrases=self.generate_suggestions(query, closest),
            )

        # Check if query is a general or explanatory study query
        is_general_query = any(
            p in query.lower()
            for p in [
                "overview",
                "summar",
                "explain",
                "topic",
                "concept",
                "main",
                "teach",
                "cover",
                "material",
                "document",
                "notes",
                "what is",
                "how is",
            ]
        )
        if is_summary_query:
            min_coverage = 0.0
        elif is_general_query:
            min_coverage = 0.20
        else:
            min_coverage = 0.40

        # If key terms are missing, abstain to prevent hallucinations
        if key_tokens and coverage < min_coverage:
            return GateDecision(
                should_abstain=True,
                best_score=round(best_score, 4),
                coverage=round(coverage, 4),
                threshold=threshold,
                reason="insufficient_coverage",
                closest_chunks=closest,
                suggested_rephrases=self.generate_suggestions(query, closest),
            )

        return GateDecision(
            should_abstain=False,
            best_score=round(best_score, 4),
            coverage=round(coverage, 4),
            threshold=threshold,
            reason="passed",
            closest_chunks=closest,
            suggested_rephrases=[],
        )
