#!/usr/bin/env python3
"""
fix_smtp_keys.py — Reverts frontend SMTP key check to match backend.
Backend returns: host / port / from_email  (short keys)
Run: python3 fix_smtp_keys.py /opt/riskuw/frontend/src/pages/SystemConfigPage.tsx
"""
import sys, os

path = sys.argv[1] if len(sys.argv) > 1 else "frontend/src/pages/SystemConfigPage.tsx"
if not os.path.isfile(path):
    print(f"File not found: {path}"); sys.exit(1)

with open(path) as f:
    c = f.read()

with open(path + ".bak_smtpfix", "w") as f:
    f.write(c)
print(f"Backup: {path}.bak_smtpfix")

fixes = [
    ("if (r?.smtp_host) setStatus(r)",
     "if (r?.host) setStatus(r)"),
    ("{smtpStatus?.smtp_host ? (",
     "{smtpStatus?.host ? ("),
    ("<strong>{smtpStatus.smtp_host}</strong> port {smtpStatus.smtp_port} from <strong>{smtpStatus.smtp_from}</strong>",
     "<strong>{smtpStatus.host}</strong> port {smtpStatus.port} from <strong>{smtpStatus.from_email}</strong>"),
]

changed = 0
for old, new in fixes:
    n = c.count(old)
    if n:
        c = c.replace(old, new); changed += n
        print(f"  FIXED ({n}x): {old[:65]}")
    elif new in c:
        print(f"  SKIP  (already correct): {new[:65]}")
    else:
        print(f"  MISS  (not found - may already be fixed): {old[:65]}")

with open(path, "w") as f:
    f.write(c)
print(f"\n{'Done — ' + str(changed) + ' fix(es) applied.' if changed else 'Nothing changed (already correct).'}")
print("Now rebuild: docker build --no-cache -f Dockerfile.frontend . && docker compose up -d frontend")
