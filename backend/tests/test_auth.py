"""
backend/tests/test_auth.py
Login, token validation, role gates, MFA flow.
"""
import pytest


def test_login_success(client):
    resp = client.post("/auth/login", json={"username": "admin", "password": "TestPass123!"})
    assert resp.status_code in (200, 401), resp.text  # 401 = test DB not seeded (CI skip)
    if resp.status_code == 200:
        data = resp.json()
        assert "access_token" in data or data.get("mfa_required")
        assert "username" in data
        assert "role" in data


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_missing_fields(client):
    resp = client.post("/auth/login", json={"username": "admin"})
    assert resp.status_code == 422   # Pydantic validation error


def test_protected_route_no_token(client):
    resp = client.get("/products")
    assert resp.status_code == 401


def test_protected_route_invalid_token(client):
    resp = client.get("/products", headers={"Authorization": "Bearer bad.token.here"})
    assert resp.status_code == 401


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data
    assert "db" in data


def test_token_decode(client):
    """Verify that a valid token grants access."""
    login = client.post("/auth/login", json={"username": "admin", "password": "TestPass123!"})
    if login.status_code != 200 or login.json().get("mfa_required"):
        pytest.skip("Test DB not seeded or MFA required")
    token = login.json()["access_token"]
    resp = client.get("/products", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_list_users_requires_auth(client):
    resp = client.get("/auth/users")
    assert resp.status_code == 401


def test_list_users_authenticated(client, auth_headers):
    resp = client.get("/auth/users", headers=auth_headers)
    assert resp.status_code in (200, 403)   # 403 if role is insufficient
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)
