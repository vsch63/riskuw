"""
backend/routers/audit.py
─────────────────────────
GET  /audit/stats          — 30-day summary metrics
GET  /audit                — paginated, filtered event list
GET  /audit/export         — CSV export of matching events
GET  /audit/{event_id}     — single event detail
GET  /audit/entity/{id}    — all events for a specific entity
POST /audit/seed           — record a manual login event (first-run helper)

Table: audit_trail
"""
from __future__ import annotations
from datetime import datetime, timedelta, date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from deps import CurrentUser
import io, csv

router = APIRouter(prefix="/audit", tags=["audit"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                                    AS total,
                COUNT(*) FILTER (WHERE event_category = 'DECISION')        AS decisions,
                COUNT(*) FILTER (WHERE event_category = 'OVERRIDE')        AS overrides,
                COUNT(*) FILTER (WHERE event_category = 'AUTH')            AS auth,
                COUNT(*) FILTER (WHERE event_category = 'CONFIG')          AS config,
                COUNT(*) FILTER (WHERE event_category = 'ASSIGNMENT')      AS assignments,
                COUNT(*) FILTER (WHERE event_category = 'USER_MGMT')       AS user_mgmt,
                COUNT(*) FILTER (WHERE outcome = 'FAILURE')                AS failures
            FROM audit_trail
            WHERE occurred_at >= NOW() - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return {"total":0,"decisions":0,"overrides":0,"auth":0,"config":0,"assignments":0,"user_mgmt":0,"failures":0}
        return dict(row)
    except Exception as e:
        return {"total":0,"decisions":0,"overrides":0,"auth":0,"config":0,"assignments":0,"user_mgmt":0,"failures":0,"_error":str(e)}
    finally:
        release(conn)


# ── List (paginated + filtered) ────────────────────────────────────────────────

@router.get("")
def list_events(
    current:    CurrentUser,
    search:     str  = Query(""),
    date_from:  str  = Query(""),
    date_to:    str  = Query(""),
    category:   str  = Query("All"),
    outcome:    str  = Query("All"),
    page:       int  = Query(1, ge=1),
    page_size:  int  = Query(50, ge=1, le=200),
):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Build WHERE
        conditions = []
        params: list = []

        if date_from:
            try:
                conditions.append("occurred_at >= %s")
                params.append(datetime.fromisoformat(date_from))
            except ValueError:
                pass
        else:
            conditions.append("occurred_at >= %s")
            params.append(datetime.now() - timedelta(days=30))

        if date_to:
            try:
                conditions.append("occurred_at <= %s")
                params.append(datetime.fromisoformat(date_to + "T23:59:59"))
            except ValueError:
                pass
        else:
            conditions.append("occurred_at <= %s")
            params.append(datetime.now())

        if category and category != "All":
            conditions.append("event_category = %s")
            params.append(category)

        if outcome and outcome != "All":
            conditions.append("outcome = %s")
            params.append(outcome)

        if search.strip():
            conditions.append("""(
                actor_username ILIKE %s OR
                event_type     ILIKE %s OR
                entity_ref     ILIKE %s OR
                entity_id::text ILIKE %s OR
                entity_type    ILIKE %s
            )""")
            s = f"%{search.strip()}%"
            params.extend([s, s, s, s, s])

        where = " AND ".join(conditions) if conditions else "1=1"

        # Count
        cur.execute(f"SELECT COUNT(*) FROM audit_trail WHERE {where}", params)
        total = cur.fetchone()["count"]

        # Fetch page
        offset = (page - 1) * page_size
        cur.execute(f"""
            SELECT
                event_id, occurred_at, event_category, event_type,
                actor_username, actor_role, entity_type, entity_id::text,
                entity_ref, outcome, failure_reason,
                before_state, after_state, event_metadata, actor_ip
            FROM audit_trail
            WHERE {where}
            ORDER BY occurred_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])

        rows = cur.fetchall()
        cur.close()

        events = []
        for r in rows:
            d = dict(r)
            d["event_id"]   = str(d.get("event_id") or "")
            d["occurred_at"] = str(d["occurred_at"])[:19] if d.get("occurred_at") else ""
            # Stringify JSON fields
            for k in ("before_state", "after_state", "event_metadata"):
                v = d.get(k)
                if v and not isinstance(v, str):
                    import json
                    d[k] = json.dumps(v)
            events.append(d)

        return {
            "total":      total,
            "page":       page,
            "page_size":  page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "events":     events,
        }
    finally:
        release(conn)


# ── Export CSV ─────────────────────────────────────────────────────────────────

@router.get("/export")
def export_csv(
    current:   CurrentUser,
    search:    str = Query(""),
    date_from: str = Query(""),
    date_to:   str = Query(""),
    category:  str = Query("All"),
    outcome:   str = Query("All"),
):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        conditions = []
        params: list = []

        if date_from:
            try: conditions.append("occurred_at >= %s"); params.append(datetime.fromisoformat(date_from))
            except ValueError: pass
        else:
            conditions.append("occurred_at >= %s"); params.append(datetime.now() - timedelta(days=30))

        if date_to:
            try: conditions.append("occurred_at <= %s"); params.append(datetime.fromisoformat(date_to + "T23:59:59"))
            except ValueError: pass
        else:
            conditions.append("occurred_at <= %s"); params.append(datetime.now())

        if category != "All": conditions.append("event_category = %s"); params.append(category)
        if outcome  != "All": conditions.append("outcome = %s");        params.append(outcome)
        if search.strip():
            conditions.append("(actor_username ILIKE %s OR event_type ILIKE %s OR entity_ref ILIKE %s OR entity_id::text ILIKE %s OR entity_type ILIKE %s)")
            s = f"%{search.strip()}%"; params.extend([s,s,s,s,s])

        where = " AND ".join(conditions) if conditions else "1=1"
        cur.execute(f"""
            SELECT event_id, occurred_at, event_category, event_type,
                   actor_username, actor_role, entity_type, entity_id::text,
                   entity_ref, outcome, failure_reason, actor_ip
            FROM audit_trail WHERE {where}
            ORDER BY occurred_at DESC LIMIT 10000
        """, params)
        rows = cur.fetchall()
        cur.close()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["event_id","occurred_at","category","event_type","actor","role","entity_type","entity_id","entity_ref","outcome","failure_reason","actor_ip"])
        for r in rows:
            writer.writerow([str(r.get(k,"") or "") for k in ["event_id","occurred_at","event_category","event_type","actor_username","actor_role","entity_type","entity_id","entity_ref","outcome","failure_reason","actor_ip"]])

        buf.seek(0)
        fn = f"audit_{date_from or 'all'}_{date_to or 'all'}.csv"
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'})
    finally:
        release(conn)


# ── Single event detail ────────────────────────────────────────────────────────

@router.get("/entity/{entity_id}")
def get_entity_timeline(entity_id: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT occurred_at, event_type, actor_username, outcome, event_category
            FROM audit_trail
            WHERE entity_id::text = %s
            ORDER BY occurred_at ASC
        """, (entity_id,))
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "occurred_at":  str(r["occurred_at"])[:19],
                "event_type":   r["event_type"],
                "actor":        r["actor_username"] or "—",
                "outcome":      r["outcome"],
                "category":     r["event_category"],
            }
            for r in rows
        ]
    finally:
        release(conn)


