"""
backend/tests/test_sso_oidc.py
────────────────────────────────
OIDC SSO against the in-process mock IdP.

  * full authorize → callback flow returns a RiskUW JWT via a 302 fragment
  * pre-provisioned user signs in; JWT carries the right sub/role/tenant
  * JIT auto-provisioning creates the uw_user on first login (NULL password)
  * auto_provision off + unknown user → error fragment (403)
  * wrong nonce in the ID token → error fragment
  * replaying the state → error fragment (single-use)
  * corrupted ID-token signature → rejected
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))

import httpx
import pytest
import uvicorn
from jose import jwt as jose_jwt

import mock_idp
from mock_idp import CLIENT_ID, issue_id_token, reset_codes, seed_code
from database import get_conn, release_conn
import routers.sso as sso_router_mod
from services.sso import SSOError, _verify_id_token, oidc_discovery

PROVIDER = "SSO-OIDC-TST"
CODE = "SSO-TEST-CODE"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def idp_url():
    """Boot the mock IdP on a random 127.0.0.1 port once per session.

    httpx 0.28's ASGITransport is async-only, so the sync SSO service can't
    talk to an in-process ASGI app; a real uvicorn origin keeps everything
    plain sync HTTP.
    """
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    mock_idp.BASE_URL = base
    config = uvicorn.Config(mock_idp.app, host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            httpx.get(f"{base}/.well-known/openid-configuration", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    yield base
    server.should_exit = True
    thread.join(timeout=5)


def _mock_client(base_url: str):
    return httpx.Client(base_url=base_url)


@pytest.fixture()
def sso_http(monkeypatch, idp_url):
    """Route the app's SSO outbound calls to the booted mock IdP; yield its URL."""
    monkeypatch.setattr(sso_router_mod, "_http_client",
                        lambda base_url=idp_url: _mock_client(base_url))
    yield idp_url


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sso_flow WHERE provider_code = %s", (PROVIDER,))
        cur.execute("DELETE FROM sso_provider WHERE provider_code = %s", (PROVIDER,))
        cur.execute("DELETE FROM uw_user WHERE sso_provider_code = %s", (PROVIDER,))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def _admin_tenant() -> str:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT tenant_id::text FROM uw_user WHERE username = 'admin'")
        return dict(cur.fetchone())["tenant_id"]
    finally:
        cur.close()
        release_conn(conn)


def _create_provider(client, auth_headers, issuer_url, *,
                     auto_provision: bool = True) -> str:
    tenant_id = _admin_tenant()
    r = client.post("/auth/sso/admin/providers", json={
        "provider_code": PROVIDER,
        "provider_type": "OIDC",
        "display_name": "Mock IdP",
        "issuer_url": issuer_url,
        "client_id": CLIENT_ID,
        "client_secret": "test-secret",
        "default_role": "underwriter",
        "default_tenant_id": tenant_id,
        "auto_provision": auto_provision,
    }, headers=auth_headers)
    assert r.status_code == 200, r.text
    return tenant_id


