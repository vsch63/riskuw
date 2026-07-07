#!/usr/bin/env python3
"""
fix_ri_batch_mode.py
--------------------
Adds batch_mode=False param to check_and_trigger_reinsurance in ri_trigger.py
so batch runs skip the per-record RI email (cession still created, email suppressed).

Also fixes the batch.py call to pass batch_mode=True correctly
(the sed already added it but with wrong position — this ensures correct syntax).

Usage:
    python3 fix_ri_batch_mode.py /opt/riskuw/backend
"""
import sys, os, shutil

base = sys.argv[1] if len(sys.argv) > 1 else "/opt/riskuw/backend"
ri_path    = os.path.join(base, "services/ri_trigger.py")
batch_path = os.path.join(base, "routers/batch.py")

for p in [ri_path, batch_path]:
    if not os.path.isfile(p):
        print(f"❌ Not found: {p}")
        sys.exit(1)

# ── Backup both files ────────────────────────────────────────────────────────
shutil.copy(ri_path,    ri_path    + ".bak_batchmode")
shutil.copy(batch_path, batch_path + ".bak_batchmode")
print(f"Backups created.")

# ── FIX 1: ri_trigger.py — add batch_mode param + skip email when True ───────
with open(ri_path) as f:
    ri = f.read()

# Add batch_mode=False to function signature
old_sig = '''def check_and_trigger_reinsurance(
    conn,
    case_id: str,
    application_id: str | None,
    product_code: str,
    face_amount: float,
    approved_premium: float | None,
    applicant_ref: str,
    submitted_by: str = "system",
) -> dict:'''

new_sig = '''def check_and_trigger_reinsurance(
    conn,
    case_id: str,
    application_id: str | None,
    product_code: str,
    face_amount: float,
    approved_premium: float | None,
    applicant_ref: str,
    submitted_by: str = "system",
    batch_mode: bool = False,
) -> dict:'''

if old_sig in ri:
    ri = ri.replace(old_sig, new_sig)
    print("  ✅ ri_trigger.py: added batch_mode=False param to signature")
elif "batch_mode" in ri:
    print("  ⏭  ri_trigger.py: batch_mode already present in signature")
else:
    # Try simpler replacement on just the last line of signature
    ri = ri.replace(
        '    submitted_by: str = "system",\n) -> dict:',
        '    submitted_by: str = "system",\n    batch_mode: bool = False,\n) -> dict:'
    )
    print("  ✅ ri_trigger.py: added batch_mode param (fallback pattern)")

# Find where email is sent inside ri_trigger and wrap with batch_mode check
# Look for the notification/email send call
email_patterns = [
    'send_email(',
    'send_ri_cession_email(',
    'notification',
    'RI_CESSION_EMAIL',
    'SMTP',
]

# Find the email send line
lines = ri.split('\n')
email_line_idx = None
for i, line in enumerate(lines):
    if any(p in line for p in email_patterns) and 'import' not in line:
        email_line_idx = i
        print(f"  Found email call at line {i+1}: {line.strip()[:80]}")
        break

if email_line_idx:
    # Find the block — could be a try block or direct call
    # Wrap the entire email send section with: if not batch_mode:
    # Find indentation level
    indent = len(lines[email_line_idx]) - len(lines[email_line_idx].lstrip())
    indent_str = ' ' * indent

    # Find the extent of the email block (contiguous non-empty lines at same/deeper indent)
    block_start = email_line_idx
    block_end   = email_line_idx

    # Look backwards for a try: or similar block start at same indent
    for j in range(email_line_idx - 1, max(0, email_line_idx - 10), -1):
        stripped = lines[j].strip()
        if stripped.startswith('try:') or stripped.startswith('if ') or stripped.startswith('with '):
            line_indent = len(lines[j]) - len(lines[j].lstrip())
            if line_indent == indent:
                block_start = j
                break

    # Find block end
    for j in range(email_line_idx + 1, min(len(lines), email_line_idx + 30)):
        if lines[j].strip() == '':
            block_end = j - 1
            break
        line_indent = len(lines[j]) - len(lines[j].lstrip())
        if line_indent < indent and lines[j].strip():
            block_end = j - 1
            break
        block_end = j

    # Wrap the block
    guard = f"{indent_str}if not batch_mode:\n"
    # Add 4 spaces to each line in block
    for j in range(block_start, block_end + 1):
        if lines[j].strip():
            lines[j] = '    ' + lines[j]

    lines.insert(block_start, guard.rstrip())
    ri = '\n'.join(lines)
    print(f"  ✅ ri_trigger.py: wrapped email block (lines {block_start+1}–{block_end+1}) with 'if not batch_mode:'")
