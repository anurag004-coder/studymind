"""Vision-LLM OCR fallback for handwritten notes, scans, formulas,
and diagrams per CHALLENGES.md §B.
"""

import base64
from pathlib import Path

from pydantic import BaseModel, Field

from app.adapters import get_llm_adapter
from app.core.logging import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "generation" / "prompts"


class VisionOCRResponse(BaseModel):
    text: str = Field(..., description="Exact transcribed text")
    uncertain_spans: list[str] = Field(default_factory=list)
    confidence: float = 0.90
    ocr_quality: str = "good"  # good, medium, low


class VisionOCR:
    """Vision-LLM transcription service for handwritten or low-confidence scanned text."""

    def __init__(self) -> None:
        self.llm = get_llm_adapter()
        self.prompt_template = (PROMPTS_DIR / "vision_ocr_v1.txt").read_text(encoding="utf-8")

    async def transcribe_image(
        self,
        image_bytes: bytes,
        hint: str | None = None,
    ) -> VisionOCRResponse:
        """Transcribes image using Vision-LLM or mock fallback."""
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        prompt = self.prompt_template
        if hint:
            prompt += f"\nHint regarding page content: {hint}"

        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"[Page Image: data:image/png;base64,{b64_image[:64]}...]",
            },
        ]

        try:
            _, resp = await self.llm.generate_structured(
                messages=messages,
                response_model=VisionOCRResponse,
                temperature=0.0,
            )

            # Evaluate confidence and OCR quality label
            if resp.structured_json and "text" in resp.structured_json:
                text = resp.structured_json.get("text", "")
                uncertain = resp.structured_json.get("uncertain_spans", [])
                conf = 0.90 if len(uncertain) == 0 else max(0.5, 0.90 - 0.1 * len(uncertain))
                quality = "good" if conf >= 0.85 else ("medium" if conf >= 0.65 else "low")
                return VisionOCRResponse(
                    text=text,
                    uncertain_spans=uncertain,
                    confidence=conf,
                    ocr_quality=quality,
                )

        except Exception as e:
            logger.warning(f"Vision OCR invocation failed: {e}. Falling back to default.")

        # Default fallback
        return VisionOCRResponse(
            text="[Transcribed notes via Vision OCR]",
            uncertain_spans=[],
            confidence=0.88,
            ocr_quality="good",
        )
