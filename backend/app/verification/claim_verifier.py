"""Layer 4 semantic NLI claim verification ensuring sentences are strictly entailed by sources."""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.adapters import LLMAdapter, get_llm_adapter
from app.adapters.base import ScoredChunk
from app.core.logging import logger
from app.verification.citation_validator import ValidatedSentence

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "generation" / "prompts"


class ClaimVerificationResponse(BaseModel):
    """Structured NLI verification verdict."""

    label: Literal["ENTAILED", "NEUTRAL", "CONTRADICTED"] = Field(
        default="ENTAILED",
        description="NLI relationship label between premise and claim",
    )
    reason: str = Field(
        default="Claim verified by premise.",
        description="Short explanation for the label",
    )


class ClaimVerificationResult(BaseModel):
    """Summary of claim-level semantic verification."""

    entailed_sentences: list[ValidatedSentence]
    dropped_sentences: list[str]
    dropped_reasons: list[str]
    all_entailed: bool


class ClaimVerifier:
    """Verifies each answer sentence claim against the cited source premises."""

    def __init__(
        self,
        llm: LLMAdapter | None = None,
        prompt_version: str = "claim_verifier_v1.txt",
    ) -> None:
        self.llm = llm or get_llm_adapter()
        self.prompt_file = PROMPTS_DIR / prompt_version
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        if self.prompt_file.exists():
            return self.prompt_file.read_text(encoding="utf-8").strip()
        return (
            "You are a strict fact-checker. Given a PREMISE (source text) and a CLAIM, "
            "answer with one label: ENTAILED, NEUTRAL, CONTRADICTED. Return JSON: "
            '{"label": "...", "reason": "..."}'
        )

    @staticmethod
    def _rule_based_nli(premise: str, claim: str) -> ClaimVerificationResponse:
        """Heuristic NLI evaluation when running deterministic offline test harness."""
        p_lower = premise.lower()
        c_lower = claim.lower()

        # If claim (without bullets or numbering) is directly in premise, it is entailed
        clean_claim = re.sub(r"^[-*•\s\d\.)]+", "", c_lower).strip()
        if len(clean_claim) > 10 and clean_claim in p_lower:
            return ClaimVerificationResponse(
                label="ENTAILED",
                reason="Claim is directly sourced from premise text.",
            )

        # If claim is structured as Q&A (e.g. "**Ans:** ..." or "**Answer:** ..."),
        # evaluate the answer portion
        eval_claim = clean_claim
        for marker in ["**ans:**", "ans:", "**answer:**", "answer:"]:
            if marker in c_lower:
                ans_part = c_lower.split(marker, 1)[1].strip()
                clean_ans = re.sub(r"^[-*•\s\d\.)]+", "", ans_part).strip(" \t\n\r.!?\"'")
                if len(clean_ans) > 5 and clean_ans in p_lower:
                    return ClaimVerificationResponse(
                        label="ENTAILED",
                        reason="Answer content is directly sourced from premise text.",
                    )
                if len(clean_ans) > 5:
                    eval_claim = clean_ans
                break

        # Extract informative content words
        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "and",
            "or",
            "in",
            "on",
            "at",
            "to",
            "for",
            "with",
            "this",
            "that",
            "these",
            "those",
            "by",
            "from",
            "via",
            "through",
            "into",
            "also",
            "its",
            "their",
            "our",
            "been",
        }
        claim_words = [
            w for w in re.findall(r"\b\w+\b", eval_claim) if len(w) > 2 and w not in stop_words
        ]

        if not claim_words:
            return ClaimVerificationResponse(label="ENTAILED", reason="Trivial claim entailed.")

        # Check for explicit contradictions (polarity mismatch against the relevant premise clause)
        negations = [r"\bnot\b", r"\bnever\b", r"\bcannot\b", r"\bno\b", r"\bneither\b"]
        claim_has_neg = any(re.search(n, eval_claim) for n in negations)

        premise_lines = [s.strip() for s in re.split(r"[.!?\n]+", p_lower) if len(s.strip()) > 5]
        best_line = ""
        best_line_overlap = 0.0

        for line in premise_lines:
            matched_in_line = sum(1 for w in claim_words if w in line)
            line_overlap = matched_in_line / len(claim_words)
            if line_overlap > best_line_overlap:
                best_line_overlap = line_overlap
                best_line = line

        if best_line_overlap >= 0.50:
            line_has_neg = any(re.search(n, best_line) for n in negations)
            if claim_has_neg and not line_has_neg:
                return ClaimVerificationResponse(
                    label="CONTRADICTED",
                    reason="Claim contains negation contradicting positive source premise.",
                )
            if line_has_neg and not claim_has_neg:
                return ClaimVerificationResponse(
                    label="CONTRADICTED",
                    reason="Claim contains assertion contradicting negative source premise.",
                )

        matched = sum(1 for w in claim_words if w in p_lower)
        overlap = matched / len(claim_words)

        # At least 60% of informative content words must exist in premise
        if overlap >= 0.60:
            return ClaimVerificationResponse(
                label="ENTAILED",
                reason=f"Claim is supported by source ({overlap:.0%} overlap).",
            )
        else:
            return ClaimVerificationResponse(
                label="NEUTRAL",
                reason=f"Details not fully grounded in premise ({overlap:.0%} overlap).",
            )

    async def verify_claim(self, premise: str, claim: str) -> ClaimVerificationResponse:
        """Checks whether premise strictly entails claim."""
        from app.adapters.llm import MockLLMAdapter

        if isinstance(self.llm, MockLLMAdapter) or not (await self.llm.health_check()):
            return self._rule_based_nli(premise, claim)

        user_content = f"PREMISE (source text):\n{premise}\n\nCLAIM:\n{claim}"

        try:
            parsed, _ = await self.llm.generate_structured(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_model=ClaimVerificationResponse,
                temperature=0.0,
            )
            if isinstance(parsed, ClaimVerificationResponse) and parsed.label in {
                "ENTAILED",
                "NEUTRAL",
                "CONTRADICTED",
            }:
                return parsed
            return self._rule_based_nli(premise, claim)
        except Exception as exc:
            logger.warning("LLM claim verification failed: %s. Using heuristic NLI.", exc)
            return self._rule_based_nli(premise, claim)

    async def verify_sentences(
        self,
        sentences: list[ValidatedSentence],
        block_map: dict[str, ScoredChunk],
    ) -> ClaimVerificationResult:
        """Evaluates all sentences and drops any non-entailed claims."""
        entailed: list[ValidatedSentence] = []
        dropped: list[str] = []
        reasons: list[str] = []

        for sent in sentences:
            # Build premise from cited blocks
            premises: list[str] = []
            for cite in sent.citations:
                chunk = block_map.get(cite.block_id)
                if chunk:
                    premises.append(chunk.text)

            combined_premise = "\n".join(premises)
            nli_verdict = await self.verify_claim(combined_premise, sent.text)

            if nli_verdict.label == "ENTAILED":
                entailed.append(sent)
            else:
                dropped.append(sent.text)
                preview = sent.text[:35]
                reasons.append(
                    f"Claim rejected as {nli_verdict.label}: '{preview}...' ({nli_verdict.reason})"
                )

        all_entailed = len(dropped) == 0 and len(entailed) > 0

        return ClaimVerificationResult(
            entailed_sentences=entailed,
            dropped_sentences=dropped,
            dropped_reasons=reasons,
            all_entailed=all_entailed,
        )
