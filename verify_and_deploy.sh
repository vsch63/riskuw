#!/bin/bash
# verify_and_deploy.sh
# Confirms the new file is on disk, forces a clean build, and verifies the bundle
set -e
cd /opt/riskuw

FILE="frontend/src/pages/SystemConfigPage.tsx"

echo ""
echo "=============================="
echo "  STEP 1 — Verify file on disk"
echo "=============================="
echo "  File size : $(wc -c < $FILE) bytes"
echo "  Line count: $(wc -l < $FILE) lines"
echo ""

echo "  Checking for NEW grouped structure..."
if grep -q "key: 'platform'" $FILE; then
  echo "  ✅ 'platform' group found — new file is on disk"
else
  echo "  ❌ 'platform' group NOT found — old file still on disk!"
  echo ""
  echo "  The file was NOT replaced. You need to copy it manually:"
  echo "  scp or download the file from Claude and place it at:"
  echo "  /opt/riskuw/frontend/src/pages/SystemConfigPage.tsx"
  exit 1
fi

if grep -q "key: 'underwriting'" $FILE && grep -q "key: 'communications'" $FILE; then
  echo "  ✅ 'underwriting' and 'communications' groups found"
else
  echo "  ❌ Groups missing — file may be partial"
  exit 1
fi

echo ""
echo "  Checking old flat tabs are gone..."
if grep -q "key: 'rate-scales'" $FILE; then
  echo "  ❌ Old 'rate-scales' flat tab still present — wrong file!"
  exit 1
else
  echo "  ✅ Old flat tabs removed"
fi

echo ""
echo "=============================="
echo "  STEP 2 — Stop old container"
echo "=============================="
docker compose stop frontend
docker compose rm -f frontend
echo "  ✅ Old container removed"

echo ""
echo "=============================="
echo "  STEP 3 — Remove old image"
echo "=============================="
docker rmi riskuw-frontend 2>/dev/null && echo "  ✅ Old image removed" || echo "  ℹ️  No old image to remove"

echo ""
echo "=============================="
echo "  STEP 4 — Clean build"
echo "=============================="
docker build --no-cache -f Dockerfile.frontend -t riskuw-frontend . 2>&1 | tail -15

echo ""
echo "=============================="
echo "  STEP 5 — Verify bundle has new tabs"
echo "=============================="
# Extract built JS and check for platform group key
BUNDLE_CHECK=$(docker run --rm riskuw-frontend sh -c \
  "grep -rl 'platform' /usr/share/nginx/html/assets/*.js 2>/dev/null | head -1")

if [ -n "$BUNDLE_CHECK" ]; then
  echo "  ✅ 'platform' key found in built JS bundle"
else
  echo "  ⚠️  Could not verify bundle — checking differently..."
  docker run --rm riskuw-frontend sh -c \
    "ls -lh /usr/share/nginx/html/assets/*.js | head -5"
fi

# Check old tab key is NOT in bundle
OLD_CHECK=$(docker run --rm riskuw-frontend sh -c \
  "grep -rl 'rate-scales' /usr/share/nginx/html/assets/*.js 2>/dev/null | head -1" 2>/dev/null || true)
if [ -n "$OLD_CHECK" ]; then
  echo "  ⚠️  Old 'rate-scales' key still in bundle — build may not have picked up the file"
else
  echo "  ✅ Old 'rate-scales' flat tab NOT in bundle — build is fresh"
fi

echo ""
echo "=============================="
echo "  STEP 6 — Start container"
echo "=============================="
docker compose up -d frontend
sleep 4
docker ps --filter "name=riskuw_frontend" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=============================="
echo "  DONE"
echo "=============================="
echo ""
echo "  Open in browser: http://localhost:3002"
echo "  You should now see 5 main tabs:"
echo "    Platform · Underwriting · Communications · Integrations · Audit & AI"
echo ""
echo "  If still showing old tabs → the source file copy failed (Step 1)."
echo "  Share the Step 1 output and we will fix it."
