#!/usr/bin/env python3
"""
scripts/admin/reset_password.py
────────────────────────────────
CLI tool to reset a user's password directly in the DB.
Used when a user is locked out and cannot use the UI reset flow.

Usage:
    python scripts/admin/reset_password.py --username chakra --password "NewPass123!"
    python scripts/admin/reset_password.py --username chakra --generate   # auto-generate
"""
from __future__ import annotations
import argparse, os, secrets, string, sys

import bcrypt
import psycopg2


def get_db_url() -> str:
    return os.environ.get("DATABASE_URL",
        f"postgresql://{os.environ.get('DB_USER','uw_user')}:"
        f"{os.environ.get('DB_PASSWORD','')}@"
        f"{os.environ.get('DB_HOST','localhost')}:"
        f"{os.environ.get('DB_PORT','5432')}/"
        f"{os.environ.get('DB_NAME','riskuw')}"
    )


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # Ensure it meets complexity requirements
        if (any(c.isupper() for c in pwd)
                and any(c.islower() for c in pwd)
                and any(c.isdigit() for c in pwd)
                and any(c in "!@#$%^&*" for c in pwd)):
            return pwd


def reset_password(username: str, new_password: str, actor: str = "admin_script") -> bool:
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(rounds=12)).decode()
    conn = psycopg2.connect(get_db_url())
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # Verify user exists
        cur.execute("SELECT is_active, role FROM uw_user WHERE username=%s AND is_deleted=false",
                    (username,))
        row = cur.fetchone()
        if not row:
            print(f"❌  User '{username}' not found.", file=sys.stderr)
            return False

        is_active, role = row
        if not is_active:
            print(f"⚠️   User '{username}' is inactive — resetting password anyway.")

        cur.execute(
            "UPDATE uw_user SET hashed_password=%s, updated_at=now(), updated_by=%s "
            "WHERE username=%s AND is_deleted=false",
            (hashed, actor, username),
        )

        # Clear any lockout
        cur.execute(
            "UPDATE login_attempts SET failed_count=0, locked_until=NULL, updated_at=now() "
            "WHERE username=%s",
            (username,),
        )

        # Audit trail
        import json
        cur.execute(
            "INSERT INTO audit_trail "
            "(event_category, event_type, actor_username, entity_type, entity_id, "
            "after_state, source) "
            "VALUES ('AUTH','PASSWORD_RESET_CLI',%s,'uw_user',%s,%s::jsonb,'SCRIPT')",
            (actor, username, json.dumps({"username": username, "reset_by": actor})),
        )
        conn.commit()
        cur.close()
        print(f"✅  Password reset for '{username}' (role: {role})")
        return True
    except Exception as exc:
        conn.rollback()
        print(f"❌  Error: {exc}", file=sys.stderr)
        return False
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Reset a RiskUW user password")
    ap.add_argument("--username",  required=True)
    ap.add_argument("--password",  default=None, help="New password (or use --generate)")
    ap.add_argument("--generate",  action="store_true", help="Auto-generate a secure password")
    ap.add_argument("--actor",     default="admin_script", help="Who is doing the reset")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass

    if args.generate:
        pwd = generate_password()
        print(f"Generated password: {pwd}")
    elif args.password:
        pwd = args.password
        if len(pwd) < 8:
            print("❌  Password must be at least 8 characters.", file=sys.stderr)
            sys.exit(1)
    else:
        import getpass
        pwd = getpass.getpass(f"New password for '{args.username}': ")
        confirm = getpass.getpass("Confirm password: ")
        if pwd != confirm:
            print("❌  Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    ok = reset_password(args.username, pwd, actor=args.actor)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
