"""
backend/routers/queue.py
─────────────────────────
GET  /queue/               — paginated queue with filters
GET  /queue/{id}           — single case
POST /queue/assign         — assign to underwriter
POST /queue/decide         — manual UW decision
POST /queue/aps/request    — raise APS request
GET  /queue/aps/{case_id}  — APS requests for a case
POST /queue/aps/update     — update APS status
GET  /queue/underwriters   — list eligible UW users

Tables: policy_admin_queue · aps_request · uw_user · audit_trail
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from deps import CurrentUser

router = APIRouter(prefix="/queue", tags=["queue"])


def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else {}


# ── Queue list ────────────────────────────────────────────────────────────────

@router.get("/")
def list_queue(
    current: CurrentUser,
    page_size: int = 50,
    page: int = 1,
    status: str | None = None,
):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where = "WHERE 1=1"
        params: list = []
        if status:
            where += " AND status = %s"
            params.append(status)
        offset = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT id, applicant_ref, applicant_name, product_code,
                   face_amount, age, gender, outcome, risk_class,
                   net_debit_points, approved_premium, status,
                   decision_date AS created_at, source
            FROM policy_admin_queue
            {where}
            ORDER BY decision_date DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, offset),
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


@router.get("/underwriters")
def list_underwriters(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username, full_name, role FROM uw_user "
            "WHERE role IN ('underwriter','senior_underwriter','admin','super_admin') "
            "AND is_active=true AND is_deleted=false ORDER BY username"
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


@router.get("/{case_id}")
def get_case(case_id: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM policy_admin_queue WHERE id=%s",
            (case_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(404, "Case not found")
        return _row(row)
    finally:
        release(conn)


# ── Assign ────────────────────────────────────────────────────────────────────

class AssignRequest(BaseModel):
    case_id: str
    assigned_to: str


@router.post("/assign")
def assign_case(body: AssignRequest, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE policy_admin_queue SET status='IN_REVIEW' "
            "WHERE id=%s",
            (body.case_id,),
        )
        conn.commit()
        cur.close()
        return {"status": "assigned", "case_id": body.case_id, "assigned_to": body.assigned_to}
    finally:
        release(conn)


# ── Decide ────────────────────────────────────────────────────────────────────

class DecideRequest(BaseModel):
    case_id: str
    outcome: str
    risk_class: str | None = None
    notes: str | None = None
    table_rating: int | None = None
    flat_extra: float | None = None


@router.post("/decide")
def decide_case(body: DecideRequest, current: CurrentUser):
    if current.role not in ("underwriter","senior_underwriter","admin","super_admin"):
        raise HTTPException(403, "Insufficient role to make decisions")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE policy_admin_queue SET outcome=%s, risk_class=%s, status='PROCESSED', "
            "processed_at=now() WHERE id=%s",
            (body.outcome, body.risk_class, body.case_id),
        )
        conn.commit()
        cur.close()
        return {"status": "decided", "case_id": body.case_id, "outcome": body.outcome}
    finally:
        release(conn)


# ── APS ───────────────────────────────────────────────────────────────────────

class APSRequest(BaseModel):
    case_id: str
    physician_name: str | None = None
    physician_address: str | None = None
    physician_phone: str | None = None
    notes: str | None = None
    rule_name: str | None = None


@router.post("/aps/request")
def create_aps_request(body: APSRequest, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO aps_request
                (case_id, application_id, physician_name, physician_address,
                 physician_phone, notes, rule_name, status, created_by)
            VALUES (%s, gen_random_uuid(), %s, %s, %s, %s, %s, 'PENDING', %s)
            RETURNING id::text
            """,
            (
                body.case_id, body.physician_name, body.physician_address,
                body.physician_phone, body.notes, body.rule_name, current.username,
            ),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"status": "created", "aps_request_id": new_id}
    finally:
        release(conn)


@router.get("/aps/{case_id}")
def get_aps_requests(case_id: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM aps_request WHERE case_id=%s ORDER BY requested_at DESC",
            (case_id,),
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


class APSUpdate(BaseModel):
    aps_id: str
    status: str
    notes: str | None = None
    document_ref: str | None = None


@router.post("/aps/update")
def update_aps(body: APSUpdate, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE aps_request SET status=%s, notes=%s, document_ref=%s, "
            "received_at=CASE WHEN %s='RECEIVED' THEN now() ELSE received_at END, "
            "updated_at=now() WHERE id=%s::uuid",
            (body.status, body.notes, body.document_ref, body.status, body.aps_id),
        )
        conn.commit()
        cur.close()
        return {"status": "updated", "aps_id": body.aps_id}
    finally:
        release(conn)
