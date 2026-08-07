"""
backend/tests/test_evaluate_path.py
────────────────────────────────────
End-to-end integration tests for the FULL decision path through the real
HTTP layer:

    config (DB) → SAR loader → SAR engine → UW rules → final decision

These drive the same wiring that broke silently before (a config loader
querying a missing column killed all SAR; `row[0]` on RealDict rows; a
`products` vs `product` table split). Unit tests cannot see those breaks —
only a test that seeds config through the real endpoints and then calls
evaluate-proposal can.

Every scenario seeds its own config via the public APIs and cleans up after
itself, so the suite is repeatable and order-independent.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from database import get_conn, release_conn

PRODUCT = "CI-E2E-20"


# ── helpers ───────────────────────────────────────────────────────────────

def _api(client, headers, method: str, path: str, body=None):
    fn = getattr(client, method)
    resp = fn(path, json=body, headers=headers) if body is not None else fn(path, headers=headers)
    return resp


def _cleanup(code: str = PRODUCT):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM uw_benefit_master WHERE benefit_code = %s", (code,))
        cur.execute("DELETE FROM uw_fcl_config WHERE product_code = %s", (code,))
        cur.execute("DELETE FROM uw_formula WHERE product_code = %s", (code,))
        cur.execute("DELETE FROM product_decision_thresholds WHERE product_code = %s", (code,))
        cur.execute("DELETE FROM uw_medical_standard WHERE product_code = %s", (code,))
        cur.execute("DELETE FROM products WHERE product_code = %s", (code,))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


@pytest.fixture(autouse=True)
def _cleanup_around():
    """Every test starts and ends with a clean slate for our product code."""
    _cleanup()
    yield
    _cleanup()


def _create_product(client, headers, *, min_age=18, max_age=65, min_face=100000, max_face=10000000):
    resp = _api(client, headers, "post", "/products", {
        "product_code": PRODUCT,
        "product_name": f"CI E2E {PRODUCT}",
        "product_type": "individual",
        "min_age": min_age,
        "max_age": max_age,
        "min_face_amount": min_face,
        "max_face_amount": max_face,
        "available_terms": [20],
        "stp_threshold": 75,
        "refer_threshold": 150,
        "decline_threshold": 300,
    })
    assert resp.status_code in (200, 201), f"create_product failed: {resp.text}"


def _evaluate(client, headers, *, age, ref_suffix, face_amount=6000000, salary=None,
              tobacco="NEVER", build=None):
    body = {
        "proposal_ref": f"E2E-{ref_suffix}-{uuid.uuid4().hex[:6]}",
        "applicant_ref": f"E2E-APP-{ref_suffix}",
        "age": age,
        "gender": "MALE",
        "state": "MH",
        "annual_income": 1000000,
        "annual_salary": salary or 100000,
        "tobacco_status": tobacco,
        "heart_condition": "NONE",
        "diabetes_type": "NONE",
        "benefits": [{
            "benefit_type": "BASE",
            "product_code": PRODUCT,
            "face_amount": face_amount,
            "coverage_term_yrs": 20,
            "premium_mode": "ANNUAL",
        }],
    }
    if build is not None:
        body["build"] = build
    resp = _api(client, headers, "post", "/underwriting/evaluate-proposal", body)
    return resp


# ── scenarios ─────────────────────────────────────────────────────────────

def test_baseline_clean_applicant_stp(client, auth_headers):
    """Healthy 30yo, no SAR config → APPROVED_STP under default thresholds."""
    _create_product(client, auth_headers)
    resp = _evaluate(client, auth_headers, age=30, ref_suffix="STP")
    assert resp.status_code == 200, f"evaluate failed: {resp.text}"
    data = resp.json()
    # Composite status is ALL_APPROVED; the per-benefit outcome is APPROVED_STP.
    assert data["overall_status"] == "ALL_APPROVED"
    assert data["benefits"][0]["outcome"] == "APPROVED_STP"


def test_fcl_formula_if_else_branch(client, auth_headers):
    """FCL formula with IF/ELSE: age>=40 → 30×salary, else 20×salary.
    Exercises config → loader → formula engine (the wiring that broke
    silently before)."""
    _create_product(client, auth_headers)

    # Benefit master row so the product participates in SAR (loader matches
    # uw_benefit_master.benefit_code to the product code).
    bm = _api(client, auth_headers, "post", "/sar-config/benefits", {
        "benefit_code": PRODUCT,
        "benefit_type": "BASE",
        "risk_type": "MORTALITY",
        "uw_exposure_group": "INDIVIDUAL",
        "risk_group": "LIFE",
        "premium_payer": "EMPLOYEE",
        "underwriting_required": True,
        "include_in_sar": True,
        "sar_formula": "FACE_AMOUNT",
        "processing_sequence": 1,
    })
    assert bm.status_code in (200, 201), f"benefit master failed: {bm.text}"

    # Formula: IF age>=40 THEN salary*30 ELSE salary*20
    fid = _api(client, auth_headers, "post", "/formulas", {
        "formula_name": f"FCL IF/ELSE {PRODUCT}",
        "description": "e2e branch test",
        "formula_type": "FCL",
        "is_active": True,
        "effective_date": "2026-01-01",
    }).json()["id"]

    steps = [
        (10, "IF", "USER_VALUE", {"clauses": [{"field": "age", "op": "GTE", "value": 40}]}),
        (20, "+", "ANNUAL_SALARY", None),
        (30, "*", "USER_VALUE", None, 30),
        (40, "ELSE", "USER_VALUE", None),
        (50, "+", "ANNUAL_SALARY", None),
        (60, "*", "USER_VALUE", None, 20),
        (70, "ENDIF", "USER_VALUE", None),
    ]
    for s in steps:
        body = {"seq_no": s[0], "operator": s[1], "parameter_type": s[2], "factor": 1}
        if s[3]:
            body["condition"] = s[3]
        if len(s) > 4 and s[4]:
            body["user_value"] = s[4]
        r = _api(client, auth_headers, "post", f"/formulas/{fid}/steps", body)
        assert r.status_code in (200, 201), f"step {s[0]} failed: {r.text}"

    fcl = _api(client, auth_headers, "post", "/sar-config/fcl", {
        "product_code": PRODUCT,
        "exposure_group": None,
        "fcl_basis": "FORMULA",
        "formula_id": fid,
        "apply_fcl_per_benefit": False,
        "premium_payer_filter": "ANY",
        "is_active": True,
        "effective_date": "2026-01-01",
    })
    assert fcl.status_code in (200, 201), f"fcl config failed: {fcl.text}"

    # age 45 → THEN branch → 30 × 100000 = 3,000,000
    r_old = _evaluate(client, auth_headers, age=45, ref_suffix="OLD")
    assert r_old.status_code == 200, r_old.text
    sar_old = r_old.json().get("sar") or {}
    fcl_old = (sar_old.get("fcl_applied") or {}).get("INDIVIDUAL")

    # age 35 → ELSE branch → 20 × 100000 = 2,000,000
    r_young = _evaluate(client, auth_headers, age=35, ref_suffix="YNG")
    assert r_young.status_code == 200, r_young.text
    sar_young = r_young.json().get("sar") or {}
    fcl_young = (sar_young.get("fcl_applied") or {}).get("INDIVIDUAL")

    assert Decimal(str(fcl_old)) == Decimal("3000000"), \
        f"expected THEN-branch FCL 3000000, got {fcl_old}"
    assert Decimal(str(fcl_young)) == Decimal("2000000"), \
        f"expected ELSE-branch FCL 2000000, got {fcl_young}"


def test_config_changes_are_audited(client, auth_headers):
    """Every config write (product, formula, SAR config) must leave a CONFIG
    audit_trail row attributable to the actor. Guards the uniform
    config-change audit trail."""
    _create_product(client, auth_headers)
    fid = _api(client, auth_headers, "post", "/formulas", {
        "formula_name": f"AUDIT-FORMULA {PRODUCT}",
        "description": "audit check",
        "formula_type": "FCL",
        "is_active": True,
        "effective_date": "2026-01-01",
    }).json()["id"]

    _api(client, auth_headers, "post", "/sar-config/fcl", {
        "product_code": PRODUCT,
        "exposure_group": None,
        "fcl_basis": "FORMULA",
        "formula_id": fid,
        "apply_fcl_per_benefit": False,
        "premium_payer_filter": "ANY",
        "is_active": True,
        "effective_date": "2026-01-01",
    })

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT event_type, entity_type, after_state, actor_username
        FROM audit_trail
        WHERE event_category = 'CONFIG' AND actor_username = 'admin'
        ORDER BY occurred_at DESC
        LIMIT 25
    """)
    rows = cur.fetchall()
    cur.close()
    release_conn(conn)

    types = [r[0] if not hasattr(r, "keys") else r["event_type"] for r in rows]
    assert "product.create" in types, f"product.create not audited: {types}"
    assert "formula.create" in types, f"formula.create not audited: {types}"
    assert "sar.fcl.upsert" in types, f"sar.fcl.upsert not audited: {types}"
    # The after-state must be recorded (attributable, not a tombstone)
    states = [r[2] if not hasattr(r, "keys") else r["after_state"] for r in rows]
    assert any("fcl_basis" in (s or {}) for s in states), "fcl after_state missing"


