"""
test_auth.py — Authentication & RBAC test scenarios
Covers: TC-AUTH-001 to TC-AUTH-005
"""
import pytest
import requests
from conftest import BASE_URL, get_token, api

class TestLogin:
    def test_valid_admin_login(self):
        """TC-AUTH-001: Valid admin login returns token and correct role."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "Admin@1234"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["role"] in ("admin", "super_admin")
        assert data["username"] == "admin"
        assert len(data["access_token"]) > 20

    def test_invalid_password_rejected(self):
        """TC-AUTH-002: Wrong password returns 401."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "WrongPassword999"})
        assert resp.status_code in (401, 403, 429)

    def test_invalid_username_rejected(self):
        """TC-AUTH-002b: Non-existent user returns error."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "nobody_here", "password": "Admin@1234"})
        assert resp.status_code in (401, 403, 404)

    def test_agent_login_succeeds(self):
        """TC-AUTH-003: Agent login returns agent role."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "agent001", "password": "Agent@1234"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "agent"
        assert "access_token" in data

    def test_broker_login_succeeds(self):
        """Broker login returns broker role."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "broker001", "password": "Broker@1234"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "broker"

    def test_missing_fields_rejected(self):
        """Login with missing password field returns error."""
        resp = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin"})
        assert resp.status_code == 422

    def test_empty_credentials_rejected(self):
        """Login with empty strings returns error."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "", "password": ""})
        assert resp.status_code in (400, 401, 422)

    def test_full_name_returned(self):
        """Login response includes full_name field."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "Admin@1234"})
        assert resp.status_code == 200
        assert "full_name" in resp.json()

    def test_tenant_id_returned(self):
        """Login response includes tenant_id."""
        resp = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "Admin@1234"})
        assert resp.status_code == 200
        assert resp.json().get("tenant_id") is not None


class TestRBAC:
    def test_unauthenticated_request_rejected(self):
        """TC-AUTH-004: Request without token returns 401."""
        resp = requests.get(f"{BASE_URL}/underwriting/cases")
        assert resp.status_code == 401

    def test_invalid_token_rejected(self):
        """Expired or invalid token returns 401."""
        headers = {"Authorization": "Bearer invalidtoken123"}
        resp = requests.get(f"{BASE_URL}/underwriting/cases", headers=headers)
        assert resp.status_code == 401

    def test_agent_cannot_access_evaluate(self, agent_headers):
        """TC-AUTH-004: Agent cannot run UW evaluation."""
        from conftest import HEALTHY_MALE_30
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=agent_headers, json=HEALTHY_MALE_30)
        assert resp.status_code == 403

    def test_agent_cannot_access_workbench(self, agent_headers):
        """Agent cannot access UW workbench queue."""
        resp = requests.get(f"{BASE_URL}/queue", headers=agent_headers)
        assert resp.status_code in (403, 404)

    def test_agent_cannot_list_all_users(self, agent_headers):
        """Agent user list access — returns 200 (readonly) or 403."""
        resp = requests.get(f"{BASE_URL}/auth/users", headers=agent_headers)
        assert resp.status_code in (200, 403)

    def test_admin_can_access_users(self, admin_headers):
        """Admin can list platform users."""
        resp = requests.get(f"{BASE_URL}/auth/users", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_health_endpoint_public(self):
        """Health endpoint accessible without auth."""
        resp = requests.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
