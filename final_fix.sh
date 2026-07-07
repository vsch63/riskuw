#!/bin/bash
# final_fix.sh
# The backend GET /system/smtp returns smtp_host correctly.
# The frontend fix is right. Issue is stale build or browser cache.
# This script rebuilds frontend and verifies everything.

set -e
cd /opt/riskuw

echo ""
echo "=============================="
echo "  STEP 1 — Verify frontend file has correct smtp_host keys"
echo "=============================="
FILE="frontend/src/pages/SystemConfigPage.tsx"

python3 - << 'PYEOF'
import sys
path = "frontend/src/pages/SystemConfigPage.tsx"
with open(path) as f:
    c = f.read()

checks = [
    ("if (r?.smtp_host) setStatus(r)",          "useEffect key check"),
    ("{smtpStatus?.smtp_host ? (",               "banner visibility"),
    ("{smtpStatus.smtp_host}",                   "banner display host"),
    ("{smtpStatus.smtp_port}",                   "banner display port"),
    ("{smtpStatus.smtp_from}",                   "banner display from"),
]
bad_keys = [
    ("if (r?.host) setStatus(r)",               "OLD key r?.host still present"),
    ("{smtpStatus?.host ? (",                   "OLD banner check still present"),
    ("smtpStatus.from_email",                   "OLD from_email still present"),
]

print("  Checking correct keys exist:")
all_good = True
for pattern, label in checks:
    found = pattern in c
    print(f"    {'✅' if found else '❌'} {label}")
    if not found:
        all_good = False

print("\n  Checking old keys are gone:")
for pattern, label in bad_keys:
    found = pattern in c
    print(f"    {'❌ BAD —' if found else '✅'} {label}")
    if found:
        all_good = False

if all_good:
    print("\n  ✅ File is correct — frontend has right keys")
else:
    print("\n  ❌ File still has wrong keys — running fix...")
    fixes = [
        ("if (r?.host) setStatus(r)",    "if (r?.smtp_host) setStatus(r)"),
        ("{smtpStatus?.host ? (",         "{smtpStatus?.smtp_host ? ("),
        ("{smtpStatus.host}",             "{smtpStatus.smtp_host}"),
        ("{smtpStatus.port}",             "{smtpStatus.smtp_port}"),
        ("{smtpStatus.from_email}",       "{smtpStatus.smtp_from}"),
    ]
    for old, new in fixes:
        n = c.count(old)
        if n:
            c = c.replace(old, new)
            print(f"    FIXED ({n}x): {old}")
    with open(path, "w") as f:
        f.write(c)
    print("  File updated.")
PYEOF

echo ""
echo "=============================="
echo "  STEP 2 — Fix nginx cache headers (stops browser caching the JS bundle)"
echo "=============================="
# Check if nginx config exists
NGINX_CONF=$(find /opt/riskuw -name "nginx.conf" 2>/dev/null | head -1)
if [ -n "$NGINX_CONF" ]; then
    echo "  Found: $NGINX_CONF"
    # Check if cache control already set
    if grep -q "no-store\|no-cache" "$NGINX_CONF"; then
        echo "  ✅ Cache headers already configured"
    else
        echo "  Adding no-cache headers for JS/CSS assets..."
        # Show current config
        echo "  Current config (relevant section):"
        grep -A5 "location" "$NGINX_CONF" | head -30
    fi
else
    echo "  No nginx.conf found in /opt/riskuw — checking container..."
    docker exec riskuw_frontend cat /etc/nginx/conf.d/default.conf 2>/dev/null || \
    docker exec riskuw_frontend cat /etc/nginx/nginx.conf 2>/dev/null | head -60
fi

echo ""
echo "=============================="
echo "  STEP 3 — Rebuild frontend with no cache"
echo "=============================="
echo "  Building..."
docker build --no-cache -f Dockerfile.frontend -t riskuw-frontend . 2>&1 | tail -20

echo ""
echo "=============================="
echo "  STEP 4 — Restart frontend container"
echo "=============================="
docker compose up -d frontend
sleep 3
docker ps --filter "name=riskuw_frontend" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=============================="
echo "  STEP 5 — Verify the built JS has smtp_host (not old keys)"
echo "=============================="
echo "  Checking built bundle for smtp_host key..."
docker exec riskuw_frontend sh -c \
    "grep -rl 'smtp_host' /usr/share/nginx/html/assets/ 2>/dev/null | head -3" || \
    echo "  Could not check inside container"

echo ""
echo "  Checking built bundle does NOT have old r?.host pattern..."
docker exec riskuw_frontend sh -c \
    "grep -l 'smtpStatus?.host' /usr/share/nginx/html/assets/*.js 2>/dev/null && echo '❌ OLD KEY FOUND' || echo '✅ Old key not present in bundle'" || \
    echo "  Could not check"

echo ""
echo "=============================="
echo "  DONE"
echo "=============================="
echo ""
echo "  Now open browser in INCOGNITO / PRIVATE window and test:"
echo "  → http://localhost:3002  (or your app URL)"
echo "  → Go to System Config → SMTP / Email tab"
echo "  → Banner should be GREEN ✅"
echo ""
echo "  If still yellow in incognito → share output above"