def _preprovision(username: str = "sso-user", subject: str = "sub-123") -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO uw_user
              (id, username, email, hashed_password, full_name, role, is_active,
               tenant_id, created_by, updated_by, version, is_deleted,
               sso_provider_code, sso_subject)
            VALUES (gen_random_uuid(), %s, 'sso.user@corp.example.com', NULL, 'SSO User',
                    'underwriter', true, %s::uuid, 'test', 'test', 1, false, %s, %s)
            """,
            (username, _admin_tenant(), PROVIDER, subject),
        )
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def _start_flow(client) -> tuple[str, str]:
    """GET authorize → return (state, nonce from sso_flow)."""
    r = client.get(f"/auth/sso/{PROVIDER}/authorize")
    assert r.status_code == 200, r.text
    qs = parse_qs(urlparse(r.json()["authorize_url"]).query)
    state = qs["state"][0]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT nonce, code_verifier FROM sso_flow WHERE state = %s", (state,))
        flow = dict(cur.fetchone())
    finally:
        cur.close()
        release_conn(conn)
    return state, flow["nonce"], flow["code_verifier"]


def _run_callback(client, state: str, nonce: str, verifier: str,
                  *, subject: str = "sub-123") -> tuple[int, str]:
    """Seed the mock code registry and drive the callback; return (status, fragment dict)."""
    seed_code(CODE, sub=subject, email="sso.user@corp.example.com",
              name="SSO User", nonce=nonce, verifier=verifier)
    # follow_redirects=False: the callback answers with a 302 to the SPA
    # fragment; we need the raw redirect to read the JWT out of Location.
    r = client.get(f"/auth/sso/{PROVIDER}/callback?code={CODE}&state={state}",
                   follow_redirects=False)
    frag = {}
    if r.status_code == 302:
        loc = r.headers["location"]
        frag = parse_qs(loc.split("#", 1)[1])
    return r.status_code, frag


def test_oidc_full_flow_preprovisioned(client, auth_headers, sso_http):
    try:
        tenant_id = _create_provider(client, auth_headers, sso_http)
        _preprovision()

        state, nonce, verifier = _start_flow(client)
        status, frag = _run_callback(client, state, nonce, verifier)

        assert status == 302, frag
        assert "access_token" in frag, frag
        claims = jose_jwt.decode(frag["access_token"][0],
                                 os.environ["JWT_SECRET"], algorithms=["HS256"])
        assert claims["sub"] == "sso-user"
        assert claims["role"] == "underwriter"
        assert claims["tenant_id"] == tenant_id
    finally:
        _cleanup()


def test_oidc_jit_provisions_user(client, auth_headers, sso_http):
    try:
        _create_provider(client, auth_headers, sso_http, auto_provision=True)
        state, nonce, verifier = _start_flow(client)
        status, frag = _run_callback(client, state, nonce, verifier)
        assert status == 302, frag

        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT username, role, tenant_id::text, hashed_password, email "
                "FROM uw_user WHERE sso_provider_code = %s AND sso_subject = %s",
                (PROVIDER, "sub-123"),
            )
            row = dict(cur.fetchone())
        finally:
            cur.close()
            release_conn(conn)

        assert row["username"] == "sso.user"          # preferred_username claim
        assert row["role"] == "underwriter"            # default_role
        assert row["hashed_password"] is None          # SSO-only account
        assert row["email"] == "sso.user@corp.example.com"
        assert row["tenant_id"] == _admin_tenant()
    finally:
        _cleanup()


def test_oidc_deny_unprovisioned(client, auth_headers, sso_http):
    try:
        _create_provider(client, auth_headers, sso_http, auto_provision=False)
        state, nonce, verifier = _start_flow(client)
        status, frag = _run_callback(client, state, nonce, verifier)
        assert status == 302
        assert "error" in frag, frag
        assert "not provisioned" in frag["error"][0].lower()
    finally:
        _cleanup()


def test_oidc_rejects_wrong_nonce(client, auth_headers, sso_http):
    try:
        _create_provider(client, auth_headers, sso_http)
        state, nonce, verifier = _start_flow(client)
        status, frag = _run_callback(client, state, "wrong-nonce", verifier)
        assert status == 302
        assert "error" in frag and "nonce" in frag["error"][0].lower(), frag
    finally:
        _cleanup()


def test_oidc_rejects_replayed_state(client, auth_headers, sso_http):
    try:
        _create_provider(client, auth_headers, sso_http)
        _preprovision()

        state, nonce, verifier = _start_flow(client)
        status, frag = _run_callback(client, state, nonce, verifier)
        assert status == 302 and "access_token" in frag

        # Same code + state again → flow row already consumed.
        status2, frag2 = _run_callback(client, state, nonce, verifier)
        assert status2 == 302
        assert "error" in frag2, frag2
    finally:
        _cleanup()


def test_oidc_rejects_corrupted_signature(sso_http):
    provider = {"issuer_url": sso_http, "client_id": CLIENT_ID}
    http = _mock_client(sso_http)
    try:
        endpoints = oidc_discovery(provider, http)
        good = issue_id_token("sub-1", "a@corp.example.com", "A", "nonce-1")
        parts = good.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        bad = ".".join(parts)
        with pytest.raises(SSOError) as ei:
            _verify_id_token(provider, endpoints, bad, "nonce-1", http)
        assert ei.value.status_code == 401
    finally:
        http.close()
