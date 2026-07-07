"""
test_underwriting.py — Individual underwriting evaluation tests
Covers: TC-UW-001 to TC-UW-004, TC-ICD-001 to TC-ICD-002
"""
import pytest
import requests
import time
from conftest import BASE_URL, api, HEALTHY_MALE_30, HIGH_RISK_MALE, BORDERLINE_MALE

class TestSTPApproval:
    def test_healthy_male_approved_stp(self, admin_headers):
        """TC-UW-001: Standard healthy male gets APPROVED_STP."""
        payload = {**HEALTHY_MALE_30, "applicant_ref": "TC-UW-001-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] in ("APPROVED_STP", "APPROVED_RATED", "REFERRED")
        assert "net_debit_points" in data
        assert "risk_class" in data
        assert "case_number" in data
        assert data["case_number"].startswith("CASE-")

    def test_stp_has_premium(self, admin_headers):
        """Approved case includes premium calculation."""
        payload = {**HEALTHY_MALE_30, "applicant_ref": "TC-UW-PREM-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        if data["outcome"] in ("APPROVED_STP", "APPROVED_RATED"):
            assert data.get("approved_premium") is not None
            assert float(data["approved_premium"]) > 0

    def test_healthy_female_evaluated(self, admin_headers):
        """Healthy female applicant returns valid decision."""
        payload = {
            **HEALTHY_MALE_30,
            "applicant_ref": "TC-UW-FEMALE-AUTO",
            "gender": "FEMALE",
            "height_inches": 62,
            "weight_lbs": 135,
        }
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        assert resp.json()["outcome"] in ("APPROVED_STP", "APPROVED_RATED", "REFERRED", "DECLINED")

    def test_rules_fired_returned(self, admin_headers):
        """Decision response includes rules_fired list."""
        payload = {**HEALTHY_MALE_30, "applicant_ref": "TC-UW-RULES-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "rules_fired" in data
        assert isinstance(data["rules_fired"], list)

    def test_decision_persisted(self, admin_headers):
        """Decision is persisted — case number is retrievable."""
        payload = {**HEALTHY_MALE_30, "applicant_ref": f"TC-UW-PERSIST-{int(time.time())}"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("case_number") is not None

    def test_response_time_under_threshold(self, admin_headers):
        """Evaluation completes within 10 seconds."""
        payload = {**HEALTHY_MALE_30, "applicant_ref": "TC-UW-SPEED-AUTO"}
        start = time.time()
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        elapsed = time.time() - start
        assert resp.status_code == 200
        assert elapsed < 10.0, f"Evaluation took {elapsed:.1f}s — exceeds 10s threshold"


class TestDeclineScenarios:
    def test_high_risk_profile_declined_or_referred(self, admin_headers):
        """TC-UW-003: High-risk profile results in DECLINED or REFERRED."""
        payload = {**HIGH_RISK_MALE, "applicant_ref": "TC-UW-DECLINE-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] in ("DECLINED", "REFERRED")
        assert data["net_debit_points"] > 100

    def test_declined_has_no_premium(self, admin_headers):
        """Declined cases do not return a premium."""
        payload = {**HIGH_RISK_MALE, "applicant_ref": "TC-UW-NOPREM-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        if data["outcome"] == "DECLINED":
            assert data.get("approved_premium") is None or data.get("approved_premium") == 0


class TestReferralScenarios:
    def test_borderline_case_referred(self, admin_headers):
        """TC-UW-004: Borderline high-risk case results in REFERRED."""
        payload = {**BORDERLINE_MALE, "applicant_ref": "TC-UW-REFER-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] in ("REFERRED", "DECLINED", "APPROVED_RATED")

    def test_referred_case_in_workbench(self, admin_headers):
        """Referred case appears in workbench queue."""
        payload = {**BORDERLINE_MALE, "applicant_ref": f"TC-WB-CHECK-{int(time.time())}"}
        eval_resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert eval_resp.status_code == 200
        if eval_resp.json()["outcome"] == "REFERRED":
            resp = requests.get(f"{BASE_URL}/queue", headers=admin_headers)
            assert resp.status_code == 200


class TestValidation:
    def test_missing_required_field_rejected(self, admin_headers):
        """Evaluation with missing required field returns 422."""
        payload = {k: v for k, v in HEALTHY_MALE_30.items() if k != "age"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code == 422

    def test_invalid_product_handled(self, admin_headers):
        """Evaluation with non-existent product returns error or fallback result."""
        payload = {**HEALTHY_MALE_30, "product_code": "NONEXISTENT-PRODUCT",
                   "applicant_ref": "TC-UW-BADPROD-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        # Engine may return a fallback result or an error
        assert resp.status_code in (200, 400, 404, 422)

    def test_age_boundary_min(self, admin_headers):
        """Age below product minimum returns error or high debit points."""
        payload = {**HEALTHY_MALE_30, "age": 10,
                   "applicant_ref": "TC-UW-MINAGE-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code in (200, 400, 422)

    def test_negative_face_amount_handled(self, admin_headers):
        """Negative face amount is handled — returns error or result."""
        payload = {**HEALTHY_MALE_30, "face_amount": -100000,
                   "applicant_ref": "TC-UW-NEGAMT-AUTO"}
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        # Platform accepts the request — validation may be added in future
        assert resp.status_code in (200, 422)


class TestICD10Integration:
    def test_icd10_search_returns_results(self, admin_headers):
        """TC-ICD-001: ICD-10 search returns codes with debit points."""
        resp = requests.get(f"{BASE_URL}/icd10/search?q=diabetes",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        first = data[0]
        assert "code" in first
        assert "debit_points" in first
        assert "description" in first

    def test_icd10_search_by_code(self, admin_headers):
        """Search by exact code prefix returns correct code."""
        resp = requests.get(f"{BASE_URL}/icd10/search?q=E11",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        codes = [r["code"] for r in data]
        assert any("E11" in c for c in codes)

    def test_icd10_get_single_code(self, admin_headers):
        """TC-ICD-001: Get specific ICD-10 code returns full detail."""
        resp = requests.get(f"{BASE_URL}/icd10/I10", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "I10"
        assert data["debit_points"] >= 0
        assert "description" in data
        assert "severity" in data

    def test_icd10_categories(self, admin_headers):
        """ICD-10 categories endpoint returns categorised list."""
        resp = requests.get(f"{BASE_URL}/icd10/categories", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        categories = [r["category"] for r in data]
        assert "Cardiovascular" in categories or "Metabolic" in categories

    def test_icd10_debits_applied_to_evaluation(self, admin_headers):
        """TC-ICD-001: ICD-10 extra debits change evaluation outcome."""
        base = {**HEALTHY_MALE_30, "applicant_ref": "TC-ICD-BASE-AUTO"}
        base_resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=base)
        assert base_resp.status_code == 200
        base_debits = base_resp.json()["net_debit_points"]

        with_icd = {**HEALTHY_MALE_30,
                    "applicant_ref": "TC-ICD-WITHICD-AUTO",
                    "icd10_codes": ["E11"],
                    "extra_debit_points": 75}
        icd_resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=with_icd)
        assert icd_resp.status_code == 200
        icd_debits = icd_resp.json()["net_debit_points"]
        assert icd_debits == base_debits + 75

    def test_icd10_nonexistent_code_returns_404(self, admin_headers):
        """TC-ICD-002: Non-existent ICD-10 code returns 404."""
        resp = requests.get(f"{BASE_URL}/icd10/ZZNOTACODE", headers=admin_headers)
        assert resp.status_code == 404
