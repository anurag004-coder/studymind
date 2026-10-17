"""End-to-end grounded generation pipeline coordinating retrieval, gating,
generator, validation, and composition.
"""

from app.core.logging import logger
from app.generation.composer import FinalChatResponse, ResponseComposer
from app.generation.generator import GroundedGenerator
from app.retrieval.service import RetrievalResult, RetrievalService
from app.verification.citation_validator import CitationValidator
from app.verification.claim_verifier import ClaimVerifier


class GroundedGenerationPipeline:
    """Full anti-hallucination grounded answering pipeline for StudyMind."""

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        generator: GroundedGenerator | None = None,
        citation_validator: CitationValidator | None = None,
        claim_verifier: ClaimVerifier | None = None,
        composer: ResponseComposer | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()
        self.generator = generator or GroundedGenerator()
        self.citation_validator = citation_validator or CitationValidator()
        self.claim_verifier = claim_verifier or ClaimVerifier()
        self.composer = composer or ResponseComposer()

    async def answer_question(
        self,
        question: str,
        user_id: str,
        workspace_id: str,
        document_ids: list[str] | None = None,
        chat_history: list[dict[str, str]] | None = None,
        top_k: int = 6,
        strict_mode: bool = False,
        page: int | None = None,
    ) -> FinalChatResponse:
        """Executes 5-layer anti-hallucination pipeline strictly scoped to user_id."""
        logger.info("Executing grounded answer pipeline for user %s: '%s'", user_id, question)

        # Layer 1: Hybrid Retrieval & Relevance Gate
        retrieval_res: RetrievalResult = await self.retrieval_service.retrieve(
            query=question,
            user_id=user_id,
            workspace_id=workspace_id,
            document_ids=document_ids,
            chat_history=chat_history,
            top_k=top_k,
            page=page,
        )

        if retrieval_res.gate_decision.should_abstain:
            logger.info(
                "Layer 1 gate triggered early abstention for user %s (reason: %s)",
                user_id,
                retrieval_res.gate_decision.reason,
            )
            reason_str = retrieval_res.gate_decision.reason
            return self.composer.compose_abstain_response(
                gate_decision=retrieval_res.gate_decision,
                missing_info=f"Insufficient evidence in study notes ({reason_str}).",
            )

        # Layer 2: Constrained LLM Generation
        payload, block_map = await self.generator.generate_answer(
            question=question,
            chunks=retrieval_res.chunks,
            chat_history=chat_history,
        )

        if not payload.answerable or not payload.answer_sentences:
            logger.info(
                "Layer 2 generator reported question unanswerable: %s", payload.missing_info
            )
            return self.composer.compose_abstain_response(
                gate_decision=retrieval_res.gate_decision,
                missing_info=payload.missing_info or "Material does not answer this question.",
            )

        # Layer 3: Deterministic Citation Validation
        citation_val = self.citation_validator.validate_payload(
            payload=payload,
            block_map=block_map,
        )

        if not citation_val.passed_sentences:
            logger.warning(
                "Layer 3 validation dropped all sentences due to citation/numeric errors: %s",
                citation_val.rejection_reasons,
            )
            err_msg = (
                "Generated statements failed citation or numerical verification "
                "against source material."
            )
            return self.composer.compose_abstain_response(
                gate_decision=retrieval_res.gate_decision,
                missing_info=err_msg,
                dropped_claims=len(citation_val.dropped_sentences),
            )

        # Layer 4: Semantic NLI Claim Verification
        claim_ver = await self.claim_verifier.verify_sentences(
            sentences=citation_val.passed_sentences,
            block_map=block_map,
        )

        total_dropped = len(citation_val.dropped_sentences) + len(claim_ver.dropped_sentences)

        if not claim_ver.entailed_sentences:
            logger.warning(
                "Layer 4 NLI verification rejected all remaining claims: %s",
                claim_ver.dropped_reasons,
            )
            return self.composer.compose_abstain_response(
                gate_decision=retrieval_res.gate_decision,
                missing_info="Claims could not be verified by source material.",
                dropped_claims=total_dropped,
            )

        # In strict mode, any dropped claim causes full abstention
        if strict_mode and total_dropped > 0:
            logger.info("Strict mode enabled and %d claims dropped -> abstaining", total_dropped)
            return self.composer.compose_abstain_response(
                gate_decision=retrieval_res.gate_decision,
                missing_info="Some details were dropped under strict verification mode.",
                dropped_claims=total_dropped,
            )

        # Layer 5: Response Composition
        missing_note = payload.missing_info
        if total_dropped > 0:
            dropped_note = (
                f"{total_dropped} detail(s) could not be verified against the source text."
            )
            missing_note = f"{missing_note}; {dropped_note}" if missing_note else dropped_note

        final_response = self.composer.compose_grounded_response(
            sentences=claim_ver.entailed_sentences,
            best_score=retrieval_res.gate_decision.best_score,
            dropped_claims=total_dropped,
            missing_info=missing_note,
        )

        return final_response
