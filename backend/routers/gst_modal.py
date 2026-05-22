"""
routers/gst_modal.py
GST Config and Modal Factors with system/product override + date ranges
"""
from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from deps import CurrentUser
from database import get_conn, release_conn
import psycopg2.extras

router = APIRouter(tags=["GST & Modal Factors"])

def _db():
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn

def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]

def _row(r) -> dict:
    return dict(r) if r else {}

def _fmt(rows: list[dict]) -> list[dict]:
    for r in rows:
        if "effective_date" in r:
            r["effective_date"] = str(r["effective_date"])
        if "expiry_date" in r:
            r["expiry_date"] = str(r["expiry_date"]) if r["expiry_date"] else None
        if "first_year_rate" in r:
            r["first_year_rate"] = float(r["first_year_rate"])
        if "renewal_rate" in r:
            r["renewal_rate"] = float(r["renewal_rate"])
        if "factor" in r:
            r["factor"] = float(r["factor"])
        if "id" in r and r["id"]:
            r["id"] = str(r["id"])
    return rows

class GSTIn(BaseModel):
    product_code:    Optional[str]  = None
    category:        str            = "LIFE"
    first_year_rate: float
    renewal_rate:    float
    effective_date:  date
    expiry_date:     Optional[date] = None
    is_active:       bool           = True

    @validator("expiry_date")
    def expiry_after_effective(cls, v, values):
        if v and "effective_date" in values and values["effective_date"] and v < values["effective_date"]:
            raise ValueError("expiry_date must be after effective_date")
        return v

class ModalIn(BaseModel):
    product_code:   Optional[str]  = None
    mode:           str
    factor:         float
    effective_date: date
    expiry_date:    Optional[date] = None
    is_active:      bool           = True

    @validator("expiry_date")
    def expiry_after_effective(cls, v, values):
        if v and "effective_date" in values and values["effective_date"] and v < values["effective_date"]:
            raise ValueError("expiry_date must be after effective_date")
        return v

# ── GST endpoints ─────────────────────────────────────────────────────────────

@router.get("/gst-config")
def list_gst(product_code: Optional[str] = None):
    conn, release = _db()
    try:
        cur = conn.cursor()
        if product_code:
            cur.execute("""
                SELECT *,
                       CASE WHEN product_code IS NULL THEN 'system' ELSE 'product' END AS source
                FROM gst_config
                WHERE (product_code = %s OR product_code IS NULL)
                  AND is_active = true
                ORDER BY product_code NULLS LAST, effective_date DESC
            """, (product_code,))
        else:
            cur.execute("""
                SELECT *,
                       CASE WHEN product_code IS NULL THEN 'system' ELSE 'product' END AS source
                FROM gst_config
                WHERE product_code IS NULL AND is_active = true
                ORDER BY effective_date DESC
            """)
        rows = _fmt(_rows(cur.fetchall()))
        cur.close()
        return rows
    finally:
        release(conn)

