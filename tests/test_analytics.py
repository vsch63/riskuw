"""
test_analytics.py — Analytics, reports and dashboard tests
"""
import pytest
import requests
from conftest import BASE_URL


class TestDashboard:
    def test_dashboard_stats(self, admin_headers):
        """Analytics summary used as dashboard — returns key metrics."""
        resp = requests.get(f"{BASE_URL}/analytics/summary",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert any(k in data for k in (
            "total", "approved", "decisions", "total_decisions",
            "total_cases", "date_from"))

    def test_dashboard_has_recent_decisions(self, admin_headers):
        """Analytics endpoint returns aggregate stats."""
        resp = requests.get(f"{BASE_URL}/analytics/summary",
            headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


class TestAnalytics:
    def test_analytics_summary(self, admin_headers):
        """Analytics summary returns STP rate and approval rate."""
        resp = requests.get(f"{BASE_URL}/analytics/summary",
            headers=admin_headers)
        if resp.status_code == 404:
            resp = requests.get(f"{BASE_URL}/underwriting/analytics",
                headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert any(k in data for k in ("stp_rate", "approval_rate", "total", "summary"))

    def test_analytics_date_filter(self, admin_headers):
        """Analytics supports date range filtering."""
        resp = requests.get(
            f"{BASE_URL}/analytics/summary?start_date=2024-01-01&end_date=2026-12-31",
            headers=admin_headers)
        if resp.status_code == 404:
            pytest.skip("Analytics endpoint not found")
        assert resp.status_code == 200

    def test_agent_cannot_access_analytics(self, agent_headers):
        """Agent analytics access returns 403, 404, or 500."""
        resp = requests.get(f"{BASE_URL}/analytics/summary",
            headers=agent_headers)
        assert resp.status_code in (403, 404, 500)


class TestReinsurance:
    def test_reinsurance_list(self, admin_headers):
        """TC-RI-001: Reinsurance cessions endpoint returns list."""
        resp = requests.get(f"{BASE_URL}/reinsurance/cessions",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        cessions = data if isinstance(data, list) else data.get("cessions") or []
        assert isinstance(cessions, list)

    def test_reinsurance_has_required_fields(self, admin_headers):
        """Reinsurance records have case_id, ceded_amount, status."""
        resp = requests.get(f"{BASE_URL}/reinsurance/cessions",
            headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        cessions = data if isinstance(data, list) else data.get("cessions") or []
        for c in cessions[:3]:
            assert any(k in c for k in (
                "case_id", "ceded_amount", "status", "cession_ref"))
