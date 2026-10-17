"""Format-aware ingestion router dispatching to specialized parsers."""

from pathlib import Path

from app.ingestion.models import ParsedPage
from app.ingestion.ocr_engine import OCREngine
from app.ingestion.office_parser import OfficeParser
from app.ingestion.pdf_parser import PyMuPDFParser


class DocumentParserRouter:
    """Dispatches document bytes to the correct parser based on extension and content."""

    def __init__(self) -> None:
        self.ocr_engine = OCREngine()

    async def parse_document(
        self,
        file_bytes: bytes,
        filename: str,
        mime: str,
        force_vision_ocr: bool = False,
    ) -> list[ParsedPage]:
        """Routes file bytes to appropriate layout parser or OCR engine."""
        ext = Path(filename).suffix.lower()

        # 1. PDF
        if ext == ".pdf":
            pages = PyMuPDFParser.parse_pdf_bytes(file_bytes, render_images=True)
            # Check for scanned pages lacking text layer
            for page in pages:
                if not page.has_text_layer and page.image_bytes:
                    ocr_page = await self.ocr_engine.ocr_page_image(
                        image_bytes=page.image_bytes,
                        page_no=page.page_no,
                        force_vision_ocr=force_vision_ocr,
                    )
                    page.blocks = ocr_page.blocks
                    page.raw_text = ocr_page.raw_text
                    page.ocr_confidence = ocr_page.ocr_confidence
            return pages

        # 2. Standalone image (PNG, JPG, JPEG)
        elif ext in (".png", ".jpg", ".jpeg"):
            ocr_page = await self.ocr_engine.ocr_page_image(
                image_bytes=file_bytes,
                page_no=1,
                force_vision_ocr=force_vision_ocr,
            )
            return [ocr_page]

        # 3. Word Document (DOCX)
        elif ext == ".docx":
            return OfficeParser.parse_docx_bytes(file_bytes)

        # 4. PowerPoint Presentation (PPTX)
        elif ext == ".pptx":
            return OfficeParser.parse_pptx_bytes(file_bytes)

        # 5. Plain text or Markdown
        elif ext in (".txt", ".md"):
            return OfficeParser.parse_text_bytes(file_bytes, filename=filename)

        else:
            raise ValueError(f"Unsupported file format for parsing: {ext}")
