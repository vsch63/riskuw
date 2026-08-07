"""
backend/tests/test_workbench_sla.py
────────────────────────────────────
SLA dashboard + requirements decision gate (Phase 3a / 3b).

Pure HTTP tests through the real endpoints:
  GET  /workbench/sla-dashboard
  POST /workbench/cases/{id}/decision     — gated on pending requirements

Seeds its own policy_admin_queue + case_assignments rows and cleans up.
"""
from __future__ import annotations

import uuid

from database import get_conn, release_conn

PREFIX = f"SLA-{uuid.uuid4().hex[:6]}"


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM case_requirements WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",),
        )
        cur.execute(
            "DELETE FROM case_assignments WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",),
        )
        cur.execute("DELETE FROM policy_admin_queue WHERE applicant_ref LIKE %s", (PREFIX + "%",))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def _seed_referred_case() -> int:
    """Insert a REFERRED case + an OPEN assignment; returns case_ref_id."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO policy_admin_queue
                (applicant_ref, applicant_name, product_code, face_amount, age, gender,
                 outcome, risk_class, net_debit_points, decision_date)
            VALUES (%s, 'SLA Test Applicant', 'TST', 1000000, 35, 'M',
                    'REFERRED', 'STANDARD', 25, now())
            RETURNING id
        """, (f"{PREFIX}-APP",))
        row = cur.fetchone()
        cid = row["id"] if hasattr(row, "keys") else row[0]
        cur.execute("""
            INSERT INTO case_assignments
                (case_ref_id, workbench_status, priority, assigned_to, sla_due_at)
            VALUES (%s, 'OPEN', 'HIGH', 'tester', now() + interval '2 hours')
        """, (cid,))
        conn.commit()
        return cid
    finally:
        cur.close()
        release_conn(conn)


def test_sla_dashboard_shape(client, auth_headers):
    """GET /workbench/sla-dashboard returns stats + breached queue without error."""
    _seed_referred_case()
    try:
        resp = client.get("/workbench/sla-dashboard", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "stats" in data and "tat_by_product" in data and "breached_cases" in data
        assert "sla_breached" in data["stats"]
        assert isinstance(data["stats"]["sla_breached"], int)
    finally:
        _cleanup()


def test_decision_gate_blocks_pending_requirements(client, auth_headers):
    """Final decision on APPROVED/DECLINED is blocked while a REQUESTED
    requirement exists; unblocked once it is WAIVED/RECEIVED."""
    cid = _seed_referred_case()
    try:
        # Add a pending (REQUESTED) requirement
        r = client.post(
            f"/workbench/cases/{cid}/requirements",
            json={"requirement_type": "APS", "description": "latest report"},
            headers=auth_headers,
        )
        assert r.status_code in (200, 201), r.text
        req_id = r.json()["id"]

        # Gate: APPROVED should be rejected with a 400
        blocked = client.post(
            f"/workbench/cases/{cid}/decision",
            json={"final_outcome": "APPROVED", "final_reason": "clean"},
            headers=auth_headers,
        )
        assert blocked.status_code == 400, f"expected 400, got {blocked.status_code}: {blocked.text}"
        assert "pending requirement" in blocked.json()["detail"].lower()

        # Mark the requirement WAIVED → gate clears
        w = client.patch(
            f"/workbench/requirements/{req_id}",
            json={"status": "WAIVED", "notes": "not needed"},
            headers=auth_headers,
        )
        assert w.status_code in (200, 204), w.text

        ok = client.post(
            f"/workbench/cases/{cid}/decision",
            json={"final_outcome": "APPROVED", "final_reason": "clean after review"},
            headers=auth_headers,
        )
        assert ok.status_code == 200, f"expected 200 after waive, got {ok.text}"
        assert ok.json()["final_outcome"] == "APPROVED"
    finally:
        _cleanup()


def test_decision_gate_allows_when_no_requirements(client, auth_headers):
    """No requirements → decision proceeds immediately (no false block)."""
    cid = _seed_referred_case()
    try:
        ok = client.post(
            f"/workbench/cases/{cid}/decision",
            json={"final_outcome": "DECLINED", "final_reason": "high debit"},
            headers=auth_headers,
        )
        assert ok.status_code == 200, f"expected 200, got {ok.text}"
        assert ok.json()["final_outcome"] == "DECLINED"
    finally:
        _cleanup()
