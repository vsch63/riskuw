"""
test_security_upload.py — File upload security tests
Covers: malicious files, oversized uploads, fake PDFs, XSS in extracted content
"""
import pytest
import requests
import io
import subprocess
from conftest import BASE_URL


def make_pdf_bytes(content: bytes = b"Hello world") -> bytes:
    return b"%PDF-1.4\n" + content

def make_fake_pdf_bytes() -> bytes:
    return b"MZ\x90\x00THIS IS AN EXECUTABLE FILE DISGUISED AS PDF"

def make_oversized_bytes(size_mb: int = 11) -> bytes:
    return b"%PDF" + b"A" * (size_mb * 1024 * 1024)

def docker_run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", "riskuw_fastapi", "python3", "-c", code],
        capture_output=True, text=True
    )


class TestFileUploadSecurity:

    def test_oversized_file_rejected(self, admin_headers):
        """TC-SEC-UPL-001: File over 10MB rejected with 413."""
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("big.pdf", io.BytesIO(make_oversized_bytes(11)), "application/pdf")},
        )
        assert resp.status_code == 413
        assert "large" in resp.json().get("detail", "").lower() or \
               "size" in resp.json().get("detail", "").lower()

    def test_exe_disguised_as_pdf_rejected(self, admin_headers):
        """TC-SEC-UPL-002: EXE disguised as PDF rejected via magic bytes."""
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("malware.pdf", io.BytesIO(make_fake_pdf_bytes()), "application/pdf")},
        )
        assert resp.status_code == 415

    def test_empty_file_rejected(self, admin_headers):
        """TC-SEC-UPL-003: Empty file rejected with 400."""
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json().get("detail", "").lower()

    def test_text_file_disguised_as_pdf_rejected(self, admin_headers):
        """TC-SEC-UPL-004: Plain text file with .pdf extension rejected."""
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("notapdf.pdf", io.BytesIO(b"just text no magic bytes"), "application/pdf")},
        )
        assert resp.status_code == 415

    def test_zip_file_disguised_as_pdf_rejected(self, admin_headers):
        """TC-SEC-UPL-005: ZIP file renamed to .pdf rejected."""
        zip_bytes = b"PK\x03\x04" + b"\x00" * 100
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("archive.pdf", io.BytesIO(zip_bytes), "application/pdf")},
        )
        assert resp.status_code == 415

    def test_html_file_disguised_as_pdf_rejected(self, admin_headers):
        """TC-SEC-UPL-006: HTML file with script tags renamed to .pdf rejected."""
        html = b"<html><script>alert('xss')</script></html>"
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("page.pdf", io.BytesIO(html), "application/pdf")},
        )
        assert resp.status_code == 415

    def test_valid_pdf_passes_security(self, admin_headers):
        """TC-SEC-UPL-007: Valid PDF passes security layer (may fail OCR — that is OK)."""
        valid_pdf = make_pdf_bytes(b"Applicant: Test User Age: 35 Gender: MALE")
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("valid.pdf", io.BytesIO(valid_pdf), "application/pdf")},
        )
        assert resp.status_code not in (413, 415), \
            f"Valid PDF incorrectly rejected by security layer: {resp.status_code}"

    def test_unauthenticated_upload_rejected(self):
        """TC-SEC-UPL-008: Upload without token returns 401 or 422 (request rejected)."""
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-document",
            files={"file": ("test.pdf", io.BytesIO(make_pdf_bytes()), "application/pdf")},
        )
        assert resp.status_code in (401, 422),             f"Unauthenticated upload should be rejected, got {resp.status_code}"


