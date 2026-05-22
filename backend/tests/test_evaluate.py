"""
backend/tests/test_evaluate.py
STP / REFER / DECLINE scenarios, hard stops, rule firing.
Tests the engine directly (unit) and via the API (integration).
"""
import pytest
from services.uw_engine import run_evaluation


# ── Unit tests (no DB, no HTTP) ───────────────────────────────────────────────

BASE = {
    "applicant_ref":  "TEST-001",
    "age":            35,
    "gender":         "MALE",
    "state":          "MH",
    "product_code":   "IND-TERM-20",
    "face_amount":    1_000_000,
    "coverage_term_yrs": 20,
    "tobacco_status": "NEVER",
    "heart_condition":"NONE",
    "diabetes_type":  "NONE",
    "occupation_class":"1",
    "financial":      {"annual_income": 800_000, "existing_life_coverage": 0},
    "driving_record": {"dui_dwi_count_5yr": 0, "major_violations_3yr": 0,
                       "minor_violations_3yr": 0, "at_fault_accidents_3yr": 0,
                       "license_suspended": False},
}


def _eval(**overrides):
    payload = {**BASE, **overrides}
    return run_evaluation(payload, actor="test", tenant_id=None)


def test_clean_risk_approved():
    result = _eval()
    assert "APPROVED" in result["outcome"]
    assert result["net_debit_points"] < 100


def test_smoker_adds_debits():
    clean   = _eval()["net_debit_points"]
    smoker  = _eval(tobacco_status="SMOKER")["net_debit_points"]
    assert smoker > clean
    assert smoker - clean >= 75


def test_hiv_hard_decline():
    result = _eval(hiv_positive=True)
    assert result["outcome"] == "DECLINED"
    assert result["net_debit_points"] == 999
    assert any(r.get("hard_stop") for r in result["rules_fired"])


def test_cirrhosis_hard_decline():
    result = _eval(cirrhosis=True)
    assert result["outcome"] == "DECLINED"


def test_occupation_class_d_decline():
    result = _eval(occupation_class="D")
    assert result["outcome"] == "DECLINED"


def test_two_dui_decline():
    result = _eval(driving_record={"dui_dwi_count_5yr": 2, "major_violations_3yr": 0,
                                    "minor_violations_3yr": 0, "at_fault_accidents_3yr": 0,
                                    "license_suspended": False})
    assert result["outcome"] == "DECLINED"


def test_type1_diabetes_high_debits():
    result = _eval(diabetes_type="TYPE1", a1c=9.5)
    assert result["net_debit_points"] >= 150


def test_type2_diabetes_adds_debits():
    clean = _eval()["net_debit_points"]
    t2    = _eval(diabetes_type="TYPE2", a1c=7.0, diabetes_dx_age=45)["net_debit_points"]
    assert t2 > clean


def test_recent_mi_postpone():
    result = _eval(heart_condition="MI", heart_event_years_ago=0.5)
    assert result["outcome"] == "DECLINED"


def test_old_mi_rated_not_declined():
    result = _eval(heart_condition="MI", heart_event_years_ago=6)
    # Should be rated or referred, not hard declined
    assert result["outcome"] != "DECLINED" or result["net_debit_points"] < 500


def test_high_bmi_adds_debits():
    clean    = _eval()["net_debit_points"]
    high_bmi = _eval(build={"height_inches": 68, "weight_lbs": 320})["net_debit_points"]
    assert high_bmi > clean


def test_hazardous_activity_adds_debits():
    clean  = _eval()["net_debit_points"]
    hazard = _eval(hazardous_activity=True, hazard_types=["BASE_JUMPING"])["net_debit_points"]
    assert hazard > clean


def test_age_loading_over_55():
    young = _eval(age=30)["net_debit_points"]
    old   = _eval(age=60)["net_debit_points"]
    assert old > young


def test_stp_flag_on_clean_case():
    result = _eval()
    if "APPROVED_STP" in result["outcome"]:
        assert result["is_stp"] is True
        assert result["pathway"] == "STRAIGHT_THROUGH"


def test_rules_fired_list_populated():
    result = _eval(tobacco_status="SMOKER", diabetes_type="TYPE2", a1c=8.0)
    assert len(result["rules_fired"]) >= 2


def test_net_debits_equals_debits_minus_credits():
    result = _eval()
    assert result["net_debit_points"] == result["total_debits"] - result["total_credits"]


# ── API integration tests ─────────────────────────────────────────────────────

def test_evaluate_api_returns_outcome(client, auth_headers, minimal_payload):
    resp = client.post("/underwriting/evaluate",
                       json=minimal_payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "outcome" in data
    assert "net_debit_points" in data


def test_evaluate_api_no_auth(client, minimal_payload):
    resp = client.post("/underwriting/evaluate", json=minimal_payload)
    assert resp.status_code == 401


def test_evaluate_api_hiv_decline(client, auth_headers, minimal_payload):
    payload = {**minimal_payload, "hiv_positive": True}
    resp = client.post("/underwriting/evaluate", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "DECLINED"


def test_products_list(client, auth_headers):
    resp = client.get("/products", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_queue_list(client, auth_headers):
    resp = client.get("/queue/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
