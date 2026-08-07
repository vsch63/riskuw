"""
scripts/ci/seed_test_db.py
──────────────────────────
Deterministic, idempotent seed for a test database: creates the CI tenant
(if absent) and the admin user the pytest suite expects
(username=admin / password=TestPass123! — matches backend/tests/conftest.py).

Usage (after migrations have been applied):
    DATABASE_URL=postgresql://user:pass@host:port/dbname \
        python3 scripts/ci/seed_test_db.py

Safe to re-run — existing rows are left untouched.
"""
from __future__ import annotations

import os
import sys
import uuid

import bcrypt
import psycopg2
import psycopg2.extras

TENANT_CODE = "CITEST"
TENANT_NAME = "CI Test Tenant"
ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@ci.local"
ADMIN_PASSWORD = "TestPass123!"  # test-only credential; not used in prod


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5433")
    name = os.environ.get("DB_NAME", "riskuw_test")
    user = os.environ.get("DB_USER", "uw_user")
    pwd = os.environ.get("DB_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


def seed() -> None:
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # Tenant
        cur.execute("SELECT id FROM tenant WHERE tenant_code = %s", (TENANT_CODE,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
            print(f"→ tenant {TENANT_CODE} exists ({tenant_id})")
        else:
            cur.execute("""
                INSERT INTO tenant (tenant_code, tenant_name, status, plan_tier,
                                    contact_email, company_type, max_users,
                                    max_decisions_per_month, api_enabled,
                                    timezone, date_format, created_by)
                VALUES (%s, %s, 'ACTIVE', 'STANDARD', %s, 'INSURER',
                        25, 10000, true, 'Asia/Kolkata', 'DD-MM-YYYY', 'system')
                RETURNING id
            """, (TENANT_CODE, TENANT_NAME, ADMIN_EMAIL))
            tenant_id = cur.fetchone()["id"]
            print(f"→ created tenant {TENANT_CODE} ({tenant_id})")

        # Admin user (only if absent — do not clobber an existing password)
        cur.execute("SELECT id FROM uw_user WHERE username = %s", (ADMIN_USERNAME,))
        if cur.fetchone():
            print(f"→ user {ADMIN_USERNAME} exists")
        else:
            cur.execute("""
                INSERT INTO uw_user (id, username, email, hashed_password, full_name,
                                     role, is_active, is_deleted, tenant_id,
                                     created_by, updated_by, version)
                VALUES (%s, %s, %s, %s, 'CI Admin', 'admin', true, false, %s,
                        'system', 'system', 1)
            """, (str(uuid.uuid4()), ADMIN_USERNAME, ADMIN_EMAIL,
                   bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode(),
                   tenant_id))
            print(f"→ created user {ADMIN_USERNAME}")

        conn.commit()
        print("✅ seed complete")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        seed()
    except Exception as e:  # noqa: BLE001
        print(f"❌ seed failed: {e}", file=sys.stderr)
        sys.exit(1)
