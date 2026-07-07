"""
backend/api_key_auth.py
─────────────────────────
API key authentication for external/programmatic access (Developer Portal).
Separate from the JWT-based CurrentUser used by the web UI.

Usage in a router:
    from api_key_auth import APIKeyAuth
    @router.post("/some-endpoint")
    def endpoint(body: SomeModel, auth: APIKeyAuth):
        # auth.tenant_id, auth.key_id available
        ...

Clients authenticate via header:  X-API-Key: ruw_live_xxxxxxxxxxxx
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel


class APIKeyContext(BaseModel):
    tenant_id: str
    key_id: int
    environment: str  # live | sandbox


def hash_key(plaintext_key: str) -> str:
    return hashlib.sha256(plaintext_key.encode()).hexdigest()


def generate_key(environment: str = "live") -> tuple[str, str, str]:
    """
    Generates a new API key.
    Returns: (plaintext_key, key_hash, key_prefix)
    Format: ruw_live_<32 random hex chars> or ruw_sandbox_<32 random hex chars>
    """
    raw = secrets.token_hex(24)  # 48 hex chars
    plaintext = f"ruw_{environment}_{raw}"
    key_hash = hash_key(plaintext)
    key_prefix = plaintext[:20]  # enough to identify without revealing the full key
    return plaintext, key_hash, key_prefix


async def verify_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> APIKeyContext:
    """
    FastAPI dependency — validates X-API-Key header against api_keys table.
    Updates last_used_at/last_used_ip/request_count on successful auth.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header. Generate a key in the Developer Portal.",
        )

    key_hash = hash_key(x_api_key)

    from database import get_conn, release_conn
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, tenant_id::text, environment, is_active, expires_at
            FROM api_keys
            WHERE key_hash = %s
        """, (key_hash,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

        d = dict(row) if hasattr(row, "keys") else dict(zip(
            ["id", "tenant_id", "environment", "is_active", "expires_at"], row))

        if not d["is_active"]:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This API key has been revoked")

        if d.get("expires_at") and d["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This API key has expired")

        # Update usage tracking (best-effort, non-blocking)
        try:
            client_ip = request.client.host if request.client else None
            cur.execute("""
                UPDATE api_keys
                SET last_used_at = now(), last_used_ip = %s, request_count = request_count + 1
                WHERE id = %s
            """, (client_ip, d["id"]))

            endpoint = request.url.path
            cur.execute("""
                INSERT INTO api_usage_daily (tenant_id, api_key_id, usage_date, endpoint, request_count)
                VALUES (%s::uuid, %s, CURRENT_DATE, %s, 1)
                ON CONFLICT (tenant_id, api_key_id, usage_date, endpoint)
                DO UPDATE SET request_count = api_usage_daily.request_count + 1
            """, (d["tenant_id"], d["id"], endpoint))
            conn.commit()
        except Exception:
            conn.rollback()

        cur.close()
        return APIKeyContext(
            tenant_id=d["tenant_id"], key_id=d["id"], environment=d["environment"]
        )
    finally:
        release_conn(conn)


APIKeyAuth = Annotated[APIKeyContext, Depends(verify_api_key)]


# ── Combined auth: accepts EITHER a JWT bearer token OR an X-API-Key header ───
# Produces a CurrentUser-compatible object so existing endpoint code needs no changes.

class ResolvedAuth(BaseModel):
    username: str
    role: str
    tenant_id: str
    auth_method: str  # "jwt" | "api_key"


async def verify_jwt_or_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ResolvedAuth:
    """
    FastAPI dependency for endpoints that should be callable both from the
    web UI (JWT) and external API integrations (API key).
    Tries API key first if present, else falls back to JWT.
    """
    # Path 1: API key
    if x_api_key:
        ctx = await verify_api_key(request, x_api_key)
        return ResolvedAuth(
            username=f"api:{ctx.key_id}",
            role="api_client",
            tenant_id=ctx.tenant_id,
            auth_method="api_key",
        )

    # Path 2: JWT bearer token
    if authorization and authorization.lower().startswith("bearer "):
        from deps import decode_token
        token = authorization.split(" ", 1)[1]
        token_data = decode_token(token)
        return ResolvedAuth(
            username=token_data.username,
            role=token_data.role,
            tenant_id=token_data.tenant_id or "",
            auth_method="jwt",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide either an X-API-Key header or a Bearer JWT token",
    )


FlexibleAuth = Annotated[ResolvedAuth, Depends(verify_jwt_or_api_key)]

