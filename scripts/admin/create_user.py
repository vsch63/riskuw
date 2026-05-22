#!/usr/bin/env python3
"""
scripts/admin/create_user.py
──────────────────────────────
Creates a uw_user row with a bcrypt-hashed password.
Optionally sets up TOTP MFA and prints the QR URL.

Usage:
    python scripts/admin/create_user.py \
        --username chakra \
        --email chakra@riskuw.online \
        --password "S3cur3Pass!" \
        --role admin \
        --tenant-id <UUID from create_tenant.py>

    # Setup MFA at the same time:
    python scripts/admin/create_user.py ... --mfa
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

import bcrypt
import psycopg2
import psycopg2.extras

VALID_ROLES = [
    "super_admin", "admin", "senior_underwriter",
    "underwriter", "api_client", "readonly",
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


def create_user(
    username: str,
    email: str,
    password: str,
    role: str,
    tenant_id: str,
    full_name: str = "",
    setup_mfa: bool = False,
    dry_run: bool = False,
) -> dict:
    user_id = str(uuid.uuid4())
    hashed  = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Check tenant exists
        cur.execute("SELECT tenant_name FROM tenant WHERE id = %s::uuid", (tenant_id,))
        t = cur.fetchone()
        if not t:
            print(f"❌  Tenant {tenant_id!r} not found. Run create_tenant.py first.", file=sys.stderr)
            sys.exit(1)
        print(f"   → Tenant: {t['tenant_name']}")

        # Check duplicate username
        cur.execute("SELECT 1 FROM uw_user WHERE username = %s", (username,))
        if cur.fetchone():
            print(f"⚠️  Username '{username}' already exists — aborting.")
            sys.exit(1)

        # Insert user
        cur.execute(
            """
            INSERT INTO uw_user
                (id, username, email, hashed_password, full_name, role,
                 is_active, tenant_id, created_by, updated_by, version, is_deleted)
            VALUES
                (%s::uuid, %s, %s, %s, %s, %s,
                 true, %s::uuid, 'admin_script', 'admin_script', 1, false)
            """,
            (user_id, username, email, hashed, full_name or username, role, tenant_id),
        )
        print(f"✅  Created user: {username}  role={role}  id={user_id}")

        # Audit
        cur.execute(
            """
            INSERT INTO audit_trail
                (event_category, event_type, actor_username, entity_type,
                 entity_id, after_state, source)
            VALUES ('AUTH','USER_CREATED','admin_script','uw_user',%s,
                    %s::jsonb,'SCRIPT')
            """,
            (
                user_id,
                __import__("json").dumps({
                    "username": username, "role": role, "email": email,
                }),
            ),
        )

        # Optional MFA setup
        totp_uri = None
        if setup_mfa:
            import pyotp
            secret = pyotp.random_base32()
            totp   = pyotp.TOTP(secret)
            issuer = os.environ.get("PLATFORM_NAME", "RiskUW")
            totp_uri = totp.provisioning_uri(name=email, issuer_name=issuer)

            cur.execute(
                """
                INSERT INTO mfa_config
                    (username, totp_secret, is_enabled, is_verified, created_at)
                VALUES (%s, %s, true, false, now())
                ON CONFLICT (username) DO UPDATE
                    SET totp_secret=EXCLUDED.totp_secret,
                        is_enabled=true, is_verified=false
                """,
                (username, secret),
            )
            print(f"\n   🔐  MFA secret: {secret}")
            print(f"   📱  Scan this URI in Google Authenticator / Authy:")
            print(f"       {totp_uri}")
            print(f"\n   ⚠️  is_verified = false until the user completes their first login.")
            print(f"       The user must enter a valid TOTP code before MFA activates.")

        if dry_run:
            print("\n🔍  DRY RUN — rolling back.")
            conn.rollback()
        else:
            conn.commit()
            print(f"\n🎉  User ready. Credentials:\n    username: {username}\n    password: (as set)\n    role:     {role}")
            if setup_mfa:
                print(f"\n    Run:  python -c \"import pyotp; print(pyotp.TOTP('{secret}').now())\"")
                print(f"    to get a test TOTP code.")

        return {
            "user_id": user_id,
            "username": username,
            "role": role,
            "mfa_secret": secret if setup_mfa else None,
            "totp_uri": totp_uri,
        }

    except Exception as exc:
        conn.rollback()
        print(f"❌  Error: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Create a RiskUW user")
    ap.add_argument("--username",  required=True)
    ap.add_argument("--email",     required=True)
    ap.add_argument("--password",  required=True)
    ap.add_argument("--role",      default="underwriter", choices=VALID_ROLES)
    ap.add_argument("--tenant-id", required=True,  help="UUID from create_tenant.py output")
    ap.add_argument("--full-name", default="")
    ap.add_argument("--mfa",       action="store_true", help="Generate and store TOTP secret")
    ap.add_argument("--dry-run",   action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    create_user(
        username=args.username,
        email=args.email,
        password=args.password,
        role=args.role,
        tenant_id=args.tenant_id,
        full_name=args.full_name,
        setup_mfa=args.mfa,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
