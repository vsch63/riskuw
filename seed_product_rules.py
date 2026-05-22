"""
scripts/admin/seed_product_rules.py
─────────────────────────────────────
Seeds standard UW rules into product_rules for all active products.

Usage:
    python scripts/admin/seed_product_rules.py
    python scripts/admin/seed_product_rules.py --product-code IND-TERM-20
    python scripts/admin/seed_product_rules.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

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


# ── Standard rule definitions ─────────────────────────────────────────────────
# These map to the hardcoded rules in underwriting.py _fallback_evaluate()
# rule_id must match what the engine uses

STANDARD_RULES = [
    # ── Age loadings ──────────────────────────────────────────────────────────
    {"rule_id": "R001", "rule_name": "Age Loading 46–55",           "category": "AGE",       "default_debit": 15,  "is_enabled": True},
    {"rule_id": "R002", "rule_name": "Age Loading 56+",             "category": "AGE",       "default_debit": 30,  "is_enabled": True},

    # ── Tobacco / Lifestyle ───────────────────────────────────────────────────
    {"rule_id": "R005", "rule_name": "Tobacco / Smoker Loading",    "category": "LIFESTYLE", "default_debit": 50,  "is_enabled": True},
    {"rule_id": "R040", "rule_name": "Heavy Alcohol Use",           "category": "LIFESTYLE", "default_debit": 50,  "is_enabled": True},
    {"rule_id": "R045", "rule_name": "Hazardous Activity",          "category": "LIFESTYLE", "default_debit": 30,  "is_enabled": True},

    # ── Build / BMI ───────────────────────────────────────────────────────────
    {"rule_id": "R010", "rule_name": "Elevated BMI (30–35)",        "category": "BUILD",     "default_debit": 25,  "is_enabled": True},
    {"rule_id": "R011", "rule_name": "Elevated BMI (>35)",          "category": "BUILD",     "default_debit": 75,  "is_enabled": True},

    # ── Medical ───────────────────────────────────────────────────────────────
    {"rule_id": "R015", "rule_name": "Diabetes Type 2",             "category": "MEDICAL",   "default_debit": 50,  "is_enabled": True},
    {"rule_id": "R016", "rule_name": "Diabetes Type 1",             "category": "MEDICAL",   "default_debit": 100, "is_enabled": True},
    {"rule_id": "R020", "rule_name": "Cardiac Event < 2 years",     "category": "MEDICAL",   "default_debit": 125, "is_enabled": True},
    {"rule_id": "R021", "rule_name": "Cardiac Event 2–5 years",     "category": "MEDICAL",   "default_debit": 75,  "is_enabled": True},
    {"rule_id": "R022", "rule_name": "Cardiac Event > 5 years",     "category": "MEDICAL",   "default_debit": 40,  "is_enabled": True},
    {"rule_id": "R025", "rule_name": "Stage 2 Hypertension",        "category": "MEDICAL",   "default_debit": 25,  "is_enabled": True},
    {"rule_id": "R026", "rule_name": "Uncontrolled Hypertension",   "category": "MEDICAL",   "default_debit": 50,  "is_enabled": True},
    {"rule_id": "R030", "rule_name": "Stroke History",              "category": "MEDICAL",   "default_debit": 75,  "is_enabled": True},
    {"rule_id": "R031", "rule_name": "Kidney Disease",              "category": "MEDICAL",   "default_debit": 75,  "is_enabled": True},
    {"rule_id": "R032", "rule_name": "Depression — Hospitalized",   "category": "MEDICAL",   "default_debit": 75,  "is_enabled": True},
    {"rule_id": "R033", "rule_name": "Depression — Outpatient",     "category": "MEDICAL",   "default_debit": 25,  "is_enabled": True},
    {"rule_id": "R034", "rule_name": "Epilepsy / Seizure Disorder", "category": "MEDICAL",   "default_debit": 50,  "is_enabled": True},
    {"rule_id": "R035", "rule_name": "COPD / Emphysema",            "category": "MEDICAL",   "default_debit": 75,  "is_enabled": True},

    # ── Family history ────────────────────────────────────────────────────────
    {"rule_id": "R050", "rule_name": "Family History — CVD < 60",   "category": "FAMILY",    "default_debit": 15,  "is_enabled": True},
    {"rule_id": "R051", "rule_name": "Family History — Stroke < 65","category": "FAMILY",    "default_debit": 15,  "is_enabled": True},
    {"rule_id": "R052", "rule_name": "Family History — Cancer",     "category": "FAMILY",    "default_debit": 10,  "is_enabled": True},
    {"rule_id": "R053", "rule_name": "Family History — Diabetes",   "category": "FAMILY",    "default_debit": 10,  "is_enabled": True},

    # ── Hard stops (debit=999 flags instant decline) ──────────────────────────
    {"rule_id": "R100", "rule_name": "HIV Positive — Hard Stop",    "category": "HARD_STOP", "default_debit": 999, "is_enabled": True},
    {"rule_id": "R101", "rule_name": "Liver Cirrhosis — Hard Stop", "category": "HARD_STOP", "default_debit": 999, "is_enabled": True},
    {"rule_id": "R102", "rule_name": "2+ DUI/DWI in 5 Years",      "category": "HARD_STOP", "default_debit": 999, "is_enabled": True},
    {"rule_id": "R103", "rule_name": "Declined Occupation Class",   "category": "HARD_STOP", "default_debit": 999, "is_enabled": True},
    {"rule_id": "R104", "rule_name": "Age Outside Product Range",   "category": "HARD_STOP", "default_debit": 999, "is_enabled": True},

    # ── Driving ───────────────────────────────────────────────────────────────
    {"rule_id": "R060", "rule_name": "Major Traffic Violation",     "category": "DRIVING",   "default_debit": 25,  "is_enabled": True},
    {"rule_id": "R061", "rule_name": "At-Fault Accident",           "category": "DRIVING",   "default_debit": 15,  "is_enabled": True},
    {"rule_id": "R062", "rule_name": "License Suspended",           "category": "DRIVING",   "default_debit": 50,  "is_enabled": True},
]


def seed(product_code: str | None = None, dry_run: bool = False) -> None:
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    # Get products to seed
    if product_code:
        cur.execute("SELECT product_code FROM products WHERE product_code=%s", (product_code,))
    else:
        cur.execute("SELECT product_code FROM products WHERE is_active=true ORDER BY product_code")

    products = [r["product_code"] for r in cur.fetchall()]

    if not products:
        print("❌  No products found. Run seed_products.py first.")
        sys.exit(1)

    print(f"Seeding {len(STANDARD_RULES)} rules for {len(products)} product(s)...\n")
    total_created = 0
    total_skipped = 0

    for pcode in products:
        created = 0
        skipped = 0
        for rule in STANDARD_RULES:
            cur.execute(
                "SELECT id FROM product_rules WHERE product_code=%s AND rule_id=%s",
                (pcode, rule["rule_id"]),
            )
            if cur.fetchone():
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO product_rules
                    (product_code, rule_id, is_enabled,
                     debit_points_override, debit_override_active,
                     flat_extra_override, flat_extra_override_active)
                VALUES (%s, %s, %s, NULL, false, NULL, false)
                """,
                (pcode, rule["rule_id"], rule["is_enabled"]),
            )
            created += 1

        print(f"   {'✅' if created > 0 else '⏭️ '} {pcode:<20} — {created} created, {skipped} skipped")
        total_created += created
        total_skipped += skipped

    if dry_run:
        print(f"\n🔍  DRY RUN — rolling back. Would create {total_created} rule rows.")
        conn.rollback()
    else:
        conn.commit()
        print(f"\n🎉  Done — {total_created} rules created, {total_skipped} already existed.")
        print(f"\n   Refresh Product Config → Rules & Overrides to see them.")

    cur.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Seed standard UW rules for RiskUW products")
    ap.add_argument("--product-code", default=None, help="Seed a single product only")
    ap.add_argument("--dry-run",      action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass

    seed(product_code=args.product_code, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