@router.get("/{event_id}")
def get_event(event_id: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT event_id, occurred_at, event_category, event_type,
                   actor_username, actor_role, entity_type, entity_id::text,
                   entity_ref, outcome, failure_reason,
                   before_state, after_state, event_metadata, actor_ip
            FROM audit_trail WHERE event_id = %s::uuid
        """, (event_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(404, "Event not found")
        d = dict(row)
        d["occurred_at"] = str(d["occurred_at"])[:19]
        return d
    finally:
        release(conn)


# ── Seed helper ────────────────────────────────────────────────────────────────

class SeedBody(BaseModel):
    note: Optional[str] = "Manual seed from Audit Log page"


@router.post("/seed")
def seed_login_event(body: SeedBody, current: CurrentUser):
    conn, release = _get_db()
    try:
        import json
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_trail
                (event_category, event_type, actor_username, actor_role,
                 entity_type, entity_id, outcome, event_metadata, occurred_at)
            VALUES ('AUTH', 'LOGIN_SUCCESS', %s, %s, 'USER', %s, 'SUCCESS', %s::jsonb, NOW())
        """, (
            current.username, current.role, current.username,
            json.dumps({"method": "manual_seed", "note": body.note})
        ))
        conn.commit(); cur.close()
        return {"status": "seeded", "message": "Login event written to audit trail"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Seed failed: {e}")
    finally:
        release(conn)
