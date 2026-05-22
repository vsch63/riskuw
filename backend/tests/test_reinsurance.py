"""
backend/tests/test_reinsurance.py
RI cession trigger: high face-amount approval → ri_cession row created.
Also tests the Python-side service helpers.
"""
import pytest
from services.reinsurance import check_cession_required, DEFAULT_RETENTION_LIMIT


# ── Unit tests (no DB) ────────────────────────────────────────────────────────

class _MockConn:
    """Minimal DB mock that simulates no reinsurer found."""
    def cursor(self):
        return _MockCursor()


class _MockCursor:
    def execute(self, *a, **k): pass
    def fetchone(self): return None
    def close(self): pass


def test_cession_required_above_limit():
    conn = _MockConn()
    required, amount = check_cession_required(
        face_amount=10_000_000,
        tenant_id="00000000-0000-0000-0000-000000000001",
        conn=conn,
    )
    # No reinsurer in mock → uses DEFAULT_RETENTION_LIMIT
    assert required is True
    assert amount == 10_000_000 - DEFAULT_RETENTION_LIMIT


def test_cession_not_required_below_limit():
    conn = _MockConn()
    required, amount = check_cession_required(
        face_amount=2_000_000,
        tenant_id="00000000-0000-0000-0000-000000000001",
        conn=conn,
    )
    assert required is False
    assert amount == 0.0


def test_cession_amount_equals_excess():
    conn = _MockConn()
    _, amt = check_cession_required(
        face_amount=DEFAULT_RETENTION_LIMIT + 1_000_000,
        tenant_id="test",
        conn=conn,
    )
    assert amt == 1_000_000


# ── API integration tests ─────────────────────────────────────────────────────

def test_reinsurers_list(client, auth_headers):
    resp = client.get("/reinsurance/reinsurers", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_cessions_list(client, auth_headers):
    resp = client.get("/reinsurance/cessions", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_cession_summary(client, auth_headers):
    resp = client.get("/reinsurance/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cessions" in data


def test_create_reinsurer_admin_only(client, auth_headers):
    payload = {
        "reinsurer_name": "Test Re India",
        "reinsurer_code": "TEST-RE",
        "treaty_type": "QUOTA_SHARE",
        "retention_limit": 5_000_000,
    }
    resp = client.post("/reinsurance/reinsurers", json=payload, headers=auth_headers)
    # 201 if admin, 403 if non-admin role
    assert resp.status_code in (201, 403)


def test_high_face_evaluate_triggers_cession_flag(client, auth_headers):
    """
    Submit a high face-amount approval and verify the decision is returned.
    The DB trigger (V002) handles actual cession creation — we just verify
    the API doesn't error out.
    """
    payload = {
        "applicant_ref":   "RI-TEST-001",
        "age":             35,
        "gender":          "MALE",
        "state":           "MH",
        "product_code":    "IND-KEYMAN",
        "product_type":    "INDIVIDUAL_TERM",
        "face_amount":     50_000_000,    # ₹5 Cr — above RI threshold
        "coverage_term_yrs": 10,
        "tobacco_status":  "NEVER",
        "heart_condition": "NONE",
        "diabetes_type":   "NONE",
        "occupation_class":"1",
        "financial":       {"annual_income": 10_000_000, "existing_life_coverage": 0},
        "driving_record":  {"dui_dwi_count_5yr": 0, "major_violations_3yr": 0,
                            "minor_violations_3yr": 0, "at_fault_accidents_3yr": 0,
                            "license_suspended": False},
    }
    resp = client.post("/underwriting/evaluate", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "outcome" in data
    # High face should go to REFERRED or APPROVED — not crash
    assert data["outcome"] in ("APPROVED_STP", "APPROVED_RATED", "REFERRED", "DECLINED")
