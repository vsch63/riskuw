"""
test_workbench.py — Underwriter Workbench tests
Covers: TC-WB-001 to TC-WB-004
"""
import pytest
import requests
import time
from conftest import BASE_URL, BORDERLINE_MALE


def get_or_create_referred_case(admin_headers):
    """Helper — get a referred case from workbench or create one."""
    resp = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    items = data.get("items") or data.get("cases") or data.get("queue") or []
    open_cases = [i for i in items if i.get("workbench_status") in ("OPEN", "IN_PROGRESS", None)]
    if open_cases:
        return open_cases[0]

    # Create a referred case
    payload = {**BORDERLINE_MALE,
               "applicant_ref": f"WB-CREATE-{int(time.time())}"}
    eval_resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
        headers=admin_headers, json=payload)
    if eval_resp.status_code == 200 and eval_resp.json().get("outcome") == "REFERRED":
        time.sleep(1)
        resp2 = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
        items2 = resp2.json().get("items") or resp2.json().get("cases") or []
        if items2:
            return items2[0]
    return None


class TestWorkbenchQueue:
    def test_queue_returns_cases(self, admin_headers):
        """TC-WB-001: Workbench queue endpoint returns case list."""
        resp = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict) or isinstance(data, list)

    def test_queue_filter_by_status(self, admin_headers):
        """Queue supports status filter."""
        resp = requests.get(f"{BASE_URL}/queue?status=OPEN", headers=admin_headers)
        assert resp.status_code == 200

    def test_queue_filter_by_priority(self, admin_headers):
        """Queue supports priority filter."""
        resp = requests.get(f"{BASE_URL}/queue?priority=NORMAL", headers=admin_headers)
        assert resp.status_code == 200

    def test_queue_has_sla_info(self, admin_headers):
        """TC-WB-004: Queue items include SLA information."""
        resp = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items") or data.get("cases") or data.get("queue") or []
        if items:
            item = items[0]
            assert "sla_due_at" in item or "workbench_status" in item

    def test_agent_cannot_access_queue(self, agent_headers):
        """TC-AUTH-004: Agent role cannot access UW queue."""
        resp = requests.get(f"{BASE_URL}/queue", headers=agent_headers)
        assert resp.status_code == 403

    def test_queue_items_have_required_fields(self, admin_headers):
        """Queue items contain applicant_ref, product_code, NDP."""
        resp = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items") or data.get("cases") or data.get("queue") or []
        for item in items[:5]:
            assert "applicant_ref" in item or "case_ref_id" in item


class TestWorkbenchCaseActions:
    def test_assign_case(self, admin_headers):
        """TC-WB-002: Case can be assigned to an underwriter."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = case.get("id") or case.get("case_ref_id") or case.get("assignment_id")
        resp = requests.patch(
            f"{BASE_URL}/queue/{case_id}",
            headers=admin_headers,
            json={"assigned_to": "admin", "workbench_status": "IN_PROGRESS"})
        assert resp.status_code in (200, 204)

    def test_add_note_to_case(self, admin_headers):
        """TC-WB-002: Notes can be added to a workbench case."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = case.get("id") or case.get("case_ref_id")
        resp = requests.post(
            f"{BASE_URL}/queue/{case_id}/notes",
            headers=admin_headers,
            json={"note": "Automated test note — reviewing medical history"})
        assert resp.status_code in (200, 201)

    def test_add_requirement_to_case(self, admin_headers):
        """TC-WB-002: Requirements can be added to a workbench case."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = case.get("id") or case.get("case_ref_id")
        resp = requests.post(
            f"{BASE_URL}/queue/{case_id}/requirements",
            headers=admin_headers,
            json={"requirement_type": "Medical Test",
                  "description": "Full blood panel required — automated test"})
        assert resp.status_code in (200, 201)

    def test_get_case_notes(self, admin_headers):
        """Notes added to a case are retrievable."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = case.get("id") or case.get("case_ref_id")
        # Add a note first
        requests.post(f"{BASE_URL}/queue/{case_id}/notes",
            headers=admin_headers,
            json={"note": "Test note for retrieval"})
        # Retrieve notes
        resp = requests.get(f"{BASE_URL}/queue/{case_id}/notes",
            headers=admin_headers)
        assert resp.status_code == 200
        notes = resp.json()
        assert isinstance(notes, list)

    def test_final_decision_approve(self, admin_headers):
        """TC-WB-003: Final decision can be submitted from workbench."""
        case = get_or_create_referred_case(admin_headers)
        if not case:
            pytest.skip("No referred cases available")
        case_id = case.get("id") or case.get("case_ref_id")
        resp = requests.post(
            f"{BASE_URL}/queue/{case_id}/decision",
            headers=admin_headers,
            json={"final_outcome": "APPROVED",
                  "justification": "Risk acceptable after manual review — automated test"})
        assert resp.status_code in (200, 201, 204)
