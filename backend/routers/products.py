"""
backend/routers/products.py
────────────────────────────
GET    /products                          — list all products
GET    /products/{code}                   — get single product
POST   /products                          — create product
PATCH  /products/{code}                   — update product
GET    /products/{code}/rules             — get rules for product
PUT    /products/{code}/rules/{rule_id}   — enable/disable rule override
GET    /products/{code}/thresholds        — get thresholds
PUT    /products/{code}/thresholds        — save thresholds
GET    /products/{code}/build-table       — get BMI build table
POST   /products/{code}/build-table       — add/upsert BMI band
DELETE /products/{code}/build-table       — delete a BMI band

Tables: products · product_rules · product_decision_thresholds · product_build_table
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from deps import CurrentUser

router = APIRouter(prefix="/products", tags=["products"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


# ── Schemas ────────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    product_code:           str
    product_name:           str
    product_type:           str = "INDIVIDUAL_TERM"
    category:               str = "Individual Life"
    uw_method:              str = "FULL_UW"
    min_age:                int = 18
    max_age:                int = 65
    min_face_amount:        float = 50000
    max_face_amount:        float = 2000000
    available_terms:        Optional[list] = None
    benefit_terms:          Optional[list] = None
    premium_terms:          Optional[list] = None
    exam_required:          str = "NONE"
    non_medical_limit:      float = 500000
    reinsurance_threshold:  float = 5000000
    max_issue_age:          int = 65
    stp_threshold:          int = 50
    refer_threshold:        int = 150
    decline_threshold:      int = 300
    is_guaranteed_issue:    bool = False
    is_group_product:       bool = False
    description:            Optional[str] = None
    uw_notes:               Optional[str] = None
    effective_date:         Optional[str] = None
    expire_date:            Optional[str] = None
    is_active:              bool = True


class ProductUpdate(BaseModel):
    product_name:           Optional[str] = None
    product_type:           Optional[str] = None
    category:               Optional[str] = None
    uw_method:              Optional[str] = None
    min_age:                Optional[int] = None
    max_age:                Optional[int] = None
    min_face_amount:        Optional[float] = None
    max_face_amount:        Optional[float] = None
    available_terms:        Optional[list] = None
    benefit_terms:          Optional[list] = None
    premium_terms:          Optional[list] = None
    exam_required:          Optional[str] = None
    non_medical_limit:      Optional[float] = None
    reinsurance_threshold:  Optional[float] = None
    max_issue_age:          Optional[int] = None
    stp_threshold:          Optional[int] = None
    refer_threshold:        Optional[int] = None
    decline_threshold:      Optional[int] = None
    is_guaranteed_issue:    Optional[bool] = None
    is_group_product:       Optional[bool] = None
    description:            Optional[str] = None
    uw_notes:               Optional[str] = None
    effective_date:         Optional[str] = None
    expire_date:            Optional[str] = None
    is_active:              Optional[bool] = None


class ThresholdUpdate(BaseModel):
    stp_threshold:      int
    refer_threshold:    int
    decline_threshold:  int
    max_table_rating:   int = 16
    max_flat_extra:     float = 10.0
    change_reason:      Optional[str] = None
    effective_date:     Optional[str] = None
    expire_date:        Optional[str] = None


class RuleUpdate(BaseModel):
    is_enabled:                 bool
    debit_points_override:      Optional[int]   = None
    debit_override_active:      bool = False
    flat_extra_override:        Optional[float] = None
    flat_extra_override_active: bool = False


class BuildBand(BaseModel):
    bmi_min:      float
    bmi_max:      float
    debit_points: int = 0
    is_decline:   bool = False
    band_label:   Optional[str] = None


class DeleteBand(BaseModel):
    bmi_min: float
    bmi_max: float


# ── Products ───────────────────────────────────────────────────────────────────

@router.get("")
def list_products(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT product_code, product_name, product_type, category,
                   uw_method, min_age, max_age, min_face_amount, max_face_amount,
                   is_active, is_guaranteed_issue, is_group_product,
                   stp_threshold, refer_threshold, decline_threshold,
                   available_terms, exam_required, non_medical_limit,
                   reinsurance_threshold, max_issue_age,
                   effective_date, expire_date, description, created_at
            FROM products
            ORDER BY product_code
        """)
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = dict(r)
            d["is_active"]           = bool(d.get("is_active", True))
            d["is_guaranteed_issue"] = bool(d.get("is_guaranteed_issue", False))
            d["is_group_product"]    = bool(d.get("is_group_product", False))
            for k in ("effective_date", "expire_date", "created_at"):
                if d.get(k):
                    d[k] = str(d[k])[:10]
            result.append(d)
        return result
    finally:
        release(conn)


