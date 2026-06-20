"""
routers/icd10.py
────────────────────────────────────────────────────────
GET  /icd10/search?q=diabetes        — search codes
GET  /icd10/{code}                   — get single code
GET  /icd10/categories               — list categories
POST /icd10                          — add new code (admin)
PATCH /icd10/{code}                  — update debit points (admin)
"""
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from deps import CurrentUser

router = APIRouter(prefix="/icd10", tags=["icd10"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


class ICD10Update(BaseModel):
    debit_points:    Optional[int]  = None
    is_hard_decline: Optional[bool] = None
    severity:        Optional[str]  = None
    uw_notes:        Optional[str]  = None
    is_active:       Optional[bool] = None


class ICD10Create(BaseModel):
    code:            str
    description:     str
    category:        Optional[str] = None
    debit_points:    int  = 0
    is_hard_decline: bool = False
    severity:        str  = "MODERATE"
    uw_notes:        Optional[str] = None


@router.get("/categories")
def list_categories(current: CurrentUser = None):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT category, COUNT(*) as code_count
            FROM icd10_codes WHERE is_active = true AND category IS NOT NULL
            GROUP BY category ORDER BY category
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.get("/search")
def search_icd10(
    q:        str   = Query(..., min_length=1),
    category: str   = Query(default=""),
    limit:    int   = Query(default=20, le=100),
    current:  CurrentUser = None,
):
    """Search ICD-10 codes by code or description."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        q_upper = q.upper()
        cat_filter = ""
        cat_params = []
        if category:
            cat_filter = "AND category = %s"
            cat_params = [category]
        cur.execute(f"""
            SELECT id, code, description, category,
                   debit_points, is_hard_decline, severity, uw_notes
            FROM icd10_codes
            WHERE is_active = true
              AND (UPPER(code) LIKE %s OR UPPER(description) LIKE %s)
              {cat_filter}
            ORDER BY
                CASE WHEN UPPER(code) = %s THEN 0
                     WHEN UPPER(code) LIKE %s THEN 1
                     ELSE 2 END,
                code
            LIMIT %s
        """, [f"%{q_upper}%", f"%{q_upper}%"] + cat_params + [q_upper, f"{q_upper}%", limit])
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.get("/{code}")
def get_icd10(code: str, current: CurrentUser = None):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM icd10_codes WHERE UPPER(code) = %s
        """, (code.upper(),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"ICD-10 code '{code}' not found")
        return dict(row)
    finally:
        release(conn)


@router.post("", status_code=201)
def create_icd10(body: ICD10Create, current: CurrentUser = None):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO icd10_codes
                (code, description, category, debit_points, is_hard_decline, severity, uw_notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, code
        """, (body.code.upper(), body.description, body.category,
              body.debit_points, body.is_hard_decline, body.severity, body.uw_notes))
        row = cur.fetchone()
        conn.commit()
        return {"status": "created", "id": row["id"], "code": row["code"]}
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        release(conn)


@router.patch("/{code}")
def update_icd10(code: str, body: ICD10Update, current: CurrentUser = None):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(400, "No fields to update")
        sets = ", ".join(f"{k}=%s" for k in updates)
        cur.execute(
            f"UPDATE icd10_codes SET {sets} WHERE UPPER(code)=%s RETURNING code",
            (*updates.values(), code.upper())
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Code '{code}' not found")
        conn.commit()
        return {"status": "updated", "code": code.upper()}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        release(conn)
