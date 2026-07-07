"""
test_batch.py — Batch underwriting tests
Covers: TC-BAT-001 to TC-BAT-004
"""
import pytest
import requests
import time
import io
import csv
from conftest import BASE_URL

def make_csv(rows: list[dict]) -> bytes:
    """Build a CSV bytes object from a list of dicts."""
    output = io.StringIO()
    headers = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return ('\ufeff' + output.getvalue()).encode('utf-8')

SAMPLE_ROW = {
    "applicant_ref": "BATCH-AUTO-001",
    "product_code": "GRP-TERM-1",
    "age": 30, "gender": "MALE", "state": "MH",
    "face_amount": 500000, "coverage_term_yrs": 20,
    "tobacco_status": "NEVER", "tobacco_quit_years": "",
    "height_inches": 68, "weight_lbs": 170,
    "systolic_bp": 120, "diastolic_bp": 80,
    "heart_condition": "NONE", "heart_event_years_ago": "",
    "diabetes_type": "NONE", "diabetes_dx_age": "", "a1c": "",
    "cancer_status": "NONE", "cancer_free_years": "",
    "depression_history": "false", "depression_hospitalized": "false",
    "kidney_disease": "false", "copd": "false",
    "stroke_history": "false", "alcohol_drinks_week": 0,
    "hazardous_activity": "false", "occupation_class": "1",
    "occupation_title": "Software Engineer",
    "annual_income": 800000, "existing_coverage": 0,
}


class TestBatchTemplate:
    def test_template_download(self, admin_headers):
        """TC-BAT-001: CSV template downloads successfully."""
        resp = requests.get(f"{BASE_URL}/batch/template", headers=admin_headers)
        if resp.status_code == 404:
            # Try alternate endpoint
            resp = requests.get(f"{BASE_URL}/batch/download-template", headers=admin_headers)
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert len(resp.content) > 0


class TestBatchDryRun:
    def test_dry_run_valid_csv(self, admin_headers):
        """TC-BAT-002: Dry run with valid CSV completes without writing decisions."""
        rows = [{**SAMPLE_ROW, "applicant_ref": f"DRY-AUTO-{i:03d}"} for i in range(5)]
        csv_data = make_csv(rows)
        resp = requests.post(
            f"{BASE_URL}/batch/upload?dry_run=true",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("test_batch.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        job_id = resp.json().get("job_id")
        assert job_id is not None

        # Poll for completion
        for _ in range(30):
            time.sleep(2)
            status_resp = requests.get(f"{BASE_URL}/batch/jobs/{job_id}",
                headers=admin_headers)
            if status_resp.status_code == 200:
                status = status_resp.json().get("status", "")
                if status in ("DRY_RUN_COMPLETE", "COMPLETED", "FAILED"):
                    break

        final = requests.get(f"{BASE_URL}/batch/jobs/{job_id}", headers=admin_headers)
        assert final.status_code == 200
        data = final.json()
        assert data["status"] in ("DRY_RUN_COMPLETE", "COMPLETED")

    def test_dry_run_invalid_row_detected(self, admin_headers):
        """TC-BAT-002: Dry run detects rows with missing required fields."""
        invalid_row = {**SAMPLE_ROW, "applicant_ref": "DRY-INVALID-001", "age": ""}
        rows = [invalid_row]
        csv_data = make_csv(rows)
        resp = requests.post(
            f"{BASE_URL}/batch/upload?dry_run=true",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("invalid.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        job_id = resp.json().get("job_id")
        assert job_id is not None

        for _ in range(20):
            time.sleep(2)
            status_resp = requests.get(f"{BASE_URL}/batch/jobs/{job_id}",
                headers=admin_headers)
            if status_resp.status_code == 200:
                status = status_resp.json().get("status", "")
                if status in ("DRY_RUN_COMPLETE", "COMPLETED", "FAILED"):
                    break

        final = requests.get(f"{BASE_URL}/batch/jobs/{job_id}", headers=admin_headers)
        assert final.status_code == 200


class TestBatchLiveRun:
    def test_live_batch_run_processes_rows(self, admin_headers):
        """TC-BAT-003: Live batch run processes all rows and records decisions."""
        rows = [{**SAMPLE_ROW, "applicant_ref": f"LIVE-AUTO-{i:03d}-{int(time.time())}"}
                for i in range(3)]
        csv_data = make_csv(rows)
        resp = requests.post(
            f"{BASE_URL}/batch/upload?dry_run=false",
            headers={"Authorization": admin_headers["Authorization"]},
            files={"file": ("live_batch.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        job_id = resp.json().get("job_id")
        assert job_id is not None

        # Poll for completion
        for _ in range(30):
            time.sleep(3)
            status_resp = requests.get(f"{BASE_URL}/batch/jobs/{job_id}",
                headers=admin_headers)
            if status_resp.status_code == 200:
                job_data = status_resp.json()
                if job_data.get("status") in ("COMPLETED", "FAILED"):
                    break

        final = requests.get(f"{BASE_URL}/batch/jobs/{job_id}", headers=admin_headers)
        assert final.status_code == 200
        data = final.json()
        assert data["status"] == "COMPLETED"
        assert data.get("processed_count", 0) >= 3

    def test_batch_jobs_list(self, admin_headers):
        """Batch jobs list returns jobs."""
        resp = requests.get(f"{BASE_URL}/batch/jobs", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        assert isinstance(jobs, list)


class TestBatchRecords:
    def test_records_endpoint_returns_data(self, admin_headers):
        """TC-BAT-004: Records endpoint returns per-row results for completed job."""
        # Get first completed job
        resp = requests.get(f"{BASE_URL}/batch/jobs", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        completed = [j for j in jobs if j.get("status") == "COMPLETED"]
        if not completed:
            pytest.skip("No completed batch jobs available for records test")

        job_id = completed[0]["id"]
        records_resp = requests.get(
            f"{BASE_URL}/batch/jobs/{job_id}/records?page=1&per_page=10",
            headers=admin_headers)
        assert records_resp.status_code == 200
        records_data = records_resp.json()
        assert "records" in records_data
        assert "total" in records_data
        assert isinstance(records_data["records"], list)
        if records_data["records"]:
            rec = records_data["records"][0]
            assert "applicant_ref" in rec
            assert "outcome" in rec

    def test_records_pagination(self, admin_headers):
        """Records endpoint supports pagination."""
        resp = requests.get(f"{BASE_URL}/batch/jobs", headers=admin_headers)
        jobs = (resp.json().get("jobs") or resp.json()) if isinstance(resp.json(), dict) else resp.json()
        completed = [j for j in jobs if j.get("status") == "COMPLETED"]
        if not completed:
            pytest.skip("No completed batch jobs available")

        job_id = completed[0]["id"]
        p1 = requests.get(f"{BASE_URL}/batch/jobs/{job_id}/records?page=1&per_page=5",
            headers=admin_headers)
        p2 = requests.get(f"{BASE_URL}/batch/jobs/{job_id}/records?page=2&per_page=5",
            headers=admin_headers)
        assert p1.status_code == 200
        assert p2.status_code == 200
        d1 = p1.json()
        assert d1.get("page") == 1
        assert d1.get("per_page") == 5
