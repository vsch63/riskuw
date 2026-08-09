"""
backend/services/sso.py
────────────────────────
Corporate-directory single sign-on.

  * OIDC — authorization-code + PKCE (S256) against any OpenID
    Connect provider; the ID token is verified against the provider's
    JWKS (RS256/ES256/EdDSA). No new dependencies: httpx does the
    discovery + token exchange, python-jose[cryptography] verifies.
  * LDAP — bind + search against Active Directory / OpenLDAP via
    ldap3 (pure-Python, the one new dependency this feature adds).

Both protocols converge on `resolve_sso_user`: find the matching
uw_user (by SSO subject, then by email to link an existing account),
or JIT-provision one when the provider has auto_provision enabled,
then return the identity the router turns into a normal RiskUW JWT.

OIDC needs the frontend URL to build the redirect_uri; it reads
FRONTEND_URL from the environment (same default as routers/auth.py).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from jose import jwk as jose_jwk
from jose import jwt as jose_jwt

logger = logging.getLogger("uw_platform")

# ── Errors ────────────────────────────────────────────────────────
class SSOError(Exception):
    """Carries an HTTP status + detail for the router to translate."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


OIDC_WELL_KNOWN = "/.well-known/openid-configuration"
OIDC_FLOW_TTL_MINUTES = 5

# Roles that a claim/attribute may select. Anything else falls back to
# the provider's default_role (never lets an IdP claim escalate).
ALLOWED_ROLES = {
    "super_admin", "admin", "senior_underwriter", "underwriter",
    "api_client", "readonly", "agent", "broker",
}
# Signature algorithms accepted for OIDC ID tokens (HS256 deliberately
# excluded — a symmetric client_secret key is a weaker trust anchor).
ID_TOKEN_ALGS = {"RS256", "ES256", "EdDSA"}


# ── Small helpers ─────────────────────────────────────────────────

def _get_db():
    from database import get_conn, release_conn  # noqa: PLC0415
    return get_conn(), release_conn


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=10, follow_redirects=False)


def frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "https://riskuw.online").rstrip("/")


def redirect_uri(provider_code: str) -> str:
    return f"{frontend_url()}/auth/sso/{provider_code}/callback"


def _audit(conn, event_type, actor, entity_id, after: dict, tenant_id=None):
    try:
        from routers.auth import _audit as _auth_audit  # lazy — avoid import cycle
        _auth_audit(conn, event_type, actor, entity_id, after,
                    ip=None, tenant_id=tenant_id)
    except Exception as e:  # audit must never break the login
        logger.warning("SSO audit failed: %s", e)


# ── Provider row access ───────────────────────────────────────────

def load_provider(conn, provider_code: str, active: bool | None = None) -> dict:
    """Load one sso_provider row as a plain dict (uuid tenant as text)."""
    cur = conn.cursor()
    try:
        sql = "SELECT * FROM sso_provider WHERE provider_code = %s"
        params: list = [provider_code]
        if active is not None:
            sql += " AND is_active = %s"
            params.append(active)
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            raise SSOError(404, "SSO provider not found")
        d = dict(row)
        if d.get("default_tenant_id") is not None:
            d["default_tenant_id"] = str(d["default_tenant_id"])
        return d
    finally:
        cur.close()


def _tenant_name(conn, tenant_id: str | None) -> str | None:
    if not tenant_id:
        return None
    cur = conn.cursor()
    try:
        cur.execute("SELECT tenant_name FROM tenant WHERE id = %s::uuid", (tenant_id,))
        row = cur.fetchone()
        return (row[0] if isinstance(row, tuple) else row["tenant_name"]) if row else None
    except Exception:
        return None
    finally:
        cur.close()


# ── OIDC ──────────────────────────────────────────────────────────

def oidc_discovery(provider: dict, http: httpx.Client) -> dict:
    """Fill missing endpoint URLs from the provider's discovery doc.

    Explicit per-provider URLs always win; discovery is a fallback and
    its failure (IdP unreachable, non-conformant) is non-fatal here so
    the caller can report a precise error.
    """
    issuer = (provider.get("issuer_url") or "").rstrip("/")
    if not issuer:
        raise SSOError(400, "issuer_url is required for OIDC providers")
    meta: dict = {}
    try:
        resp = http.get(issuer + OIDC_WELL_KNOWN, headers={"Accept": "application/json"})
        if resp.status_code < 400:
            meta = resp.json()
    except Exception as e:
        logger.warning("OIDC discovery failed for %s: %s", issuer, e)
    return {
        "authorize_url": provider.get("authorize_url") or meta.get("authorization_endpoint"),
        "token_url": provider.get("token_url") or meta.get("token_endpoint"),
        "jwks_url": provider.get("jwks_url") or meta.get("jwks_uri"),
    }


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(48)  # 64 chars → fits S256