else:
    print("  ⚠️  ri_trigger.py: could not find email send call — add manually:")
    print("      Wrap the RI email send with:  if not batch_mode:")

with open(ri_path, 'w') as f:
    f.write(ri)

# ── FIX 2: batch.py — fix the sed-injected call (may have wrong syntax) ──────
with open(batch_path) as f:
    batch = f.read()

# The sed command produced: check_and_trigger_reinsurance(batch_mode=True, conn=conn, ...
# This is invalid — batch_mode must be a keyword arg AFTER positional args
# OR we need to ensure all args are keyword args

# Fix the call to use correct kwarg ordering
old_call = "check_and_trigger_reinsurance(batch_mode=True, \n                            conn=conn,"
new_call = "check_and_trigger_reinsurance(\n                            conn=conn,"

# Try the exact pattern from the sed output
bad_patterns = [
    "check_and_trigger_reinsurance(batch_mode=True, \n",
    "check_and_trigger_reinsurance(batch_mode=True,\n",
    "check_and_trigger_reinsurance(batch_mode=True, conn",
]

fixed_batch = False
for bad in bad_patterns:
    if bad in batch:
        # Move batch_mode to end, before closing paren of the call
        # Find the full call block
        start = batch.find(bad)
        end   = batch.find(')', start + len(bad))
        # Get indentation
        line_start = batch.rfind('\n', 0, start) + 1
        indent_str = ' ' * (len(batch[line_start:start]) )

        old_block = batch[start:end+1]
        # Remove batch_mode=True from front, add to end
        new_block = old_block.replace("batch_mode=True, \n", "\n")
        new_block = new_block.replace("batch_mode=True,\n", "\n")
        new_block = new_block.replace("batch_mode=True, ", "")
        # Insert batch_mode=True before closing paren
        new_block = new_block.rstrip(')') + f"\n{indent_str}    batch_mode=True,\n{indent_str})"
        batch = batch[:start] + new_block + batch[end+1:]
        fixed_batch = True
        print("  ✅ batch.py: fixed batch_mode=True kwarg position in RI call")
        break

if not fixed_batch:
    # Check if batch_mode already correctly placed
    if "batch_mode=True," in batch and "check_and_trigger_reinsurance" in batch:
        print("  ✅ batch.py: batch_mode=True already in call (checking position...)")
        # Verify it's not at the start (which would cause TypeError with positional args)
        idx = batch.find("check_and_trigger_reinsurance(")
        call_start = idx
        call_end   = batch.find(')', idx)
        call_block = batch[call_start:call_end+1]
        if call_block.startswith("check_and_trigger_reinsurance(batch_mode"):
            print("  ⚠️  batch_mode is FIRST arg — this will fail. Manual fix needed:")
            print("      Move batch_mode=True to be the LAST argument in the call")
        else:
            print("  ✅ batch_mode position looks correct")
    else:
        # Add batch_mode=True to the call
        batch = batch.replace(
            "submitted_by=submitted_by,\n                    )",
            "submitted_by=submitted_by,\n                        batch_mode=True,\n                    )"
        )
        print("  ✅ batch.py: added batch_mode=True to RI call (fallback)")

with open(batch_path, 'w') as f:
    f.write(batch)

# ── Verify ────────────────────────────────────────────────────────────────────
print("\nVerification:")
with open(ri_path) as f:    ri_check    = f.read()
with open(batch_path) as f: batch_check = f.read()

checks = [
    ("ri_trigger.py has batch_mode param",    "batch_mode: bool = False" in ri_check),
    ("ri_trigger.py guards email with batch_mode", "if not batch_mode" in ri_check),
    ("batch.py passes batch_mode=True",       "batch_mode=True" in batch_check),
    ("batch_mode not first arg in batch.py",  "check_and_trigger_reinsurance(batch_mode" not in batch_check),
]
all_ok = True
for label, ok in checks:
    print(f"  {'✅' if ok else '❌'} {label}")
    if not ok: all_ok = False

print()
if all_ok:
    print("All fixes verified.")
    print("Apply after job 000089 completes:")
    print("  docker compose build --no-cache fastapi && docker compose up -d fastapi")
    print()
    print("Next batch run will:")
    print("  - Still create RI cession records (audit trail intact)")
    print("  - Skip per-record RI emails (no 5s delay per row)")
    print("  - Expected time: ~5 min for 1000 records (vs 83 min now)")
else:
    print("Some checks failed — review the file manually before rebuilding.")
