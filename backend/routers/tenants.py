"""
backend/routers/tenants.py
───────────────────────────
GET   /tenants/         — list (super_admin / admin only)
GET   /tenants/{id}     — detail
POST  /tenants/         — create
PATCH /tenants/{id}     — update
POST  /tenants/{id}/suspend
POST  /tenants/{id}/activate
GET   /tenants/{id}/audit

Tables: tenant · tenant_audit
"""
from __future__ import annotations
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from deps import CurrentUser

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else {}


# ── Schemas ────────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    tenant_name:             str
    tenant_code:             str
    plan_tier:               str = "trial"
    company_type:            Optional[str] = None
    naic_code:               Optional[str] = None
    state_of_domicile:       Optional[str] = None
    contact_name:            Optional[str] = None
    contact_email:           Optional[str] = None
    contact_phone:           Optional[str] = None
    max_users:               int = 10
    max_decisions_per_month: int = 1000
    sso_enabled:             bool = False
    api_enabled:             bool = True
    timezone:                str = "Asia/Kolkata"
    date_format:             str = "DD/MM/YYYY"
    logo_url:                Optional[str] = None
    notes:                   Optional[str] = None
    trial_ends_at:           Optional[str] = None
    contract_start:          Optional[str] = None
    contract_end:            Optional[str] = None
    created_by:              Optional[str] = None


class TenantUpdate(BaseModel):
    tenant_name:             Optional[str] = None
    plan_tier:               Optional[str] = None
    company_type:            Optional[str] = None
    naic_code:               Optional[str] = None
    state_of_domicile:       Optional[str] = None
    contact_name:            Optional[str] = None
    contact_email:           Optional[str] = None
    contact_phone:           Optional[str] = None
    max_users:               Optional[int] = None
    max_decisions_per_month: Optional[int] = None
    sso_enabled:             Optional[bool] = None
    api_enabled:             Optional[bool] = None
    timezone:                Optional[str] = None
    date_format:             Optional[str] = None
    logo_url:                Optional[str] = None
    notes:                   Optional[str] = None
    trial_ends_at:           Optional[str] = None
    contract_start:          Optional[str] = None
    contract_end:            Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/")
def list_tenants(current: CurrentUser):
    if current.role not in ("super_admin", "admin"):
        raise HTTPException(403, "Super admin only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id::text, tenant_code, tenant_name, status, plan_tier,"
            " contact_name, contact_email, contact_phone, company_type,"
            " state_of_domicile, naic_code, max_users, max_decisions_per_month,"
            " decisions_this_month, sso_enabled, api_enabled, timezone,"
            " date_format, notes, trial_ends_at, contract_start, contract_end,"
            " created_at, logo_url "
            "FROM tenant ORDER BY tenant_name"
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


@router.get("/{tid}")
def get_tenant(tid: str, current: CurrentUser):
    if current.role not in ("super_admin", "admin"):
        raise HTTPException(403, "Super admin only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id::text, tenant_code, tenant_name, status, plan_tier,"
            " contact_name, contact_email, contact_phone, company_type,"
            " state_of_domicile, naic_code, max_users, max_decisions_per_month,"
            " decisions_this_month, sso_enabled, api_enabled, timezone,"
            " date_format, notes, trial_ends_at, contract_start, contract_end,"
            " created_at, updated_at, logo_url "
            "FROM tenant WHERE id=%s::uuid",
            (tid,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(404, "Tenant not found")
        return _row(row)
    finally:
        release(conn)


@router.post("/", status_code=201)
def create_tenant(body: TenantCreate, current: CurrentUser):
    if current.role not in ("super_admin",):
        raise HTTPException(403, "Super admin only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Check tenant_code uniqueness
        cur.execute("SELECT 1 FROM tenant WHERE tenant_code=%s", (body.tenant_code,))
        if cur.fetchone():
            raise HTTPException(409, f"Tenant code '{body.tenant_code}' already exists")

        tid = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO tenant (
                id, tenant_code, tenant_name, status, plan_tier,
                contact_name, contact_email, contact_phone,
                company_type, naic_code, state_of_domicile,
                max_users, max_decisions_per_month, decisions_this_month,
                sso_enabled, api_enabled, timezone, date_format,
                logo_url, notes, trial_ends_at, contract_start, contract_end,
                created_at, updated_at, created_by
            ) VALUES (
                %s::uuid, %s, %s, 'ACTIVE', %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, 0,
                %s, %s, %s, %s,
                %s, %s,
                %s::timestamptz, %s::date, %s::date,
                now(), now(), %s
            )
            RETURNING id::text, tenant_code, tenant_name, status, plan_tier
            """,
            (
                tid, body.tenant_code, body.tenant_name, body.plan_tier,
                body.contact_name, body.contact_email, body.contact_phone,
                body.company_type, body.naic_code, body.state_of_domicile,
                body.max_users, body.max_decisions_per_month,
                body.sso_enabled, body.api_enabled, body.timezone, body.date_format,
                body.logo_url, body.notes,
                body.trial_ends_at or None,
                body.contract_start or None,
                body.contract_end or None,
                body.created_by or current.username,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return _row(row)
    finally:
        release(conn)


@router.patch("/{tid}")
def update_tenant(tid: str, body: TenantUpdate, current: CurrentUser):
    if current.role not in ("super_admin", "admin"):
        raise HTTPException(403, "Admins only")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sets = ", ".join(f"{k}=%s" for k in updates)
        cur.execute(
            f"UPDATE tenant SET {sets}, updated_at=now() WHERE id=%s::uuid RETURNING id::text",
            (*updates.values(), tid),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            raise HTTPException(404, "Tenant not found")
        return {"status": "updated", "tenant_id": tid}
    finally:
        release(conn)


@router.post("/{tid}/suspend")
def suspend_tenant(tid: str, current: CurrentUser):
    if current.role not in ("super_admin",):
        raise HTTPException(403, "Super admin only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tenant SET status='SUSPENDED', updated_at=now() WHERE id=%s::uuid",
            (tid,),
        )
        conn.commit()
        cur.close()
        return {"status": "suspended", "tenant_id": tid}
    finally:
        release(conn)


@router.post("/{tid}/activate")
def activate_tenant(tid: str, current: CurrentUser):
    if current.role not in ("super_admin",):
        raise HTTPException(403, "Super admin only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tenant SET status='ACTIVE', updated_at=now() WHERE id=%s::uuid",
            (tid,),
        )
        conn.commit()
        cur.close()
        return {"status": "activated", "tenant_id": tid}
    finally:
        release(conn)


@router.get("/{tid}/audit")
def tenant_audit(tid: str, current: CurrentUser):
    if current.role not in ("super_admin", "admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tenant_audit WHERE tenant_id=%s::uuid ORDER BY occurred_at DESC LIMIT 100",
            (tid,),
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)