@router.get("/{code}")
def get_product(code: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT product_code, product_name, product_type, category,
                   uw_method, min_age, max_age, min_face_amount, max_face_amount,
                   available_terms, exam_required, non_medical_limit,
                   reinsurance_threshold, max_issue_age,
                   stp_threshold, refer_threshold, decline_threshold,
                   is_guaranteed_issue, is_group_product, is_active,
                   description, uw_notes, effective_date, expire_date, created_at
            FROM products WHERE product_code = %s
        """, (code.upper(),))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(404, f"Product '{code}' not found")
        d = dict(row)
        for k in ("is_active", "is_guaranteed_issue", "is_group_product"):
            d[k] = bool(d.get(k, False))
        for k in ("effective_date", "expire_date", "created_at"):
            if d.get(k):
                d[k] = str(d[k])[:10]
        return d
    finally:
        release(conn)


@router.post("", status_code=201)
def create_product(body: ProductCreate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM products WHERE product_code=%s", (body.product_code.upper(),))
        if cur.fetchone():
            raise HTTPException(409, f"Product code '{body.product_code}' already exists")
        cur.execute("""
            INSERT INTO products (
                product_code, product_name, product_type, category, uw_method,
                min_age, max_age, min_face_amount, max_face_amount,
                available_terms, benefit_terms, premium_terms,
                exam_required, non_medical_limit, reinsurance_threshold, max_issue_age,
                stp_threshold, refer_threshold, decline_threshold,
                is_guaranteed_issue, is_group_product, is_active,
                description, uw_notes, effective_date, expire_date,
                created_at, updated_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s::date,%s::date,now(),now()
            ) RETURNING product_code, product_name, is_active
        """, (
            body.product_code.upper(), body.product_name, body.product_type,
            body.category, body.uw_method,
            body.min_age, body.max_age, body.min_face_amount, body.max_face_amount,
            body.available_terms, body.benefit_terms, body.premium_terms,
            body.exam_required, body.non_medical_limit, body.reinsurance_threshold,
            body.max_issue_age, body.stp_threshold, body.refer_threshold, body.decline_threshold,
            body.is_guaranteed_issue, body.is_group_product, body.is_active,
            body.description, body.uw_notes,
            body.effective_date or None, body.expire_date or None,
        ))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return dict(row)
    finally:
        release(conn)


@router.patch("/{code}")
def update_product(code: str, body: ProductUpdate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sets = ", ".join(f"{k}=%s" for k in updates)
        cur.execute(
            f"UPDATE products SET {sets}, updated_at=now() WHERE product_code=%s RETURNING product_code",
            (*updates.values(), code.upper())
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            raise HTTPException(404, f"Product '{code}' not found")
        return {"status": "updated", "product_code": code.upper()}
    finally:
        release(conn)


# ── Rules ──────────────────────────────────────────────────────────────────────

@router.get("/{code}/rules")
def get_rules(code: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT rule_id, rule_name, category, default_debit, is_enabled,
                   debit_points_override, debit_override_active,
                   flat_extra_override,   flat_extra_override_active
            FROM product_rules
            WHERE product_code = %s
            ORDER BY rule_id
        """, (code.upper(),))
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "rule_id":                    r["rule_id"],
                "rule_name":                  r.get("rule_name") or r["rule_id"],
                "category":                   r.get("category") or "GENERAL",
                "default_debit":              r.get("default_debit") or 0,
                "is_enabled":                 bool(r["is_enabled"]),
                "debit_points_override":      r["debit_points_override"],
                "debit_override_active":      bool(r["debit_override_active"]) if r["debit_override_active"] is not None else False,
                "flat_extra_override":        r["flat_extra_override"],
                "flat_extra_override_active": bool(r["flat_extra_override_active"]) if r["flat_extra_override_active"] is not None else False,
            }
            for r in rows
        ]
    finally:
        release(conn)


