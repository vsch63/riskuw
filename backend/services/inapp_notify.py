"""
backend/services/inapp_notify.py
──────────────────────────────────
In-app notification feed (Phase 3d). Event triggers across the Underwriter
Workbench write rows to `uw_notification`; the frontend header bell reads them.

Three entry points:
  * emit()              — insert a notification row (used by workbench events)
  * emit_to_case_owner()— notify the underwriter a case is assigned to
  * check_sla_breaches()— scan for overdue open cases and notify their owners
                          once (deduped), callable from the worker loop or the
                          /notifications/sync endpoint.
"""
from __future__ import annotations

import logging

from database import get_conn, release_conn

logger = logging.getLogger("uw_platform")

EVENT_TYPES = ("ASSIGNMENT", "REQUIREMENT", "NOTE", "DECISION", "SLA_BREACH")


def emit(conn, *, tenant_id, recipient, event_type: str, title: str,
         body=None, case_ref_id=None) -> int:
    """Insert one notification row. Returns the new id."""
    if not recipient or recipient == "system":
        return 0
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO uw_notification
                (tenant_id, recipient, event_type, title, body, case_ref_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (tenant_id, recipient, event_type, title[:160], body, case_ref_id),
        )
        row = cur.fetchone()
        return int(dict(row)["id"] if hasattr(row, "keys") else row[0])
    finally:
        cur.close()


def emit_to_case_owner(conn, case_ref_id: int, *, event_type: str, title: str,
                       body=None, except_actor=None, tenant_id=None) -> int | None:
    """Notify the underwriter a case is assigned to, skipping `except_actor`
    (the user performing the action). No-op when the case is unassigned or the
    actor is the owner. Returns the notification id or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT assigned_to FROM case_assignments WHERE case_ref_id=%s",
            (case_ref_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        owner = row["assigned_to"] if hasattr(row, "keys") else row[0]
    finally:
        cur.close()

    if not owner or owner == except_actor:
        return None
    return emit(conn, tenant_id=tenant_id, recipient=owner,
                event_type=event_type, title=title, body=body, case_ref_id=case_ref_id)


# ---------------------------------------------------------------------------
# SLA breach detection
# ---------------------------------------------------------------------------

def check_sla_breaches(conn=None, *, tenant_id=None) -> int:
    """Emit SLA_BREACH notifications for open cases whose sla_due_at has
    passed. Each (case, owner) is notified at most once: an existing unread
    SLA_BREACH row for that case suppresses a duplicate.

    Manages its own connection when none is passed (worker loop). Returns the
    number of notifications emitted.
    """
    own = conn is None
    if own:
        conn = get_conn()
    emitted = 0
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT ca.case_ref_id, ca.assigned_to, pq.applicant_ref
                FROM case_assignments ca
                JOIN policy_admin_queue pq ON pq.id = ca.case_ref_id
                WHERE ca.assigned_to IS NOT NULL
                  AND ca.sla_due_at IS NOT NULL
                  AND ca.sla_due_at < now()
                  AND ca.workbench_status NOT IN ('APPROVED','DECLINED','CLOSED')
                """,
            )
            rows = cur.fetchall()
            for r in rows:
                case_ref_id, owner, applicant = (
                    (r["case_ref_id"], r["assigned_to"], r["applicant_ref"])
                    if hasattr(r, "keys") else (r[0], r[1], r[2])
                )
                # Dedupe: already have an unread SLA_BREACH for this case/owner?
                cur.execute(
                    """
                    SELECT 1 FROM uw_notification
                    WHERE case_ref_id=%s AND recipient=%s
                      AND event_type='SLA_BREACH' AND is_read=false
                    """,
                    (case_ref_id, owner),
                )
                if cur.fetchone():
                    continue
                emit(
                    conn, tenant_id=tenant_id, recipient=owner,
                    event_type="SLA_BREACH",
                    title=f"SLA breach — case {case_ref_id}",
                    body=f"Case {case_ref_id} ({applicant or 'applicant'}) has passed its SLA deadline.",
                    case_ref_id=case_ref_id,
                )
                emitted += 1
        finally:
            cur.close()
        conn.commit()
    except Exception as e:
        if own:
            conn.rollback()
        logger.warning("check_sla_breaches failed: %s", e)
    finally:
        if own:
            release_conn(conn)
    return emitted
