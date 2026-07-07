#!/usr/bin/env python3
"""
fix_batch_download.py
---------------------
Fixes two bugs in /opt/riskuw/backend/routers/batch.py:

BUG 1: @router.get("/jobs/{job_id}/download/{type}") at line 701 is bound
        to get_job_records (line 703) — download_results (line 749) has NO decorator.
        FastAPI binds a decorator to the IMMEDIATELY NEXT function.
        Result: downloads return paginated JSON instead of CSV/Excel file.

BUG 2: ORDER BY created_at on batch_jobs table — column doesn't exist.
        Fix: use submitted_at (confirmed in schema).

Usage:
    python3 fix_batch_download.py /opt/riskuw/backend/routers/batch.py
"""

import sys, os, re, shutil

path = sys.argv[1] if len(sys.argv) > 1 else "/opt/riskuw/backend/routers/batch.py"

if not os.path.isfile(path):
    print(f"File not found: {path}")
    sys.exit(1)

with open(path) as f:
    lines = f.readlines()

# Backup
bak = path + ".bak_download_fix"
shutil.copy(path, bak)
print(f"Backup: {bak}")

content = "".join(lines)

# ── FIX 1: Separate the two functions that share one decorator block ──────────
# Current (broken):
#   @router.get("/jobs/{job_id}/download/{type}")   <- line 701
#   @router.get("/jobs/{job_id}/records")           <- line 702
#   def get_job_records(...):                        <- line 703 gets BOTH decorators
#   ...
#   def download_results(...):                       <- line 749 gets NO decorator
#
# Fixed:
#   @router.get("/jobs/{job_id}/records")
#   def get_job_records(...):
#   ...
#   @router.get("/jobs/{job_id}/download/{type}")
#   def download_results(...):

old_decorator_block = '''@router.get("/jobs/{job_id}/download/{type}")
@router.get("/jobs/{job_id}/records")
def get_job_records('''

new_decorator_block = '''@router.get("/jobs/{job_id}/records")
def get_job_records('''

if old_decorator_block in content:
    content = content.replace(old_decorator_block, new_decorator_block, 1)
    print("  FIXED [BUG 1a]: Removed /download/{type} decorator from get_job_records")
else:
    print("  SKIP  [BUG 1a]: Decorator block not found as expected — checking alternative...")
    # Try finding just the stacked decorators differently
    alt = '@router.get("/jobs/{job_id}/download/{type}")\n@router.get("/jobs/{job_id}/records")'
    if alt in content:
        content = content.replace(alt, '@router.get("/jobs/{job_id}/records")')
        print("  FIXED [BUG 1a]: Alternative pattern fixed")
    else:
        print("  WARN  [BUG 1a]: Could not auto-fix decorator stacking — manual fix needed")
        print("         Remove the @router.get(\"/jobs/{job_id}/download/{type}\") line")
        print("         from above get_job_records and add it above download_results instead")

# Add decorator to download_results
old_download_def = 'def download_results(job_id: str, type: str, fmt: str = "csv", current: CurrentUser = None):'
new_download_def = '''@router.get("/jobs/{job_id}/download/{type}")
def download_results(job_id: str, type: str, fmt: str = "csv", current: CurrentUser = None):'''

if '@router.get("/jobs/{job_id}/download/{type}")\ndef download_results' in content:
    print("  SKIP  [BUG 1b]: download_results already has decorator")
elif old_download_def in content:
    content = content.replace(old_download_def, new_download_def, 1)
    print("  FIXED [BUG 1b]: Added @router.get decorator to download_results")
else:
    print("  WARN  [BUG 1b]: download_results signature not found — check manually")

# ── FIX 2: ORDER BY created_at → submitted_at on batch_jobs ─────────────────
old_order = "FROM batch_jobs ORDER BY created_at DESC"
new_order = "FROM batch_jobs ORDER BY submitted_at DESC"
if old_order in content:
    content = content.replace(old_order, new_order)
    print("  FIXED [BUG 2]: ORDER BY created_at → submitted_at on batch_jobs")
else:
    print("  SKIP  [BUG 2]: created_at ORDER BY not found (may already be fixed)")

# ── FIX 3: cursor_factory pollution ──────────────────────────────────────────
# RealDictCursor set on shared connection breaks other cursors
# Replace: db.cursor_factory = psycopg2.extras.RealDictCursor
# With:    using named cursor instead (safe pattern)
old_cursor_factory = "db.cursor_factory = psycopg2.extras.RealDictCursor"
if old_cursor_factory in content:
    content = content.replace(
        old_cursor_factory,
        "# cursor_factory set per-cursor instead (safe for shared connections)"
    )
    # Replace subsequent cur = db.cursor() with RealDictCursor
    content = content.replace(
        "# cursor_factory set per-cursor instead (safe for shared connections)\n        cur = db.cursor()",
        "# cursor_factory set per-cursor instead (safe for shared connections)\n        import psycopg2.extras\n        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)"
    )
    print("  FIXED [BUG 3]: cursor_factory pollution on shared connection")
else:
    print("  SKIP  [BUG 3]: cursor_factory not set on connection (good)")

# ── Write fixed file ──────────────────────────────────────────────────────────
with open(path, "w") as f:
    f.write(content)
print(f"\nFixed file written: {path}")

# ── Verify ────────────────────────────────────────────────────────────────────
print("\nVerification:")
with open(path) as f:
    result = f.read()

checks = [
    ("download_results has decorator",
     '@router.get("/jobs/{job_id}/download/{type}")\ndef download_results' in result),
    ("get_job_records does NOT have download decorator",
     '@router.get("/jobs/{job_id}/download/{type}")\n@router.get("/jobs/{job_id}/records")' not in result),
    ("submitted_at used for batch_jobs ORDER BY",
     "ORDER BY submitted_at DESC" in result or "created_at DESC" not in result),
]
all_ok = True
for label, ok in checks:
    print(f"  {'✅' if ok else '❌'} {label}")
    if not ok: all_ok = False

print()
if all_ok:
    print("All fixes verified. Rebuild and restart:")
    print("  docker compose build --no-cache fastapi && docker compose up -d fastapi")
else:
    print("Some fixes need manual attention — check the file.")
    print(f"Original backed up at: {bak}")
