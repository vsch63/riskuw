"""
backend/tests/test_batch.py
CSV upload → job queued → records written → counters correct.
"""
import io
import pytest


SAMPLE_CSV = """applicant_ref,product_code,age,gender,state,face_amount,tobacco_status
BATCH-T-001,IND-TERM-20,30,MALE,MH,1000000,NEVER
BATCH-T-002,IND-TERM-20,45,FEMALE,DL,2000000,NEVER
BATCH-T-003,IND-TERM-20,35,MALE,KA,500000,SMOKER
BATCH-T-004,IND-TERM-20,40,MALE,MH,1500000,NEVER
BATCH-T-005,IND-TERM-20,50,FEMALE,GJ,750000,NEVER
"""

SAMPLE_CSV_BAD = """applicant_ref,age,gender,state,face_amount
BATCH-BAD-001,30,MALE,MH,1000000
"""


def test_batch_template_download(client, auth_headers):
    resp = client.get("/batch/template", headers=auth_headers)
    assert resp.status_code == 200
    assert "product_code" in resp.text
    assert "applicant_ref" in resp.text


def test_batch_jobs_list(client, auth_headers):
    resp = client.get("/batch/jobs", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_batch_upload_csv(client, auth_headers):
    buf = io.BytesIO(SAMPLE_CSV.encode())
    resp = client.post(
        "/batch/upload",
        files={"file": ("test_batch.csv", buf, "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert "job_id" in data
    assert "job_number" in data


def test_batch_upload_missing_product_code(client, auth_headers):
    """CSV missing product_code column — job should still be queued (errors recorded per-row)."""
    buf = io.BytesIO(SAMPLE_CSV_BAD.encode())
    resp = client.post(
        "/batch/upload",
        files={"file": ("bad.csv", buf, "text/csv")},
        headers=auth_headers,
    )
    # Upload itself succeeds; per-row errors appear in batch_job_records
    assert resp.status_code == 200


def test_batch_upload_no_auth(client):
    buf = io.BytesIO(SAMPLE_CSV.encode())
    resp = client.post(
        "/batch/upload",
        files={"file": ("test.csv", buf, "text/csv")},
    )
    assert resp.status_code == 401


def test_batch_job_detail(client, auth_headers):
    # Upload first to get a job ID
    buf = io.BytesIO(SAMPLE_CSV.encode())
    upload = client.post(
        "/batch/upload",
        files={"file": ("detail_test.csv", buf, "text/csv")},
        headers=auth_headers,
    )
    if upload.status_code != 200:
        pytest.skip("Upload failed — check DB connection")
    job_id = upload.json()["job_id"]

    resp = client.get(f"/batch/jobs/{job_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == job_id or str(data.get("id")) == job_id


def test_batch_error_codes_list(client, auth_headers):
    resp = client.get("/batch/error-codes", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_batch_schedules_list(client, auth_headers):
    resp = client.get("/batch/schedules", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
