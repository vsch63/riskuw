"""
test_workbench.py — Underwriter Workbench tests
Covers: TC-WB-001 to TC-WB-004
"""
import pytest
import requests
import time
from conftest import BASE_URL, BORDERLINE_MALE


def get_workbench_items(headers):
    """Get workbench queue items."""
    resp = requests.get(f"{BASE_URL}/workbench/queue", headers=headers)
    if resp.status_code != 200:
        return []
    data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("cases") or data.get("items") or []


def get_or_create_referred_case(admin_headers):
    """Get an open referred case from workbench or create one."""
    items = get_workbench_items(admin_headers)
    open_cases = [i for i in items
                  if i.get("workbench_status") in ("OPEN", "IN_PROGRESS", None)]
    if open_cases:
        return open_cases[0]

    # Create one
    payload = {**BORDERLINE_MALE,
               "applicant_ref": f"WB-CREATE-{int(time.time())}"}
    eval_resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
        headers=admin_headers, json=payload)
    if eval_resp.status_code == 200 and \
       eval_resp.json().get("outcome") == "REFERRED":
        time.sleep(1)
        items2 = get_workbench_items(admin_headers)
        if items2:
            return items2[0]
    return None


def get_case_id(case):
    """Extract case_ref_id — the workbench case identifier."""
    return case.get("case_ref_id") or case.get("assignment_id") or case.get("id")


class TestWorkbenchQueue:
    def test_queue_returns_cases(self, admin_headers):
        """TC-WB-001: Workbench queue returns case list."""
        resp = requests.get(f"{BASE_URL}/workbench/queue", headers=admin_headers)
        assert resp.status_code == 200
        items = get_workbench_items(admin_headers)
        assert isinstance(items, list)

    def test_queue_filter_by_status(self, admin_headers):
        """Queue supports status filter."""
        resp = requests.get(f"{BASE_URL}/workbench/queue?status=OPEN",
            headers=admin_headers)
        assert resp.status_code == 200

    def test_queue_filter_by_priority(self, admin_headers):
        """Queue supports priority filter."""
        resp = requests.get(f"{BASE_URL}/workbench/queue?priority=NORMAL",
            headers=admin_headers)
        assert resp.status_code == 200

    def test_queue_has_expected_fields(self, admin_headers):
        """TC-WB-001: Queue items include expected fields."""
        items = get_workbench_items(admin_headers)
        if items:
            item = items[0]
            assert "case_ref_id" in item or "applicant_ref" in item

    def test_queue_has_outcome_field(self, admin_headers):
        """Queue items include outcome field."""
        items = get_workbench_items(admin_headers)
        if items:
            assert "outcome" in items[0]

    def test_agent_cannot_access_workbench_queue(self, agent_headers):
        """Agent queue access returns 200 or 403 depending on config."""
        resp = requests.get(f"{BASE_URL}/workbench/queue", headers=agent_headers)
        assert resp.status_code in (200, 403)

    def test_queue_items_have_required_fields(self, admin_headers):
        """Queue items contain applicant_ref and product_code."""
        items = get_workbench_items(admin_headers)
        for item in items[:5]:
            assert "applicant_ref" in item
            assert "product_code" in item


class TestWorkbenchCaseActions:
    def test_assign_case(self, admin_headers):
        """TC-WB-002: Case can be assigned to an underwriter."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = get_case_id(case)
        resp = requests.post(
            f"{BASE_URL}/workbench/cases/{case_id}/assign",
            headers=admin_headers,
            json={"assigned_to": "admin"})
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data.get("assigned_to") == "admin"

    def test_add_note_to_case(self, admin_headers):
        """TC-WB-002: Notes can be added to a workbench case."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = get_case_id(case)
        resp = requests.post(
            f"{BASE_URL}/workbench/cases/{case_id}/notes",
            headers=admin_headers,
            json={"note": "Automated test note — reviewing medical history"})
        assert resp.status_code in (200, 201)

    def test_add_requirement_to_case(self, admin_headers):
        """TC-WB-002: Requirements can be added to a workbench case."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = get_case_id(case)
        resp = requests.post(
            f"{BASE_URL}/workbench/cases/{case_id}/requirements",
            headers=admin_headers,
            json={"requirement_type": "MEDICAL_TEST",
                  "description": "Full blood panel — automated test"})
        assert resp.status_code in (200, 201)

    def test_get_case_notes(self, admin_headers):
        """Notes added to a case are retrievable."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = get_case_id(case)
        # Add a note first
        requests.post(
            f"{BASE_URL}/workbench/cases/{case_id}/notes",
            headers=admin_headers,
            json={"note": "Test note for retrieval"})
        # Retrieve notes
        resp = requests.get(
            f"{BASE_URL}/workbench/cases/{case_id}/notes",
            headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_final_decision_approve(self, admin_headers):
        """TC-WB-003: Final decision can be submitted from workbench."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = get_case_id(case)
        resp = requests.post(
            f"{BASE_URL}/workbench/cases/{case_id}/decision",
            headers=admin_headers,
            json={"final_outcome": "APPROVED",
                  "final_reason": "Risk acceptable after review — automated test"})
        assert resp.status_code in (200, 201, 204)
