"""
backend/routers/users.py
─────────────────────────
GET  /users/authority-limits/{username}
POST /users/authority-limits
Tables: user_authority_limits
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from deps import CurrentUser

router = APIRouter(prefix="/users", tags=["users"])


def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else {}


@router.get("/authority-limits/{username}")
def get_limits(username: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM user_authority_limits WHERE username=%s AND is_active=true",
            (username,),
        )
        row = cur.fetchone()
        cur.close()
        return _row(row) if row else {}
    finally:
        release(conn)


class LimitsUpdate(BaseModel):
    username: str
    min_face_amount: float = 0
    max_face_amount: float | None = None
    product_codes: list[str] = []
    notes: str | None = None
    is_medical_officer: bool = False


@router.post("/authority-limits")
def set_limits(body: LimitsUpdate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_authority_limits
                (username, min_face_amount, max_face_amount,
                 product_codes, notes, is_medical_officer, set_by, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,true)
            ON CONFLICT (username) DO UPDATE SET
                min_face_amount=EXCLUDED.min_face_amount,
                max_face_amount=EXCLUDED.max_face_amount,
                product_codes=EXCLUDED.product_codes,
                notes=EXCLUDED.notes,
                is_medical_officer=EXCLUDED.is_medical_officer,
                set_by=EXCLUDED.set_by,
                updated_at=now()
            """,
            (
                body.username, body.min_face_amount, body.max_face_amount,
                body.product_codes, body.notes,
                body.is_medical_officer, current.username,
            ),
        )
        conn.commit()
        cur.close()
        return {"status": "saved", "username": body.username}
    finally:
        release(conn)
