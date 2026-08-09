"""
backend/routers/sso.py
────────────────────────
Single sign-on endpoints.

Public (no auth):
    GET  /auth/sso/providers                — active providers for the login page
    GET  /auth/sso/{code}/authorize         — {authorize_url} to start an OIDC login
    GET  /auth/sso/{code}/callback          — IdP redirect; exchanges code → RiskUW JWT,
                                             302-redirects to /sso/callback#<token>

Admin (admin / super_admin):
    GET    /auth/sso/admin/providers        — list providers (secrets masked)
    POST   /auth/sso/admin/providers        — create/upsert a provider
    PATCH  /auth/sso/admin/providers/{code} — partial update
    DELETE /auth/sso/admin/providers/{code} — soft-deactivate
    POST   /auth/sso/admin/providers/{code}/test — connectivity test
"""
from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from deps import AdminOnly
from schemas.sso import (
    SsoAuthorizeOut, SsoProviderBrief, SsoProviderCreate, SsoProviderUpdate,
)
from services.sso import (
    SSOError, _http_client, frontend_url, ldap_test_connection, load_provider,
    oidc_authorize, oidc_callback, oidc_discovery,
)

router = APIRouter(prefix="/auth/sso", tags=["sso"])


def _get_db():
    from database import get_conn, release_conn  # noqa: PLC0415
    return get_conn(), release_conn


def _sso_redirect_error(detail: str) -> RedirectResponse:
    """Redirect back to the SPA callback with a fragment error (never a query
    string, so the detail never reaches server logs)."""
    fragment = urlencode({"error": detail})
    return RedirectResponse(url=f"{frontend_url()}/sso/callback#{fragment}",
                            status_code=302)


def _provider_out(row: dict) -> dict:
    """Mask secrets — only report whether a secret is set."""
    return {
        "provider_code": row.get("provider_code"),
        "provider_type": row.get("provider_type"),
        "display_name": row.get("display_name"),
        "is_active": bool(row.get("is_active")),
        "client_secret_set": bool(row.get("client_secret")),
        "ldap_bind_password_set": bool(row.get("ldap_bind_password")),
        "issuer_url": row.get("issuer_url"),
        "client_id": row.get("client_id"),
        "authorize_url": row.get("authorize_url"),
        "token_url": row.get("token_url"),
        "jwks_url": row.get("jwks_url"),
        "scope": row.get("scope"),
        "oidc_username_claim": row.get("oidc_username_claim"),
        "ldap_server_uri": row.get("ldap_server_uri"),
        "ldap_base_dn": row.get("ldap_base_dn"),
        "ldap_bind_dn": row.get("ldap_bind_dn"),
        "ldap_user_filter": row.get("ldap_user_filter"),
        "ldap_username_attr": row.get("ldap_username_attr"),
        "default_role": row.get("default_role"),
        "default_tenant_id": (str(row.get("default_tenant_id"))
                              if row.get("default_tenant_id") else None),
        "claim_role_attr": row.get("claim_role_attr"),
        "auto_provision": bool(row.get("auto_provision")),
    }


def _validate_tenant_id(value: str | None) -> None:
    if value:
        try:
            uuid.UUID(value)
        except ValueError:
            raise HTTPException(400, "default_tenant_id must be a valid UUID")


# ── Public: login page + OIDC flow ───────────────────────────────

@router.get("/providers", response_model=list[SsoProviderBrief])
def list_providers():
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT provider_code, provider_type, display_name "
            "FROM sso_provider WHERE is_active = true ORDER BY display_name"
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    finally:
        release(conn)


@router.get("/{code}/authorize", response_model=SsoAuthorizeOut)
def authorize(code: str):
    conn, release = _get_db()
    try:
        provider = load_provider(conn, code, active=True)
        if provider["provider_type"] != "OIDC":
            raise SSOError(400, "Only OIDC providers support browser authorization")
        http = _http_client()
        try:
            return oidc_authorize(provider, http)
        finally:
            http.close()
    except SSOError as e:
        raise HTTPException(e.status_code, e.detail)
    finally:
        release(conn)


@router.get("/{provider}/callback")
def callback(provider: str, code: str = Query(""), state: str = Query("")):
    """IdP redirect target. Exchanges the code, verifies the ID token, resolves
    the RiskUW user, and sends them back to the SPA with a fragment JWT."""
    if not code or not state:
        return _sso_redirect_error("Missing code or state")
    http = _http_client()
    try:
        result = oidc_callback(provider, code, state, http)
    except SSOError as e:
        return _sso_redirect_error(e.detail)
    finally:
        http.close()

    from routers.auth import _make_token  # lazy — avoid import cycle
    token = _make_token(result["username"], result["role"], result["tenant_id"])
    fragment = urlencode({
        "access_token": token,
        "username": result["username"] or "",
        "role": result["role"] or "",
        "full_name": result.get("full_name") or "",
        "tenant_id": result["tenant_id"] or "",
        "tenant_name": result.get("tenant_name") or "",
    })
    return RedirectResponse(url=f"{frontend_url()}/sso/callback#{fragment}",
                            status_code=302)


# ── Admin: provider CRUD + test ──────────────────────────────────

@router.get("/admin/providers")
def admin_list_providers(current: AdminOnly):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM sso_provider ORDER BY display_name"
        )
        rows = cur.fetchall()
        cur.close()
        return [_provider_out(dict(r)) for r in rows]
    finally:
        release(conn)