@router.put("/{code}/rules/{rule_id}")
def update_rule(code: str, rule_id: str, body: RuleUpdate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO product_rules
                (product_code, rule_id, is_enabled, debit_points_override,
                 debit_override_active, flat_extra_override, flat_extra_override_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (product_code, rule_id) DO UPDATE SET
                is_enabled                 = EXCLUDED.is_enabled,
                debit_points_override      = EXCLUDED.debit_points_override,
                debit_override_active      = EXCLUDED.debit_override_active,
                flat_extra_override        = EXCLUDED.flat_extra_override,
                flat_extra_override_active = EXCLUDED.flat_extra_override_active
        """, (
            code.upper(), rule_id,
            body.is_enabled, body.debit_points_override, body.debit_override_active,
            body.flat_extra_override, body.flat_extra_override_active,
        ))
        conn.commit()
        cur.close()
        return {"status": "ok", "rule_id": rule_id}
    finally:
        release(conn)


# ── Thresholds ─────────────────────────────────────────────────────────────────

@router.get("/{code}/thresholds")
def get_thresholds(code: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        # Try dedicated thresholds table first
        try:
            cur.execute("""
                SELECT stp_threshold, refer_threshold, decline_threshold,
                       max_table_rating, max_flat_extra,
                       effective_date, expire_date, change_reason
                FROM product_decision_thresholds
                WHERE product_code = %s
                ORDER BY created_at DESC LIMIT 1
            """, (code.upper(),))
            row = cur.fetchone()
            if row:
                cur.close()
                return {
                    "stp_threshold":    row["stp_threshold"],
                    "refer_threshold":  row["refer_threshold"],
                    "decline_threshold":row["decline_threshold"],
                    "max_table_rating": row["max_table_rating"],
                    "max_flat_extra":   float(row["max_flat_extra"]) if row["max_flat_extra"] else 10.0,
                    "effective_date":   str(row["effective_date"])[:10] if row["effective_date"] else None,
                    "expire_date":      str(row["expire_date"])[:10]    if row["expire_date"]    else None,
                    "change_reason":    row["change_reason"],
                }
        except Exception:
            pass  # table may not exist yet, fall through

        # Fallback to products table inline columns
        cur.execute("""
            SELECT stp_threshold, refer_threshold, decline_threshold
            FROM products WHERE product_code = %s
        """, (code.upper(),))
        row2 = cur.fetchone()
        cur.close()
        if row2:
            return {
                "stp_threshold":    row2["stp_threshold"]    or 50,
                "refer_threshold":  row2["refer_threshold"]  or 150,
                "decline_threshold":row2["decline_threshold"] or 300,
                "max_table_rating": 16,
                "max_flat_extra":   10.0,
            }
        return {}
    finally:
        release(conn)


@router.put("/{code}/thresholds")
def save_thresholds(code: str, body: ThresholdUpdate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    if not (body.stp_threshold < body.refer_threshold < body.decline_threshold):
        raise HTTPException(400, "Must satisfy: STP < Refer < Decline")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        # Try dedicated thresholds table first
        try:
            cur.execute("""
                INSERT INTO product_decision_thresholds
                    (product_code, stp_threshold, refer_threshold, decline_threshold,
                     max_table_rating, max_flat_extra, change_reason,
                     effective_date, expire_date, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::date,%s::date,now())
                ON CONFLICT (product_code) DO UPDATE SET
                    stp_threshold     = EXCLUDED.stp_threshold,
                    refer_threshold   = EXCLUDED.refer_threshold,
                    decline_threshold = EXCLUDED.decline_threshold,
                    max_table_rating  = EXCLUDED.max_table_rating,
                    max_flat_extra    = EXCLUDED.max_flat_extra,
                    change_reason     = EXCLUDED.change_reason,
                    effective_date    = EXCLUDED.effective_date,
                    expire_date       = EXCLUDED.expire_date,
                    created_at        = now()
            """, (
                code.upper(), body.stp_threshold, body.refer_threshold, body.decline_threshold,
                body.max_table_rating, body.max_flat_extra, body.change_reason,
                body.effective_date or None, body.expire_date or None,
            ))
        except Exception:
            pass  # table may not exist, fall through to products update

        # Always update products table inline columns too
        cur.execute("""
            UPDATE products
            SET stp_threshold=%s, refer_threshold=%s, decline_threshold=%s, updated_at=now()
            WHERE product_code=%s
        """, (body.stp_threshold, body.refer_threshold, body.decline_threshold, code.upper()))

        conn.commit()
        cur.close()
        return {"status": "saved", "product_code": code.upper()}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        release(conn)


# ── Build Table ────────────────────────────────────────────────────────────────

@router.get("/{code}/build-table")
def get_build_table(code: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT bmi_min, bmi_max, debit_points, is_decline, band_label
            FROM product_build_table
            WHERE product_code = %s
            ORDER BY bmi_min
        """, (code.upper(),))
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "bmi_min":      float(r["bmi_min"]),
                "bmi_max":      float(r["bmi_max"]),
                "debit_points": int(r["debit_points"]),
                "is_decline":   bool(r["is_decline"]),
                "band_label":   r["band_label"] or "",
            }
            for r in rows
        ]
    finally:
        release(conn)


@router.post("/{code}/build-table")
def add_build_band(code: str, body: BuildBand, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    if body.bmi_min >= body.bmi_max:
        raise HTTPException(400, "BMI Min must be less than BMI Max")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO product_build_table
                (product_code, bmi_min, bmi_max, debit_points, is_decline, band_label)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (product_code, bmi_min, bmi_max) DO UPDATE SET
                debit_points = EXCLUDED.debit_points,
                is_decline   = EXCLUDED.is_decline,
                band_label   = EXCLUDED.band_label
        """, (code.upper(), body.bmi_min, body.bmi_max, body.debit_points, body.is_decline, body.band_label))
        conn.commit()
        cur.close()
        return {"status": "saved", "product_code": code.upper()}
    finally:
        release(conn)


@router.delete("/{code}/build-table")
def delete_build_band(code: str, body: DeleteBand, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM product_build_table WHERE product_code=%s AND bmi_min=%s AND bmi_max=%s",
            (code.upper(), body.bmi_min, body.bmi_max)
        )
        conn.commit()
        cur.close()
        return {"status": "deleted"}
    finally:
        release(conn)
