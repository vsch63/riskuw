"""
backend/routers/api_keys.py
─────────────────────────────
Self-service API key management for the Developer Portal.

POST   /api-keys                — generate a new key (plaintext shown ONCE)
GET    /api-keys                — list tenant's keys (masked)
DELETE /api-keys/{id}           — revoke a key
GET    /api-keys/usage          — usage summary for current month
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_conn, release_conn
from routers.auth import CurrentUser
from api_key_auth import generate_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _get_db():
    return get_conn(), release_conn


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else dict(r)


class KeyCreateRequest(BaseModel):
    name: str
    environment: str = "live"   # live | sandbox
    expires_in_days: Optional[int] = None


@router.post("", status_code=201)
def create_key(body: KeyCreateRequest, current: CurrentUser):
    if current.role not in ("admin", "super_admin", "api_client"):
        raise HTTPException(403, "Only admins or API clients can manage API keys")
    if body.environment not in ("live", "sandbox"):
        raise HTTPException(400, "environment must be 'live' or 'sandbox'")
    if not body.name.strip():
        raise HTTPException(400, "name is required")

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Check tenant has API access enabled
        cur.execute("SELECT api_enabled FROM tenant WHERE id=%s::uuid", (current.tenant_id,))
        trow = cur.fetchone()
        if not trow or not _row(trow).get("api_enabled", False):
            raise HTTPException(403, "API access is not enabled for this tenant. Contact your administrator.")

        plaintext, key_hash, key_prefix = generate_key(body.environment)

        expires_at = None
        if body.expires_in_days:
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

        cur.execute("""
            INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name, environment, expires_at, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
            RETURNING id, key_prefix, name, environment, created_at, expires_at
        """, (current.tenant_id, key_hash, key_prefix, body.name.strip(),
              body.environment, expires_at, current.username))
        row = _row(cur.fetchone())
        conn.commit()
        cur.close()

        return {
            **row,
            "id": row["id"],
            "created_at": str(row["created_at"]),
            "expires_at": str(row["expires_at"]) if row.get("expires_at") else None,
            "api_key": plaintext,  # shown ONLY in this response — never retrievable again
            "warning": "Save this key now. For security, it will not be shown again.",
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Failed to create API key: {e}")
    finally:
        release(conn)


@router.get("")
def list_keys(current: CurrentUser):
    if current.role not in ("admin", "super_admin", "api_client"):
        raise HTTPException(403, "Only admins or API clients can view API keys")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, key_prefix, name, environment, is_active,
                   last_used_at, last_used_ip, request_count,
                   expires_at, created_by, created_at, revoked_at, revoked_by
            FROM api_keys
            WHERE tenant_id = %s::uuid
            ORDER BY created_at DESC
        """, (current.tenant_id,))
        rows = [_row(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            for k in ("last_used_at", "expires_at", "created_at", "revoked_at"):
                if r.get(k):
                    r[k] = str(r[k])
            # Mask: show prefix + bullets, never the full key
            r["masked"] = f"{r['key_prefix']}{'•' * 12}"
        return rows
    finally:
        release(conn)


@router.delete("/{key_id}")
def revoke_key(key_id: int, current: CurrentUser):
    if current.role not in ("admin", "super_admin", "api_client"):
        raise HTTPException(403, "Only admins or API clients can revoke API keys")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE api_keys
            SET is_active = false, revoked_at = now(), revoked_by = %s
            WHERE id = %s AND tenant_id = %s::uuid
            RETURNING id
        """, (current.username, key_id, current.tenant_id))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            raise HTTPException(404, "API key not found")
        return {"status": "revoked", "key_id": key_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Failed to revoke key: {e}")
    finally:
        release(conn)


@router.get("/usage")
def get_usage(current: CurrentUser, days: int = 30):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT usage_date, endpoint, SUM(request_count) AS requests, SUM(error_count) AS errors
            FROM api_usage_daily
            WHERE tenant_id = %s::uuid AND usage_date >= CURRENT_DATE - %s::int
            GROUP BY usage_date, endpoint
            ORDER BY usage_date DESC
        """, (current.tenant_id, days))
        rows = [_row(r) for r in cur.fetchall()]
        for r in rows:
            r["usage_date"] = str(r["usage_date"])
            r["requests"] = int(r["requests"] or 0)
            r["errors"] = int(r["errors"] or 0)

        # Monthly total vs tenant limit
        cur.execute("""
            SELECT decisions_this_month, max_decisions_per_month
            FROM tenant WHERE id = %s::uuid
        """, (current.tenant_id,))
        trow = _row(cur.fetchone())

        cur.execute("""
            SELECT COALESCE(SUM(request_count), 0) AS total
            FROM api_usage_daily
            WHERE tenant_id = %s::uuid
              AND usage_date >= date_trunc('month', CURRENT_DATE)
        """, (current.tenant_id,))
        month_total = _row(cur.fetchone())["total"]
        cur.close()

        return {
            "daily": rows,
            "month_total_requests": int(month_total or 0),
            "decisions_this_month": trow.get("decisions_this_month", 0),
            "max_decisions_per_month": trow.get("max_decisions_per_month", 0),
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to load usage: {e}")
    finally:
        release(conn)