def test_password_policy_and_rotation_flag(client, auth_headers):
    """Security baseline: weak passwords rejected at creation; a flagged
    account surfaces password_change_required at login."""
    # Short password → rejected (model-level length check)
    r = _api(client, auth_headers, "post", "/auth/register", {
        "username": "weakuser", "email": "weakuser@example.com",
        "password": "weak", "full_name": "Weak", "role": "underwriter",
    })
    assert r.status_code in (400, 422), f"weak password should be rejected: {r.text}"

    # 8+ chars but no digit → rejected by the complexity policy
    r = _api(client, auth_headers, "post", "/auth/register", {
        "username": "weakuser2", "email": "weakuser2@example.com",
        "password": "abcdefgh", "full_name": "Weak2", "role": "underwriter",
    })
    assert r.status_code == 400, f"no-digit password should be rejected: {r.text}"

    # Create a compliant user, then flag them for forced rotation
    username = f"sec{uuid.uuid4().hex[:6]}"
    r = _api(client, auth_headers, "post", "/auth/register", {
        "username": username, "email": f"{username}@example.com",
        "password": "StrongPass1", "full_name": "Sec", "role": "underwriter",
    })
    assert r.status_code in (200, 201), r.text

    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE uw_user SET must_change_password=true WHERE username=%s", (username,))
    conn.commit(); cur.close(); release_conn(conn)

    resp = client.post("/auth/login", json={"username": username, "password": "StrongPass1"})
    assert resp.status_code == 200, resp.text
    assert resp.json().get("password_change_required") is True, \
        "flagged account must surface password_change_required at login"

    # Admin reset with a weak password → rejected
    r = _api(client, auth_headers, "post", f"/auth/users/{username}/reset-password",
             {"new_password": "short", "actor_username": "admin"})
    assert r.status_code == 400, f"weak reset should be rejected: {r.text}"