@router.post("/admin/providers")
def upsert_provider(body: SsoProviderCreate, current: AdminOnly):
    if body.provider_type == "OIDC" and not (body.issuer_url and body.client_id):
        raise HTTPException(400, "OIDC providers require issuer_url and client_id")
    if body.provider_type == "LDAP" and not (
            body.ldap_server_uri and body.ldap_base_dn and body.ldap_user_filter):
        raise HTTPException(400,
            "LDAP providers require ldap_server_uri, ldap_base_dn and ldap_user_filter")
    _validate_tenant_id(body.default_tenant_id)

    d = body.model_dump()
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sso_provider
              (provider_code, provider_type, display_name, is_active,
               issuer_url, client_id, client_secret, authorize_url, token_url,
               jwks_url, scope, oidc_username_claim,
               ldap_server_uri, ldap_base_dn, ldap_bind_dn, ldap_bind_password,
               ldap_user_filter, ldap_username_attr,
               default_role, default_tenant_id, claim_role_attr, auto_provision,
               created_by, updated_by)
            VALUES
              (%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,
               %s,%s,%s,%s, %s,%s, %s,%s::uuid,%s,%s, %s,%s)
            ON CONFLICT (provider_code) DO UPDATE SET
              provider_type = EXCLUDED.provider_type,
              display_name = EXCLUDED.display_name,
              is_active = EXCLUDED.is_active,
              issuer_url = EXCLUDED.issuer_url,
              client_id = EXCLUDED.client_id,
              client_secret = EXCLUDED.client_secret,
              authorize_url = EXCLUDED.authorize_url,
              token_url = EXCLUDED.token_url,
              jwks_url = EXCLUDED.jwks_url,
              scope = EXCLUDED.scope,
              oidc_username_claim = EXCLUDED.oidc_username_claim,
              ldap_server_uri = EXCLUDED.ldap_server_uri,
              ldap_base_dn = EXCLUDED.ldap_base_dn,
              ldap_bind_dn = EXCLUDED.ldap_bind_dn,
              ldap_bind_password = EXCLUDED.ldap_bind_password,
              ldap_user_filter = EXCLUDED.ldap_user_filter,
              ldap_username_attr = EXCLUDED.ldap_username_attr,
              default_role = EXCLUDED.default_role,
              default_tenant_id = EXCLUDED.default_tenant_id,
              claim_role_attr = EXCLUDED.claim_role_attr,
              auto_provision = EXCLUDED.auto_provision,
              updated_by = EXCLUDED.updated_by,
              updated_at = now()
            """,
            (d["provider_code"], d["provider_type"], d["display_name"], d["is_active"],
             d["issuer_url"], d["client_id"], d["client_secret"], d["authorize_url"],
             d["token_url"], d["jwks_url"], d["scope"], d["oidc_username_claim"],
             d["ldap_server_uri"], d["ldap_base_dn"], d["ldap_bind_dn"],
             d["ldap_bind_password"], d["ldap_user_filter"], d["ldap_username_attr"],
             d["default_role"], d["default_tenant_id"], d["claim_role_attr"],
             d["auto_provision"], current.username, current.username),
        )
        conn.commit()
        cur.close()
        return {"status": "saved", "provider_code": body.provider_code}
    finally:
        release(conn)


@router.patch("/admin/providers/{code}")
def update_provider(code: str, body: SsoProviderUpdate, current: AdminOnly):
    updates: dict = {}
    for k, v in body.model_dump(exclude_none=True).items():
        # Secrets only ever change when a new value is supplied — a PATCH that
        # omits client_secret must not wipe the stored one. Use the full POST
        # (upsert) to explicitly clear a secret.
        if k in ("client_secret", "ldap_bind_password"):
            if v:
                updates[k] = v
        else:
            updates[k] = v
    if "default_tenant_id" in updates:
        _validate_tenant_id(updates["default_tenant_id"])
    if not updates:
        raise HTTPException(400, "No updatable fields provided")

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sets = ", ".join(f"{k} = %s" for k in updates)
        cur.execute(
            f"UPDATE sso_provider SET {sets}, updated_by = %s, updated_at = now() "
            f"WHERE provider_code = %s",
            (*updates.values(), current.username, code),
        )
        conn.commit()
        rowcount = cur.rowcount
        cur.close()
        if not rowcount:
            raise HTTPException(404, "SSO provider not found")
        return {"status": "updated", "provider_code": code}
    finally:
        release(conn)


@router.delete("/admin/providers/{code}")
def deactivate_provider(code: str, current: AdminOnly):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sso_provider SET is_active = false, updated_by = %s, updated_at = now() "
            "WHERE provider_code = %s",
            (current.username, code),
        )
        conn.commit()
        rowcount = cur.rowcount
        cur.close()
        if not rowcount:
            raise HTTPException(404, "SSO provider not found")
        return {"status": "deactivated", "provider_code": code}
    finally:
        release(conn)


@router.post("/admin/providers/{code}/test")
def test_provider(code: str, current: AdminOnly):
    conn, release = _get_db()
    try:
        provider = load_provider(conn, code)
        if provider["provider_type"] == "OIDC":
            http = _http_client()
            try:
                ep = oidc_discovery(provider, http)
                if not ep["jwks_url"]:
                    raise SSOError(400, "No jwks_uri resolved — check issuer_url")
                r = http.get(ep["jwks_url"], headers={"Accept": "application/json"})
                if r.status_code >= 400:
                    raise SSOError(400, f"JWKS fetch failed (HTTP {r.status_code})")
                return {"status": "ok",
                        "message": f"Discovery OK — endpoints resolved, JWKS reachable"}
            except SSOError as e:
                raise HTTPException(e.status_code, e.detail)
            finally:
                http.close()
        if provider["provider_type"] == "LDAP":
            try:
                msg = ldap_test_connection(provider)
                return {"status": "ok", "message": msg}
            except SSOError as e:
                raise HTTPException(e.status_code, e.detail)
        raise HTTPException(400, "Unsupported provider type")
    finally:
        release(conn)
