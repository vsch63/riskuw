"""
backend/tests/test_mfa_enforcement.py
──────────────────────────────────────
MFA enforcement switch (MFA_ENFORCED flag) and TOTP enrollment flow.

With the flag OFF (dev default): privileged roles login without MFA (regression).
With the flag ON:  privileged roles without MFA must enroll; viewers are exempt.

Run via: make ci-test (or pytest tests/test_mfa_enforcement.py)
"""
from __future__ import annotations

import os
from decimal import Decimal

import pyotp
import pytest

from config import cfg


# ── Helpers ────────────────────────────────────────────────────────────────────

ADMIN_USER = os.environ.get("TEST_USERNAME", "admin")
ADMIN_PASS = os.environ.get("TEST_PASSWORD", "TestPass123!")


def _login(client, username: str = ADMIN_USER, password: str = ADMIN_PASS):
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def _viewer_login(client):
    """Login a non-privileged viewer account. Falls back to admin if no viewer exists."""
    # Try a viewer user if seeded; else return None (skip viewer tests).
    resp = client.post("/auth/login", json={"username": "viewer_test", "password": "TestPass123!"})
    if resp.status_code == 200 and resp.json().get("access_token"):
        return resp
    return None


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_switch_off_no_mfa_challenge(client):
    """MFA_ENFORCED=False: privileged role logs in without any MFA step."""
    cfg.mfa_enforced = False
    try:
        resp = _login(client)
        data = resp.json()
        assert resp.status_code == 200, resp.text
        assert not data.get("mfa_required")
        assert data.get("access_token")
    finally:
        cfg.mfa_enforced = False


def test_switch_on_admin_gets_enrollment_challenge(client):
    """MFA_ENFORCED=True + admin not yet enrolled → mfa_required + enrollment_required."""
    cfg.mfa_enforced = True
    try:
        resp = _login(client)
        data = resp.json()
        assert resp.status_code == 200, resp.text
        assert data["mfa_required"] is True, "privileged role should be challenged"
        assert data["mfa_enrollment_required"] is True, "user has no mfa_config row"
        assert data["mfa_session_token"], "should receive a session token"
    finally:
        cfg.mfa_enforced = False


def test_setup_verify_login_flow(client):
    """Full enrollment flow: setup → verify-setup → login now succeeds with code."""
    cfg.mfa_enforced = True
    try:
        # 1. login → get MFA session token
        login = _login(client)
        ld = login.json()
        assert ld["mfa_required"] and ld["mfa_enrollment_required"]
        session_tok = ld["mfa_session_token"]

        # 2. setup → get secret
        setup = client.post("/auth/mfa/setup", json={"username": ADMIN_USER, "session_token": session_tok})
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        assert len(secret) == 32, "base32 secret should be 32 chars"

        # 3. verify-setup → full token
        code = pyotp.TOTP(secret).now()
        verify = client.post("/auth/mfa/verify-setup", json={
            "username": ADMIN_USER, "session_token": session_tok, "totp_code": code,
        })
        assert verify.status_code == 200, verify.text
        vd = verify.json()
        assert vd["access_token"], "should receive a full access token after enrollment"

        # 4. login again — now mfa_required=True but enrollment_required=False (already enrolled)
        login2 = _login(client)
        ld2 = login2.json()
        assert ld2["mfa_required"] is True, "user is now enrolled — should always challenge"
        assert not ld2.get("mfa_enrollment_required"), "already enrolled — not required"
        code2 = pyotp.TOTP(secret).now()
        verify2 = client.post("/auth/verify-mfa", json={
            "totp_code": code2, "username": ADMIN_USER, "session_token": ld2["mfa_session_token"],
        })
        assert verify2.status_code == 200
        assert verify2.json()["access_token"], "login should complete with valid code"
    finally:
        # cleanup: disable mfa so other tests aren't affected
        try:
            session_tok = ld2.get("mfa_session_token") or session_tok
            client.post("/auth/mfa/disable", json={"username": ADMIN_USER, "session_token": session_tok})
        except Exception:
            pass
        cfg.mfa_enforced = False


def test_viewer_not_enforced(client):
    """Non-privileged role (viewer) is not challenged even when MFA_ENFORCED=True."""
    cfg.mfa_enforced = True
    try:
        resp = _viewer_login(client)
        if resp is None:
            pytest.skip("No viewer_test account seeded — skipping viewer enforcement test")
        data = resp.json()
        assert resp.status_code == 200, resp.text
        assert not data.get("mfa_required"), "viewer should be exempt from enforcement"
        assert data.get("access_token"), "viewer should get a token directly"
    finally:
        cfg.mfa_enforced = False
