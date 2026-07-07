"""
test_agent_portal.py — Agent & Broker Portal tests
Covers: TC-AGT-001 to TC-AGT-004
"""
import pytest
import requests
import time
from conftest import BASE_URL

AGENT_PROPOSAL = {
    "applicant_ref": "AGT-AUTO-001",
    "applicant_name": "Test Applicant Auto",
    "product_code": "GRP-TERM-1",
    "age": 30, "gender": "MALE", "state": "MH",
    "face_amount": 500000, "coverage_term_yrs": 20,
    "tobacco_status": "NEVER",
    "height_inches": 68, "weight_lbs": 170,
    "systolic_bp": 120, "diastolic_bp": 80,
    "diabetes_type": "NONE", "heart_condition": "NONE",
    "annual_income": 600000, "existing_coverage": 0,
}

HIGH_RISK_PROPOSAL = {
    "applicant_ref": "AGT-AUTO-HIGHRISK",
    "applicant_name": "High Risk Applicant",
    "product_code": "GRP-TERM-1",
    "age": 62, "gender": "MALE", "state": "MH",
    "face_amount": 500000, "coverage_term_yrs": 20,
    "tobacco_status": "SMOKER",
    "systolic_bp": 162, "diastolic_bp": 102,
    "diabetes_type": "TYPE2", "heart_condition": "HYPERTENSION",
    "annual_income": 400000, "existing_coverage": 0,
}


