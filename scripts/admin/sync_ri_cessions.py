#!/usr/bin/env python3
"""
scripts/admin/sync_ri_cessions.py
───────────────────────────────────
Backfill ri_cession rows for historical APPROVED decisions where
face_amount > retention_limit and no cession row exists yet.

The V002 DB trigger handles future decisions automatically.
This script handles the historical backlog.

Usage:
    python scripts/admin/sync_ri_cessions.py --tenant-id <UUID> --dry-run
    python scripts/admin/sync_ri_cessions.py --tenant-id <UUID>
    python scripts/admin/sync_ri_cessions.py --tenant-id <UUID> --limit 100
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime

import psycopg2
import psycopg2.extras

DEFAULT_RETENTION = 5_000_000


def get_db_url() -> str:
    return os.environ.get("DATABASE_URL",
        f"postgresql://{os.environ.get('DB_USER','uw_user')}:"
        f"{os.environ.get('DB_PASSWORD','')}@"
        f"{os.environ.get('DB_HOST','localhost')}:"
        f"{os.environ.get('DB_PORT','5432')}/"
        f"{os.environ.get('DB_NAME','riskuw')}"
    )


def sync(tenant_id: str, dry_run: bool = False, limit: int = 500) -> dict:
    conn = psycopg2.connect(get_db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    result = {"checked": 0, "created": 0, "skipped": 0, "errors": 0}

    try:
        # Get active reinsurer
        cur.execute(
            "SELECT id, retention_limit FROM ri_reinsurer "
            "WHERE is_active=true AND (tenant_id=%s::uuid OR tenant_id IS NULL) "
            "AND (treaty_expiry_date IS NULL OR treaty_expiry_date > CURRENT_DATE) "
            "ORDER BY retention_limit ASC LIMIT 1",
            (tenant_id,),
        )
        ri_row = cur.fetchone()
        if not ri_row:
            print("⚠️  No active reinsurer found. Run seed_demo_data.py first.")
            return result

        reinsurer_id = ri_row["id"]
        retention    = float(ri_row["retention_limit"] or DEFAULT_RETENTION)
        print(f"Reinsurer ID: {reinsurer_id} | Retention limit: ₹{retention:,.0f}")

        # Find approved decisions above retention threshold with no existing cession
        cur.execute(
            """
            SELECT paq.id, paq.applicant_ref, paq.product_code,
                   paq.face_amount, paq.risk_class, paq.decision_date
            FROM policy_admin_queue paq
            WHERE paq.outcome LIKE 'APPROVED%%'
              AND paq.face_amount > %s
              AND NOT EXISTS (
                  SELECT 1 FROM ri_cession ri
                  WHERE ri.case_id = paq.id::text
              )
            ORDER BY paq.decision_date DESC
            LIMIT %s
            """,
            (retention, limit),
        )
        rows = cur.fetchall()
        result["checked"] = len(rows)

        if not rows:
            print("✅  No outstanding cessions to backfill.")
            return result

        print(f"\nFound {len(rows)} decision(s) needing cession rows:\n")

        for row in rows:
            cession_amount = float(row["face_amount"]) - retention
            print(
                f"  {row['applicant_ref']:<20} | face=₹{float(row['face_amount']):>14,.0f} "
                f"| cession=₹{cession_amount:>12,.0f} | {row['product_code']}"
            )

            if dry_run:
                result["skipped"] += 1
                continue

            try:
                cur.execute(
                    """
                    INSERT INTO ri_cession
                        (case_id, reinsurer_id, cession_type, face_amount,
                         cession_amount, risk_class, treaty_reference,
                         status, created_at)
                    VALUES (%s, %s, 'BACKFILL', %s, %s, %s,
                            'BACKFILL-' || to_char(now(),'YYYYMMDD'),
                            'PENDING', now())
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        str(row["id"]), reinsurer_id,
                        float(row["face_amount"]), cession_amount,
                        row.get("risk_class"),
                    ),
                )
                # Audit
                cur.execute(
                    "INSERT INTO audit_trail "
                    "(event_category, event_type, actor_username, entity_type, "
                    "entity_id, after_state, source) "
                    "VALUES ('REINSURANCE','RI_CESSION_BACKFILLED','sync_script',"
                    "'policy_admin_queue',%s,%s::jsonb,'SCRIPT')",
                    (
                        str(row["id"]),
                        json.dumps({
                            "applicant_ref": row["applicant_ref"],
                            "face_amount": float(row["face_amount"]),
                            "cession_amount": cession_amount,
                        }),
                    ),
                )
                result["created"] += 1
            except Exception as exc:
                print(f"    ❌  Error for {row['applicant_ref']}: {exc}")
                result["errors"] += 1

        if dry_run:
            print(f"\n🔍  DRY RUN — {result['checked']} would be created. No changes made.")
            conn.rollback()
        else:
            conn.commit()
            print(
                f"\n✅  Done: {result['created']} cessions created | "
                f"{result['errors']} errors"
            )

    except Exception as exc:
        conn.rollback()
        print(f"❌  Fatal error: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()

    return result


def main():
    ap = argparse.ArgumentParser(description="Backfill RI cessions for historical decisions")
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--dry-run",   action="store_true")
    ap.add_argument("--limit",     type=int, default=500, help="Max rows to process")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass

    sync(args.tenant_id, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