def _pkce_challenge(verifier: str) -> str:
    import base64, hashlib  # noqa: PLC0415
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def oidc_authorize(provider: dict, http: httpx.Client) -> dict:
    """Create the sso_flow row and return the IdP authorization URL."""
    endpoints = oidc_discovery(provider, http)
    if not endpoints.get("authorize_url"):
        raise SSOError(400, "Cannot build authorize URL — no authorize_endpoint (is the issuer right?)")

    state = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    nonce = secrets.token_urlsafe(16)
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sso_flow WHERE expires_at < now()")  # opportunistic cleanup
        cur.execute(
            "INSERT INTO sso_flow (state, provider_code, code_verifier, nonce, expires_at) "
            "VALUES (%s, %s, %s, %s, now() + interval '%s minutes')",
            (state, provider["provider_code"], verifier, nonce, OIDC_FLOW_TTL_MINUTES),
        )
        conn.commit()
        cur.close()
    finally:
        release(conn)

    query = urlencode({
        "response_type": "code",
        "client_id": provider["client_id"],
        "redirect_uri": redirect_uri(provider["provider_code"]),
        "scope": provider.get("scope") or "openid email profile",
        "state": state,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "nonce": nonce,
    })
    sep = "&" if "?" in endpoints["authorize_url"] else "?"
    return {"authorize_url": f"{endpoints['authorize_url']}{sep}{query}"}


def _verify_id_token(provider: dict, endpoints: dict, id_token: str, nonce: str,
                     http: httpx.Client) -> dict:
    """Validate signature (JWKS) + iss/aud/exp/nonce of the ID token."""
    jwks_url = endpoints.get("jwks_url")
    if not jwks_url:
        raise SSOError(400, "Cannot verify ID token — no jwks_uri (is the issuer right?)")
    resp = http.get(jwks_url, headers={"Accept": "application/json"})
    if resp.status_code >= 400:
        raise SSOError(401, "Failed to fetch provider signing keys")
    keys = (resp.json() or {}).get("keys", [])

    try:
        header = jose_jwt.get_unverified_header(id_token)
    except jose_jwt.JWTError:
        raise SSOError(401, "Malformed ID token")
    if header.get("alg") not in ID_TOKEN_ALGS:
        raise SSOError(401, f"Unsupported ID token algorithm {header.get('alg')}")

    jwk = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if not jwk:
        raise SSOError(401, "No matching signing key in JWKS")
    public_key = jose_jwk.construct(jwk)
    try:
        claims = jose_jwt.decode(
            id_token, public_key, algorithms=[header["alg"]],
            audience=provider["client_id"],
            issuer=(provider.get("issuer_url") or "").rstrip("/"),
        )
    except jose_jwt.JWTError as e:
        raise SSOError(401, f"ID token verification failed: {e}")

    if nonce and claims.get("nonce") != nonce:
        raise SSOError(400, "Nonce mismatch — possible replay")
    if not claims.get("sub"):
        raise SSOError(401, "ID token has no subject")
    return claims


def oidc_callback(provider_code: str, code: str, state: str,
                  http: httpx.Client) -> dict:
    """Exchange the authorization code and resolve the RiskUW identity."""
    conn, release = _get_db()
    try:
        # Single-use flow row — consume it before the network round-trips so a
        # replayed state can never be exchanged twice.
        cur = conn.cursor()
        cur.execute(
            "SELECT provider_code, code_verifier, nonce, expires_at FROM sso_flow WHERE state = %s",
            (state,),
        )
        row = cur.fetchone()
        if not row:
            raise SSOError(400, "Invalid or expired SSO request — start again")
        flow = dict(row)
        cur.execute("DELETE FROM sso_flow WHERE state = %s", (state,))
        conn.commit()
        cur.close()

        if flow["provider_code"] != provider_code:
            raise SSOError(400, "SSO provider mismatch")
        if flow["expires_at"] < datetime.now(timezone.utc):
            raise SSOError(400, "SSO request expired — start again")

        provider = load_provider(conn, provider_code, active=True)
        if provider["provider_type"] != "OIDC":
            raise SSOError(400, "Not an OIDC provider")
        endpoints = oidc_discovery(provider, http)
        if not endpoints.get("token_url"):
            raise SSOError(400, "Cannot exchange code — no token_endpoint")

        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(provider_code),
            "client_id": provider["client_id"],
        }
        if flow.get("code_verifier"):
            body["code_verifier"] = flow["code_verifier"]
        if provider.get("client_secret"):
            body["client_secret"] = provider["client_secret"]
        token_resp = http.post(endpoints["token_url"], data=body,
                               headers={"Accept": "application/json"})
        if token_resp.status_code >= 400:
            raise SSOError(401, f"Token exchange failed (HTTP {token_resp.status_code})")
        tokens = token_resp.json()
        id_token = tokens.get("id_token")
        if not id_token:
            raise SSOError(401, "No id_token in token response")

        claims = _verify_id_token(provider, endpoints, id_token, flow.get("nonce") or "", http)
        subject = claims["sub"]
        email = (claims.get("email") or "").strip().lower()
        if not email:
            raise SSOError(400, "IdP did not return an email claim")
        name = claims.get("name") or claims.get("email") or subject
        username_claim = provider.get("oidc_username_claim") or "preferred_username"
        username_candidate = claims.get(username_claim) or email.split("@")[0]
        role_claim = _claim_role(claims, provider.get("claim_role_attr"))

        result = resolve_sso_user(conn, provider, subject, email, name,
                                  username_candidate, role_claim)
        result["tenant_name"] = _tenant_name(conn, result["tenant_id"])
        _audit(conn, "SSO_LOGIN", result["username"], result["username"],
               {"provider": provider_code, "method": "oidc"}, tenant_id=result["tenant_id"])
        conn.commit()
        return result
    finally:
        release(conn)


