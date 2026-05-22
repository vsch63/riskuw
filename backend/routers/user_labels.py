"""
routers/user_labels.py
───────────────────────
GET    /system/user-labels         — list active labels for tenant
POST   /system/user-labels         — create label
PUT    /system/user-labels/{id}    — update label
DELETE /system/user-labels/{id}    — delete label
GET    /system/user-labels/keys    — just keys+names (for formula builder dropdown)
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import CurrentUser

router = APIRouter(tags=["User Labels"])

ADMIN_ROLES = {"admin", "super_admin"}

VALID_TYPES = ("CURRENCY", "INTEGER", "DECIMAL", "PERCENTAGE", "TEXT")

TYPE_DEFAULTS = {
    "CURRENCY":   {"prefix": "₹",  "suffix": None},
    "PERCENTAGE": {"prefix": None, "suffix": "%"},
    "INTEGER":    {"prefix": None, "suffix": None},
    "DECIMAL":    {"prefix": None, "suffix": None},
    "TEXT":       {"prefix": None, "suffix": None},
}


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    # Ensure we start fresh - not inside an existing transaction
    if not conn.autocommit:
        try:
            conn.rollback()
        except Exception:
            pass
    return conn, release_conn


def _get_tenant(conn, username: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT tenant_id FROM uw_user WHERE username=%s", (username,))
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(status_code=403, detail="User tenant not found")
    return str(row["tenant_id"])


class UserLabelIn(BaseModel):
    label_key:      str
    label_name:     str
    data_type:      str = "CURRENCY"
    default_value:  Optional[str] = None
    description:    Optional[str] = None
    prefix:         Optional[str] = None
    suffix:         Optional[str] = None
    is_required:    bool = False
    is_active:      bool = True
    effective_date: date = date.today()
    expiry_date:    Optional[date] = None
    sort_order:     int = 0


@router.get("/system/user-labels")
def list_user_labels(
    active_only: bool = True,
    user: CurrentUser = CurrentUser,
):
    conn, release = _get_db()
    try:
        tenant_id = _get_tenant(conn, user.username)
        cur = conn.cursor()
        q = """
            SELECT * FROM system_user_label
            WHERE tenant_id = %s::uuid
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
        """
        params = [tenant_id]
        if active_only:
            q += " AND is_active = true"
        q += " ORDER BY sort_order, label_key"
        cur.execute(q, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release(conn)



@router.get("/system/user-labels/check-key")
def check_label_key(key: str, user: CurrentUser = CurrentUser):
    """Check if a label key already exists for this tenant."""
    conn, release = _get_db()
    try:
        tenant_id = _get_tenant(conn, user.username)
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM system_user_label WHERE tenant_id=%s::uuid AND label_key=%s",
            (tenant_id, key)
        )
        exists = cur.fetchone() is not None
        cur.close()
        return {"exists": exists}
    finally:
        release(conn)

@router.get("/system/user-labels/keys")
def list_label_keys(user: CurrentUser = CurrentUser):
    """Lightweight endpoint for formula builder dropdown."""
    conn, release = _get_db()
    try:
        tenant_id = _get_tenant(conn, user.username)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT label_key, label_name, data_type,
                   default_value, prefix, suffix, description
            FROM system_user_label
            WHERE tenant_id = %s::uuid
              AND is_active = true
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY sort_order, label_key
            """,
            (tenant_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release(conn)


@router.post("/system/user-labels", status_code=201)
def create_user_label(body: UserLabelIn, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    if body.data_type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"data_type must be one of {VALID_TYPES}")

    # Auto-set prefix/suffix from type if not provided
    defaults = TYPE_DEFAULTS[body.data_type]
    prefix = body.prefix if body.prefix is not None else defaults["prefix"]
    suffix = body.suffix if body.suffix is not None else defaults["suffix"]

    conn, release = _get_db()
    try:
        tenant_id = _get_tenant(conn, user.username)
        cur = conn.cursor()
        label_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO system_user_label
                (id, tenant_id, label_key, label_name, data_type,
                 default_value, description, prefix, suffix,
                 is_required, is_active, effective_date, expiry_date,
                 sort_order, created_by, updated_by)
            VALUES
                (%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                label_id, tenant_id, body.label_key, body.label_name,
                body.data_type, body.default_value, body.description,
                prefix, suffix, body.is_required, body.is_active,
                body.effective_date, body.expiry_date,
                body.sort_order, user.username, user.username,
            ),
        )
        conn.commit()
        cur.close()
        return {"id": label_id, "message": "User label created"}
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409,
                detail=f"Label key '{body.label_key}' already exists")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


@router.put("/system/user-labels/{label_id}")
def update_user_label(
    label_id: str, body: UserLabelIn, user: CurrentUser = CurrentUser
):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")

    defaults = TYPE_DEFAULTS.get(body.data_type, {})
    prefix = body.prefix if body.prefix is not None else defaults.get("prefix")
    suffix = body.suffix if body.suffix is not None else defaults.get("suffix")

    conn, release = _get_db()
    try:
        tenant_id = _get_tenant(conn, user.username)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE system_user_label SET
                label_key     = %s, label_name    = %s, data_type     = %s,
                default_value = %s, description   = %s, prefix        = %s,
                suffix        = %s, is_required   = %s, is_active     = %s,
                effective_date= %s, expiry_date   = %s, sort_order    = %s,
                updated_by    = %s
            WHERE id = %s::uuid AND tenant_id = %s::uuid
            """,
            (
                body.label_key, body.label_name, body.data_type,
                body.default_value, body.description, prefix, suffix,
                body.is_required, body.is_active,
                body.effective_date, body.expiry_date,
                body.sort_order, user.username,
                label_id, tenant_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Label not found")
        conn.commit()
        cur.close()
        return {"message": "Label updated"}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


@router.delete("/system/user-labels/{label_id}")
def delete_user_label(label_id: str, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        tenant_id = _get_tenant(conn, user.username)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM system_user_label WHERE id=%s::uuid AND tenant_id=%s::uuid",
            (label_id, tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Label not found")
        conn.commit()
        cur.close()
        return {"message": "Label deleted"}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)

