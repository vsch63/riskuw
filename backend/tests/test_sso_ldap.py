"""
backend/tests/test_sso_ldap.py
────────────────────────────────
LDAP SSO login against the in-process fake directory.

  * a pre-provisioned user signs in with corporate credentials → JWT
  * wrong password → 401
  * JIT auto-provisioning creates the uw_user (NULL password)
  * auto_provision off + unknown user → 403
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import ldap3

from fake_ldap import FakeLdapConnection, FakeLdapDirectory
from database import get_conn, release_conn

PROVIDER = "SSO-LDAP-TST"
USER = "uwtester"
USER_PW = "CorpPass123!"
USER_DN = "cn=uwtester,ou=Users,dc=corp,dc=local"
BASE_DN = "dc=corp,dc=local"


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sso_provider WHERE provider_code = %s", (PROVIDER,))
        cur.execute("DELETE FROM uw_user WHERE sso_provider_code = %s", (PROVIDER,))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def _directory() -> FakeLdapDirectory:
    return FakeLdapDirectory([
        {
            "username": USER,
            "password": USER_PW,
            "dn": USER_DN,
            "attributes": {
                "sAMAccountName": USER,
                "mail": f"{USER}@corp.example.com",
                "displayName": "UW Tester",
            },
        },
    ])


def _patch_ldap(monkeypatch, directory: FakeLdapDirectory):
    monkeypatch.setattr(ldap3, "Server", lambda *a, **k: directory)
    monkeypatch.setattr(
        ldap3, "Connection",
        lambda server, *a, **k: FakeLdapConnection(directory, *a, **k),
    )


def _admin_tenant() -> str:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT tenant_id::text FROM uw_user WHERE username = 'admin'")
        return dict(cur.fetchone())["tenant_id"]
    finally:
        cur.close()
        release_conn(conn)


def _create_provider(client, auth_headers, *, auto_provision: bool = False) -> str:
    tenant_id = _admin_tenant()
    r = client.post("/auth/sso/admin/providers", json={
        "provider_code": PROVIDER,
        "provider_type": "LDAP",
        "display_name": "Fake AD",
        "ldap_server_uri": "ldap://fake",
        "ldap_base_dn": BASE_DN,
        "ldap_user_filter": f"(&(objectClass=user)(sAMAccountName={{username}}))",
        "ldap_username_attr": "sAMAccountName",
        "default_role": "underwriter",
        "default_tenant_id": tenant_id,
        "auto_provision": auto_provision,
    }, headers=auth_headers)
    assert r.status_code == 200, r.text
    return tenant_id


def _preprovision() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO uw_user
              (id, username, email, hashed_password, full_name, role, is_active,
               tenant_id, created_by, updated_by, version, is_deleted,
               sso_provider_code, sso_subject)
            VALUES (gen_random_uuid(), %s, 'uwtester@corp.example.com', NULL, 'UW Tester',
                    'underwriter', true, %s::uuid, 'test', 'test', 1, false, %s, %s)
            """,
            (USER, _admin_tenant(), PROVIDER, USER),
        )
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def test_ldap_login_preprovisioned(client, auth_headers, monkeypatch):
    _patch_ldap(monkeypatch, _directory())
    try:
        _create_provider(client, auth_headers)
        _preprovision()

        r = client.post("/auth/login", json={
            "username": USER, "password": USER_PW, "sso_provider": PROVIDER,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["username"] == USER
        assert data["role"] == "underwriter"
        assert data["tenant_id"] == _admin_tenant()
        assert data["access_token"]
    finally:
        _cleanup()


def test_ldap_login_wrong_password(client, auth_headers, monkeypatch):
    _patch_ldap(monkeypatch, _directory())
    try:
        _create_provider(client, auth_headers)
        _preprovision()
        r = client.post("/auth/login", json={
            "username": USER, "password": "wrong", "sso_provider": PROVIDER,
        })
        assert r.status_code == 401, r.text
    finally:
        _cleanup()


def test_ldap_jit_provisions_user(client, auth_headers, monkeypatch):
    _patch_ldap(monkeypatch, _directory())
    try:
        _create_provider(client, auth_headers, auto_provision=True)

        r = client.post("/auth/login", json={
            "username": USER, "password": USER_PW, "sso_provider": PROVIDER,
        })
        assert r.status_code == 200, r.text
        assert r.json()["username"] == USER

        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT username, role, hashed_password, email, tenant_id::text "
                "FROM uw_user WHERE sso_provider_code = %s AND sso_subject = %s",
                (PROVIDER, USER),
            )
            row = dict(cur.fetchone())
        finally:
            cur.close()
            release_conn(conn)

        assert row["username"] == USER
        assert row["role"] == "underwriter"
        assert row["hashed_password"] is None
        assert row["email"] == f"{USER}@corp.example.com"
        assert row["tenant_id"] == _admin_tenant()
    finally:
        _cleanup()


def test_ldap_deny_unprovisioned(client, auth_headers, monkeypatch):
    _patch_ldap(monkeypatch, _directory())
    try:
        _create_provider(client, auth_headers, auto_provision=False)
        r = client.post("/auth/login", json={
            "username": USER, "password": USER_PW, "sso_provider": PROVIDER,
        })
        assert r.status_code == 403, r.text
        assert "not provisioned" in r.json()["detail"].lower()
    finally:
        _cleanup()