def _claim_role(claims: dict, attr: str | None):
    """Extract a role hint from IdP claims, sanitised against ALLOWED_ROLES."""
    if not attr:
        return None
    val = claims.get(attr)
    if isinstance(val, list):
        val = val[0] if val else None
    return val if isinstance(val, str) and val in ALLOWED_ROLES else None


# ── LDAP ──────────────────────────────────────────────────────────

def ldap_authenticate(provider: dict, username: str, password: str,
                      conn) -> dict:
    """Bind + search a corporate LDAP/AD directory.

    Uses a service account (ldap_bind_dn / ldap_bind_password, or
    anonymous when unset) for the search, then re-binds as the user's
    own DN to verify the password. `ldap_user_filter` substitutes
    {username}. Failures are generic (401) to avoid directory probing.
    """
    if provider["provider_type"] != "LDAP":
        raise SSOError(400, "Not an LDAP provider")
    if not username or not password:
        raise SSOError(401, "Invalid credentials")
    uri = provider.get("ldap_server_uri")
    base_dn = provider.get("ldap_base_dn")
    user_filter = provider.get("ldap_user_filter")
    if not (uri and base_dn and user_filter):
        raise SSOError(400, "LDAP provider is misconfigured (server_uri, base_dn, user_filter)")

    import ldap3  # noqa: PLC0415 — lazy so non-LDAP installs never need it

    try:
        server = ldap3.Server(uri)
        bind_dn = provider.get("ldap_bind_dn")
        bind_pw = provider.get("ldap_bind_password")
        with ldap3.Connection(server, user=bind_dn or None, password=bind_pw or None,
                              auto_bind=True) as c:
            filt = user_filter.replace("{username}", username)
            attrs = [provider.get("ldap_username_attr") or "sAMAccountName",
                     "mail", "displayName", "cn"]
            ok = c.search(search_base=base_dn, search_filter=filt, attributes=attrs)
            if not ok or len(c.entries) != 1:
                raise SSOError(401, "Invalid credentials")
            entry = c.entries[0]
            user_dn = str(entry.entry_dn)
            # Verify the presented password by re-binding as the user.
            try:
                ldap3.Connection(server, user=user_dn, password=password, auto_bind=True)
            except Exception:
                raise SSOError(401, "Invalid credentials")

        subject = _ldap_attr(entry, provider.get("ldap_username_attr") or "sAMAccountName") or username
        email = (_ldap_attr(entry, "mail") or "").strip().lower()
        name = _ldap_attr(entry, "displayName") or _ldap_attr(entry, "cn") or username
        role_claim = _ldap_attr(entry, provider.get("claim_role_attr")) \
            if provider.get("claim_role_attr") else None
        if role_claim not in ALLOWED_ROLES:
            role_claim = None

        result = resolve_sso_user(conn, provider, subject, email, name, username, role_claim)
        result["tenant_name"] = _tenant_name(conn, result["tenant_id"])
        _audit(conn, "SSO_LOGIN", result["username"], result["username"],
               {"provider": provider["provider_code"], "method": "ldap"},
               tenant_id=result["tenant_id"])
        conn.commit()
        return result
    except SSOError:
        raise
    except Exception as e:
        logger.warning("LDAP auth failed for %s: %s", username, e)
        raise SSOError(401, "Invalid credentials")


