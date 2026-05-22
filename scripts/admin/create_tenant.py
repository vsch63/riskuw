#!/usr/bin/env python3
"""
scripts/admin/create_tenant.py
────────────────────────────────
Creates the first (or any subsequent) tenant row and seeds all
required system_config defaults.  Run this BEFORE creating users.

Usage:
    python scripts/admin/create_tenant.py \
        --name "Bajaj Allianz Life" \
        --code BAJAJ \
        --email admin@bajaj.com \
        --plan STANDARD

    # For local demo (non-interactive, uses .env DATABASE_URL):
    python scripts/admin/create_tenant.py --demo
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date, timedelta

import psycopg2
import psycopg2.extras

# ── Default system_config values seeded for every new tenant ────────────────
SYSTEM_CONFIG_DEFAULTS = [
    ("currency_code",       "INR",        "string",  "Currency code for all monetary values"),
    ("currency_symbol",     "₹",          "string",  "Currency symbol displayed in UI"),
    ("date_format",         "DD-MMM-YYYY","string",  "Date format for UI display"),
    ("timezone",            "Asia/Kolkata","string", "Tenant timezone"),
    ("stp_threshold",       "75",         "integer", "Net debit points ≤ this → STP APPROVED"),
    ("refer_threshold",     "150",        "integer", "Net debit points ≤ this → REFERRED"),
    ("decline_threshold",   "151",        "integer", "Net debit points > refer_threshold → DECLINED"),
    ("max_income_multiple", "20",         "integer", "Max face amount as multiple of annual income"),
    ("email_from",          "noreply@riskuw.online", "string", "From address for decision emails"),
    ("platform_name",       "RiskUW",     "string",  "Platform display name"),
    ("logo_url",            "",           "string",  "URL for carrier logo (leave blank to use default)"),
    ("ri_retention_default","5000000",    "integer", "Default RI retention limit in currency units"),
    ("mfa_required_roles",  "admin,senior_underwriter", "string", "Comma-sep roles that must use MFA"),
    ("session_timeout_min", "480",        "integer", "JWT expiry in minutes (8 hours default)"),
    ("max_batch_records",   "10000",      "integer", "Max records per batch upload"),
    ("aps_auto_request",    "true",       "boolean", "Automatically create APS request when rule fires"),
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


def create_tenant(
    name: str,
    code: str,
    email: str,
    plan: str = "STANDARD",
    phone: str = "",
    company_type: str = "Life",
    state_of_domicile: str = "MH",
    dry_run: bool = False,
) -> dict:
    tenant_id = str(uuid.uuid4())
    contract_start = date.today()
    contract_end   = date.today() + timedelta(days=365)

    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ── 1. Tenant row ──────────────────────────────────────────────
        cur.execute("SELECT id FROM tenant WHERE tenant_code = %s", (code,))
        if cur.fetchone():
            print(f"⚠️  Tenant with code '{code}' already exists — skipping INSERT.")
            cur.execute("SELECT id::text, tenant_name FROM tenant WHERE tenant_code=%s", (code,))
            row = cur.fetchone()
            print(f"   → Existing tenant id: {row['id']}")
            conn.close()
            return {"tenant_id": row["id"], "tenant_name": row["tenant_name"], "existed": True}

        cur.execute(
            """
            INSERT INTO tenant
                (id, tenant_code, tenant_name, status, plan_tier,
                 contact_email, contact_phone, company_type,
                 state_of_domicile, max_users, max_decisions_per_month,
                 api_enabled, contract_start, contract_end,
                 timezone, date_format, created_by)
            VALUES
                (%s::uuid, %s, %s, 'ACTIVE', %s,
                 %s, %s, %s,
                 %s, 50, 100000,
                 true, %s, %s,
                 'Asia/Kolkata', 'DD-MMM-YYYY', 'system')
            """,
            (
                tenant_id, code, name, plan,
                email, phone, company_type,
                state_of_domicile,
                contract_start.isoformat(), contract_end.isoformat(),
            ),
        )
        print(f"✅ Created tenant: {name} ({code})  id={tenant_id}")

        # ── 2. system_config defaults ──────────────────────────────────
        inserted = 0
        for key, value, cfg_type, description in SYSTEM_CONFIG_DEFAULTS:
            cur.execute(
                """
                INSERT INTO system_config
                    (id, tenant_id, config_key, config_value, config_type, description, updated_by)
                VALUES
                    (gen_random_uuid(), %s::uuid, %s, %s, %s, %s, 'migration_create_tenant')
                ON CONFLICT DO NOTHING
                """,
                (tenant_id, key, value, cfg_type, description),
            )
            inserted += 1
        print(f"   → Seeded {inserted} system_config defaults")

        # ── 3. Seed state_codes for India ──────────────────────────────
        india_states = [
            ("AN","Andaman and Nicobar Islands"), ("AP","Andhra Pradesh"),
            ("AR","Arunachal Pradesh"),           ("AS","Assam"),
            ("BR","Bihar"),                       ("CH","Chandigarh"),
            ("CG","Chhattisgarh"),                ("DL","Delhi"),
            ("GA","Goa"),                         ("GJ","Gujarat"),
            ("HR","Haryana"),                     ("HP","Himachal Pradesh"),
            ("JK","Jammu and Kashmir"),           ("JH","Jharkhand"),
            ("KA","Karnataka"),                   ("KL","Kerala"),
            ("LA","Ladakh"),                      ("LD","Lakshadweep"),
            ("MP","Madhya Pradesh"),              ("MH","Maharashtra"),
            ("MN","Manipur"),                     ("ML","Meghalaya"),
            ("MZ","Mizoram"),                     ("NL","Nagaland"),
            ("OD","Odisha"),                      ("PY","Puducherry"),
            ("PB","Punjab"),                      ("RJ","Rajasthan"),
            ("SK","Sikkim"),                      ("TN","Tamil Nadu"),
            ("TS","Telangana"),                   ("TR","Tripura"),
            ("UP","Uttar Pradesh"),               ("UK","Uttarakhand"),
            ("WB","West Bengal"),
        ]
        for code_s, name_s in india_states:
            cur.execute(
                """
                INSERT INTO state_codes (country_code, state_code, state_name, is_active)
                VALUES ('IN', %s, %s, true)
                ON CONFLICT DO NOTHING
                """,
                (code_s, name_s),
            )
        print(f"   → Seeded {len(india_states)} Indian state codes")

        if dry_run:
            print("\n🔍  DRY RUN — rolling back all changes.")
            conn.rollback()
        else:
            conn.commit()
            print(f"\n🎉  Done. Tenant ID to copy into .env:\n\n    DEFAULT_TENANT_ID={tenant_id}\n")

        return {"tenant_id": tenant_id, "tenant_name": name, "existed": False}

    except Exception as exc:
        conn.rollback()
        print(f"❌  Error: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Create a RiskUW tenant and seed system_config")
    ap.add_argument("--name",    default="Demo Insurance Co.",  help="Tenant display name")
    ap.add_argument("--code",    default="DEMO",                help="Short uppercase code (e.g. BAJAJ)")
    ap.add_argument("--email",   default="admin@riskuw.online", help="Admin contact email")
    ap.add_argument("--plan",    default="STANDARD",            choices=["TRIAL","STANDARD","PREMIUM","ENTERPRISE"])
    ap.add_argument("--phone",   default="")
    ap.add_argument("--type",    default="Life",                help="Company type: Life, General, Health, Motor")
    ap.add_argument("--state",   default="MH",                  help="State of domicile (2-char)")
    ap.add_argument("--dry-run", action="store_true",           help="Print SQL, don't commit")
    ap.add_argument("--demo",    action="store_true",           help="Quick demo tenant with all defaults")

    args = ap.parse_args()

    # Load .env if dotenv available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.demo:
        create_tenant(
            name="RiskUW Demo Carrier",
            code="DEMO",
            email="admin@riskuw.online",
            plan="STANDARD",
            dry_run=args.dry_run,
        )
    else:
        create_tenant(
            name=args.name,
            code=args.code,
            email=args.email,
            plan=args.plan,
            phone=args.phone,
            company_type=args.type,
            state_of_domicile=args.state,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
