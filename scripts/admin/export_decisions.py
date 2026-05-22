#!/usr/bin/env python3
"""
scripts/admin/export_decisions.py
───────────────────────────────────
Export all decisions from policy_admin_queue to Excel.
Use before carrier demos to show real data.

Usage:
    python scripts/admin/export_decisions.py --out demo_decisions.xlsx
    python scripts/admin/export_decisions.py --days 30 --out last_month.xlsx
"""
from __future__ import annotations
import argparse, os, sys
from datetime import datetime, timedelta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",  default="decisions_export.xlsx")
    ap.add_argument("--days", type=int, default=90, help="Last N days")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass

    import psycopg2, psycopg2.extras, pandas as pd

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("❌  DATABASE_URL not set", file=sys.stderr); sys.exit(1)

    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    cur  = conn.cursor()
    since = datetime.now() - timedelta(days=args.days)
    cur.execute(
        "SELECT * FROM policy_admin_queue WHERE decision_date >= %s ORDER BY decision_date DESC",
        (since,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    if not rows:
        print("No decisions found for the selected period."); return

    df = pd.DataFrame(rows)
    df.to_excel(args.out, index=False)
    print(f"✅  Exported {len(rows)} decisions → {args.out}")

if __name__ == "__main__":
    main()
