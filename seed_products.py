"""
scripts/admin/seed_products.py
────────────────────────────────
Seeds standard Indian life insurance products into RiskUW.

Usage:
    python scripts/admin/seed_products.py
    python scripts/admin/seed_products.py --dry-run
"""
from __future__ import annotations

import argparse
import json
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


PRODUCTS = [
    {
        "product_code":          "IND-TERM-20",
        "product_name":          "Individual Term Plan — 20 Year",
        "product_type":          "individual",
        "category":              "Individual Life",
        "uw_method":             "debit_points",
        "min_age":               18,
        "max_age":               60,
        "min_face_amount":       500000,
        "max_face_amount":       50000000,
        "available_terms":       json.dumps([20]),
        "exam_required":         False,
        "non_medical_limit":     2500000,
        "reinsurance_threshold": 5000000,
        "max_issue_age":         60,
        "stp_threshold":         50,
        "refer_threshold":       150,
        "decline_threshold":     300,
        "is_guaranteed_issue":   False,
        "is_group_product":      False,
        "description":           "Pure term life insurance plan with 20-year coverage. Non-participating.",
        "uw_notes":              "Standard debit point method. STP up to ₹25L for age < 40.",
        "is_active":             True,
    },
    {
        "product_code":          "IND-TERM-30",
        "product_name":          "Individual Term Plan — 30 Year",
        "product_type":          "individual",
        "category":              "Individual Life",
        "uw_method":             "debit_points",
        "min_age":               18,
        "max_age":               55,
        "min_face_amount":       500000,
        "max_face_amount":       50000000,
        "available_terms":       json.dumps([30]),
        "exam_required":         False,
        "non_medical_limit":     2000000,
        "reinsurance_threshold": 5000000,
        "max_issue_age":         55,
        "stp_threshold":         50,
        "refer_threshold":       150,
        "decline_threshold":     300,
        "is_guaranteed_issue":   False,
        "is_group_product":      False,
        "description":           "Pure term life insurance plan with 30-year coverage. Non-participating.",
        "uw_notes":              "Standard debit point method. Medical required above ₹20L.",
        "is_active":             True,
    },
    {
        "product_code":          "IND-ENDOW-20",
        "product_name":          "Individual Endowment Plan — 20 Year",
        "product_type":          "individual",
        "category":              "Individual Life",
        "uw_method":             "debit_points",
        "min_age":               18,
        "max_age":               55,
        "min_face_amount":       100000,
        "max_face_amount":       10000000,
        "available_terms":       json.dumps([20]),
        "exam_required":         False,
        "non_medical_limit":     1500000,
        "reinsurance_threshold": 5000000,
        "max_issue_age":         55,
        "stp_threshold":         50,
        "refer_threshold":       150,
        "decline_threshold":     300,
        "is_guaranteed_issue":   False,
        "is_group_product":      False,
        "description":           "Participating endowment plan with savings and risk cover. 20-year term.",
        "uw_notes":              "Bonus rates apply. Medical required above ₹15L.",
        "is_active":             True,
    },
    {
        "product_code":          "IND-WHOLELIFE",
        "product_name":          "Individual Whole Life Plan",
        "product_type":          "individual",
        "category":              "Individual Life",
        "uw_method":             "debit_points",
        "min_age":               18,
        "max_age":               55,
        "min_face_amount":       200000,
        "max_face_amount":       20000000,
        "available_terms":       json.dumps([99]),
        "exam_required":         True,
        "non_medical_limit":     1000000,
        "reinsurance_threshold": 5000000,
        "max_issue_age":         55,
        "stp_threshold":         25,
        "refer_threshold":       100,
        "decline_threshold":     200,
        "is_guaranteed_issue":   False,
        "is_group_product":      False,
        "description":           "Whole life participating plan. Coverage up to age 99.",
        "uw_notes":              "Stricter UW thresholds. Medical mandatory above ₹10L.",
        "is_active":             True,
    },
    {
        "product_code":          "GRP-TERM-1",
        "product_name":          "Group Term Life — Annual Renewable",
        "product_type":          "individual",
        "category":              "Group Life",
        "uw_method":             "debit_points",
        "min_age":               18,
        "max_age":               65,
        "min_face_amount":       100000,
        "max_face_amount":       100000000,
        "available_terms":       json.dumps([1]),
        "exam_required":         False,
        "non_medical_limit":     5000000,
        "reinsurance_threshold": 10000000,
        "max_issue_age":         65,
        "stp_threshold":         75,
        "refer_threshold":       175,
        "decline_threshold":     350,
        "is_guaranteed_issue":   False,
        "is_group_product":      True,
        "description":           "Annual renewable group term life plan for employer-employee schemes.",
        "uw_notes":              "Group UW applies. Individual evidence of insurability above free cover limit.",
        "is_active":             True,
    },
]


def seed(dry_run: bool = False) -> None:
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    print(f"Seeding {len(PRODUCTS)} products...\n")
    created = 0
    skipped = 0

    for p in PRODUCTS:
        cur.execute(
            "SELECT product_code FROM products WHERE product_code = %s",
            (p["product_code"],),
        )
        if cur.fetchone():
            print(f"   ⏭️   Skipping (exists): {p['product_code']} — {p['product_name']}")
            skipped += 1
            continue

        cur.execute(
            """
            INSERT INTO products (
                product_code, product_name, product_type, category,
                uw_method, min_age, max_age, min_face_amount, max_face_amount,
                available_terms, exam_required, non_medical_limit,
                reinsurance_threshold, max_issue_age,
                stp_threshold, refer_threshold, decline_threshold,
                is_guaranteed_issue, is_group_product,
                description, uw_notes, is_active
            ) VALUES (
                %(product_code)s, %(product_name)s, %(product_type)s, %(category)s,
                %(uw_method)s, %(min_age)s, %(max_age)s, %(min_face_amount)s, %(max_face_amount)s,
                %(available_terms)s, %(exam_required)s, %(non_medical_limit)s,
                %(reinsurance_threshold)s, %(max_issue_age)s,
                %(stp_threshold)s, %(refer_threshold)s, %(decline_threshold)s,
                %(is_guaranteed_issue)s, %(is_group_product)s,
                %(description)s, %(uw_notes)s, %(is_active)s
            )
            """,
            p,
        )
        print(f"   ✅  Created: {p['product_code']} — {p['product_name']}")
        created += 1

    if dry_run:
        print(f"\n🔍  DRY RUN — rolling back. Would create {created} products.")
        conn.rollback()
    else:
        conn.commit()
        print(f"\n🎉  Done — {created} products created, {skipped} skipped.")

    cur.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Seed demo products for RiskUW")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass

    seed(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
