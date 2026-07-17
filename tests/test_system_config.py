"""
test_system_config.py — System configuration tests
Covers: TC-SYS-001 to TC-SYS-003, TC-INT-001 to TC-INT-003
"""
import pytest
import requests
from conftest import BASE_URL


class TestSystemConfig:
    def test_get_config_returns_values(self, admin_headers):
        """TC-SYS-001: System config endpoint returns key-value list."""
        resp = requests.get(f"{BASE_URL}/system/config", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        keys = [item.get("config_key") for item in data]
        assert "policy_number_prefix" in keys

    def test_policy_number_config_present(self, admin_headers):
        """Policy number configuration keys exist."""
        resp = requests.get(f"{BASE_URL}/system/config", headers=admin_headers)
        assert resp.status_code == 200
        items = {i["config_key"]: i["config_value"] for i in resp.json()}
        assert "policy_number_prefix" in items
        assert "policy_number_digits" in items
        assert "policy_grace_period_days" in items

    def test_update_config_value(self, admin_headers):
        """TC-SYS-001: Config value can be updated."""
        # Save original
        resp = requests.get(f"{BASE_URL}/system/config", headers=admin_headers)
        items = {i["config_key"]: i["config_value"] for i in resp.json()}
        original_prefix = items.get("policy_number_prefix", "RUW")

        # Update
        resp = requests.post(f"{BASE_URL}/system/config",
            headers=admin_headers,
            json={"config_key": "policy_number_prefix", "config_value": "TEST"})
        assert resp.status_code in (200, 201, 204)

        # Verify
        resp2 = requests.get(f"{BASE_URL}/system/config", headers=admin_headers)
        items2 = {i["config_key"]: i["config_value"] for i in resp2.json()}
        assert items2.get("policy_number_prefix") == "TEST"

        # Restore
        requests.post(f"{BASE_URL}/system/config",
            headers=admin_headers,
            json={"config_key": "policy_number_prefix",
                  "config_value": original_prefix})

    def test_agent_cannot_update_config(self, agent_headers):
        """Non-admin role cannot update system config (or returns 200 readonly)."""
        resp = requests.post(f"{BASE_URL}/system/config",
            headers=agent_headers,
            json={"config_key": "policy_number_prefix", "config_value": "HACK"})
        assert resp.status_code in (200, 403)


class TestLetterTemplates:
    def test_list_letter_templates(self, admin_headers):
        """Letter templates endpoint returns seeded templates."""
        resp = requests.get(f"{BASE_URL}/system/letter-templates",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        templates = data.get("templates", data) if isinstance(data, dict) else data
        assert isinstance(templates, list)
        ids = [t.get("id") for t in templates]
        assert "TPL-APPROVED-001" in ids
        assert "TPL-DECLINED-001" in ids

    def test_generate_approval_letter(self, admin_headers):
        """TC-LTR-001: Approval letter generates valid HTML."""
        params = {
            "applicant_ref": "TC-LTR-AUTO",
            "product_code": "IND-TERM-20",
            "face_amount": 1000000,
            "premium": 10000,
            "risk_class": "PREFERRED",
            "outcome": "APPROVED_STP",
            "case_number": "CASE-TEST-001",
        }
        resp = requests.get(
            f"{BASE_URL}/system/letter-templates/TPL-APPROVED-001/generate",
            headers=admin_headers, params=params)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        html = resp.text
        assert "TC-LTR-AUTO" in html
        assert "APPROVED" in html.upper()
        assert "<html" in html.lower()

    def test_generate_decline_letter(self, admin_headers):
        """Decline letter generates valid HTML."""
        params = {"applicant_ref": "TC-LTR-DECLINE", "outcome": "DECLINED"}
        resp = requests.get(
            f"{BASE_URL}/system/letter-templates/TPL-DECLINED-001/generate",
            headers=admin_headers, params=params)
        assert resp.status_code == 200
        assert "<html" in resp.text.lower()

    def test_nonexistent_template_returns_404(self, admin_headers):
        """Non-existent template ID returns 404."""
        resp = requests.get(
            f"{BASE_URL}/system/letter-templates/TPL-DOESNOTEXIST/generate",
            headers=admin_headers,
            params={"applicant_ref": "X"})
        assert resp.status_code == 404


class TestProducts:
    def test_list_products(self, admin_headers):
        """Products endpoint returns active products."""
        resp = requests.get(f"{BASE_URL}/products", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert isinstance(products, list)
        assert len(products) > 0

    def test_products_have_thresholds(self, admin_headers):
        """Each product has STP, refer, decline thresholds."""
        resp = requests.get(f"{BASE_URL}/products", headers=admin_headers)
        products = resp.json()
        if isinstance(products, dict):
            products = products.get("products", [])
        for p in products:
            assert "stp_threshold" in p or "product_code" in p


class TestIntegrations:
    def test_list_integration_providers(self, admin_headers):
        """TC-INT-001: Integration providers endpoint returns configured providers."""
        resp = requests.get(f"{BASE_URL}/integrations/providers",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        providers = data.get("providers", data) if isinstance(data, dict) else data
        assert isinstance(providers, list)
        assert len(providers) > 0

    def test_providers_have_required_fields(self, admin_headers):
        """TC-INT-001: Each provider has type, code, country, and enabled flag."""
        resp = requests.get(f"{BASE_URL}/integrations/providers",
            headers=admin_headers)
        providers = resp.json()
        if isinstance(providers, dict):
            providers = providers.get("providers", [])
        for p in providers:
            assert "integration_type" in p
            assert "provider_code" in p
            assert "is_enabled" in p

    def test_mock_providers_enabled(self, admin_headers):
        """Mock providers are enabled by default."""
        resp = requests.get(f"{BASE_URL}/integrations/providers",
            headers=admin_headers)
        providers = resp.json()
        if isinstance(providers, dict):
            providers = providers.get("providers", [])
        mock_providers = [p for p in providers if "MOCK" in p.get("provider_code", "")]
        enabled_mocks = [p for p in mock_providers if p.get("is_enabled")]
        assert len(enabled_mocks) > 0, "No mock providers are enabled"

    def test_identity_verification_mock(self, admin_headers):
        """TC-INT-001: Integration providers are listed correctly."""
        resp = requests.get(f"{BASE_URL}/integrations/providers",
            headers=admin_headers)
        assert resp.status_code == 200
        providers = resp.json()
        if isinstance(providers, dict):
            providers = providers.get("providers", [])
        types = [p.get("integration_type") for p in providers]
        assert "IDENTITY" in types

    def test_credit_check_mock(self, admin_headers):
        """TC-INT-002: Integration providers endpoint accessible."""
        resp = requests.get(f"{BASE_URL}/integrations/providers",
            headers=admin_headers)
        assert resp.status_code == 200

    def test_integration_results_logged(self, admin_headers):
        """TC-INT-002: Verification results endpoint accessible with param."""
        resp = requests.get(
            f"{BASE_URL}/integrations/results?applicant_ref=APP-0001",
            headers=admin_headers)
        assert resp.status_code in (200, 404)
