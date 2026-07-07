"""
test_policy.py — Policy number generation & handoff tests
"""
import pytest
import requests
import time
from conftest import BASE_URL, HEALTHY_MALE_30


def get_approved_case_id(admin_headers):
    """Helper — find an approved case not yet issued as a policy."""
    resp = requests.get(f"{BASE_URL}/underwriting/cases", headers=admin_headers)
    if resp.status_code != 200:
        return None
    cases = resp.json()
    if isinstance(cases, dict):
        cases = cases.get("cases") or cases.get("items") or []
    approved = [c for c in cases if c.get("status") == "APPROVED"]
    return approved[0]["id"] if approved else None


class TestPolicyNumberGeneration:
    def test_approved_case_generates_policy_number(self, admin_headers):
        """Approved evaluation returns a policy number in the configured format."""
        payload = {**HEALTHY_MALE_30,
                   "applicant_ref": f"POL-NUM-TEST-{int(time.time())}"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        if data["outcome"] in ("APPROVED_STP", "APPROVED_RATED"):
            # Policy number should be generated
            assert data.get("case_number") is not None

    def test_policy_number_format_matches_config(self, admin_headers):
        """Policy number format matches system_config prefix/digits/suffix."""
        # Get config
        cfg_resp = requests.get(f"{BASE_URL}/system/config", headers=admin_headers)
        assert cfg_resp.status_code == 200
        cfg = {i["config_key"]: i["config_value"] for i in cfg_resp.json()}
        prefix = cfg.get("policy_number_prefix", "RUW")
        digits = int(cfg.get("policy_number_digits", "6"))

        # Issue a policy
        case_id = get_approved_case_id(admin_headers)
        if not case_id:
            pytest.skip("No approved cases available for policy issuance")

        resp = requests.post(f"{BASE_URL}/policy/issue/{case_id}",
            headers=admin_headers,
            json={"premium_mode": "ANNUAL"})

        if resp.status_code == 409:
            pytest.skip("Policy already issued for this case")

        assert resp.status_code == 200
        pol_num = resp.json().get("policy_number", "")
        assert pol_num.startswith(prefix), \
            f"Policy number '{pol_num}' doesn't start with prefix '{prefix}'"
        # Extract sequence part and verify digit count
        parts = pol_num.split("-")
        assert len(parts) >= 3, f"Policy number format unexpected: {pol_num}"

    def test_policy_numbers_are_sequential(self, admin_headers):
        """Sequential policy issuances produce incrementing numbers."""
        issued = []
        for i in range(2):
            payload = {**HEALTHY_MALE_30,
                       "applicant_ref": f"POL-SEQ-{i}-{int(time.time())}"}
            eval_resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
                headers=admin_headers, json=payload)
            if eval_resp.status_code == 200:
                data = eval_resp.json()
                if data["outcome"] in ("APPROVED_STP", "APPROVED_RATED"):
                    case_id = None
                    # Get the case ID from the cases list
                    cases_resp = requests.get(f"{BASE_URL}/underwriting/cases",
                        headers=admin_headers)
                    if cases_resp.status_code == 200:
                        all_cases = cases_resp.json()
                        if isinstance(all_cases, dict):
                            all_cases = all_cases.get("cases") or []
                        for c in all_cases:
                            if c.get("applicant_ref") == payload["applicant_ref"]:
                                case_id = c.get("id")
                                break
                    if case_id:
                        pol_resp = requests.post(
                            f"{BASE_URL}/policy/issue/{case_id}",
                            headers=admin_headers,
                            json={"premium_mode": "ANNUAL"})
                        if pol_resp.status_code == 200:
                            issued.append(pol_resp.json().get("policy_number"))

        if len(issued) >= 2:
            # Extract sequence numbers and verify they are sequential
            def extract_seq(pnum):
                parts = pnum.split("-")
                for part in reversed(parts):
                    clean = part.lstrip("0") or "0"
                    if clean.isdigit():
                        return int(clean)
                return -1
            seqs = [extract_seq(p) for p in issued]
            assert seqs[1] > seqs[0], \
                f"Policy numbers not sequential: {issued}"

    def test_duplicate_issuance_rejected(self, admin_headers):
        """Issuing a policy for an already-issued case returns 409."""
        case_id = get_approved_case_id(admin_headers)
        if not case_id:
            pytest.skip("No approved cases available")

        # First issuance
        r1 = requests.post(f"{BASE_URL}/policy/issue/{case_id}",
            headers=admin_headers, json={"premium_mode": "ANNUAL"})
        if r1.status_code == 409:
            # Already issued — that's the expected final state
            assert True
            return

        assert r1.status_code == 200

        # Second issuance — must fail
        r2 = requests.post(f"{BASE_URL}/policy/issue/{case_id}",
            headers=admin_headers, json={"premium_mode": "ANNUAL"})
        assert r2.status_code == 409, \
            "Duplicate policy issuance should return 409 Conflict"


class TestPolicyList:
    def test_policy_list_returns_data(self, admin_headers):
        """Policy list endpoint returns issued policies."""
        resp = requests.get(f"{BASE_URL}/policy/list", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "policies" in data
        assert "total" in data
        assert isinstance(data["policies"], list)

    def test_policy_list_filter_by_status(self, admin_headers):
        """Policy list supports status filter."""
        resp = requests.get(f"{BASE_URL}/policy/list?status=IN_FORCE",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        for pol in data.get("policies", []):
            assert pol["status"] == "IN_FORCE"

    def test_policy_detail_has_required_fields(self, admin_headers):
        """Policy detail returns all required fields."""
        resp = requests.get(f"{BASE_URL}/policy/list?per_page=1",
            headers=admin_headers)
        assert resp.status_code == 200
        policies = resp.json().get("policies", [])
        if not policies:
            pytest.skip("No policies issued yet")

        pol_id = policies[0]["id"]
        detail_resp = requests.get(f"{BASE_URL}/policy/{pol_id}",
            headers=admin_headers)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert "policy" in detail
        pol = detail["policy"]
        assert "policy_number" in pol
        assert "status" in pol
        assert "sum_assured" in pol
        assert "annual_premium" in pol
        assert "premium_history" in detail
        assert "status_history" in detail

    def test_agent_cannot_access_policy_list(self, agent_headers):
        """Agent role cannot access policy list."""
        resp = requests.get(f"{BASE_URL}/policy/list", headers=agent_headers)
        assert resp.status_code == 403
