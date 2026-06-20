"""
backend/services/integrations/mock.py
──────────────────────────────────────
Mock providers for all integration types.
Used for demos and development — returns realistic-looking data
based on the applicant payload without calling any real API.

Mock providers auto-registered on import.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

from services.integrations.base import (
    IntegrationProvider, IntegrationResult, register
)


def _seed(applicant_ref: str, salt: str = "") -> random.Random:
    """Deterministic RNG seeded from applicant_ref — same input = same output."""
    h = int(hashlib.md5(f"{applicant_ref}{salt}".encode()).hexdigest(), 16)
    return random.Random(h)


# ── CKYC Mock ─────────────────────────────────────────────────────────────────
@register
class CKYCMockProvider(IntegrationProvider):
    """
    Mock CKYC (Central KYC Registry) provider.
    Real endpoint: https://www.ckycindia.in/
    Requires: CIN, PAN or Aadhaar number
    """
    provider_code    = "CKYC_MOCK"
    integration_type = "IDENTITY"
    is_mock          = True

    def verify(self, payload: dict) -> IntegrationResult:
        rng = _seed(payload.get("applicant_ref", ""), "ckyc")
        pan = payload.get("pan_number", "")
        name = payload.get("full_name") or payload.get("applicant_name", "")
        age  = payload.get("age", 35)

        # 95% success rate in mock
        if rng.random() > 0.05:
            # Mask Aadhaar: only last 4 digits visible
            aadhaar = f"XXXX-XXXX-{rng.randint(1000,9999)}"
            # Generate a deterministic DOB from age
            dob_year = date.today().year - int(age)
            dob = date(dob_year, rng.randint(1,12), rng.randint(1,28))

            return IntegrationResult(
                success          = True,
                provider_code    = self.provider_code,
                integration_type = self.integration_type,
                kyc_verified     = True,
                kyc_name         = name.upper() if name else "APPLICANT NAME",
                kyc_dob          = str(dob),
                kyc_pan          = pan.upper() if pan else f"ABCDE{rng.randint(1000,9999)}F",
                kyc_aadhaar_masked = aadhaar,
                kyc_address      = f"{rng.randint(1,999)}, Sample Colony, Mumbai, MH - 400001",
                confidence_score = round(rng.uniform(0.92, 0.99), 2),
                raw_response     = {"ckyc_number": f"CKY{rng.randint(100000,999999)}",
                                    "verified": True, "source": "CKYC_MOCK"},
                notes            = "CKYC mock verification — replace with live CDSL endpoint for production",
                expires_in_days  = 365,
            )
        else:
            return IntegrationResult(
                success          = False,
                provider_code    = self.provider_code,
                integration_type = self.integration_type,
                kyc_verified     = False,
                confidence_score = 0.0,
                error            = "CKYC record not found for provided PAN/Aadhaar",
                notes            = "Mock: ~5% not-found rate",
            )


# ── CIBIL Mock ────────────────────────────────────────────────────────────────
@register
class CIBILMockProvider(IntegrationProvider):
    """
    Mock CIBIL/credit bureau provider.
    Real endpoint: TransUnion CIBIL API (requires CIBIL membership)
    Score range: 300-900 (India); 750+ considered good
    """
    provider_code    = "CIBIL_MOCK"
    integration_type = "CREDIT"
    is_mock          = True

    def verify(self, payload: dict) -> IntegrationResult:
        rng = _seed(payload.get("applicant_ref", ""), "cibil")
        income = float(payload.get("annual_income") or 0)
        age    = int(payload.get("age") or 35)
        tobacco = str(payload.get("tobacco_status", "")).upper()

        # Base score influenced by income and age — deterministic per applicant
        base = 650
        if income > 1_500_000: base += 80
        elif income > 800_000:  base += 40
        if age > 45:            base += 20
        if tobacco in ("SMOKER", "TOBACCO"): base -= 30
        score = min(900, max(300, base + rng.randint(-50, 80)))

        flags = []
        if score < 650:   flags.append("BELOW_AVERAGE_SCORE")
        if score < 550:   flags.append("HIGH_RISK_PROFILE")
        if rng.random() < 0.08: flags.append("MULTIPLE_LOAN_ENQUIRIES_90D")
        if rng.random() < 0.04: flags.append("LATE_PAYMENT_HISTORY")
        if rng.random() < 0.02: flags.append("WRITTEN_OFF_ACCOUNT")

        return IntegrationResult(
            success           = True,
            provider_code     = self.provider_code,
            integration_type  = self.integration_type,
            credit_score      = score,
            credit_bureau     = "TransUnion CIBIL (Mock)",
            credit_report_ref = f"CR{rng.randint(10000000,99999999)}",
            credit_flags      = flags,
            confidence_score  = round(rng.uniform(0.90, 0.99), 2),
            raw_response      = {
                "score": score, "report_ref": f"CR{rng.randint(10000000,99999999)}",
                "accounts": rng.randint(1,8), "enquiries_90d": rng.randint(0,4),
                "delinquencies": len([f for f in flags if "LATE" in f or "WRITTEN" in f]),
            },
            notes             = "CIBIL mock — replace with live TransUnion CIBIL API for production",
            expires_in_days   = 30,
        )


# ── Lab Mock ──────────────────────────────────────────────────────────────────
@register
class LabMockProvider(IntegrationProvider):
    """
    Mock lab/diagnostic provider.
    Real providers: Healthians, 1mg, SRL, Thyrocare
    Returns: HbA1c, lipid profile, CBC, eGFR, liver panel
    """
    provider_code    = "LAB_MOCK"
    integration_type = "LAB"
    is_mock          = True

    def verify(self, payload: dict) -> IntegrationResult:
        rng = _seed(payload.get("applicant_ref", ""), "lab")
        age     = int(payload.get("age") or 35)
        diabetes = str(payload.get("diabetes_type","NONE")).upper()
        tobacco  = str(payload.get("tobacco_status","")).upper()

        # HbA1c — elevated if diabetic
        hba1c_base = 5.2 if diabetes == "NONE" else (7.8 if diabetes == "TYPE2" else 9.1)
        hba1c = round(hba1c_base + rng.uniform(-0.4, 0.8), 1)

        # Cholesterol — elevated if older/smoker
        chol_base = 170 + (age - 30) * 0.8
        if "SMOKER" in tobacco: chol_base += 20
        total_chol = int(chol_base + rng.randint(-20, 30))
        ldl        = int(total_chol * 0.62 + rng.randint(-15, 15))
        hdl        = int(50 - (age * 0.1) + rng.randint(-8, 8))
        trigly     = int(130 + rng.randint(-40, 80))

        # eGFR — decreases with age
        egfr = max(45, int(110 - (age - 30) * 0.6 + rng.randint(-10, 10)))

        # Glucose fasting
        glucose = int(88 + rng.randint(-10, 20)) if diabetes == "NONE" else int(
            130 + rng.randint(-15, 35))

        def flag(val, low, high):
            if val < low:   return "LOW"
            if val > high:  return "HIGH"
            return "NORMAL"

        tests = [
            {"test":"HbA1c",           "value":hba1c,     "unit":"%",     "normal_range":"<5.7",     "flag":flag(hba1c,0,5.7)},
            {"test":"Total Cholesterol","value":total_chol,"unit":"mg/dL", "normal_range":"<200",     "flag":flag(total_chol,0,200)},
            {"test":"LDL",             "value":ldl,       "unit":"mg/dL", "normal_range":"<130",     "flag":flag(ldl,0,130)},
            {"test":"HDL",             "value":hdl,       "unit":"mg/dL", "normal_range":">40",      "flag":"LOW" if hdl<40 else "NORMAL"},
            {"test":"Triglycerides",   "value":trigly,    "unit":"mg/dL", "normal_range":"<150",     "flag":flag(trigly,0,150)},
            {"test":"eGFR",            "value":egfr,      "unit":"mL/min","normal_range":">60",      "flag":"LOW" if egfr<60 else "NORMAL"},
            {"test":"Fasting Glucose", "value":glucose,   "unit":"mg/dL", "normal_range":"70-100",   "flag":flag(glucose,70,100)},
        ]

        return IntegrationResult(
            success          = True,
            provider_code    = self.provider_code,
            integration_type = self.integration_type,
            lab_order_ref    = f"LAB{rng.randint(1000000,9999999)}",
            lab_tests        = tests,
            lab_report_url   = f"https://reports.labmock.example.com/LAB{rng.randint(1000000,9999999)}.pdf",
            confidence_score = 0.99,
            raw_response     = {"provider":"LabMock","tests":tests},
            notes            = "Lab mock — integrate with Healthians/1mg/SRL API for production",
            expires_in_days  = 180,
        )


# ── AML Mock ──────────────────────────────────────────────────────────────────
@register
class AMLMockProvider(IntegrationProvider):
    """
    Mock AML/sanctions screening provider.
    Real providers: LexisNexis, Refinitiv WorldCheck, Dow Jones
    Checks: PEP lists, OFAC, EU/UN sanctions, RBI defaulter list
    """
    provider_code    = "AML_MOCK"
    integration_type = "AML"
    is_mock          = True

    def verify(self, payload: dict) -> IntegrationResult:
        rng = _seed(payload.get("applicant_ref", ""), "aml")

        # 98% CLEAR, 1.5% MANUAL_REVIEW, 0.5% HIT
        roll = rng.random()
        if roll < 0.98:
            status = "CLEAR"
            flags  = []
        elif roll < 0.995:
            status = "MANUAL_REVIEW"
            flags  = [rng.choice(["NAME_MATCH_PEP","FUZZY_MATCH_WATCHLIST",
                                   "COUNTRY_OF_BIRTH_RISK","COMMON_NAME_COLLISION"])]
        else:
            status = "HIT"
            flags  = ["DIRECT_MATCH_SANCTIONS_LIST"]

        return IntegrationResult(
            success          = True,
            provider_code    = self.provider_code,
            integration_type = self.integration_type,
            aml_status       = status,
            aml_flags        = flags,
            confidence_score = round(rng.uniform(0.93, 0.99), 2),
            raw_response     = {
                "status": status, "flags": flags,
                "screening_ref": f"AML{rng.randint(10000000,99999999)}",
                "lists_checked": ["OFAC","UN_CONSOLIDATED","EU_CONSOLIDATED",
                                   "RBI_DEFAULTER","INTERPOL","PEP_GLOBAL"],
            },
            notes            = "AML mock — integrate with LexisNexis/WorldCheck for production",
            expires_in_days  = 7,
        )


# ── Pharmacy Mock ─────────────────────────────────────────────────────────────
@register
class PharmacyMockProvider(IntegrationProvider):
    """
    Mock pharmacy database lookup.
    Checks prescription history for undisclosed conditions.
    Real providers: Practo, 1mg Rx, Apollo Pharmacy API
    """
    provider_code    = "PHARMACY_MOCK"
    integration_type = "PHARMACY"
    is_mock          = True

    _DRUG_MAP = {
        "Metformin":    {"condition": "Diabetes",      "risk_flag": "UNDISCLOSED_DIABETES"},
        "Amlodipine":   {"condition": "Hypertension",  "risk_flag": "UNDISCLOSED_HYPERTENSION"},
        "Atorvastatin": {"condition": "Dyslipidaemia", "risk_flag": "ELEVATED_LIPIDS"},
        "Clopidogrel":  {"condition": "Cardiac",       "risk_flag": "UNDISCLOSED_CARDIAC"},
        "Sertraline":   {"condition": "Depression",    "risk_flag": "UNDISCLOSED_DEPRESSION"},
        "Salbutamol":   {"condition": "Asthma/COPD",   "risk_flag": "UNDISCLOSED_RESPIRATORY"},
        "Warfarin":     {"condition": "Clotting disorder","risk_flag":"ANTICOAGULANT_USE"},
    }

    def verify(self, payload: dict) -> IntegrationResult:
        rng = _seed(payload.get("applicant_ref", ""), "pharmacy")
        diabetes = str(payload.get("diabetes_type","NONE")).upper()
        heart    = str(payload.get("heart_condition","NONE")).upper()

        drugs_found = []
        # 85% of the time, find nothing
        if rng.random() < 0.15:
            # Pick 1-2 random drugs
            candidates = list(self._DRUG_MAP.keys())
            count = rng.randint(1, 2)
            for drug in rng.sample(candidates, count):
                info = self._DRUG_MAP[drug]
                drugs_found.append({
                    "drug":       drug,
                    "condition":  info["condition"],
                    "risk_flag":  info["risk_flag"],
                    "last_filled": str(date.today() - timedelta(days=rng.randint(30, 365))),
                    "refills":    rng.randint(1, 12),
                })

        flags = [d["risk_flag"] for d in drugs_found]

        return IntegrationResult(
            success          = True,
            provider_code    = self.provider_code,
            integration_type = self.integration_type,
            raw_response     = {"drugs_found": drugs_found, "flags": flags},
            aml_status       = None,
            aml_flags        = flags,
            confidence_score = round(rng.uniform(0.88, 0.99), 2),
            notes            = (
                f"Pharmacy mock: {len(drugs_found)} prescription(s) found. "
                + ("Possible undisclosed conditions." if drugs_found else "No flags.")
            ),
            expires_in_days  = 30,
        )


# ── Driving Record Mock ───────────────────────────────────────────────────────
@register
class DrivingMockProvider(IntegrationProvider):
    """
    Mock driving record / licence verification.
    Real provider: Sarathi Parivahan API (MoRTH), VAHAN for vehicle data
    """
    provider_code    = "DRIVING_MOCK"
    integration_type = "DRIVING"
    is_mock          = True

    def verify(self, payload: dict) -> IntegrationResult:
        rng = _seed(payload.get("applicant_ref", ""), "driving")
        age = int(payload.get("age") or 35)

        licence_valid = rng.random() < 0.92
        dui_history   = rng.random() < 0.03
        violations    = rng.randint(0, 2) if not dui_history else rng.randint(1, 3)

        flags = []
        if dui_history:  flags.append("DUI_HISTORY")
        if violations > 1: flags.append(f"MULTIPLE_VIOLATIONS_{violations}")
        if not licence_valid: flags.append("LICENCE_EXPIRED_OR_INVALID")

        expiry_year = date.today().year + rng.randint(1, 5)
        expiry = date(expiry_year, rng.randint(1,12), rng.randint(1,28))

        return IntegrationResult(
            success          = True,
            provider_code    = self.provider_code,
            integration_type = self.integration_type,
            raw_response     = {
                "licence_number": f"MH{rng.randint(10,99)}20{rng.randint(10,24)}{rng.randint(100000,999999)}",
                "valid":          licence_valid,
                "expiry":         str(expiry) if licence_valid else None,
                "violations":     violations,
                "dui":            dui_history,
                "flags":          flags,
            },
            aml_flags        = flags,
            confidence_score = round(rng.uniform(0.90, 0.99), 2),
            notes            = "Driving mock — integrate with Sarathi Parivahan API for production",
            expires_in_days  = 90,
        )
