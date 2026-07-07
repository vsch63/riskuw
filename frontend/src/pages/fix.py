#!/usr/bin/env python3
"""
fix_systemconfig.py
-------------------
Fixes two issues in SystemConfigPage.tsx:

  1. Pre-existing JSX corruption at line ~1552:
       <div style={secTitle}>Parametediv>
     → <div style={secTitle}>Parameters</div>

  2. SMTP key mismatch (banner never turns green after save):
       r?.host        → r?.smtp_host        (useEffect + save)
       smtpStatus?.host → smtpStatus?.smtp_host  (banner check)
       smtpStatus.host/port/from_email → smtp_host/smtp_port/smtp_from

Usage:
    python3 fix_systemconfig.py /opt/riskuw/frontend/src/pages/SystemConfigPage.tsx
"""

import sys
import os
import re

# ── Define all fixes ─────────────────────────────────────────────────────────
FIXES = [
    {
        "id": "corruption_line1552",
        "description": "Fix JSX corruption: Parametediv> → Parameters</div>",
        "old": '<div style={secTitle}>Parametediv>',
        "new": '<div style={secTitle}>Parameters</div>',
    },
    {
        "id": "smtp_useeffect",
        "description": "Fix SMTP useEffect: r?.host → r?.smtp_host",
        "old": 'if (r?.host) setStatus(r)',
        "new": 'if (r?.smtp_host) setStatus(r)',
    },
    {
        "id": "smtp_banner_check",
        "description": "Fix SMTP banner check: smtpStatus?.host → smtpStatus?.smtp_host",
        "old": '{smtpStatus?.host ? (',
        "new": '{smtpStatus?.smtp_host ? (',
    },
    {
        "id": "smtp_banner_display",
        "description": "Fix SMTP banner display fields: .host/.port/.from_email → .smtp_host/.smtp_port/.smtp_from",
        "old": '✅ SMTP configured: <strong>{smtpStatus.host}</strong> port {smtpStatus.port} from <strong>{smtpStatus.from_email}</strong>',
        "new": '✅ SMTP configured: <strong>{smtpStatus.smtp_host}</strong> port {smtpStatus.smtp_port} from <strong>{smtpStatus.smtp_from}</strong>',
    },
]

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fix_systemconfig.py <path/to/SystemConfigPage.tsx>")
        sys.exit(1)

    filepath = sys.argv[1]

    if not os.path.isfile(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)

    # Read original
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content  # keep for backup

    print(f"\n📄 File: {filepath}")
    print(f"   Size: {len(content):,} bytes\n")

    applied   = []
    skipped   = []
    not_found = []

    for fix in FIXES:
        count = content.count(fix["old"])
        if count == 0:
            # Check if new string already present (already applied)
            if fix["new"] in content:
                skipped.append(fix)
                print(f"  ⏭  SKIP  [{fix['id']}] — already applied")
            else:
                not_found.append(fix)
                print(f"  ⚠️  MISS  [{fix['id']}] — pattern not found (file may differ)")
        else:
            content = content.replace(fix["old"], fix["new"])
            applied.append(fix)
            print(f"  ✅ FIXED [{fix['id']}] — {fix['description']} ({count}x)")

    print()

    if not applied:
        print("Nothing to change — file already clean or patterns not matched.")
        if not_found:
            print("\n⚠️  Some patterns were NOT found. Check the file manually:")
            for f in not_found:
                print(f"   - {f['id']}: expected → {f['old'][:60]}")
        sys.exit(0)

    # Write backup
    backup = filepath + ".bak"
    with open(backup, "w", encoding="utf-8") as f:
        f.write(original)
    print(f"💾 Backup saved: {backup}")

    # Write fixed file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Fixed file written: {filepath}")

    # Quick sanity check
    print("\n🔍 Sanity check:")
    checks = [
        ("Parametediv>",         "corruption still present ❌"),
        ("if (r?.host) setStatus","smtp useEffect key still wrong ❌"),
        ("{smtpStatus?.host ?",   "smtp banner check still wrong ❌"),
        ("smtpStatus.from_email", "smtp banner display still wrong ❌"),
    ]
    clean = True
    with open(filepath, "r", encoding="utf-8") as f:
        result = f.read()
    for pattern, label in checks:
        if pattern in result:
            print(f"   ❌ {label}")
            clean = False
        else:
            print(f"   ✅ {pattern!r} — not present (good)")

    print()
    if clean:
        print("🎉 All fixes verified. Run your Docker build now:\n")
        print("   docker build --no-cache -f Dockerfile.frontend .\n")
    else:
        print("⚠️  Some issues remain — check the file manually.\n")


if __name__ == "__main__":
    main()
