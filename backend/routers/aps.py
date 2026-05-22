"""
backend/routers/aps.py
───────────────────────
GET  /letter-templates/active   — active template for outcome
GET  /letter-templates          — all templates
PATCH /letter-templates/{id}    — update template

Tables: letter_templates · aps_letter_templates · physicians
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from deps import CurrentUser

router = APIRouter(tags=["aps"])


def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else {}


@router.get("/letter-templates/active")
def get_active_template(current: CurrentUser, outcome: str = "APPROVED"):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM letter_templates WHERE outcome=%s AND is_active=true LIMIT 1",
            (outcome,),
        )
        row = cur.fetchone()
        cur.close()
        return _row(row) if row else {}
    finally:
        release(conn)


@router.get("/letter-templates")
def list_templates(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM letter_templates ORDER BY outcome, template_name")
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


@router.patch("/letter-templates/{tid}")
def update_template(tid: str, updates: dict, current: CurrentUser):
    allowed = {"body_text", "footer_text", "header_company_name",
               "header_tagline", "contact_email", "contact_phone",
               "next_steps", "is_active"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        raise HTTPException(400, "No updatable fields")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sets = ", ".join(f"{k}=%s" for k in safe)
        cur.execute(
            f"UPDATE letter_templates SET {sets}, updated_at=now() WHERE id=%s",
            (*safe.values(), tid),
        )
        conn.commit()
        cur.close()
        return {"status": "updated", "id": tid}
    finally:
        release(conn)

# ── Physician Registry ────────────────────────────────────────────────────────
from pydantic import BaseModel
from typing import Optional
from datetime import date as _date

class PhysicianIn(BaseModel):
    physician_name:  str
    registration_no: str
    specialisation:  Optional[str] = None
    clinic_name:     Optional[str] = None
    email:           Optional[str] = None
    phone:           Optional[str] = None
    address_line1:   Optional[str] = None
    address_line2:   Optional[str] = None
    city:            Optional[str] = None
    state:           Optional[str] = None
    pincode:         Optional[str] = None
    effective_date:  Optional[_date] = None
    expire_date:     Optional[_date] = None
    is_active:       bool = True

@router.get("/physicians")
def list_physicians(
    current: CurrentUser,
    search: Optional[str] = None,
    active_only: bool = False,
):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where = []
        params = []
        if active_only:
            where.append("is_active = true")
        if search:
            where.append(
                "(physician_name ILIKE %s OR registration_no ILIKE %s "
                "OR specialisation ILIKE %s OR city ILIKE %s)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s])
        sql = "SELECT * FROM physicians"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY physician_name"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        result = []
        for r in rows:
            row = dict(zip(cols, r))
            row["effective_date"] = str(row["effective_date"]) if row["effective_date"] else None
            row["expire_date"]    = str(row["expire_date"])    if row["expire_date"]    else None
            result.append(row)
        cur.close()
        return result
    finally:
        release(conn)

@router.post("/physicians", status_code=201)
def create_physician(body: PhysicianIn, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO physicians
                (physician_name, registration_no, specialisation, clinic_name,
                 email, phone, address_line1, address_line2, city, state,
                 pincode, effective_date, expire_date, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            body.physician_name, body.registration_no, body.specialisation,
            body.clinic_name, body.email, body.phone, body.address_line1,
            body.address_line2, body.city, body.state, body.pincode,
            body.effective_date, body.expire_date, body.is_active,
        ))
        conn.commit()
        pid = cur.fetchone()[0]
        cur.close()
        return {"id": pid, "message": "Physician created"}
    finally:
        release(conn)

@router.put("/physicians/{pid}")
def update_physician(pid: int, body: PhysicianIn, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE physicians SET
                physician_name=%s, registration_no=%s, specialisation=%s,
                clinic_name=%s, email=%s, phone=%s, address_line1=%s,
                address_line2=%s, city=%s, state=%s, pincode=%s,
                effective_date=%s, expire_date=%s, is_active=%s
            WHERE id=%s
        """, (
            body.physician_name, body.registration_no, body.specialisation,
            body.clinic_name, body.email, body.phone, body.address_line1,
            body.address_line2, body.city, body.state, body.pincode,
            body.effective_date, body.expire_date, body.is_active, pid,
        ))
        conn.commit()
        cur.close()
        return {"message": "Physician updated"}
    finally:
        release(conn)

@router.delete("/physicians/{pid}")
def delete_physician(pid: int, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM physicians WHERE id=%s", (pid,))
        conn.commit()
        cur.close()
        return {"message": "Physician deleted"}
    finally:
        release(conn)