@router.post("/gst-config", status_code=201)
def create_gst(body: GSTIn, user: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO gst_config
                    (product_code, category, first_year_rate, renewal_rate,
                     effective_date, expiry_date, is_active, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (body.product_code, body.category, body.first_year_rate,
                  body.renewal_rate, body.effective_date, body.expiry_date,
                  body.is_active, user.username, user.username))
            conn.commit()
            row_id = str(cur.fetchone()["id"])
            cur.close()
            return {"id": row_id, "message": "GST config created"}
        except Exception as e:
            conn.rollback()
            if "gst_no_overlap" in str(e):
                raise HTTPException(status_code=409,
                    detail="A GST rate already exists for this period. Adjust dates to avoid overlap.")
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        release(conn)

@router.put("/gst-config/{gst_id}")
def update_gst(gst_id: str, body: GSTIn, user: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE gst_config SET
                    first_year_rate = %s, renewal_rate = %s,
                    effective_date  = %s, expiry_date  = %s,
                    is_active = %s, updated_by = %s, updated_at = now()
                WHERE id = %s::uuid
            """, (body.first_year_rate, body.renewal_rate,
                  body.effective_date, body.expiry_date,
                  body.is_active, user.username, gst_id))
            conn.commit()
            cur.close()
            return {"message": "GST config updated"}
        except Exception as e:
            conn.rollback()
            if "gst_no_overlap" in str(e):
                raise HTTPException(status_code=409,
                    detail="Date range overlaps with existing GST config.")
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        release(conn)

@router.delete("/gst-config/{gst_id}")
def delete_gst(gst_id: str, user: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM gst_config WHERE id = %s::uuid", (gst_id,))
        conn.commit()
        cur.close()
        return {"message": "GST config deleted"}
    finally:
        release(conn)

@router.get("/gst-config/effective")
def effective_gst(product_code: Optional[str] = None, as_of: Optional[date] = None):
    check_date = as_of or date.today()
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT first_year_rate::float, renewal_rate::float, "
            "CASE WHEN product_code IS NULL THEN 'system' ELSE 'product' END AS source "
            "FROM get_gst(%s, %s)",
            (product_code, check_date)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="No GST config found for this date")
        return _row(row)
    finally:
        release(conn)

# ── Modal Factor endpoints ────────────────────────────────────────────────────

@router.get("/modal-factor-config")
def list_modal(product_code: Optional[str] = None):
    conn, release = _db()
    try:
        cur = conn.cursor()
        if product_code:
            cur.execute("""
                SELECT *,
                       CASE WHEN product_code IS NULL THEN 'system' ELSE 'product' END AS source
                FROM modal_factor_config
                WHERE (product_code = %s OR product_code IS NULL) AND is_active = true
                ORDER BY mode, product_code NULLS LAST, effective_date DESC
            """, (product_code,))
        else:
            cur.execute("""
                SELECT *,
                       CASE WHEN product_code IS NULL THEN 'system' ELSE 'product' END AS source
                FROM modal_factor_config
                WHERE product_code IS NULL AND is_active = true
                ORDER BY mode, effective_date DESC
            """)
        rows = _fmt(_rows(cur.fetchall()))
        cur.close()
        return rows
    finally:
        release(conn)

@router.post("/modal-factor-config", status_code=201)
def create_modal(body: ModalIn, user: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO modal_factor_config
                    (product_code, mode, factor, effective_date,
                     expiry_date, is_active, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (body.product_code, body.mode, body.factor,
                  body.effective_date, body.expiry_date,
                  body.is_active, user.username, user.username))
            conn.commit()
            row_id = str(cur.fetchone()["id"])
            cur.close()
            return {"id": row_id, "message": "Modal factor created"}
        except Exception as e:
            conn.rollback()
            if "modal_no_overlap" in str(e):
                raise HTTPException(status_code=409,
                    detail=f"Modal factor for '{body.mode}' already exists for this period.")
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        release(conn)

@router.put("/modal-factor-config/{factor_id}")
def update_modal(factor_id: str, body: ModalIn, user: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE modal_factor_config SET
                    factor = %s, effective_date = %s,
                    expiry_date = %s, is_active = %s,
                    updated_by = %s, updated_at = now()
                WHERE id = %s::uuid
            """, (body.factor, body.effective_date, body.expiry_date,
                  body.is_active, user.username, factor_id))
            conn.commit()
            cur.close()
            return {"message": "Modal factor updated"}
        except Exception as e:
            conn.rollback()
            if "modal_no_overlap" in str(e):
                raise HTTPException(status_code=409,
                    detail="Date range overlaps with existing modal factor.")
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        release(conn)

@router.delete("/modal-factor-config/{factor_id}")
def delete_modal(factor_id: str, user: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM modal_factor_config WHERE id = %s::uuid", (factor_id,))
        conn.commit()
        cur.close()
        return {"message": "Modal factor deleted"}
    finally:
        release(conn)
