"""File Security and Malware Scanning per TECH_REQUIREMENTS.md §9 and PRD.md §5."""

import io
import logging
import zipfile
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# Standard EICAR test string for anti-malware verification
EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

# Known dangerous executable headers
EXECUTABLE_HEADERS = [
    (b"MZ", "Windows PE executable / DLL"),
    (b"\x7fELF", "Linux ELF executable"),
    (b"\xfe\xed\xfa\xce", "Mach-O 32-bit binary"),
    (b"\xfe\xed\xfa\xcf", "Mach-O 64-bit binary"),
    (b"\xce\xfa\xed\xfe", "Mach-O reverse binary"),
    (b"\xcf\xfa\xed\xfe", "Mach-O 64-bit reverse binary"),
]

# Suspicious script patterns
SUSPICIOUS_PAYLOADS = [
    b"eval(base64_decode",
    b"system($_GET",
    b"shell_exec(",
    b"passthru(",
    b"powershell -encodedcommand",
    b"<script>alert(",
]


class FileSecurityScanner:
    """Validates file integrity, sniffing magic bytes, zip bombs, and malware signatures."""

    @classmethod
    def scan_and_validate(cls, filename: str, file_bytes: bytes, mime_type: str = "") -> None:
        """Runs the complete security validation suite on uploaded file bytes.

        Raises HTTPException on any security violation.
        """
        # 1. Size check
        max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum upload limit of {settings.MAX_UPLOAD_MB} MB",
            )

        if len(file_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes)",
            )

        # 2. Executable header check (disallow masquerading executables)
        for header_bytes, desc in EXECUTABLE_HEADERS:
            if file_bytes.startswith(header_bytes):
                logger.warning("Rejected malicious executable file '%s': %s", filename, desc)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Security violation: Executable binaries are disallowed ({desc})",
                )

        # 3. Malware signature scan (EICAR and shell triggers)
        if settings.ENABLE_MALWARE_SCAN:
            if EICAR_SIGNATURE in file_bytes:
                logger.warning("EICAR test malware signature detected in upload '%s'", filename)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security violation: Malware signature detected (EICAR test string)",
                )

            for payload in SUSPICIOUS_PAYLOADS:
                if payload in file_bytes.lower():
                    logger.warning("Suspicious script payload detected in '%s'", filename)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Security violation: Disallowed script or shell payload detected",
                    )

        # 4. Extension and Magic Bytes Sniffing
        ext = Path(filename).suffix.lower()

        if ext == ".pdf":
            # PDF must contain %PDF- in the header bytes
            if b"%PDF-" not in file_bytes[:1024]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid PDF file: Missing standard '%PDF-' magic header",
                )

        elif ext == ".png":
            # PNG signature is 89 50 4E 47 0D 0A 1A 0A
            if not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid PNG image: Magic header does not match PNG format",
                )

        elif ext in (".jpg", ".jpeg"):
            # JPEG starts with FF D8 FF
            if not file_bytes.startswith(b"\xff\xd8\xff"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid JPEG image: Magic header does not match JPEG format",
                )

        elif ext in (".docx", ".pptx"):
            # Office Open XML files are ZIP archives starting with PK\x03\x04
            if not file_bytes.startswith(b"PK\x03\x04"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid {ext.upper()} document: Missing standard ZIP container header",
                )
            # Zip bomb & decompression ratio check
            cls._check_zip_bomb(file_bytes, filename)

        elif ext in (".txt", ".md"):
            # Text files must not contain binary null bytes
            if b"\x00" in file_bytes[:4096]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid text file: Detected binary null bytes in plain text file",
                )
            try:
                file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Text file must be valid UTF-8 or ASCII encoded",
                ) from None

    @classmethod
    def _check_zip_bomb(cls, file_bytes: bytes, filename: str) -> None:
        """Protects against zip bomb denial-of-service decompression attacks."""
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                total_uncompressed = 0
                compressed_size = max(1, len(file_bytes))

                for info in zf.infolist():
                    total_uncompressed += info.file_size
                    # Limit entry count
                    if len(zf.infolist()) > 5000:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Security violation: Archive exceeds maximum allowed entries",
                        )

                ratio = total_uncompressed / compressed_size
                if ratio > settings.MAX_ZIP_RATIO:
                    logger.warning(
                        "Zip bomb detected in '%s': ratio %.1f exceeds max %.1f",
                        filename,
                        ratio,
                        settings.MAX_ZIP_RATIO,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Security violation: Archive compression ratio "
                            f"({ratio:.1f}) exceeds safe limit"
                        ),
                    )
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Corrupt or malformed ZIP document container",
            ) from None
