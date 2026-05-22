#!/usr/bin/env python3
"""
scripts/db/seed_demo_data.py
──────────────────────────────
Seeds realistic demo data for carrier pitches:
  • 8 life insurance products  (product table)
  • product_decision_thresholds for each
  • 25 sample decisions spread across APPROVED / REFERRED / DECLINED
  • 1 reinsurer (SCOR Re India) with ₹50L retention
  • Demo applicant records

Run AFTER create_tenant.py.

Usage:
    python scripts/db/seed_demo_data.py --tenant-id <UUID>
    python scripts/db/seed_demo_data.py --tenant-id <UUID> --dry-run
    python scripts/db/seed_demo_data.py --tenant-id <UUID> --wipe   # clear existing demo data first
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, date
import random

import psycopg2
import psycopg2.extras

random.seed(42)  # reproducible demo data

# ── Products ──────────────────────────────────────────────────────────────────
DEMO_PRODUCTS = [
    dict(code="IND-TERM-20", name="IndiaFirst Term 20",    cat="Term Life",     sub="Term",        min_age=18, max_age=65, min_face=500_000,   max_face=50_000_000, is_gi=False, uw="Full UW",    exam="Exam required for SA > ₹1Cr", terms=[20]),
    dict(code="IND-TERM-30", name="IndiaFirst Term 30",    cat="Term Life",     sub="Term",        min_age=18, max_age=55, min_face=500_000,   max_face=50_000_000, is_gi=False, uw="Full UW",    exam="Exam + ECG for age 45+",      terms=[30]),
    dict(code="BSLI-END-10", name="BSLI Endowment 10yr",  cat="Endowment",     sub="Endowment",   min_age=18, max_age=65, min_face=100_000,   max_face=10_000_000, is_gi=False, uw="Simplified", exam="Medical for SA > ₹25L",       terms=[10, 15]),
    dict(code="IND-UL-100",  name="IndiaFirst UL 100",     cat="Universal Life",sub="UL",          min_age=18, max_age=70, min_face=500_000,   max_face=100_000_000,is_gi=False, uw="Full UW",    exam="Full exam + labs required",   terms=[]),
    dict(code="IND-GI-FE",   name="IndiaFirst Final Exp.", cat="Final Expense", sub="Final Exp",   min_age=45, max_age=80, min_face=50_000,    max_face=500_000,    is_gi=True,  uw="Guaranteed", exam="No medical underwriting",     terms=[]),
    dict(code="IND-GRP-BASIC", name="IndiaFirst Group Basic",   cat="Group",         sub="Group Basic", min_age=18, max_age=70, min_face=100_000,   max_face=5_000_000,  is_gi=False, uw="Group UW",   exam="Group scheme — no individual exam", terms=[1]),
    dict(code="IND-KEYMAN",  name="IndiaFirst Key Person", cat="Key Person",    sub="Key Person",  min_age=18, max_age=65, min_face=1_000_000, max_face=100_000_000,is_gi=False, uw="Full UW",    exam="Full financial + medical",    terms=[5, 10, 20]),
    dict(code="IND-WL-65",   name="IndiaFirst Whole Life", cat="Whole Life",    sub="Whole Life",  min_age=18, max_age=65, min_face=200_000,   max_face=20_000_000, is_gi=False, uw="Full UW",    exam="Comprehensive medical",       terms=[]),
]

SAMPLE_DECISIONS = [
    # (applicant_ref, product_code, age, gender, face, outcome, risk_class, debit_pts, is_stp)
    ("APP-D-001", "IND-TERM-20", 32, "MALE",   1_000_000, "APPROVED_STP",       "STANDARD",    25, True),
    ("APP-D-002", "IND-TERM-20", 45, "FEMALE", 2_500_000, "APPROVED_STP",       "STANDARD",    40, True),
    ("APP-D-003", "IND-TERM-20", 38, "MALE",   5_000_000, "REFERRED",           "SUBSTANDARD", 95, False),
    ("APP-D-004", "IND-TERM-30", 28, "FEMALE", 1_000_000, "APPROVED_STP",       "PREFERRED",   10, True),
    ("APP-D-005", "BSLI-END-10", 50, "MALE",   500_000,   "APPROVED_STP",       "STANDARD",    55, True),
    ("APP-D-006", "BSLI-END-10", 55, "MALE",   800_000,   "REFERRED",           "SUBSTANDARD", 120, False),
    ("APP-D-007", "IND-TERM-20", 42, "MALE",   3_000_000, "DECLINED",           "DECLINE",     220, False),
    ("APP-D-008", "IND-UL-100",  35, "FEMALE", 10_000_000,"REFERRED",           "STANDARD",    80, False),
    ("APP-D-009", "IND-GRP-BASIC",30,"MALE",   500_000,   "APPROVED_STP",       "STANDARD",    20, True),
    ("APP-D-010", "IND-TERM-20", 60, "MALE",   2_000_000, "DECLINED",           "DECLINE",     195, False),
    ("APP-D-011", "IND-TERM-20", 29, "FEMALE", 1_500_000, "APPROVED_STP",       "PREFERRED",   15, True),
    ("APP-D-012", "IND-KEYMAN",  44, "MALE",   25_000_000,"REFERRED",           "STANDARD",    60, False),
    ("APP-D-013", "IND-WL-65",   40, "MALE",   1_000_000, "APPROVED_RATED",     "TABLE_2",     100, False),
    ("APP-D-014", "IND-TERM-30", 33, "FEMALE", 2_000_000, "APPROVED_STP",       "STANDARD",    30, True),
    ("APP-D-015", "BSLI-END-10", 48, "FEMALE", 300_000,   "APPROVED_STP",       "STANDARD",    45, True),
    ("APP-D-016", "IND-TERM-20", 36, "MALE",   7_500_000, "REFERRED",           "SUBSTANDARD", 110, False),
    ("APP-D-017", "IND-GI-FE",   68, "FEMALE", 200_000,   "APPROVED_STP",       "STANDARD",    0,  True),
    ("APP-D-018", "IND-TERM-20", 51, "MALE",   1_000_000, "POSTPONED",          "POSTPONE",    160, False),
    ("APP-D-019", "IND-UL-100",  27, "FEMALE", 5_000_000, "APPROVED_STP",       "PREFERRED",   20, True),
    ("APP-D-020", "IND-TERM-20", 43, "MALE",   1_000_000, "APPROVED_RATED",     "TABLE_4",     130, False),
    ("APP-D-021", "IND-KEYMAN",  39, "MALE",   50_000_000,"REFERRED",           "STANDARD",    50, False),
    ("APP-D-022", "IND-WL-65",   55, "FEMALE", 500_000,   "DECLINED",           "DECLINE",     200, False),
    ("APP-D-023", "IND-TERM-20", 31, "MALE",   2_000_000, "APPROVED_STP",       "STANDARD",    35, True),
    ("APP-D-024", "BSLI-END-10", 42, "MALE",   1_000_000, "APPROVED_STP",       "STANDARD",    50, True),
    ("APP-D-025", "IND-TERM-30", 37, "FEMALE", 3_000_000, "REFERRED",           "SUBSTANDARD", 105, False),
]


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


def seed(tenant_id: str, wipe: bool = False, dry_run: bool = False):
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Validate tenant
        cur.execute("SELECT tenant_name FROM tenant WHERE id=%s::uuid", (tenant_id,))
        t = cur.fetchone()
        if not t:
            print(f"❌  Tenant {tenant_id!r} not found.", file=sys.stderr)
            sys.exit(1)
        print(f"🏢  Seeding demo data for tenant: {t['tenant_name']}")

        if wipe:
            print("🗑️   Wiping existing demo data…")
            cur.execute("DELETE FROM batch_job_records WHERE applicant_ref LIKE 'APP-D-%'")
            cur.execute("DELETE FROM policy_admin_queue WHERE applicant_ref LIKE 'APP-D-%'")
            cur.execute("DELETE FROM product_decision_thresholds WHERE tenant_id=%s::uuid", (tenant_id,))
            cur.execute("DELETE FROM product WHERE tenant_id=%s::uuid", (tenant_id,))
            cur.execute("DELETE FROM ri_reinsurer WHERE reinsurer_code='SCOR-IN'")

        # ── Products ──────────────────────────────────────────────────
        print("\n📦  Inserting products…")
        for p in DEMO_PRODUCTS:
            cur.execute(
                """
                INSERT INTO product
                    (id, tenant_id, product_code, product_name, category,
                     sub_type, uw_method, min_age, max_age,
                     min_face, max_face, is_active, is_gi, effective_date)
                VALUES
                    (gen_random_uuid(), %s::uuid, %s, %s, %s,
                     %s, %s, %s, %s,
                     %s, %s, true, %s, now())
                ON CONFLICT DO NOTHING
                """,
                (
                    tenant_id, p["code"], p["name"], p["cat"],
                    p["sub"], p["uw"], p["min_age"], p["max_age"],
                    p["min_face"], p["max_face"], p["is_gi"],
                ),
            )
            # Decision thresholds
            cur.execute(
                """
                INSERT INTO product_decision_thresholds
                    (id, tenant_id, product_code,
                     refer_threshold, decline_threshold, stp_threshold,
                     max_table_rating, max_flat_extra, allow_permanent_flat_extra,
                     allow_exclusion_riders, max_income_multiple, max_net_worth_multiple,
                     large_face_threshold, version, created_by, created_at)
                VALUES
                    (gen_random_uuid(), %s::uuid, %s,
                     150, 200, 75,
                     8, 25.0, false,
                     true, 20, 5.0,
                     10000000, 1, 'seed_script', now())
                ON CONFLICT DO NOTHING
                """,
                (tenant_id, p["code"]),
            )
            print(f"   + {p['code']}  — {p['name']}")

        # ── Reinsurer ─────────────────────────────────────────────────
        print("\n🔄  Inserting reinsurer…")
        cur.execute(
            """
            INSERT INTO ri_reinsurer
                (reinsurer_name, reinsurer_code,
                 treaty_type, retention_limit, is_active, treaty_effective_date)
            VALUES
                ('SCOR Re India', 'SCOR-IN',
                 'QUOTA_SHARE', 5000000, true, %s)
            ON CONFLICT DO NOTHING
            """,
            (date.today().isoformat(),),
        )
        print("   + SCOR Re India  retention=₹50L")

        # ── Sample decisions via policy_admin_queue ────────────────────
        print("\n📋  Inserting sample decisions…")
        base_dt = datetime.now() - timedelta(days=30)
        for i, (ref, prod, age, gender, face, outcome, risk_class, debits, stp) in enumerate(SAMPLE_DECISIONS):
            decided_at = base_dt + timedelta(hours=i * 3)
            cur.execute(
                """
                INSERT INTO policy_admin_queue
                    (applicant_ref, applicant_name, product_code, face_amount,
                     age, gender, outcome, risk_class, net_debit_points,
                     decision_date, source, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DEMO', 'UNPROCESSED')
                ON CONFLICT DO NOTHING
                """,
                (
                    ref,
                    f"Demo Applicant {i+1:03d}",
                    prod, face, age, gender,
                    outcome, risk_class, debits,
                    decided_at,
                ),
            )
        approved = sum(1 for d in SAMPLE_DECISIONS if "APPROVED" in d[5])
        declined = sum(1 for d in SAMPLE_DECISIONS if "DECLINED" in d[5])
        referred = sum(1 for d in SAMPLE_DECISIONS if "REFER" in d[5])
        print(f"   + {len(SAMPLE_DECISIONS)} decisions: {approved} approved / {referred} referred / {declined} declined")

        if dry_run:
            print("\n🔍  DRY RUN — rolling back.")
            conn.rollback()
        else:
            conn.commit()
            print(f"\n🎉  Demo data seeded successfully for tenant {tenant_id}")
            print(f"   Open riskuw.online → Dashboard to verify.")

    except Exception as exc:
        conn.rollback()
        print(f"❌  Error: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Seed RiskUW demo data")
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--wipe",    action="store_true", help="Delete existing demo data first")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    seed(args.tenant_id, wipe=args.wipe, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
