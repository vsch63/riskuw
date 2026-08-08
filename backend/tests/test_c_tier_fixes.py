"""
backend/tests/test_c_tier_fixes.py
───────────────────────────────────
Regression tests for the C-tier code-vs-schema mismatches found by the drift
audit (V039 + the 4 clusters it produced). Every endpoint here previously
failed against a fresh-DB schema:

  * PUT /products/{code}/thresholds — INSERT referenced change_reason /
    expire_date and ON CONFLICT (product_code), none of which exist on
    product_decision_thresholds (real: expiry_date, unique (tenant_id,
    product_code), several NOT NULL risk-flag columns). Silently swallowed →
    the dedicated row was never written and the engine kept using defaults.
  * POST /custom-rules — INSERT referenced rule_name/condition_json/
    debit_points/is_hard_stop/aps_required; the real custom_uw_rule table has
    rule_id/name/logic/conditions/action/priority/… NOT NULL. Always 500.
  * POST+GET+PATCH /batch/schedules — wrote is_active/created_by/updated_at /
    ordered by submitted_at; the real table has status and none of those.
"""
from __future__ import annotations

import uuid

from database import get_conn, release_conn

PRODUCT = f"CTFIX-{uuid.uuid4().hex[:6].upper()}"
RULE_ID = f"CTFIX-R1-{uuid.uuid4().hex[:4].upper()}"
SCHED_NAME = f"CTFIX schedule {uuid.uuid4().hex[:6]}"


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM product_decision_thresholds WHERE product_code = %s", (PRODUCT,))
        cur.execute("DELETE FROM products WHERE product_code = %s", (PRODUCT,))
        cur.execute("DELETE FROM custom_uw_rule WHERE rule_id LIKE 'CTFIX-%'")
        cur.execute("DELETE FROM batch_recurring_schedules WHERE schedule_name LIKE 'CTFIX schedule %'")
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def _make_product(client, headers):
    resp = client.post("/products", json={
        "product_code": PRODUCT,
        "product_name": f"CI C-tier fix {PRODUCT}",
        "product_type": "individual",
        "min_age": 18, "max_age": 65,
        "min_face_amount": 100000, "max_face_amount": 10000000,
        "available_terms": [20],
        "stp_threshold": 75, "refer_threshold": 150, "decline_threshold": 300,
    }, headers=headers)
    assert resp.status_code in (200, 201), f"create_product failed: {resp.text}"


def test_thresholds_put_persists_and_engine_reads(client, auth_headers):
    _cleanup()
    try:
        _make_product(client, auth_headers)

        resp = client.put(f"/products/{PRODUCT}/thresholds", json={
            "stp_threshold": 60, "refer_threshold": 140, "decline_threshold": 280,
            "max_table_rating": 10, "max_flat_extra": 12.5,
            "change_reason": "regression", "effective_date": "2026-08-01",
            "expire_date": None,
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text

        # Dedicated row must be readable (previously the SELECT fell through
        # to the products inline columns because its column list was invalid).
        resp = client.get(f"/products/{PRODUCT}/thresholds", headers=auth_headers)
        d = resp.json()
        assert resp.status_code == 200, resp.text
        assert d["stp_threshold"] == 60 and d["refer_threshold"] == 140, d
        assert d["max_table_rating"] == 10, d
        assert d["expire_date"] is None and d["change_reason"] is None, d

        # Engine must read the persisted row, not the 75/150/200 defaults.
        from services.uw_engine import _get_thresholds
        t = _get_thresholds(PRODUCT)
        assert t == {"stp_threshold": 60, "refer_threshold": 140, "decline_threshold": 280}, t
    finally:
        _cleanup()


def test_custom_rule_create_lists_and_maps_fields(client, auth_headers):
    _cleanup()
    try:
        resp = client.post("/custom-rules", json={
            "rule_id": RULE_ID,
            "rule_name": "C-tier regression rule",
            "category": "CUSTOM",
            "description": "created by regression test",
            "condition_logic": "AND",
            "priority": 2,
            "debit_points": 25, "hard_stop": False, "requires_aps": True,
            "conditions": {"logic": "AND",
                           "conditions": [{"field": "age", "operator": ">", "value": 50}]},
            "status": "DRAFT",
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text

        resp = client.get("/custom-rules", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json() if isinstance(resp.json(), list) else []
        mine = [r for r in rows if r.get("rule_id") == RULE_ID]
        assert len(mine) == 1, f"rule not found: {rows}"
        row = mine[0]
        # Real-table columns mapped back to the frontend contract:
        assert row["rule_name"] == "C-tier regression rule", row
        assert row["rule_code"] == RULE_ID, row
        assert row["debit_points"] == 25, row
        assert row["requires_aps"] is True and row["hard_stop"] is False, row
        assert row["status"] == "DRAFT", row
    finally:
        _cleanup()


def test_batch_schedule_create_list_toggle(client, auth_headers):
    _cleanup()
    try:
        resp = client.post("/batch/schedules", json={
            "schedule_name": SCHED_NAME, "cron_expression": "0 2 * * *", "is_active": True,
        }, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        sid = resp.json()["id"]

        resp = client.get("/batch/schedules", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json() if isinstance(resp.json(), list) else []
        sched = [s for s in rows if s.get("id") == sid]
        assert len(sched) == 1, f"schedule not listed: {rows}"
        assert sched[0]["is_active"] is True, sched[0]

        resp = client.patch(f"/batch/schedules/{sid}", json={"is_active": False}, headers=auth_headers)
        assert resp.status_code == 200, resp.text

        resp = client.get("/batch/schedules", headers=auth_headers)
        sched = [s for s in (resp.json() if isinstance(resp.json(), list) else []) if s.get("id") == sid]
        assert len(sched) == 1 and sched[0]["is_active"] is False, sched
    finally:
        _cleanup()