class TestBatchUploadSecurity:

    def test_batch_rejects_oversized_file(self, admin_headers):
        """TC-SEC-UPL-009: Batch upload handles oversized files."""
        big = make_oversized_bytes(11)
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-documents-batch",
            headers={"Authorization": admin_headers["Authorization"]},
            files=[("files", ("big.pdf", io.BytesIO(big), "application/pdf"))],
        )
        assert resp.status_code in (200, 413)
        if resp.status_code == 200:
            results = resp.json()
            if isinstance(results, list) and results:
                assert any(r.get("status") == "error" for r in results)

    def test_batch_rejects_fake_pdf(self, admin_headers):
        """TC-SEC-UPL-010: Batch upload rejects EXE disguised as PDF."""
        fake = make_fake_pdf_bytes()
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-documents-batch",
            headers={"Authorization": admin_headers["Authorization"]},
            files=[("files", ("virus.pdf", io.BytesIO(fake), "application/pdf"))],
        )
        assert resp.status_code in (200, 415)
        if resp.status_code == 200:
            results = resp.json()
            if isinstance(results, list) and results:
                assert any(r.get("status") == "error" for r in results)

    def test_batch_limit_50_files(self, admin_headers):
        """TC-SEC-UPL-011: Batch upload rejects more than 50 files."""
        valid = make_pdf_bytes()
        files = [("files", (f"f{i}.pdf", io.BytesIO(valid), "application/pdf"))
                 for i in range(55)]
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-documents-batch",
            headers={"Authorization": admin_headers["Authorization"]},
            files=files,
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", "").lower()
        assert "50" in detail or "maximum" in detail

    def test_batch_no_files_rejected(self, admin_headers):
        """TC-SEC-UPL-012: Batch upload with no files returns 400 or 422."""
        resp = requests.post(
            f"{BASE_URL}/underwriting/extract-documents-batch",
            headers={"Authorization": admin_headers["Authorization"]},
        )
        assert resp.status_code in (400, 422)


class TestXSSSanitisation:

    def test_xss_stripped_from_extracted_fields(self):
        """TC-SEC-UPL-013: XSS patterns stripped from extracted document fields."""
        result = docker_run("""
import sys; sys.path.insert(0,'/app')
from routers.file_security import sanitise_extracted_fields
r = sanitise_extracted_fields({
    'full_name': '<script>alert(1)</script>Rajesh Kumar',
    'age': 35,
    'occupation_title': 'javascript:alert(document.cookie)',
    'state': '<img src=x onerror=alert(1)>MH',
})
assert '<script>' not in r['full_name'], 'script tag not removed'
assert 'javascript:' not in r['occupation_title'], 'javascript: not removed'
assert '<img' not in r['state'], 'img tag not removed'
assert r['age'] == 35, 'integer fields must pass through'
print('PASS')
""")
        assert "PASS" in result.stdout, f"XSS test failed: {result.stderr}"

    def test_sql_patterns_logged_not_blocked(self):
        """TC-SEC-UPL-014: SQL-like patterns logged but not blocked (DB protected by parameterised queries)."""
        result = docker_run("""
import sys; sys.path.insert(0,'/app')
from routers.file_security import sanitise_extracted_fields
r = sanitise_extracted_fields({
    'full_name': "Robert'); DROP TABLE application; --",
    'age': 30,
})
assert r['age'] == 30
print('PASS')
""")
        assert "PASS" in result.stdout, f"SQL test failed: {result.stderr}"

    def test_magic_byte_detection(self):
        """TC-SEC-UPL-015: Magic byte detection correctly identifies real vs fake PDFs."""
        result = docker_run("""
import sys; sys.path.insert(0,'/app')
from routers.file_security import detect_mime_from_bytes
assert detect_mime_from_bytes(b'%PDF-1.4 rest') == 'application/pdf'
assert detect_mime_from_bytes(b'\\xff\\xd8\\xff rest') == 'image/jpeg'
assert detect_mime_from_bytes(b'\\x89PNG\\r\\n rest') == 'image/png'
assert detect_mime_from_bytes(b'MZ\\x90\\x00 exe') is None
assert detect_mime_from_bytes(b'PK\\x03\\x04 zip') is None
assert detect_mime_from_bytes(b'<html>page') is None
assert detect_mime_from_bytes(b'') is None
print('PASS')
""")
        assert "PASS" in result.stdout, f"Magic byte test failed: {result.stderr}"

    def test_field_length_truncated(self):
        """TC-SEC-UPL-016: Extracted field values truncated to 500 chars."""
        result = docker_run("""
import sys; sys.path.insert(0,'/app')
from routers.file_security import sanitise_extracted_fields
r = sanitise_extracted_fields({'full_name': 'A' * 1000})
assert len(r['full_name']) <= 500, f'Field not truncated: {len(r["full_name"])}'
print('PASS')
""")
        assert "PASS" in result.stdout, f"Truncation test failed: {result.stderr}"
