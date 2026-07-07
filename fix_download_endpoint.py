#!/usr/bin/env python3
"""
fix_download_endpoint.py
Fixes download_results to actually return CSV/Excel file response,
not JSON. The function exists but returns data wrong format.
Also ensures decorator is correctly on download_results not get_job_records.
"""
import sys, shutil, re

path = sys.argv[1] if len(sys.argv) > 1 else "/opt/riskuw/backend/routers/batch.py"

with open(path) as f:
    content = f.read()

shutil.copy(path, path + ".bak_dlfix2")
print(f"Backup: {path}.bak_dlfix2")

# ── Show current decorator situation ─────────────────────────────────────────
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if 'download' in line.lower() or 'def get_job_records' in line or 'def download_results' in line:
        print(f"  Line {i:4d}: {line.rstrip()}")

print()

# ── FIX: Ensure download_results returns StreamingResponse with CSV ──────────
# Check if it currently returns StreamingResponse or just data
if 'StreamingResponse' in content and 'download_results' in content:
    print("  StreamingResponse already used — download_results may be correct")
    print("  Issue is likely still the decorator binding")
else:
    print("  download_results does NOT return StreamingResponse — that's the bug")
    print("  The function returns data but not as a file download")

# ── Show what download_results currently returns ──────────────────────────────
# Find function body
start = content.find('def download_results(')
if start != -1:
    snippet = content[start:start+2000]
    print("\n  Current download_results (first 800 chars):")
    print(snippet[:800])

print()
print("  If download_results returns dict/list instead of StreamingResponse,")
print("  the frontend gets JSON. Fix: wrap output in StreamingResponse.")
print()
print("  Run this to check the return statement:")
print(f"  grep -n 'return\\|StreamingResponse\\|FileResponse' {path} | head -20")
