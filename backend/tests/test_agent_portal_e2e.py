"""
backend/tests/test_agent_portal_e2e.py
────────────────────────────────────────
End-to-end integration through the REAL agent → workbench → notification flow:

    agent login → POST /agent/submit → SAR pre-check → UW engine → persist
        → REFERRED case appears in /workbench/queue (assignment auto-created)
    → assign                        → ASSIGNMENT  notification to assignee
    → add requirement               → REQUIREMENT notification to owner
    → mark requirement RECEIVED     → clears the decision gate
    → record decision               → DECISION    notification to owner

This ties together seams that unit tests cover in isolation (SAR loader/engine,
UW rules, _persist_decision/_persist_to_queue wiring, workbench mutations,
inapp_notify emission), so a wiring break anywhere in the chain fails here —
the same class of bug that has repeatedly broken this platform.

Seeds its own product + agent user and cleans up after itself.
"""
from __future__ import annotations

import uuid

import pytest
from database import get_conn, release_conn

PRODUCT    = "AGENT-E2E"
PREFIX     = f"AGENT-E2E-{uuid.uuid4().hex[:4]}"
AGENT_USER = "e2e_agent"
AGENT_PASS = "AgentPass123"
OWNER      = "e2e_uw_owner"


# ── helpers ───────────────────────────────────────────────────────────────

def _api(client, headers, method: str, path: str, body=None):
    fn = getattr(client, method)
    return fn(path, json=body, headers=headers) if body is not None else fn(path, headers=headers)


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM uw_notification WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",))
        cur.execute(
            "DELETE FROM case_requirements WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",))
        cur.execute(
            "DELETE FROM case_notes WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",))
        cur.execute(
            "DELETE FROM case_assignments WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",))
        cur.execute(
            "DELETE FROM uw_decision WHERE application_id IN "
            "(SELECT id FROM application WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",))
        cur.execute(
            "DELETE FROM uw_case WHERE application_id IN "
            "(SELECT id FROM application WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",))
        cur.execute("DELETE FROM application WHERE applicant_ref LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM applicant_master WHERE applicant_ref LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM policy_admin_queue WHERE applicant_ref LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM uw_user WHERE username = %s", (AGENT_USER,))
        cur.execute("DELETE FROM products WHERE product_code = %s", (PRODUCT,))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


@pytest.fixture(autouse=True)
def _cleanup_around():
    _cleanup()
    yield
    _cleanup()


def _create_product(client, headers):
    r = _api(client, headers, "post", "/products", {
        "product_code": PRODUCT,
        "product_name": "CI Agent E2E",
        "product_type": "individual",
        "min_age": 18, "max_age": 70,
        "min_face_amount": 100000, "max_face_amount": 20000000,
        "available_terms": [20],
        "stp_threshold": 75, "refer_threshold": 150, "decline_threshold": 300,
    })
    assert r.status_code in (200, 201), f"create product failed: {r.text}"


def _create_agent(client, headers):
    r = _api(client, headers, "post", "/auth/register", {
        "username": AGENT_USER,
        "email": f"{AGENT_USER}@example.com",
        "password": AGENT_PASS,
        "full_name": "CI E2E Agent",
        "role": "agent",
    })
    assert r.status_code == 201, f"register agent failed: {r.text}"


def _agent_headers(client):
    r = _api(client, None, "post", "/auth/login", {
        "username": AGENT_USER, "password": AGENT_PASS})
    assert r.status_code == 200, f"agent login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _submit(client, agent_headers, *, ref, age, tobacco, height, weight):
    return _api(client, agent_headers, "post", "/agent/submit", {
        "applicant_ref": ref,
        "product_code": PRODUCT,
        "age": age, "gender": "MALE", "state": "MH",
        "face_amount": 5_000_000, "coverage_term_yrs": 20,
        "tobacco_status": tobacco,
        "height_inches": height, "weight_lbs": weight,
        "annual_income": 1_500_000,
    })


def _queue_case(client, headers, applicant_ref):
    r = _api(client, headers, "get", "/workbench/queue")
    assert r.status_code == 200, r.text
    return next((c for c in r.json()["cases"] if c["applicant_ref"] == applicant_ref), None)


def _count_notifications(recipient: str, event_type: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM uw_notification WHERE recipient=%s AND event_type=%s",
            (recipient, event_type))
        row = cur.fetchone()
        return int(row[0] if isinstance(row, tuple) else row["count"])
    finally:
        cur.close()
        release_conn(conn)