def test_product_age_eligibility_enforced(client, auth_headers):
    """A product with a narrow age band rejects out-of-range applicants.
    Guards the products-vs-product table wiring (engine must read the live
    `products` catalog, not the stale `product` table)."""
    _create_product(client, auth_headers, min_age=25, max_age=40)
    resp = _evaluate(client, auth_headers, age=60, ref_suffix="OLD60")
    assert resp.status_code == 200, f"evaluate failed: {resp.text}"
    data = resp.json()
    assert data["benefits"][0]["outcome"] in ("DECLINED", "POSTPONED"), \
        f"out-of-range applicant should be rejected, got {data['benefits'][0]['outcome']}"


# ── Phase 2 — data-driven medical standards ──────────────────────────────────

def _admin_tenant():
    """tenant_id of the CI admin — the scope the standards API writes under."""
    import os
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT tenant_id::text FROM uw_user WHERE username=%s LIMIT 1",
            (os.environ.get("TEST_USERNAME", "admin"),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return row["tenant_id"] if hasattr(row, "keys") else row[0]
    finally:
        cur.close()
        release_conn(conn)


def test_medical_standard_override_changes_points(client, auth_headers):
    """A per-product override of a standard's ranges must change evaluated
    debit points for that product, leave other products on system defaults,
    and be recorded in the audit trail."""
    _create_product(client, auth_headers)
    build = {"height_inches": 68, "weight_lbs": 240}   # BMI 36.5 → system 75

    base = _evaluate(client, auth_headers, age=40, ref_suffix="BMI0", build=build)
    assert base.status_code == 200, base.text
    base_net = base.json()["benefits"][0]["net_debit_points"]
    assert base_net >= 75, f"system BMI band should fire 75, got {base_net}"

    # Override R010 for THIS product: any BMI ≥30 → 40 points.
    ov = _api(client, auth_headers, "put", "/medical-standards/R010", {
        "family": "Build", "name": "BMI (CI override)", "category": "BUILD",
        "product_code": PRODUCT,
        "rules": [{
            "rule_type": "RANGE", "param": "bmi", "name": "Body mass index",
            "ranges": [{
                "min_value": 30, "max_value": None, "min_exclusive": False,
                "max_exclusive": False, "name": "BMI ≥30 (override)", "debit_points": 40,
            }],
        }],
    })
    assert ov.status_code == 200, f"override failed: {ov.text}"

    over = _evaluate(client, auth_headers, age=40, ref_suffix="BMI1", build=build)
    assert over.status_code == 200, over.text
    over_net = over.json()["benefits"][0]["net_debit_points"]
    assert over_net == 40, f"override should give 40 pts, got {over_net}"

    # Other product code keeps the system band (75) via engine with admin tenant
    from services.uw_engine import run_evaluation
    other = run_evaluation({
        "age": 40, "gender": "MALE", "product_code": "OTHER-CODE",
        "face_amount": 1_000_000, "tobacco_status": "NEVER",
        "heart_condition": "NONE", "diabetes_type": "NONE",
        "occupation_class": "1", "build": build,
    }, actor="test", tenant_id=_admin_tenant())
    assert other["net_debit_points"] == 75, \
        f"non-overridden product should stay on system 75, got {other['net_debit_points']}"

    # The change is audited as a CONFIG event
    import os
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT event_type FROM audit_trail "
        "WHERE entity_type='medical_standard' AND entity_id='R010' "
        "AND actor_username=%s ORDER BY occurred_at DESC LIMIT 1",
        (os.environ.get("TEST_USERNAME", "admin"),),
    )
    row = cur.fetchone(); cur.close(); release_conn(conn)
    evt = row["event_type"] if hasattr(row, "keys") else row[0]
    assert row and evt == "medical_standard.upsert", \
        f"override should be audited, got {row}"


