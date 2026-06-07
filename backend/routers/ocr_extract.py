"""
routers/ocr_extract.py
─────────────────────────────────────────────────────────────────────────────
POST /underwriting/extract-document
  - Accepts PDF or image upload
  - Extracts text using pdfplumber (PDF) or pymupdf (image)
  - Sends to Claude API to map to UW fields
  - Returns structured JSON matching EvaluateRequest fields
"""
from __future__ import annotations
import io
import os
import json
import logging
import re
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("uw_platform")
router = APIRouter()


# ── Field mapping prompt ──────────────────────────────────────────────────────
EXTRACTION_PROMPT = """You are an insurance underwriting assistant. Extract structured data from the following insurance proposal form or medical document text.

Return ONLY a valid JSON object with these fields (omit any field you cannot find):

{
  "applicant_ref": "string — applicant/proposal reference number",
  "product_code": "string — insurance product code if mentioned",
  "age": "integer — age in years",
  "gender": "string — MALE or FEMALE",
  "state": "string — 2-letter state code or full state name",
  "face_amount": "number — sum assured / coverage amount in rupees",
  "coverage_term_yrs": "integer — policy term in years",
  "tobacco_status": "string — NEVER, NON_TOBACCO, SMOKER, or TOBACCO",
  "height_inches": "number — height in inches (convert from cm if needed: cm/2.54)",
  "weight_lbs": "number — weight in pounds (convert from kg if needed: kg*2.205)",
  "systolic_bp": "integer — systolic blood pressure",
  "diastolic_bp": "integer — diastolic blood pressure",
  "diabetes_type": "string — NONE, TYPE1, or TYPE2",
  "heart_condition": "string — NONE, HYPERTENSION, CAD, or other",
  "annual_income": "number — annual income in rupees",
  "existing_coverage": "number — existing life cover in rupees",
  "hiv_positive": "boolean",
  "cirrhosis": "boolean",
  "stroke_history": "boolean",
  "kidney_disease": "boolean",
  "depression_history": "boolean",
  "copd": "boolean",
  "hazardous_activity": "boolean",
  "alcohol_drinks_week": "integer — drinks per week",
  "a1c": "number — HbA1c percentage",
  "occupation_class": "integer — 1, 2, 3, or 4",
  "occupation_title": "string",
  "full_name": "string — applicant full name",
  "date_of_birth": "string — YYYY-MM-DD format",
  "email": "string",
  "phone": "string"
}

Rules:
- Return ONLY the JSON object, no explanation, no markdown
- For boolean fields: true if condition present/positive, false if absent/negative/none
- Convert all currency to INR numbers (no commas, no symbols)
- If a value is ambiguous or not found, omit that field entirely
- For tobacco: any smoking/tobacco use → SMOKER, quit > 1yr → NON_TOBACCO, never → NEVER

Document text:
"""


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
                # Also extract tables
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            row_text = " | ".join(str(cell or "") for cell in row)
                            if row_text.strip():
                                text_parts.append(row_text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise HTTPException(500, f"PDF extraction failed: {str(e)}")


def _extract_text_from_image(file_bytes: bytes) -> str:
    """Extract text from image using pymupdf."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text = page.get_text()
            if text:
                text_parts.append(text)
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        # Try as image
        try:
            import fitz
            doc = fitz.open(stream=file_bytes)
            text_parts = []
            for page in doc:
                text = page.get_text()
                if text:
                    text_parts.append(text)
            doc.close()
            return "\n".join(text_parts)
        except Exception as e2:
            logger.error(f"Image extraction failed: {e2}")
            raise HTTPException(500, f"Image text extraction failed: {str(e2)}")


def _call_claude(text: str) -> dict:
    """Send extracted text to Claude API for field mapping."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "sk-ant-your-key-here":
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Truncate text if too long
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT + text
                }
            ]
        )

        response_text = message.content[0].text.strip()

        # Clean markdown if present
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)

        extracted = json.loads(response_text)
        return extracted

    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON: {e}")
        raise HTTPException(500, "Could not parse extracted fields — try a clearer document")
    except Exception as e:
        logger.error(f"Claude API call failed: {e}")
        raise HTTPException(500, f"AI extraction failed: {str(e)}")


def _post_process(extracted: dict) -> dict:
    """Clean and validate extracted fields."""
    # Ensure numeric types
    int_fields = ["age", "coverage_term_yrs", "systolic_bp", "diastolic_bp",
                  "alcohol_drinks_week", "occupation_class", "height_inches", "weight_lbs"]
    float_fields = ["face_amount", "annual_income", "existing_coverage", "a1c",
                    "height_inches", "weight_lbs"]
    bool_fields = ["hiv_positive", "cirrhosis", "stroke_history", "kidney_disease",
                   "depression_history", "copd", "hazardous_activity"]

    result = {}
    for k, v in extracted.items():
        if v is None or v == "":
            continue
        try:
            if k in int_fields:
                result[k] = int(float(str(v)))
            elif k in float_fields:
                result[k] = float(str(v).replace(",", ""))
            elif k in bool_fields:
                result[k] = bool(v) if isinstance(v, bool) else str(v).lower() in ("true", "yes", "1")
            else:
                result[k] = v
        except (ValueError, TypeError):
            result[k] = v

    # Normalize gender
    if "gender" in result:
        g = str(result["gender"]).upper()
        result["gender"] = "MALE" if "M" in g and "F" not in g else "FEMALE"

    # Normalize tobacco
    if "tobacco_status" in result:
        t = str(result["tobacco_status"]).upper()
        if "NEVER" in t:
            result["tobacco_status"] = "NEVER"
        elif "NON" in t or "NON_TOBACCO" in t:
            result["tobacco_status"] = "NON_TOBACCO"
        elif "SMOK" in t or "TOBACCO" in t:
            result["tobacco_status"] = "SMOKER"

    return result


# ── Endpoint ─────────────────────────────────────────────────────────────────
@router.post("/underwriting/extract-document")
async def extract_document(file: UploadFile = File(...)):
    """
    Extract UW fields from an uploaded proposal form PDF or image.
    Returns structured JSON ready to pre-fill the evaluation form.
    """
    filename = (file.filename or "").lower()
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(400, "Empty file uploaded")

    # Limit file size to 10MB
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large — maximum 10MB")

    # Extract text based on file type
    if filename.endswith(".pdf"):
        raw_text = _extract_text_from_pdf(file_bytes)
    elif filename.endswith((".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp")):
        raw_text = _extract_text_from_image(file_bytes)
    else:
        raise HTTPException(400, "Unsupported file type. Upload PDF or image (JPG, PNG, TIFF)")

    if not raw_text or len(raw_text.strip()) < 20:
        raise HTTPException(422, "Could not extract readable text from document. "
                                 "Ensure the PDF is not scanned/image-only or try a clearer image.")

    logger.info(f"Extracted {len(raw_text)} chars from {filename}")

    # Send to Claude for field mapping
    extracted = _call_claude(raw_text)

    # Post-process and clean
    result = _post_process(extracted)

    # Count extracted fields
    uw_fields = [k for k in result if k not in ("full_name", "date_of_birth", "email", "phone")]

    return {
        "status":           "success",
        "fields_extracted": len(result),
        "uw_fields_found":  len(uw_fields),
        "filename":         file.filename,
        "char_count":       len(raw_text),
        "extracted":        result,
    }
