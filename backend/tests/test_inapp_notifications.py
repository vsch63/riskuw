"""
backend/tests/test_inapp_notifications.py
──────────────────────────────────────────
In-app notification feed (Phase 3d) — event triggers + header bell API.

  * Assignment / note / requirement / decision events write rows
  * GET /notifications, /unread-count, POST /read work per-recipient
  * POST /notifications/sync detects SLA breaches (deduped)

Seeds its own cases + cleans up. Uses DB reads to assert rows targeted at a
user other than the acting one.
"""
from __future__ import annotations

import uuid

from database import get_conn, release_conn

PREFIX = f"NOTIF-{uuid.uuid4().hex[:6]}"
OWNER = "notif_owner"


def _ensure_owner_user():
    """Ensure the OWNER test user exists with a tenant_id."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT tenant_id FROM uw_user WHERE username = %s", (OWNER,))
        row = cur.fetchone()
        if row:
            return row["tenant_id"] if hasattr(row, "keys") else row[0]
        # Create the user in the CITEST tenant (same as admin)
        cur.execute("SELECT tenant_id FROM uw_user WHERE username = 'admin'")
        row = cur.fetchone()
        admin_tenant = row["tenant_id"] if hasattr(row, "keys") else row[0]

        import bcrypt
        cur.execute("""
            INSERT INTO uw_user (id, username, email, hashed_password, full_name,
                                 role, is_active, is_deleted, tenant_id,
                                 created_by, updated_by, version)
            VALUES (%s, %s, %s, %s, 'Notif Owner', 'underwriter', true, false, %s,
                    'system', 'system', 1)
        """, (str(uuid.uuid4()), OWNER, f"{OWNER}@test.local",
               bcrypt.hashpw(b"TestPass123!", bcrypt.gensalt(rounds=12)).decode(),
               admin_tenant))
        conn.commit()
        return admin_tenant
    finally:
        cur.close()
        release_conn(conn)


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM uw_notification WHERE case_ref_id IN "
            "(SELECT id FROM policy_admin_queue WHERE applicant_ref LIKE %s)",
            (PREFIX + "%",),
        )
        cur.execute("DELETE FROM uw_notification WHERE recipient IN (%s, %s, 'admin')",
                    (PREFIX, OWNER))
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


def _seed_case(*, assigned_to: str | None = None, overdue: bool = False) -> int:
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Ensure OWNER user exists if we're assigning to them
        if assigned_to == OWNER:
            _ensure_owner_user()

        # Get the tenant_id for the assigned_to user (or demo tenant if not specified)
        if assigned_to:
            cur.execute("SELECT tenant_id FROM uw_user WHERE username = %s", (assigned_to,))
            row = cur.fetchone()
            tenant_id = row["tenant_id"] if hasattr(row, "keys") else row[0]
        else:
            tenant_id = '00000000-0000-0000-0000-000000000001'

        cur.execute("""
            INSERT INTO policy_admin_queue
                (applicant_ref, applicant_name, product_code, face_amount, age, gender,
                 outcome, risk_class, net_debit_points, decision_date, tenant_id)
            VALUES (%s, 'Notif Test Applicant', 'TST', 1000000, 35, 'M',
                    'REFERRED', 'STANDARD', 25, now(), %s)
            RETURNING id
        """, (f"{PREFIX}-{uuid.uuid4().hex[:4]}", tenant_id))
        row = cur.fetchone()
        cid = row["id"] if hasattr(row, "keys") else row[0]
        if assigned_to is not None:
            sla = "now() - interval '2 hours'" if overdue else "now() + interval '2 hours'"
            cur.execute(f"""
                INSERT INTO case_assignments
                    (case_ref_id, workbench_status, priority, assigned_to, sla_due_at)
                VALUES (%s, 'OPEN', 'NORMAL', %s, {sla})
            """, (cid, assigned_to))
        conn.commit()
        return cid
    finally:
        cur.close()
        release_conn(conn)


def _count_for(recipient: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM uw_notification WHERE recipient=%s", (recipient,))
        row = cur.fetchone()
        return int(row[0] if isinstance(row, tuple) else row["count"])
    finally:
        cur.close()
        release_conn(conn)


def test_assign_emits_notification(client, auth_headers):
    cid = _seed_case()
    try:
        before = _count_for(OWNER)
        r = client.post(f"/workbench/cases/{cid}/assign",
                        json={"assigned_to": OWNER}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert _count_for(OWNER) == before + 1
    finally:
        _cleanup()


def test_note_by_non_owner_notifies_owner(client, auth_headers):
    cid = _seed_case(assigned_to=OWNER)
    try:
        before = _count_for(OWNER)
        r = client.post(f"/workbench/cases/{cid}/notes",
                        json={"note": "please review urgently"}, headers=auth_headers)
        assert r.status_code in (200, 201), r.text
        assert _count_for(OWNER) == before + 1
    finally:
        _cleanup()


def test_note_by_owner_does_not_self_notify(client, auth_headers):
    cid = _seed_case(assigned_to="admin")  # auth_headers user owns the case
    try:
        before = _count_for("admin")
        r = client.post(f"/workbench/cases/{cid}/notes",
                        json={"note": "self note"}, headers=auth_headers)
        assert r.status_code in (200, 201), r.text
        assert _count_for("admin") == before, "owner should not be notified of own note"
    finally:
        _cleanup()


def test_requirement_added_notifies_owner(client, auth_headers):
    cid = _seed_case(assigned_to=OWNER)
    try:
        before = _count_for(OWNER)
        r = client.post(f"/workbench/cases/{cid}/requirements",
                        json={"requirement_type": "APS", "description": "latest report"},
                        headers=auth_headers)
        assert r.status_code in (200, 201), r.text
        assert _count_for(OWNER) == before + 1
    finally:
        _cleanup()


def test_requirement_received_notifies_requester(client, auth_headers):
    cid = _seed_case(assigned_to="admin")
    try:
        # admin requests the requirement, then admin marks it RECEIVED — but
        # requester == actor, so no self-notify. Seed a requirement requested
        # by OWNER instead, then admin marks it RECEIVED.
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO case_requirements (case_ref_id, requirement_type, description, requested_by)
            VALUES (%s, 'APS', 'report', %s) RETURNING id
        """, (cid, OWNER))
        row = cur.fetchone()
        req_id = row["id"] if hasattr(row, "keys") else row[0]
        conn.commit()
        cur.close()
        release_conn(conn)

        before = _count_for(OWNER)
        r = client.patch(f"/workbench/requirements/{req_id}",
                         json={"status": "RECEIVED", "notes": "got it"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert _count_for(OWNER) == before + 1
    finally:
        _cleanup()


def test_decision_notifies_owner(client, auth_headers):
    cid = _seed_case(assigned_to=OWNER)
    try:
        before = _count_for(OWNER)
        r = client.post(f"/workbench/cases/{cid}/decision",
                        json={"final_outcome": "DECLINED", "final_reason": "high risk"},
                        headers=auth_headers)
        assert r.status_code == 200, r.text
        assert _count_for(OWNER) == before + 1
    finally:
        _cleanup()


def test_unread_count_list_and_mark_read(client, auth_headers):
    try:
        # For admin's own feed, direct-insert a row (event triggers target the
        # case owner, which is OWNER in our seeded scenarios).
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO uw_notification (recipient, event_type, title, body)
            VALUES ('admin', 'NOTE', 'Direct test', 'for admin feed')
        """)
        conn.commit()
        cur.close()
        release_conn(conn)

        uc = client.get("/notifications/unread-count", headers=auth_headers)
        assert uc.status_code == 200, uc.text
        assert uc.json()["unread"] >= 1

        lst = client.get("/notifications?limit=5", headers=auth_headers)
        assert lst.status_code == 200, lst.text
        notifs = lst.json()["notifications"]
        assert any(n["title"] == "Direct test" for n in notifs)
        assert all("case_ref_id" in n for n in notifs)  # row-shaped

        mr = client.post("/notifications/read", json={"all": True}, headers=auth_headers)
        assert mr.status_code == 200, mr.text
        uc2 = client.get("/notifications/unread-count", headers=auth_headers)
        assert uc2.json()["unread"] == 0
    finally:
        _cleanup()


def test_sync_detects_sla_breach_once(client, auth_headers):
    cid = _seed_case(assigned_to="admin", overdue=True)
    try:
        before = _count_for("admin")
        s1 = client.post("/notifications/sync", headers=auth_headers)
        assert s1.status_code == 200, s1.text
        data = s1.json()
        assert data["unread"] == before + 1
        assert data["emitted"] >= 1

        # Dedup: a second sync must not re-emit for the same breach
        s2 = client.post("/notifications/sync", headers=auth_headers)
        assert s2.json()["unread"] == before + 1, "breach must not double-notify"
    finally:
        _cleanup()