def test_medical_standard_seed_is_complete(client, auth_headers):
    """The V034 system seed must contain all R001–R080 families with their
    rules/bands. A malformed INSERT silently drops a standard's rules and
    breaks evaluations for that family — this locks the seed shape in."""
    resp = _api(client, auth_headers, "get", "/medical-standards")
    assert resp.status_code == 200, resp.text
    standards = {s["code"]: s for s in resp.json()}

    for code in ["R001", "R005", "R010", "R015", "R020", "R030", "R040",
                 "R045", "R050", "R055", "R060", "R070", "R080"]:
        assert code in standards, f"seed missing standard {code}"

    def rule_map(code):
        return {(r["rule_type"], r.get("param"), r.get("name")): r
                for r in standards[code]["rules"]}

    # R015: T1/T2 banded on a1c, plus flat duration/pre-diabetic
    r015 = rule_map("R015")
    t1 = [r for r in standards["R015"]["rules"]
          if r.get("param") == "a1c" and r.get("condition") and
          r["condition"].get("clauses", [{}])[0].get("value") == "TYPE1"]
    assert t1 and len(t1[0]["ranges"]) == 3, f"T1 a1c bands missing: {t1}"
    assert any(r.get("name") == "Type 2 diabetes duration >10yr" and r.get("debit_points") == 25
               for r in r015.values()), "T2 duration flat rule missing"

    # R020: MI banded, angina flat at 75
    r020 = rule_map("R020")
    mi = [r for r in standards["R020"]["rules"] if r.get("param") == "heart_event_years_ago"
          and r.get("condition") and r["condition"].get("clauses", [{}])[0].get("value") == "MI"]
    assert mi and len(mi[0]["ranges"]) == 3, f"MI bands missing: {mi}"
    assert any(r.get("name") == "Angina" and r.get("debit_points") == 75
               for r in r020.values()), "Angina flat rule missing"

    # R010: 4 BMI bands, severe obesity requires APS
    r010 = rule_map("R010")
    severe = [r for r in standards["R010"]["rules"]
              if r.get("ranges") and any(b.get("requires_aps") for b in r["ranges"])]
    assert severe, "R010 should carry an APS-flagged band"
