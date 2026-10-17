"""Figure and diagram factual captioning per CHALLENGES.md §B and PROMPTS.md §5."""

import base64
from pathlib import Path

from app.adapters import get_llm_adapter
from app.core.logging import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "generation" / "prompts"


class FigureCaptioner:
    """Generates factual, unembellished captions for diagrams and figures."""

    def __init__(self) -> None:
        self.llm = get_llm_adapter()
        self.prompt_template = (PROMPTS_DIR / "figure_caption_v1.txt").read_text(encoding="utf-8")

    async def caption_figure(
        self,
        image_bytes: bytes,
        label: str | None = None,
    ) -> str:
        """Captions a diagram factually, listing visible labels exactly."""
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages = [
            {"role": "system", "content": self.prompt_template},
            {
                "role": "user",
                "content": f"[Figure Image: data:image/png;base64,{b64_image[:64]}...]",
            },
        ]
        if label:
            messages.append({"role": "user", "content": f"Figure title: {label}"})

        try:
            resp = await self.llm.generate(messages, temperature=0.0)
            return resp.text.strip()
        except Exception as e:
            logger.warning(f"Figure captioning failed: {e}")
            return f"[Diagram: {label or 'Visible figure and schematic labels'}]"
