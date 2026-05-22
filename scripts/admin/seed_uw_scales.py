"""
scripts/admin/seed_uw_scales.py
────────────────────────────────
Seeds standard UW debit point scales and premium rate scales
for Indian life insurance underwriting.

Usage:
    python scripts/admin/seed_uw_scales.py --tenant-id <UUID>
    python scripts/admin/seed_uw_scales.py --tenant-id <UUID> --dry-run

Scales created:
  UW Scales (Debit Points):
    1. Standard Mortality Debit Scale
    2. BMI / Build Debit Scale
    3. Blood Pressure Debit Scale
    4. Smoker Loading Scale
    5. Occupation Hazard Scale
    6. Family History Debit Scale

  Premium Rate Scales:
    7. Term Plan Premium Rate Scale (Rate per ₹1,000 SA)
    8. Endowment Plan Premium Rate Scale (Rate per ₹1,000 SA)
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date

import psycopg2
import psycopg2.extras


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "riskuw")
    user = os.environ.get("DB_USER", "uw_user")
    pwd  = os.environ.get("DB_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


# ── Scale definitions ─────────────────────────────────────────────────────────

TODAY      = date.today().isoformat()
OPEN_END   = None   # open-ended tranche

SCALES = [

    # ══════════════════════════════════════════════════════════
    # 1. STANDARD MORTALITY DEBIT SCALE
    #    Age-based mortality loading for standard lives
    # ══════════════════════════════════════════════════════════
    {
        "name":        "Standard Mortality Debit Scale",
        "description": "Age-based mortality debit points for standard non-smoker male lives. Used as base UW score.",
        "scale_type":  "UW",
        "premium_output_type": None,
        "tranches": [
            {
                "description":       "Standard Male Non-Smoker",
                "effective_date":    TODAY,
                "expiry_date":       OPEN_END,
                "parameter_logic":   "AND",
                "parameters": [
                    {"parameter_name": "gender",  "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                    {"parameter_name": "smoker",  "parameter_type": "DISCRETE", "min_value": 0,  "max_value": 0},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value":  0},
                    {"age_from": 26, "age_to": 30, "value":  5},
                    {"age_from": 31, "age_to": 35, "value": 10},
                    {"age_from": 36, "age_to": 40, "value": 20},
                    {"age_from": 41, "age_to": 45, "value": 35},
                    {"age_from": 46, "age_to": 50, "value": 50},
                    {"age_from": 51, "age_to": 55, "value": 75},
                    {"age_from": 56, "age_to": 60, "value": 100},
                    {"age_from": 61, "age_to": 65, "value": 150},
                ],
            },
            {
                "description":       "Standard Female Non-Smoker",
                "effective_date":    TODAY,
                "expiry_date":       OPEN_END,
                "parameter_logic":   "AND",
                "parameters": [
                    {"parameter_name": "gender",  "parameter_type": "DISCRETE", "min_value": 2,  "max_value": 2},
                    {"parameter_name": "smoker",  "parameter_type": "DISCRETE", "min_value": 0,  "max_value": 0},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value":  0},
                    {"age_from": 26, "age_to": 30, "value":  0},
                    {"age_from": 31, "age_to": 35, "value":  5},
                    {"age_from": 36, "age_to": 40, "value": 15},
                    {"age_from": 41, "age_to": 45, "value": 25},
                    {"age_from": 46, "age_to": 50, "value": 40},
                    {"age_from": 51, "age_to": 55, "value": 60},
                    {"age_from": 56, "age_to": 60, "value": 85},
                    {"age_from": 61, "age_to": 65, "value": 125},
                ],
            },
            {
                "description":       "Standard Male Smoker",
                "effective_date":    TODAY,
                "expiry_date":       OPEN_END,
                "parameter_logic":   "AND",
                "parameters": [
                    {"parameter_name": "gender",  "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                    {"parameter_name": "smoker",  "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value": 25},
                    {"age_from": 26, "age_to": 30, "value": 35},
                    {"age_from": 31, "age_to": 35, "value": 50},
                    {"age_from": 36, "age_to": 40, "value": 75},
                    {"age_from": 41, "age_to": 45, "value": 100},
                    {"age_from": 46, "age_to": 50, "value": 125},
                    {"age_from": 51, "age_to": 55, "value": 150},
                    {"age_from": 56, "age_to": 60, "value": 200},
                    {"age_from": 61, "age_to": 65, "value": 250},
                ],
            },
            {
                "description":       "Standard Female Smoker",
                "effective_date":    TODAY,
                "expiry_date":       OPEN_END,
                "parameter_logic":   "AND",
                "parameters": [
                    {"parameter_name": "gender",  "parameter_type": "DISCRETE", "min_value": 2,  "max_value": 2},
                    {"parameter_name": "smoker",  "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value": 20},
                    {"age_from": 26, "age_to": 30, "value": 25},
                    {"age_from": 31, "age_to": 35, "value": 40},
                    {"age_from": 36, "age_to": 40, "value": 60},
                    {"age_from": 41, "age_to": 45, "value": 80},
                    {"age_from": 46, "age_to": 50, "value": 100},
                    {"age_from": 51, "age_to": 55, "value": 125},
                    {"age_from": 56, "age_to": 60, "value": 160},
                    {"age_from": 61, "age_to": 65, "value": 200},
                ],
            },
        ],
    },

    # ══════════════════════════════════════════════════════════
    # 2. BMI / BUILD DEBIT SCALE
    #    Extra debit for overweight / underweight lives
    # ══════════════════════════════════════════════════════════
    {
        "name":        "BMI / Build Debit Scale",
        "description": "Debit points based on Body Mass Index (BMI). Applied on top of base mortality scale.",
        "scale_type":  "UW",
        "premium_output_type": None,
        "tranches": [
            {
                "description":     "Underweight (BMI < 17.5)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bmi", "parameter_type": "RANGE", "min_value": 10.0, "max_value": 17.4},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 50},
                    {"age_from": 36, "age_to": 50, "value": 75},
                    {"age_from": 51, "age_to": 65, "value": 100},
                ],
            },
            {
                "description":     "Normal BMI (17.5 – 24.9) — No loading",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bmi", "parameter_type": "RANGE", "min_value": 17.5, "max_value": 24.9},
                ],
                "details": [
                    {"age_from": 18, "age_to": 65, "value": 0},
                ],
            },
            {
                "description":     "Overweight (BMI 25 – 29.9)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bmi", "parameter_type": "RANGE", "min_value": 25.0, "max_value": 29.9},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 25},
                    {"age_from": 36, "age_to": 50, "value": 50},
                    {"age_from": 51, "age_to": 65, "value": 75},
                ],
            },
            {
                "description":     "Obese Class I (BMI 30 – 34.9)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bmi", "parameter_type": "RANGE", "min_value": 30.0, "max_value": 34.9},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 75},
                    {"age_from": 36, "age_to": 50, "value": 100},
                    {"age_from": 51, "age_to": 65, "value": 150},
                ],
            },
            {
                "description":     "Obese Class II+ (BMI ≥ 35)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bmi", "parameter_type": "RANGE", "min_value": 35.0, "max_value": 70.0},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 150},
                    {"age_from": 36, "age_to": 50, "value": 200},
                    {"age_from": 51, "age_to": 65, "value": 250},
                ],
            },
        ],
    },

    # ══════════════════════════════════════════════════════════
    # 3. BLOOD PRESSURE DEBIT SCALE
    #    Systolic BP loading
    # ══════════════════════════════════════════════════════════
    {
        "name":        "Blood Pressure Debit Scale",
        "description": "Debit points for elevated systolic blood pressure readings. Assumes controlled/uncontrolled BP.",
        "scale_type":  "UW",
        "premium_output_type": None,
        "tranches": [
            {
                "description":     "Normal BP (Systolic < 130 mmHg)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bp_systolic", "parameter_type": "RANGE", "min_value": 70, "max_value": 129},
                ],
                "details": [
                    {"age_from": 18, "age_to": 65, "value": 0},
                ],
            },
            {
                "description":     "Elevated BP (Systolic 130–139 mmHg)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bp_systolic", "parameter_type": "RANGE", "min_value": 130, "max_value": 139},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 25},
                    {"age_from": 36, "age_to": 50, "value": 50},
                    {"age_from": 51, "age_to": 65, "value": 75},
                ],
            },
            {
                "description":     "Stage 1 Hypertension (Systolic 140–159 mmHg)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bp_systolic", "parameter_type": "RANGE", "min_value": 140, "max_value": 159},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 75},
                    {"age_from": 36, "age_to": 50, "value": 100},
                    {"age_from": 51, "age_to": 65, "value": 125},
                ],
            },
            {
                "description":     "Stage 2 Hypertension (Systolic 160–179 mmHg)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bp_systolic", "parameter_type": "RANGE", "min_value": 160, "max_value": 179},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 125},
                    {"age_from": 36, "age_to": 50, "value": 175},
                    {"age_from": 51, "age_to": 65, "value": 225},
                ],
            },
            {
                "description":     "Severe Hypertension (Systolic ≥ 180 mmHg)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "bp_systolic", "parameter_type": "RANGE", "min_value": 180, "max_value": 300},
                ],
                "details": [
                    {"age_from": 18, "age_to": 65, "value": 300},
                ],
            },
        ],
    },

    # ══════════════════════════════════════════════════════════
    # 4. OCCUPATION HAZARD SCALE
    #    Debit points by occupation class
    # ══════════════════════════════════════════════════════════
    {
        "name":        "Occupation Hazard Debit Scale",
        "description": "Debit points based on occupational risk class. Class 1=lowest risk (professional/office), Class 4=highest risk (hazardous).",
        "scale_type":  "UW",
        "premium_output_type": None,
        "tranches": [
            {
                "description":     "Class 1 — Professional / Office / Sedentary",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "occupation_class", "parameter_type": "DISCRETE", "min_value": 1, "max_value": 1},
                ],
                "details": [
                    {"age_from": 18, "age_to": 65, "value": 0},
                ],
            },
            {
                "description":     "Class 2 — Light Manual / Supervisory",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "occupation_class", "parameter_type": "DISCRETE", "min_value": 2, "max_value": 2},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 25},
                    {"age_from": 36, "age_to": 50, "value": 25},
                    {"age_from": 51, "age_to": 65, "value": 50},
                ],
            },
            {
                "description":     "Class 3 — Skilled Manual / Field Work",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "occupation_class", "parameter_type": "DISCRETE", "min_value": 3, "max_value": 3},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 50},
                    {"age_from": 36, "age_to": 50, "value": 75},
                    {"age_from": 51, "age_to": 65, "value": 100},
                ],
            },
            {
                "description":     "Class 4 — Hazardous / Mining / Construction",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "occupation_class", "parameter_type": "DISCRETE", "min_value": 4, "max_value": 4},
                ],
                "details": [
                    {"age_from": 18, "age_to": 35, "value": 100},
                    {"age_from": 36, "age_to": 50, "value": 150},
                    {"age_from": 51, "age_to": 65, "value": 200},
                ],
            },
        ],
    },

    # ══════════════════════════════════════════════════════════
    # 5. FAMILY HISTORY DEBIT SCALE
    #    Loading for adverse family history
    # ══════════════════════════════════════════════════════════
    {
        "name":        "Family History Debit Scale",
        "description": "Debit points for adverse family history (parents/siblings with heart disease, cancer, diabetes before age 60).",
        "scale_type":  "UW",
        "premium_output_type": None,
        "tranches": [
            {
                "description":     "No Adverse Family History",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "family_history", "parameter_type": "DISCRETE", "min_value": 0, "max_value": 0},
                ],
                "details": [
                    {"age_from": 18, "age_to": 65, "value": 0},
                ],
            },
            {
                "description":     "Adverse Family History Present",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "family_history", "parameter_type": "DISCRETE", "min_value": 1, "max_value": 1},
                ],
                "details": [
                    {"age_from": 18, "age_to": 30, "value": 25},
                    {"age_from": 31, "age_to": 40, "value": 50},
                    {"age_from": 41, "age_to": 50, "value": 75},
                    {"age_from": 51, "age_to": 65, "value": 100},
                ],
            },
        ],
    },

    # ══════════════════════════════════════════════════════════
    # 6. TERM PLAN PREMIUM RATE SCALE
    #    Rate per ₹1,000 SA — Standard Indian term rates
    # ══════════════════════════════════════════════════════════
    {
        "name":        "Term Plan Premium Rate Scale 2024",
        "description": "Standard premium rates per ₹1,000 Sum Assured for term insurance. Non-smoker male rates — 20-year term.",
        "scale_type":  "PREMIUM",
        "premium_output_type": "RATE_PER_THOUSAND",
        "tranches": [
            {
                "description":     "Male Non-Smoker — 20 Year Term",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "gender",      "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                    {"parameter_name": "smoker",      "parameter_type": "DISCRETE", "min_value": 0,  "max_value": 0},
                    {"parameter_name": "policy_term", "parameter_type": "DISCRETE", "min_value": 20, "max_value": 20},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value": 0.85},
                    {"age_from": 26, "age_to": 30, "value": 1.10},
                    {"age_from": 31, "age_to": 35, "value": 1.55},
                    {"age_from": 36, "age_to": 40, "value": 2.30},
                    {"age_from": 41, "age_to": 45, "value": 3.75},
                    {"age_from": 46, "age_to": 50, "value": 5.90},
                    {"age_from": 51, "age_to": 55, "value": 9.20},
                    {"age_from": 56, "age_to": 60, "value": 14.50},
                ],
            },
            {
                "description":     "Female Non-Smoker — 20 Year Term",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "gender",      "parameter_type": "DISCRETE", "min_value": 2,  "max_value": 2},
                    {"parameter_name": "smoker",      "parameter_type": "DISCRETE", "min_value": 0,  "max_value": 0},
                    {"parameter_name": "policy_term", "parameter_type": "DISCRETE", "min_value": 20, "max_value": 20},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value": 0.65},
                    {"age_from": 26, "age_to": 30, "value": 0.85},
                    {"age_from": 31, "age_to": 35, "value": 1.20},
                    {"age_from": 36, "age_to": 40, "value": 1.80},
                    {"age_from": 41, "age_to": 45, "value": 2.90},
                    {"age_from": 46, "age_to": 50, "value": 4.50},
                    {"age_from": 51, "age_to": 55, "value": 7.10},
                    {"age_from": 56, "age_to": 60, "value": 11.20},
                ],
            },
            {
                "description":     "Male Smoker — 20 Year Term",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "gender",      "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                    {"parameter_name": "smoker",      "parameter_type": "DISCRETE", "min_value": 1,  "max_value": 1},
                    {"parameter_name": "policy_term", "parameter_type": "DISCRETE", "min_value": 20, "max_value": 20},
                ],
                "details": [
                    {"age_from": 18, "age_to": 25, "value": 1.40},
                    {"age_from": 26, "age_to": 30, "value": 1.90},
                    {"age_from": 31, "age_to": 35, "value": 2.75},
                    {"age_from": 36, "age_to": 40, "value": 4.10},
                    {"age_from": 41, "age_to": 45, "value": 6.50},
                    {"age_from": 46, "age_to": 50, "value": 10.20},
                    {"age_from": 51, "age_to": 55, "value": 15.80},
                    {"age_from": 56, "age_to": 60, "value": 24.50},
                ],
            },
        ],
    },

    # ══════════════════════════════════════════════════════════
    # 7. SUBSTANDARD LIFE MULTIPLIER SCALE
    #    Multiplier for rated-up lives
    # ══════════════════════════════════════════════════════════
    {
        "name":        "Substandard Life Premium Multiplier Scale",
        "description": "Premium multiplier for substandard lives based on total debit points. Applied after base premium calculation.",
        "scale_type":  "PREMIUM",
        "premium_output_type": "MULTIPLIER",
        "tranches": [
            {
                "description":     "Standard Risk (0–50 debit points)",
                "effective_date":  TODAY,
                "expiry_date":     OPEN_END,
                "parameter_logic": "AND",
                "parameters": [
                    {"parameter_name": "sum_assured", "parameter_type": "RANGE", "min_value": 0, "max_value": 99999999},
                ],
                "details": [
                    {"age_from": 18, "age_to": 65, "value": 1.00},
                ],
            },
        ],
    },

]


# ── Seed function ─────────────────────────────────────────────────────────────
def seed(tenant_id: str, dry_run: bool = False) -> None:
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    # Verify tenant
    cur.execute("SELECT tenant_name FROM tenant WHERE id=%s::uuid", (tenant_id,))
    t = cur.fetchone()
    if not t:
        print(f"❌  Tenant {tenant_id!r} not found.", file=sys.stderr)
        sys.exit(1)
    print(f"✅  Tenant: {t['tenant_name']}")
    print()

    created = 0
    skipped = 0

    for scale_def in SCALES:
        # Check if scale already exists by name + tenant
        cur.execute(
            "SELECT id FROM uw_rate_scale WHERE name=%s AND tenant_id=%s::uuid",
            (scale_def["name"], tenant_id),
        )
        existing = cur.fetchone()
        if existing:
            print(f"⏭️   Skipping (already exists): {scale_def['name']}")
            skipped += 1
            continue

        scale_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO uw_rate_scale
                (id, tenant_id, name, description, scale_type,
                 premium_output_type, is_active, created_by, updated_by)
            VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,true,'seed_script','seed_script')
            """,
            (
                scale_id, tenant_id,
                scale_def["name"], scale_def["description"],
                scale_def["scale_type"], scale_def["premium_output_type"],
            ),
        )

        for ti, tranche in enumerate(scale_def["tranches"]):
            tranche_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO uw_scale_tranche
                    (id, scale_id, description, effective_date,
                     expiry_date, parameter_logic, sort_order)
                VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
                """,
                (
                    tranche_id, scale_id,
                    tranche["description"],
                    tranche["effective_date"],
                    tranche["expiry_date"],
                    tranche["parameter_logic"],
                    ti,
                ),
            )

            for pi, p in enumerate(tranche["parameters"]):
                cur.execute(
                    """
                    INSERT INTO uw_tranche_parameter
                        (id, tranche_id, parameter_name, parameter_type,
                         min_value, max_value, sort_order)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
                    """,
                    (
                        str(uuid.uuid4()), tranche_id,
                        p["parameter_name"], p["parameter_type"],
                        p["min_value"], p["max_value"], pi,
                    ),
                )

            for di, d in enumerate(tranche["details"]):
                cur.execute(
                    """
                    INSERT INTO uw_tranche_detail
                        (id, tranche_id, age_from, age_to, value, sort_order)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s)
                    """,
                    (
                        str(uuid.uuid4()), tranche_id,
                        d["age_from"], d["age_to"], d["value"], di,
                    ),
                )

        tranches_count = len(scale_def["tranches"])
        print(f"   ✅  {scale_def['scale_type']:7s} | {scale_def['name']}  ({tranches_count} tranches)")
        created += 1

    if dry_run:
        print(f"\n🔍  DRY RUN — rolling back. Would create {created} scales.")
        conn.rollback()
    else:
        conn.commit()
        print(f"\n🎉  Done — {created} scales created, {skipped} skipped (already existed).")
        print(f"\n   Go to System Config → UW Scales to view them.")

    cur.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Seed standard UW scales for RiskUW")
    ap.add_argument("--tenant-id", required=True, help="Tenant UUID")
    ap.add_argument("--dry-run",   action="store_true", help="Preview without committing")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass

    seed(args.tenant_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

