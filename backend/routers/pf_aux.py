"""
routers/pf_aux.py
─────────────────
GET  /pf-modal-factors/{product_code}  — get modal factors
PUT  /pf-modal-factors/{product_code}  — update modal factors
GET  /pf-gst/{product_code}            — get GST config
PUT  /pf-gst/{product_code}            — update GST config

Separate from premium_formula.py to avoid FastAPI wildcard routing conflicts.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import CurrentUser

router_modal = APIRouter(prefix="/pf-modal-factors", tags=["Premium Formula"])
router_gst   = APIRouter(prefix="/pf-gst",           tags=["Premium Formula"])

ADMIN_ROLES = {"admin", "super_admin"}


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn

def _row(r) -> dict:
    return dict(r) if r else {}

def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


class ModalFactorIn(BaseModel):
    annual:      float = 1.0000
    half_yearly: float = 0.5100
    quarterly:   float = 0.2600
    monthly:     float = 0.0900


class GSTConfigIn(BaseModel):
    first_year_rate: float = 18.0
    renewal_rate:    float = 5.0


# ── Modal factors ─────────────────────────────────────────────────────────────

@router_modal.get("/{product_code}")
def get_modal_factors(product_code: str, user: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT mode, factor FROM premium_modal_factor WHERE product_code=%s ORDER BY mode",
            (product_code,),
        )
        rows = _rows(cur.fetchall())
        cur.close()
        return rows
    finally:
        release(conn)


@router_modal.put("/{product_code}")
def update_modal_factors(product_code: str, body: ModalFactorIn, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        for mode, factor in [
            ("ANNUAL",      body.annual),
            ("HALF_YEARLY", body.half_yearly),
            ("QUARTERLY",   body.quarterly),
            ("MONTHLY",     body.monthly),
        ]:
            cur.execute(
                """
                INSERT INTO premium_modal_factor (product_code, mode, factor)
                VALUES (%s, %s, %s)
                ON CONFLICT (product_code, mode) DO UPDATE SET factor=EXCLUDED.factor
                """,
                (product_code, mode, factor),
            )
        conn.commit()
        cur.close()
        return {"message": "Modal factors updated"}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


# ── GST config ────────────────────────────────────────────────────────────────

@router_gst.get("/{product_code}")
def get_gst(product_code: str, user: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM premium_gst_config WHERE product_code=%s", (product_code,)
        )
        row = cur.fetchone()
        cur.close()
        return _row(row) if row else {
            "product_code": product_code,
            "first_year_rate": 18.0,
            "renewal_rate": 5.0,
        }
    finally:
        release(conn)


@router_gst.put("/{product_code}")
def update_gst(product_code: str, body: GSTConfigIn, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO premium_gst_config (product_code, first_year_rate, renewal_rate)
            VALUES (%s, %s, %s)
            ON CONFLICT (product_code) DO UPDATE
            SET first_year_rate=EXCLUDED.first_year_rate,
                renewal_rate=EXCLUDED.renewal_rate
            """,
            (product_code, body.first_year_rate, body.renewal_rate),
        )
        conn.commit()
        cur.close()
        return {"message": "GST config updated"}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)
