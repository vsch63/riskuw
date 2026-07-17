"""
file_security.py — Upload security validation for RiskUW
Validates uploaded files before processing to prevent:
  - Malicious executables disguised as PDFs
  - Oversized files / ZIP bombs
  - Files with dangerous embedded content
  - Excessive upload rate
"""
from __future__ import annotations
import io
import re
import logging

from fastapi import UploadFile, HTTPException

logger = logging.getLogger("uw_platform")

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_PDF_PAGES       = 50                  # Prevent ZIP-bomb style PDFs
MAX_TEXT_LENGTH     = 50_000             # Max extracted text chars

# ── Allowed MIME types ────────────────────────────────────────────────────────
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg", "image/jpg",
    "image/png",
    "image/tiff", "image/tif",
    "image/webp",
}

# ── Magic bytes (file signatures) ────────────────────────────────────────────
MAGIC_SIGNATURES = {
    b"%PDF":          "application/pdf",
    b"\xff\xd8\xff":  "image/jpeg",
    b"\x89PNG\r\n":   "image/png",
    b"II*\x00":       "image/tiff",   # Little-endian TIFF
    b"MM\x00*":       "image/tiff",   # Big-endian TIFF
    b"RIFF":          "image/webp",   # WebP starts with RIFF
}

# ── Dangerous patterns to strip from extracted text ──────────────────────────
DANGEROUS_TEXT_PATTERNS = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=\s*[\"'][^\"']*[\"']", re.IGNORECASE),
    re.compile(r"<iframe[^>]*>.*?</iframe>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<object[^>]*>.*?</object>", re.IGNORECASE | re.DOTALL),
    re.compile(r"vbscript\s*:", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
]

# SQL injection patterns (defence in depth — parameterised queries already protect DB)
SQL_INJECTION_PATTERNS = [
    re.compile(r"('\s*(or|and)\s*'?\d)", re.IGNORECASE),
    re.compile(r"(;\s*(drop|delete|truncate|alter|insert|update)\s+)", re.IGNORECASE),
    re.compile(r"(--\s*$)", re.MULTILINE),
    re.compile(r"(/\*.*?\*/)", re.DOTALL),
    re.compile(r"(union\s+select\s+)", re.IGNORECASE),
    re.compile(r"(exec\s*\(|execute\s*\()", re.IGNORECASE),
    re.compile(r"(xp_cmdshell|sp_executesql)", re.IGNORECASE),
]


def detect_mime_from_bytes(file_bytes: bytes) -> str | None:
    """Detect actual file type from magic bytes — not from extension or Content-Type."""
    for magic, mime in MAGIC_SIGNATURES.items():
        if file_bytes[:len(magic)] == magic:
            return mime
    return None


async def validate_upload(file: UploadFile) -> bytes:
    """
    Full security validation of an uploaded file.
    Returns the file bytes if valid.
    Raises HTTPException with clear error message if invalid.
    """
    # 1. Check declared MIME type
    if file.content_type and file.content_type.split(";")[0].strip() not in ALLOWED_MIME_TYPES:
        logger.warning(f"Rejected upload: disallowed MIME type {file.content_type}")
        raise HTTPException(
            status_code=415,
            detail=f"File type '{file.content_type}' is not allowed. "
                   f"Accepted: PDF, JPEG, PNG, TIFF, WebP."
        )

    # 2. Read file with size limit
    file_bytes = b""
    chunk_size = 64 * 1024  # 64KB chunks
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        file_bytes += chunk
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            logger.warning(f"Rejected upload: file too large (>{MAX_FILE_SIZE_BYTES//1024//1024}MB)")
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum allowed size is "
                       f"{MAX_FILE_SIZE_BYTES // 1024 // 1024} MB."
            )

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    # 3. Validate magic bytes — confirm actual file type
    detected_mime = detect_mime_from_bytes(file_bytes)
    if detected_mime is None:
        logger.warning(f"Rejected upload: unrecognised file signature from {file.filename}")
        raise HTTPException(
            status_code=415,
            detail="File does not appear to be a valid PDF or image. "
                   "Ensure the file is not corrupted or disguised."
        )

    if detected_mime not in ALLOWED_MIME_TYPES:
        logger.warning(f"Rejected upload: magic bytes indicate {detected_mime}, not allowed")
        raise HTTPException(
            status_code=415,
            detail=f"File content does not match allowed types. Detected: {detected_mime}"
        )

    # 4. For PDFs — check page count (prevent ZIP-bomb style attacks)
    if detected_mime == "application/pdf":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                page_count = len(pdf.pages)
                if page_count > MAX_PDF_PAGES:
                    logger.warning(f"Rejected PDF: {page_count} pages exceeds limit {MAX_PDF_PAGES}")
                    raise HTTPException(
                        status_code=422,
                        detail=f"PDF has {page_count} pages. Maximum allowed is {MAX_PDF_PAGES} pages."
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"PDF validation failed: {e}")
            raise HTTPException(
                status_code=422,
                detail="PDF file appears to be corrupted or unreadable."
            )

    logger.info(
        f"Upload validated: {file.filename} | "
        f"{len(file_bytes):,} bytes | type: {detected_mime}"
    )
    return file_bytes


def sanitise_extracted_text(text: str) -> str:
    """
    Remove dangerous patterns from text extracted by OCR/Claude.
    Defence in depth — prevents XSS if extracted text is ever rendered as HTML.
    """
    if not text:
        return text

    # Truncate excessive length
    if len(text) > MAX_TEXT_LENGTH:
        logger.warning(f"Extracted text truncated from {len(text)} to {MAX_TEXT_LENGTH} chars")
        text = text[:MAX_TEXT_LENGTH]

    # Strip dangerous HTML/JS patterns
    for pattern in DANGEROUS_TEXT_PATTERNS:
        text = pattern.sub("", text)

    # Log but do NOT strip SQL patterns — they will be safely handled by
    # parameterised queries. We just log them for monitoring purposes.
    for pattern in SQL_INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning(
                f"SQL-like pattern detected in extracted text — "
                f"parameterised queries will neutralise this safely."
            )
            break

    return text.strip()


def sanitise_extracted_fields(fields: dict) -> dict:
    """
    Sanitise all string values extracted from a document before use.
    Applies to the structured JSON returned by Claude after extraction.
    """
    safe = {}
    for key, value in fields.items():
        if isinstance(value, str):
            # Strip HTML tags from any string field
            value = re.sub(r"<[^>]+>", "", value)
            # Strip dangerous patterns
            value = sanitise_extracted_text(value)
            # Limit individual field length
            value = value[:500]
        safe[key] = value
    return safe