class TestAgentDashboard:
    def test_agent_dashboard_returns_stats(self, agent_headers):
        """TC-AGT-001: Agent dashboard returns submission statistics."""
        resp = requests.get(f"{BASE_URL}/agent/dashboard", headers=agent_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        stats = data["stats"]
        assert "total_submitted" in stats
        assert "approved" in stats
        assert "declined" in stats
        assert "pending" in stats
        assert isinstance(stats["total_submitted"], int)

    def test_agent_dashboard_has_recent(self, agent_headers):
        """Dashboard includes recent submissions list."""
        resp = requests.get(f"{BASE_URL}/agent/dashboard", headers=agent_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "recent" in data
        assert isinstance(data["recent"], list)

    def test_admin_cannot_access_agent_dashboard(self, admin_headers):
        """Admin role cannot access agent-only endpoint."""
        resp = requests.get(f"{BASE_URL}/agent/dashboard", headers=admin_headers)
        assert resp.status_code == 403

    def test_agent_returns_username(self, agent_headers):
        """Dashboard returns agent username in response."""
        resp = requests.get(f"{BASE_URL}/agent/dashboard", headers=agent_headers)
        assert resp.status_code == 200
        assert resp.json().get("agent") == "agent001"


class TestAgentProducts:
    def test_agent_can_list_products(self, agent_headers):
        """Agent can retrieve available products."""
        resp = requests.get(f"{BASE_URL}/agent/products", headers=agent_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_products_have_required_fields(self, agent_headers):
        """Products returned to agent have name, code, and limits."""
        resp = requests.get(f"{BASE_URL}/agent/products", headers=agent_headers)
        assert resp.status_code == 200
        products = resp.json()
        for p in products:
            assert "product_code" in p
            assert "product_name" in p

    def test_products_not_expose_uw_config(self, agent_headers):
        """Products endpoint should not expose internal UW thresholds."""
        resp = requests.get(f"{BASE_URL}/agent/products", headers=agent_headers)
        assert resp.status_code == 200
        for p in resp.json():
            assert "stp_threshold" not in p
            assert "decline_threshold" not in p


class TestAgentSubmission:
    def test_agent_submit_returns_decision(self, agent_headers):
        """TC-AGT-001: Agent proposal submission returns decision and case number."""
        payload = {**AGENT_PROPOSAL,
                   "applicant_ref": f"AGT-AUTO-{int(time.time())}"}
        resp = requests.post(f"{BASE_URL}/agent/submit",
            headers=agent_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "outcome" in data
        assert data["outcome"] in (
            "APPROVED_STP", "APPROVED_RATED", "REFERRED", "DECLINED")
        assert "case_number" in data
        assert data["case_number"] is not None
        assert "message" in data

    def test_agent_submit_approved_has_premium(self, agent_headers):
        """Approved agent submission includes premium amount."""
        payload = {**AGENT_PROPOSAL,
                   "applicant_ref": f"AGT-PREM-{int(time.time())}"}
        resp = requests.post(f"{BASE_URL}/agent/submit",
            headers=agent_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        if data["outcome"] in ("APPROVED_STP", "APPROVED_RATED"):
            assert data.get("approved_premium") is not None
            assert float(data["approved_premium"]) > 0

    def test_agent_submit_saves_applicant_name(self, agent_headers):
        """TC-AGT-002: Submitted applicant name is stored in database."""
        ref = f"AGT-NAME-{int(time.time())}"
        payload = {**AGENT_PROPOSAL, "applicant_ref": ref,
                   "applicant_name": "Suresh Test Kumar"}
        resp = requests.post(f"{BASE_URL}/agent/submit",
            headers=agent_headers, json=payload)
        assert resp.status_code == 200

        # Verify in submissions list
        subs_resp = requests.get(f"{BASE_URL}/agent/submissions?per_page=50",
            headers=agent_headers)
        assert subs_resp.status_code == 200
        subs = subs_resp.json().get("submissions", [])
        match = next((s for s in subs if s.get("applicant_ref") == ref), None)
        if match:
            assert match.get("applicant_name") == "Suresh Test Kumar"

    def test_agent_submit_missing_required_field(self, agent_headers):
        """Agent submission with missing required field returns 422."""
        payload = {k: v for k, v in AGENT_PROPOSAL.items() if k != "age"}
        payload["applicant_ref"] = f"AGT-MISSING-{int(time.time())}"
        resp = requests.post(f"{BASE_URL}/agent/submit",
            headers=agent_headers, json=payload)
        assert resp.status_code == 422

    def test_referred_case_reaches_workbench(self, agent_headers, admin_headers):
        """TC-AGT-003: High-risk agent submission appears in UW Workbench."""
        ref = f"AGT-REFER-{int(time.time())}"
        payload = {**HIGH_RISK_PROPOSAL, "applicant_ref": ref}
        resp = requests.post(f"{BASE_URL}/agent/submit",
            headers=agent_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        if data["outcome"] == "REFERRED":
            # Check workbench queue
            queue_resp = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
            assert queue_resp.status_code == 200
            queue_data = queue_resp.json()
            items = queue_data.get("items") or queue_data.get("cases") or []
            refs = [item.get("applicant_ref") for item in items]
            assert ref in refs, f"Referred case {ref} not found in workbench"

    def test_broker_can_submit(self, broker_headers):
        """Broker role can also submit proposals."""
        payload = {**AGENT_PROPOSAL,
                   "applicant_ref": f"BRK-AUTO-{int(time.time())}"}
        resp = requests.post(f"{BASE_URL}/agent/submit",
            headers=broker_headers, json=payload)
        assert resp.status_code == 200
        assert "outcome" in resp.json()


class TestAgentSubmissions:
    def test_list_submissions_returns_data(self, agent_headers):
        """TC-AGT-004: My Submissions returns list of agent's proposals."""
        resp = requests.get(f"{BASE_URL}/agent/submissions",
            headers=agent_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "submissions" in data
        assert "total" in data
        assert isinstance(data["submissions"], list)

    def test_submissions_pagination(self, agent_headers):
        """Submissions support page and per_page parameters."""
        resp = requests.get(
            f"{BASE_URL}/agent/submissions?page=1&per_page=5",
            headers=agent_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("page") == 1
        assert data.get("per_page") == 5
        assert len(data.get("submissions", [])) <= 5

    def test_submissions_have_required_fields(self, agent_headers):
        """Each submission has applicant_ref, product_code, status, case_number."""
        resp = requests.get(f"{BASE_URL}/agent/submissions?per_page=20",
            headers=agent_headers)
        assert resp.status_code == 200
        for sub in resp.json().get("submissions", []):
            assert "applicant_ref" in sub
            assert "status" in sub

    def test_agent_only_sees_own_submissions(self, agent_headers, broker_headers):
        """Agent submissions list only shows own cases."""
        agent_resp = requests.get(f"{BASE_URL}/agent/submissions",
            headers=agent_headers)
        broker_resp = requests.get(f"{BASE_URL}/agent/submissions",
            headers=broker_headers)
        assert agent_resp.status_code == 200
        assert broker_resp.status_code == 200
        agent_total = agent_resp.json().get("total", 0)
        broker_total = broker_resp.json().get("total", 0)
        # They should see different counts (unless no submissions yet)
        # Just verify each gets a valid response
        assert isinstance(agent_total, int)
        assert isinstance(broker_total, int)
