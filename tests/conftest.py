"""
conftest.py — RiskUW automated test suite
Pytest fixtures shared across all test modules.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("RISKUW_BASE_URL", "http://localhost:8001")

def get_token(username: str, password: str) -> str:
    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]

@pytest.fixture(scope="session")
def admin_token():
    return get_token("admin", "Admin@1234")

@pytest.fixture(scope="session")
def underwriter_token():
    return get_token("admin", "Admin@1234")  # fallback to admin

@pytest.fixture(scope="session")
def agent_token():
    return get_token("agent001", "Agent@1234")

@pytest.fixture(scope="session")
def broker_token():
    return get_token("broker001", "Broker@1234")

@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="session")
def agent_headers(agent_token):
    return {"Authorization": f"Bearer {agent_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="session")
def broker_headers(broker_token):
    return {"Authorization": f"Bearer {broker_token}", "Content-Type": "application/json"}

def api(method: str, path: str, token: str, **kwargs):
    """Helper for API calls."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = getattr(requests, method)(f"{BASE_URL}{path}", headers=headers, **kwargs)
    return resp

# Standard test payloads
HEALTHY_MALE_30 = {
    "applicant_ref": "TC-AUTO-HEALTHY-001",
    "product_code": "IND-TERM-20",
    "age": 30, "gender": "MALE", "state": "MH",
    "face_amount": 1000000, "coverage_term_yrs": 20,
    "tobacco_status": "NEVER", "height_inches": 68, "weight_lbs": 170,
    "systolic_bp": 120, "diastolic_bp": 80,
    "diabetes_type": "NONE", "heart_condition": "NONE",
    "hazardous_activity": False, "annual_income": 1200000, "existing_coverage": 0,
}

HIGH_RISK_MALE = {
    "applicant_ref": "TC-AUTO-HIGHRISK-001",
    "product_code": "IND-TERM-20",
    "age": 65, "gender": "MALE", "state": "MH",
    "face_amount": 5000000, "coverage_term_yrs": 20,
    "tobacco_status": "SMOKER", "height_inches": 66, "weight_lbs": 220,
    "systolic_bp": 165, "diastolic_bp": 105,
    "diabetes_type": "TYPE1", "heart_condition": "MI",
    "hazardous_activity": True, "annual_income": 500000, "existing_coverage": 2000000,
}

BORDERLINE_MALE = {
    "applicant_ref": "TC-AUTO-BORDER-001",
    "product_code": "GRP-TERM-1",
    "age": 55, "gender": "MALE", "state": "MH",
    "face_amount": 5000000, "coverage_term_yrs": 20,
    "tobacco_status": "SMOKER", "height_inches": 68, "weight_lbs": 185,
    "systolic_bp": 148, "diastolic_bp": 93,
    "diabetes_type": "NONE", "heart_condition": "HYPERTENSION",
    "hazardous_activity": False, "annual_income": 800000, "existing_coverage": 0,
}
