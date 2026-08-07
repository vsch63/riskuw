"""
backend/tests/conftest.py
──────────────────────────
Shared pytest fixtures for all test modules.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

# Load repo-root .env so DB_USER / DB_PASSWORD are honoured even when the
# test shell doesn't export them. Repo root is two levels up from this file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# The API refuses to boot without a configured JWT_SECRET (deps.py) — give
# tests a deterministic key before anything imports the app.
os.environ.setdefault("JWT_SECRET", "test-secret-change-me")

# Point at a test DB before importing app. Override with TEST_DATABASE_URL.
# Note: postgres listens on 5433 here (5432 belongs to the DNB stack).
_default_test_url = (
    f"postgresql://{os.environ.get('DB_USER', 'uw_user')}"
    f":{os.environ.get('DB_PASSWORD', 'password')}"
    f"@localhost:5433/riskuw_test"
)
# Hard override (not setdefault): .env loads a dev DATABASE_URL and the test
# suite must never touch it. TEST_DATABASE_URL wins over the default.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", _default_test_url)
os.environ["JWT_SECRET"] = os.environ.get("TEST_JWT_SECRET", "test-secret-do-not-use-in-production")
os.environ["ENVIRONMENT"] = "test"

from main import app


@pytest.fixture(scope="session")
def client():
    """FastAPI test client — session-scoped for speed."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    """
    Log in as the demo admin user and return Bearer headers.
    Requires the test DB to have been seeded with create_user.py.
    """
    resp = client.post("/auth/login", json={
        "username": os.environ.get("TEST_USERNAME", "admin"),
        "password": os.environ.get("TEST_PASSWORD", "TestPass123!"),
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    # If MFA required, skip in CI (set TEST_SKIP_MFA=1)
    if data.get("mfa_required") and os.environ.get("TEST_SKIP_MFA"):
        pytest.skip("MFA required — set TEST_USERNAME to a non-MFA user for tests")
    token = data["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def minimal_payload():
    """Minimal valid evaluate payload."""
    return {
        "applicant_ref":  "TEST-001",
        "age":            35,
        "gender":         "MALE",
        "state":          "MH",
        "product_code":   "IND-TERM-20",
        "product_type":   "INDIVIDUAL_TERM",
        "face_amount":    1_000_000,
        "coverage_term_yrs": 20,
        "tobacco_status": "NEVER",
        "heart_condition":"NONE",
        "diabetes_type":  "NONE",
        "occupation_class":"1",
        "financial":      {"annual_income": 800_000, "existing_life_coverage": 0},
        "driving_record": {"dui_dwi_count_5yr": 0, "major_violations_3yr": 0,
                           "minor_violations_3yr": 0, "at_fault_accidents_3yr": 0,
                           "license_suspended": False},
    }