# ── scenario: the full chain ──────────────────────────────────────────────

def test_agent_referred_case_full_workbench_and_notification_flow(client, auth_headers):
    _create_product(client, auth_headers)
    _create_agent(client, auth_headers)
    agent = _agent_headers(client)

    # Age 60 (25) + current smoker (75) + BMI ~38.7 (75) ⇒ net 175 → REFERRED
    # (tobacco_status is the engine's canonical "SMOKER" — "CURRENT" matches nothing)
    ref = f"{PREFIX}-A1"
    r = _submit(client, agent, ref=ref, age=60, tobacco="SMOKER", height=66, weight=240)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["outcome"] == "REFERRED", f"expected REFERRED, got {data['outcome']}"

    # 1. REFERRED case lands in the workbench queue (assignment auto-created)
    case = _queue_case(client, auth_headers, ref)
    assert case is not None, "REFERRED agent case missing from workbench queue"
    assert case["workbench_status"] in ("OPEN", "PENDING_REQUIREMENTS")
    case_id = case["case_ref_id"]

    # 2. Assign → ASSIGNMENT notification to the assignee
    r = _api(client, auth_headers, "post", f"/workbench/cases/{case_id}/assign",
             {"assigned_to": OWNER})
    assert r.status_code == 200, r.text
    assert _count_notifications(OWNER, "ASSIGNMENT") == 1

    # 3. Add requirement → REQUIREMENT notification to the owner
    r = _api(client, auth_headers, "post", f"/workbench/cases/{case_id}/requirements",
             {"requirement_type": "APS", "description": "latest APS"})
    assert r.status_code in (200, 201), r.text
    assert _count_notifications(OWNER, "REQUIREMENT") == 1
    req_id = r.json()["id"]

    # 4. Decision is gated until the pending requirement is resolved
    r = _api(client, auth_headers, "post", f"/workbench/cases/{case_id}/decision",
             {"final_outcome": "APPROVED", "final_reason": "looks fine"})
    assert r.status_code == 400, f"expected 400 (pending requirement), got {r.text}"

    # 5. Mark requirement RECEIVED → clears the gate
    r = _api(client, auth_headers, "patch", f"/workbench/requirements/{req_id}",
             {"status": "RECEIVED", "notes": "got the APS"})
    assert r.status_code == 200, r.text

    # 6. Record decision → DECISION notification to the owner
    r = _api(client, auth_headers, "post", f"/workbench/cases/{case_id}/decision",
             {"final_outcome": "APPROVED", "final_reason": "acceptable after review"})
    assert r.status_code == 200, r.text
    assert _count_notifications(OWNER, "DECISION") == 1

    # 7. Source-of-truth updated: case leaves the queue, assignment records the decision
    assert _queue_case(client, auth_headers, ref) is None, \
        "decided case must drop out of the workbench queue"
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT final_outcome, workbench_status FROM case_assignments WHERE case_ref_id=%s",
                    (case_id,))
        row = cur.fetchone()
        row = row if isinstance(row, dict) else {"final_outcome": row[0], "workbench_status": row[1]}
        assert row["final_outcome"] == "APPROVED", row
        assert row["workbench_status"] == "APPROVED", row
        cur.execute("SELECT outcome FROM policy_admin_queue WHERE id=%s", (case_id,))
        o = cur.fetchone()
        assert (o if isinstance(o, dict) else {"outcome": o[0]})["outcome"] == "APPROVED"
    finally:
        cur.close()
        release_conn(conn)


def test_agent_clean_applicant_stp_does_not_enter_queue(client, auth_headers):
    _create_product(client, auth_headers)
    _create_agent(client, auth_headers)
    agent = _agent_headers(client)

    # Clean applicant ⇒ net 0 → APPROVED_STP (no SAR config for this product)
    ref = f"{PREFIX}-A2"
    r = _submit(client, agent, ref=ref, age=30, tobacco="NEVER", height=68, weight=160)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["outcome"] == "APPROVED_STP", f"expected APPROVED_STP, got {data['outcome']}"

    # STP cases must NOT enter the workbench queue (REFER-only filter)
    assert _queue_case(client, auth_headers, ref) is None, \
        "APPROVED_STP agent case must not appear in the workbench queue"
