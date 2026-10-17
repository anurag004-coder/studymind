"""PyMuPDF PDF layout-aware parser per ARCHITECTURE.md §2."""

from typing import Any

import pymupdf

from app.ingestion.models import ExtractedBlock, ParsedPage


class PyMuPDFParser:
    """Extracts text layers, bounding boxes, font attributes, and tables from PDF documents."""

    @classmethod
    def parse_pdf_bytes(
        cls,
        pdf_bytes: bytes,
        render_images: bool = True,
        dpi: int = 150,
    ) -> list[ParsedPage]:
        """Parses a PDF byte stream into structured ParsedPage objects."""
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        parsed_pages: list[ParsedPage] = []

        try:
            for page_index in range(len(doc)):
                page = doc[page_index]
                page_no = page_index + 1

                # 1. Detect text layer
                raw_text = page.get_text().strip()
                has_text_layer = len(raw_text) >= 20

                # 2. Extract tables if any
                table_bboxes: list[tuple[float, float, float, float]] = []
                extracted_table_blocks: list[ExtractedBlock] = []

                if hasattr(page, "find_tables"):
                    try:
                        tables = page.find_tables()
                        for tab_idx, tab in enumerate(tables):
                            bbox = list(tab.bbox)
                            table_bboxes.append(tuple(bbox))  # type: ignore[arg-type]
                            # Format table as Markdown
                            markdown_table = tab.to_markdown()
                            if markdown_table.strip():
                                extracted_table_blocks.append(
                                    ExtractedBlock(
                                        page_no=page_no,
                                        bbox=bbox,
                                        block_type="table",
                                        text=markdown_table.strip(),
                                        reading_order=tab_idx,
                                    )
                                )
                    except Exception:
                        pass

                # 3. Extract text blocks with font and layout attributes
                page_dict: dict[str, Any] = page.get_text("dict")
                extracted_text_blocks: list[ExtractedBlock] = []

                font_sizes: list[float] = []
                raw_blocks = page_dict.get("blocks", [])

                # Collect font sizes for median calculation
                for block in raw_blocks:
                    if block.get("type") == 0:  # text block
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                if span.get("text", "").strip():
                                    font_sizes.append(float(span.get("size", 10.0)))

                median_font_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 11.0

                for block_order, block in enumerate(raw_blocks):
                    if block.get("type") != 0:
                        continue  # Skip image-only blocks in text parser

                    bbox = list(block.get("bbox", [0.0, 0.0, 0.0, 0.0]))

                    # Check if this block is inside an extracted table to avoid duplicates
                    is_in_table = False
                    for t_bbox in table_bboxes:
                        if (
                            bbox[0] >= t_bbox[0] - 2
                            and bbox[1] >= t_bbox[1] - 2
                            and bbox[2] <= t_bbox[2] + 2
                            and bbox[3] <= t_bbox[3] + 2
                        ):
                            is_in_table = True
                            break
                    if is_in_table:
                        continue

                    # Assemble text and determine dominant formatting
                    block_lines: list[str] = []
                    max_size = 0.0
                    is_bold = False

                    for line in block.get("lines", []):
                        line_text = "".join(
                            span.get("text", "") for span in line.get("spans", [])
                        ).strip()
                        if line_text:
                            block_lines.append(line_text)
                        for span in line.get("spans", []):
                            size = float(span.get("size", 0.0))
                            if size > max_size:
                                max_size = size
                            flags = span.get("flags", 0)
                            if flags & 2 or "bold" in span.get("font", "").lower():
                                is_bold = True

                    text = "\n".join(block_lines).strip()
                    if not text:
                        continue

                    # Heading detection heuristic
                    block_type = "paragraph"
                    if max_size >= median_font_size * 1.25 or (
                        is_bold and len(text.splitlines()) <= 2 and len(text) < 100
                    ):
                        block_type = "heading"

                    extracted_text_blocks.append(
                        ExtractedBlock(
                            page_no=page_no,
                            bbox=bbox,
                            block_type=block_type,  # type: ignore[arg-type]
                            text=text,
                            reading_order=block_order,
                            font_size=max_size,
                            is_bold=is_bold,
                        )
                    )

                # Merge text and table blocks, sorted by vertical y0 coordinate
                all_blocks = extracted_text_blocks + extracted_table_blocks
                all_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

                # Reassign final reading_order
                for r_idx, b in enumerate(all_blocks):
                    b.reading_order = r_idx

                # 4. Render page image preview
                image_bytes: bytes | None = None
                if render_images:
                    try:
                        pix = page.get_pixmap(dpi=dpi)
                        image_bytes = pix.tobytes("png")
                    except Exception:
                        image_bytes = None

                parsed_pages.append(
                    ParsedPage(
                        page_no=page_no,
                        has_text_layer=has_text_layer,
                        blocks=all_blocks,
                        raw_text=raw_text,
                        ocr_confidence=1.0 if has_text_layer else None,
                        image_bytes=image_bytes,
                    )
                )

        finally:
            doc.close()

        return parsed_pages
