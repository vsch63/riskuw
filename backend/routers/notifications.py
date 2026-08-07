"""
backend/routers/notifications.py
──────────────────────────────────
In-app notification feed (Phase 3d) — powers the header bell.

  GET  /notifications                 — my notifications (latest first)
  GET  /notifications/unread-count    — unread count for the bell badge
  POST /notifications/read            — mark one ({notification_id}) or all ({all:true}) read
  POST /notifications/sync            — run SLA breach detection, return new unread count

Recipients are uw_user.usernames; every query is scoped to the caller.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_conn, release_conn
from deps import CurrentUser
from services.inapp_notify import check_sla_breaches

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_db():
    conn = get_conn()
    return conn, lambda c: release_conn(c)


class ReadRequest(BaseModel):
    notification_id: int | None = None
    all: bool = False


@router.get("")
def list_notifications(unread_only: bool = False, limit: int = 30,
                       current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sql = """
            SELECT id::text, event_type, title, body, case_ref_id,
                   is_read, read_at, created_at
            FROM uw_notification
            WHERE recipient = %s
        """
        params: list = [current.username]
        if unread_only:
            sql += " AND is_read = false"
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(min(int(limit), 100))
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        # Format timestamps for the UI
        for r in rows:
            r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
            r["read_at"] = r["read_at"].isoformat() if r["read_at"] else None
        return {"notifications": rows, "count": len(rows)}
    finally:
        release(conn)


@router.get("/unread-count")
def unread_count(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM uw_notification WHERE recipient=%s AND is_read=false",
            (current.username,),
        )
        row = cur.fetchone()
        n = int(row[0] if isinstance(row, tuple) else dict(row)["count"])
        return {"unread": n}
    finally:
        release(conn)


@router.post("/read")
def mark_read(body: ReadRequest, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        if body.all:
            cur.execute(
                "UPDATE uw_notification SET is_read=true, read_at=now() "
                "WHERE recipient=%s AND is_read=false",
                (current.username,),
            )
        elif body.notification_id:
            cur.execute(
                "UPDATE uw_notification SET is_read=true, read_at=now() "
                "WHERE id=%s AND recipient=%s",
                (body.notification_id, current.username),
            )
        else:
            raise HTTPException(400, "Provide notification_id or all:true")
        conn.commit()
        return {"ok": True}
    finally:
        release(conn)


@router.post("/sync")
def sync(current: CurrentUser = CurrentUser):
    """Detect fresh SLA breaches for this tenant and return the caller's
    unread count. Called by the frontend bell poll so breach alerts surface
    without a background scheduler."""
    conn, release = _get_db()
    try:
        emitted = check_sla_breaches(conn, tenant_id=current.tenant_id)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM uw_notification WHERE recipient=%s AND is_read=false",
            (current.username,),
        )
        row = cur.fetchone()
        unread = int(row[0] if isinstance(row, tuple) else dict(row)["count"])
        cur.close()
        return {"emitted": emitted, "unread": unread}
    finally:
        release(conn)
