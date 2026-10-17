"""Document cleaning and normalization utilities per ARCHITECTURE.md §2."""

import re
import unicodedata

from app.ingestion.models import ExtractedBlock, ParsedPage


class TextCleaner:
    """Cleans extracted document text without semantic alteration."""

    # Regex matching hyphenation at line breaks: e.g. "tem-\nperature" -> "temperature"
    HYPHENATION_REGEX = re.compile(r"(\b[a-zA-Z]{2,})-\n([a-zA-Z]{2,}\b)")

    # Regex matching common page number patterns
    PAGE_NUMBER_REGEX = re.compile(
        r"^(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+|[-–—]\s*\d+\s*[-–—]|\d+)$",
        re.IGNORECASE,
    )

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Normalizes unicode characters, repairs line-break hyphenation, and cleans whitespace."""
        if not text:
            return ""

        # 1. Unicode normalization (NFKC decomposes compatibility chars and canonicalizes)
        norm = unicodedata.normalize("NFKC", text)

        # 2. Fix hyphenation across linebreaks
        norm = cls.HYPHENATION_REGEX.sub(r"\1\2", norm)

        # 3. Normalize whitespace (preserve paragraphs but remove excessive carriage returns)
        norm = re.sub(r"\r\n", "\n", norm)
        norm = re.sub(r"[ \t]+", " ", norm)
        norm = re.sub(r"\n{3,}", "\n\n", norm)

        return norm.strip()

    @classmethod
    def detect_and_strip_repeated_headers_footers(cls, pages: list[ParsedPage]) -> list[ParsedPage]:
        """Detects repeated running headers and footers across pages and removes them."""
        if len(pages) < 2:
            return pages

        # Track candidate header texts (top of page) and footer texts (bottom of page)
        header_occurrences: dict[str, int] = {}
        footer_occurrences: dict[str, int] = {}

        for page in pages:
            if not page.blocks:
                continue

            # First block is candidate header, last block is candidate footer
            first_block_text = page.blocks[0].text.strip()
            last_block_text = page.blocks[-1].text.strip()

            if 0 < len(first_block_text) < 120:
                header_occurrences[first_block_text] = (
                    header_occurrences.get(first_block_text, 0) + 1
                )
            if 0 < len(last_block_text) < 120:
                footer_occurrences[last_block_text] = footer_occurrences.get(last_block_text, 0) + 1

        # A block is considered a repeated header/footer if it appears on >= 2 pages
        # or matches page numbers
        threshold = 2
        repeated_headers = {
            txt
            for txt, count in header_occurrences.items()
            if count >= threshold or cls.PAGE_NUMBER_REGEX.match(txt)
        }
        repeated_footers = {
            txt
            for txt, count in footer_occurrences.items()
            if count >= threshold or cls.PAGE_NUMBER_REGEX.match(txt)
        }

        cleaned_pages: list[ParsedPage] = []
        for page in pages:
            cleaned_blocks: list[ExtractedBlock] = []
            for idx, block in enumerate(page.blocks):
                cleaned_text = cls.normalize_text(block.text)
                if not cleaned_text:
                    continue

                # Strip if matching repeated header at top or footer at bottom
                is_top = idx == 0
                is_bottom = idx == len(page.blocks) - 1

                if is_top and (
                    cleaned_text in repeated_headers or cls.PAGE_NUMBER_REGEX.match(cleaned_text)
                ):
                    continue
                if is_bottom and (
                    cleaned_text in repeated_footers or cls.PAGE_NUMBER_REGEX.match(cleaned_text)
                ):
                    continue

                cleaned_blocks.append(
                    ExtractedBlock(
                        page_no=block.page_no,
                        bbox=block.bbox,
                        block_type=block.block_type,
                        text=cleaned_text,
                        reading_order=len(cleaned_blocks),
                        font_size=block.font_size,
                        is_bold=block.is_bold,
                    )
                )

            cleaned_pages.append(
                ParsedPage(
                    page_no=page.page_no,
                    has_text_layer=page.has_text_layer,
                    blocks=cleaned_blocks,
                    raw_text="\n\n".join(b.text for b in cleaned_blocks),
                    ocr_confidence=page.ocr_confidence,
                    image_bytes=page.image_bytes,
                )
            )

        return cleaned_pages
