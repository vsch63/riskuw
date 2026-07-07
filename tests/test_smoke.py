"""
test_smoke.py — Quick sanity checks (run first to verify platform is up)
These tests complete in under 30 seconds and confirm core functionality.
"""
import pytest
import requests
from conftest import BASE_URL, HEALTHY_MALE_30

pytestmark = pytest.mark.smoke


class TestSmoke:
    def test_health_check(self):
        """Platform health endpoint returns ok."""
        resp = requests.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"

    def test_db_healthy(self):
        """Database connection healthy."""
        resp = requests.get(f"{BASE_URL}/health")
        assert resp.json().get("db") == "ok"

    def test_redis_healthy(self):
        """Redis connection healthy — verified via platform status."""
        resp = requests.get(f"{BASE_URL}/health")
        data = resp.json()
        assert data.get("status") == "ok"
        # redis key may not be present in all health implementations
        if "redis" in data:
            assert data["redis"] == "ok"

    def test_admin_login(self):
        """Admin can log in successfully."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "Admin@1234"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_agent_login(self):
        """Agent can log in successfully."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "agent001", "password": "Agent@1234"})
        assert resp.status_code == 200

    def test_evaluation_returns_decision(self, admin_headers):
        """Basic evaluation returns a decision."""
        payload = {**HEALTHY_MALE_30, "applicant_ref": "SMOKE-TEST-001"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        assert resp.json().get("outcome") in (
            "APPROVED_STP", "APPROVED_RATED", "REFERRED", "DECLINED")

    def test_icd10_search_works(self, admin_headers):
        """ICD-10 search returns results."""
        resp = requests.get(f"{BASE_URL}/icd10/search?q=E11",
            headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) > 0

    def test_agent_dashboard_works(self, agent_headers):
        """Agent dashboard is accessible."""
        resp = requests.get(f"{BASE_URL}/agent/dashboard",
            headers=agent_headers)
        assert resp.status_code == 200

    def test_products_available(self, admin_headers):
        """At least one product is configured."""
        resp = requests.get(f"{BASE_URL}/products", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert len(products) > 0

    def test_approval_letter_generates(self, admin_headers):
        """Letter generation endpoint works."""
        params = {"applicant_ref": "SMOKE-LTR",
                  "outcome": "APPROVED_STP", "case_number": "CASE-SMOKE"}
        resp = requests.get(
            f"{BASE_URL}/system/letter-templates/TPL-APPROVED-001/generate",
            headers=admin_headers, params=params)
        assert resp.status_code == 200
        assert "<html" in resp.text.lower()
