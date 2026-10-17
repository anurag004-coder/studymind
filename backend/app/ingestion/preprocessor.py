"""Image preprocessing utilities (deskew, denoise, contrast enhancement) per CHALLENGES.md §B."""

import io
import math

import cv2
import numpy as np
from PIL import Image


class ImagePreprocessor:
    """Preprocesses document and scanned page images prior to OCR."""

    @staticmethod
    def bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
        """Decodes image bytes to OpenCV BGR array."""
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            # Fallback using PIL
            pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return img

    @staticmethod
    def cv2_to_bytes(img: np.ndarray, format: str = ".png") -> bytes:
        """Encodes an OpenCV image to compressed image bytes."""
        success, encoded = cv2.imencode(format, img)
        if not success:
            pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()
        return encoded.tobytes()

    @classmethod
    def estimate_skew_angle(cls, gray: np.ndarray) -> float:
        """Estimates document skew angle in degrees using image moments / min area rect."""
        # Invert colors: text as foreground
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if coords.shape[0] < 50:
            return 0.0

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle
        else:
            angle = -angle

        # Cap unrealistic angles
        if abs(angle) > 30.0 or math.isnan(angle):
            return 0.0
        return float(angle)

    @classmethod
    def deskew(cls, img: np.ndarray) -> tuple[np.ndarray, float]:
        """Detects and corrects skew if angle exceeds threshold."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        angle = cls.estimate_skew_angle(gray)

        if abs(angle) < 0.5:
            return img, 0.0

        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        return rotated, angle

    @classmethod
    def enhance_contrast_and_denoise(cls, img: np.ndarray) -> np.ndarray:
        """Enhances contrast using CLAHE and removes background scanner noise."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        # Denoise
        denoised = cv2.medianBlur(gray, 3)

        # Contrast Limited Adaptive Histogram Equalization (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # Convert back to BGR for uniform handling
        return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    @classmethod
    def preprocess_image(cls, image_bytes: bytes) -> tuple[bytes, float]:
        """Runs the complete preprocessing pipeline on image bytes."""
        try:
            img = cls.bytes_to_cv2(image_bytes)
            deskewed, skew_angle = cls.deskew(img)
            enhanced = cls.enhance_contrast_and_denoise(deskewed)
            output_bytes = cls.cv2_to_bytes(enhanced, format=".png")
            return output_bytes, skew_angle
        except Exception:
            # Safe fallback: return original untouched image
            return image_bytes, 0.0
