"""OCR Engine handling image preprocessing, local OCR, and Vision-LLM fallback."""

import io
from typing import Any

import pytesseract  # type: ignore[import-untyped]
from PIL import Image
from pytesseract import Output  # type: ignore[import-untyped]

from app.core.logging import logger
from app.ingestion.models import ExtractedBlock, ParsedPage
from app.ingestion.preprocessor import ImagePreprocessor
from app.ingestion.vision_ocr import VisionOCR


class OCREngine:
    """Hybrid OCR engine: Preprocessing -> Local OCR -> Vision-LLM Fallback."""

    def __init__(self) -> None:
        self.vision_ocr = VisionOCR()

    @staticmethod
    async def _ocr_with_windows_media(image_bytes: bytes, page_no: int) -> ParsedPage | None:
        """Transcribes image using Windows 10/11 native Media OCR engine."""
        try:
            import winrt.windows.graphics.imaging as imaging
            import winrt.windows.media.ocr as ocr
            import winrt.windows.storage.streams as streams

            engine = ocr.OcrEngine.try_create_from_user_profile_languages()
            if not engine:
                return None

            writer = streams.DataWriter()
            writer.write_bytes(bytearray(image_bytes))
            ibuffer = writer.detach_buffer()
            mem_stream = streams.InMemoryRandomAccessStream()
            await mem_stream.write_async(ibuffer)
            mem_stream.seek(0)

            decoder = await imaging.BitmapDecoder.create_async(mem_stream)
            software_bitmap = await decoder.get_software_bitmap_async()
            result = await engine.recognize_async(software_bitmap)

            blocks: list[ExtractedBlock] = []
            full_text_lines: list[str] = []

            for idx, line in enumerate(result.lines):
                line_text = line.text.strip()
                if not line_text:
                    continue
                full_text_lines.append(line_text)

                min_x, min_y, max_x, max_y = 10000.0, 10000.0, 0.0, 0.0
                for w in line.words:
                    min_x = min(min_x, float(w.bounding_rect.x))
                    min_y = min(min_y, float(w.bounding_rect.y))
                    max_x = max(max_x, float(w.bounding_rect.x + w.bounding_rect.width))
                    max_y = max(max_y, float(w.bounding_rect.y + w.bounding_rect.height))

                bbox = (
                    [min_x, min_y, max_x, max_y]
                    if max_x > min_x
                    else [50.0, 50.0 + idx * 30.0, 550.0, 75.0 + idx * 30.0]
                )
                blocks.append(
                    ExtractedBlock(
                        page_no=page_no,
                        bbox=bbox,
                        block_type="paragraph",
                        text=line_text,
                        reading_order=idx,
                    )
                )

            if blocks:
                logger.info(
                    "Windows Media OCR successfully extracted %d lines from page %d",
                    len(blocks),
                    page_no,
                )
                return ParsedPage(
                    page_no=page_no,
                    has_text_layer=True,
                    blocks=blocks,
                    raw_text="\n".join(full_text_lines),
                    ocr_confidence=0.96,
                    image_bytes=image_bytes,
                )
        except Exception as exc:
            logger.info("Windows Media OCR unavailable: %s", exc)
        return None

    async def ocr_page_image(
        self,
        image_bytes: bytes,
        page_no: int,
        force_vision_ocr: bool = False,
    ) -> ParsedPage:
        """Processes an image or scanned page, extracting text blocks and confidence scores."""
        # 1. Image preprocessing (deskew, denoise, CLAHE contrast)
        preprocessed_bytes, _ = ImagePreprocessor.preprocess_image(image_bytes)

        # 2. Local OCR path (Windows Media OCR or Tesseract)
        if not force_vision_ocr:
            win_page = await self._ocr_with_windows_media(preprocessed_bytes, page_no)
            if win_page:
                return win_page

            try:
                pil_image = Image.open(io.BytesIO(preprocessed_bytes))
                ocr_data: dict[str, list[Any]] = pytesseract.image_to_data(
                    pil_image, output_type=Output.DICT
                )

                # Parse words, confidences, and bounding boxes
                blocks: list[ExtractedBlock] = []
                confidences: list[float] = []
                current_line_words: list[str] = []
                current_line_bbox: list[float] = [0.0, 0.0, 0.0, 0.0]

                n_boxes = len(ocr_data.get("text", []))
                for i in range(n_boxes):
                    word = ocr_data["text"][i].strip()
                    conf = float(ocr_data["conf"][i])

                    if not word or conf < 0:
                        continue

                    confidences.append(conf / 100.0)
                    x, y, w, h = (
                        float(ocr_data["left"][i]),
                        float(ocr_data["top"][i]),
                        float(ocr_data["width"][i]),
                        float(ocr_data["height"][i]),
                    )

                    if not current_line_words:
                        current_line_bbox = [x, y, x + w, y + h]
                    else:
                        current_line_bbox[0] = min(current_line_bbox[0], x)
                        current_line_bbox[1] = min(current_line_bbox[1], y)
                        current_line_bbox[2] = max(current_line_bbox[2], x + w)
                        current_line_bbox[3] = max(current_line_bbox[3], y + h)

                    current_line_words.append(word)

                    # Line break on punctuation or length
                    if word.endswith((".", "!", "?")) or len(current_line_words) >= 12:
                        blocks.append(
                            ExtractedBlock(
                                page_no=page_no,
                                bbox=list(current_line_bbox),
                                block_type="paragraph",
                                text=" ".join(current_line_words),
                                reading_order=len(blocks),
                            )
                        )
                        current_line_words = []

                if current_line_words:
                    blocks.append(
                        ExtractedBlock(
                            page_no=page_no,
                            bbox=list(current_line_bbox),
                            block_type="paragraph",
                            text=" ".join(current_line_words),
                            reading_order=len(blocks),
                        )
                    )

                avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

                # If local OCR succeeded with satisfactory confidence (>= 0.80), return
                if avg_conf >= 0.80 and blocks:
                    return ParsedPage(
                        page_no=page_no,
                        has_text_layer=True,
                        blocks=blocks,
                        raw_text="\n".join(b.text for b in blocks),
                        ocr_confidence=avg_conf,
                        image_bytes=preprocessed_bytes,
                    )

            except Exception as e:
                logger.info(f"Local Tesseract OCR unavailable or failed: {e}. Using Vision-LLM.")

        # 3. Vision-LLM Fallback (for handwriting, math formulas, scans without local OCR)
        vision_result = await self.vision_ocr.transcribe_image(preprocessed_bytes)
        fallback_blocks = [
            ExtractedBlock(
                page_no=page_no,
                bbox=[50.0, 50.0, 550.0, 750.0],  # Full-page region
                block_type="paragraph",
                text=vision_result.text,
                reading_order=0,
            )
        ]

        return ParsedPage(
            page_no=page_no,
            has_text_layer=False,
            blocks=fallback_blocks,
            raw_text=vision_result.text,
            ocr_confidence=vision_result.confidence,
            image_bytes=preprocessed_bytes,
        )