def ldap_test_connection(provider: dict) -> str:
    """Probe an LDAP provider: bind (service account or anonymous) and run a
    base-DN search. Returns a human-readable success message."""
    uri = provider.get("ldap_server_uri")
    base_dn = provider.get("ldap_base_dn")
    if not (uri and base_dn):
        raise SSOError(400, "ldap_server_uri and ldap_base_dn are required")
    import ldap3  # noqa: PLC0415
    server = ldap3.Server(uri)
    try:
        with ldap3.Connection(server, user=provider.get("ldap_bind_dn") or None,
                              password=provider.get("ldap_bind_password") or None,
                              auto_bind=True) as c:
            ok = c.search(search_base=base_dn, search_filter="(objectClass=*)",
                          search_scope=ldap3.BASE, attributes=["1.1"])
            if not ok:
                raise SSOError(400, f"Search on {base_dn} failed")
            base_dn_name = str(c.response[0]["dn"]) if c.response else base_dn
    except SSOError:
        raise
    except Exception as e:
        raise SSOError(400, f"LDAP bind/search failed: {e}")
    return f"OK — bound and resolved base DN {base_dn_name}"


def _ldap_attr(entry, name: str) -> str | None:
    try:
        vals = entry[name].values
        return str(vals[0]) if vals else None
    except Exception:
        return None


# ── Shared: find or provision the RiskUW user ─────────────────────

def resolve_sso_user(conn, provider: dict, subject: str, email: str, name: str,
                     username_candidate: str, role_claim: str | None) -> dict:
    """Return (username, role, tenant_id) for an SSO identity.

    Match order: (1) same provider+subject, (2) same email (links an
    existing account on first SSO login), (3) JIT-provision when the
    provider allows it. Provisioned users get hashed_password = NULL,
    so they can only ever authenticate through SSO.
    """
    cur = conn.cursor()
    try:
        # 1. Exact SSO identity.
        cur.execute(
            "SELECT username, role, tenant_id::text, full_name, is_active FROM uw_user "
            "WHERE sso_provider_code = %s AND sso_subject = %s AND is_deleted = false",
            (provider["provider_code"], subject),
        )
        row = cur.fetchone()
        if row:
            d = dict(row)
            if not d["is_active"]:
                raise SSOError(401, "Account is deactivated")
            return {"username": d["username"], "role": d["role"], "tenant_id": d["tenant_id"],
                    "full_name": d["full_name"]}

        # 2. Existing account by email — link the SSO identity to it.
        if email:
            cur.execute(
                "SELECT username, role, tenant_id::text, full_name, is_active FROM uw_user "
                "WHERE email = %s AND is_deleted = false LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
            if row:
                d = dict(row)
                if not d["is_active"]:
                    raise SSOError(401, "Account is deactivated")
                cur.execute(
                    "UPDATE uw_user SET sso_provider_code = %s, sso_subject = %s, "
                    "updated_at = now(), updated_by = 'sso' WHERE username = %s",
                    (provider["provider_code"], subject, d["username"]),
                )
                conn.commit()
                return {"username": d["username"], "role": d["role"], "tenant_id": d["tenant_id"],
                        "full_name": d["full_name"]}

        # 3. JIT provisioning.
        if not provider.get("auto_provision"):
            raise SSOError(403, "Account not provisioned for SSO — contact your administrator")
        if not email:
            raise SSOError(400, "SSO identity has no email — cannot provision an account")
        tenant_id = provider.get("default_tenant_id")
        if not tenant_id:
            raise SSOError(400, "Provider has no default_tenant_id — cannot provision")

        role = role_claim if role_claim in ALLOWED_ROLES else provider.get("default_role") or "viewer"
        username = (username_candidate or email.split("@")[0] or subject)[:80].strip()
        if not username:
            username = f"sso_{provider['provider_code'].lower()}_{secrets.token_hex(3)}"
        cur.execute("SELECT 1 FROM uw_user WHERE username = %s", (username,))
        if cur.fetchone():
            username = f"{username[:77]}_{secrets.token_hex(2)}"

        cur.execute(
            """
            INSERT INTO uw_user
              (id, username, email, hashed_password, full_name, role, is_active,
               tenant_id, created_by, updated_by, version, is_deleted,
               sso_provider_code, sso_subject)
            VALUES
              (gen_random_uuid(), %s, %s, NULL, %s, %s, true, %s::uuid,
               'sso', 'sso', 1, false, %s, %s)
            RETURNING username
            """,
            (username, email, name, role, tenant_id,
             provider["provider_code"], subject),
        )
        row = cur.fetchone()
        conn.commit()
        username = (row[0] if isinstance(row, tuple) else row["username"]) if row else username
        _audit(conn, "SSO_PROVISION", username, username,
               {"provider": provider["provider_code"], "via": "sso"},
               tenant_id=tenant_id)
        conn.commit()
        return {"username": username, "role": role, "tenant_id": tenant_id, "full_name": name}
    finally:
        cur.close()
