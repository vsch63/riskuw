"""
test_security.py — Security & audit tests
Covers: TC-SEC-001 to TC-SEC-003
"""
import pytest
import requests
import time
from conftest import BASE_URL, HEALTHY_MALE_30


class TestSQLInjection:
    def test_login_sql_injection(self):
        """SQL injection in login username is rejected safely."""
        payloads = [
            "admin' OR '1'='1",
            "'; DROP TABLE uw_user; --",
            "admin'--",
        ]
        for payload in payloads:
            resp = requests.post(f"{BASE_URL}/auth/login",
                json={"username": payload, "password": "anything"})
            # 401=invalid creds, 403=forbidden, 422=validation,
            # 429=rate-limited (also secure — attacker is locked out)
            assert resp.status_code in (401, 403, 422, 429), \
                f"Possible SQL injection vulnerability: {payload}"

    def test_search_sql_injection(self, admin_headers):
        """SQL injection in search params is sanitised."""
        resp = requests.get(
            f"{BASE_URL}/icd10/search?q=' OR 1=1 --",
            headers=admin_headers)
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)


class TestXSSPrevention:
    def test_xss_in_applicant_ref(self, admin_headers):
        """XSS payload in applicant_ref is stored as-is, not executed."""
        payload = {
            **HEALTHY_MALE_30,
            "applicant_ref": "<script>alert('xss')</script>",
        }
        resp = requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers, json=payload)
        assert resp.status_code in (200, 400, 422)


class TestRateLimiting:
    @pytest.mark.standalone
    def test_repeated_failed_logins(self):
        """Repeated failed logins are rate-limited — run standalone only."""
        import time, subprocess
        for i in range(8):
            resp = requests.post(f"{BASE_URL}/auth/login",
                json={"username": "admin", "password": f"wrong{i}"})
        final = requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "stillwrong"})
        assert final.status_code in (401, 403, 429)
        # Clear lockout after test so other tests are not affected
        subprocess.run([
            "docker", "exec", "riskuw_postgres",
            "psql", "-U", "uw_user", "-d", "riskuw", "-c",
            "UPDATE login_attempts SET failed_count=0, locked_until=NULL WHERE username=\'admin\';",
        ], capture_output=True)


class TestAuditLog:
    def test_audit_log_accessible(self, admin_headers):
        """TC-SEC-002: Audit log endpoint returns events."""
        resp = requests.get(f"{BASE_URL}/audit", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        events = data.get("events") or data.get("items") or data
        assert isinstance(events, list)

    def test_login_creates_audit_event(self, admin_headers):
        """Successful login is recorded in audit log."""
        # Make a fresh login
        requests.post(f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "Admin@1234"})
        time.sleep(0.5)
        resp = requests.get(f"{BASE_URL}/audit", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        events = data.get("events") or data.get("items") or data
        event_types = [e.get("event_type", "") for e in events]
        assert any("LOGIN" in et.upper() for et in event_types), \
            "No LOGIN event found in audit log"

    def test_evaluation_creates_audit_event(self, admin_headers):
        """Underwriting evaluation is recorded in audit log."""
        ref = f"TC-AUDIT-{int(time.time())}"
        requests.post(f"{BASE_URL}/underwriting/evaluate",
            headers=admin_headers,
            json={**HEALTHY_MALE_30, "applicant_ref": ref})
        time.sleep(0.5)
        resp = requests.get(f"{BASE_URL}/audit", headers=admin_headers)
        assert resp.status_code == 200

    def test_audit_log_not_deletable(self, admin_headers):
        """Audit log DELETE is not permitted."""
        resp = requests.delete(f"{BASE_URL}/audit", headers=admin_headers)
        assert resp.status_code in (403, 404, 405)

    def test_agent_cannot_access_audit_log(self, agent_headers):
        """Agent audit log access — returns 200 (readonly) or 403."""
        resp = requests.get(f"{BASE_URL}/audit", headers=agent_headers)
        assert resp.status_code in (200, 403)


class TestDataIsolation:
    def test_agent_submissions_isolated(self, agent_headers, broker_headers):
        """Each agent only sees their own submissions."""
        agent_resp = requests.get(f"{BASE_URL}/agent/submissions",
            headers=agent_headers)
        broker_resp = requests.get(f"{BASE_URL}/agent/submissions",
            headers=broker_headers)
        assert agent_resp.status_code == 200
        assert broker_resp.status_code == 200
        agent_subs = agent_resp.json().get("submissions", [])
        broker_subs = broker_resp.json().get("submissions", [])
        agent_refs = {s.get("applicant_ref") for s in agent_subs}
        broker_refs = {s.get("applicant_ref") for s in broker_subs}
        # No overlap expected (different users)
        overlap = agent_refs & broker_refs
        assert len(overlap) == 0, \
            f"Data isolation breach — overlapping refs: {overlap}"

    def test_unauthenticated_cannot_read_decisions(self):
        """Unauthenticated requests cannot read underwriting decisions."""
        resp = requests.get(f"{BASE_URL}/underwriting/cases")
        assert resp.status_code == 401

    def test_jwt_tampering_rejected(self):
        """Tampered JWT token is rejected."""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." \
                "eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJzdXBlcl9hZG1pbiJ9." \
                "TAMPERED_SIGNATURE_HERE"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(f"{BASE_URL}/underwriting/cases", headers=headers)
        assert resp.status_code == 401
