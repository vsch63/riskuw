#!/bin/bash
# find_port.sh — finds RiskUW backend port and tests login
# Run: bash find_port.sh --user admin --password yourpassword

USER=""
PASS=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --user)     USER="$2";  shift 2 ;;
    --password) PASS="$2";  shift 2 ;;
    *)          shift ;;
  esac
done

if [ -z "$USER" ]; then read -p "Username: " USER; fi
if [ -z "$PASS" ]; then read -sp "Password: " PASS; echo; fi

echo ""
echo "=============================="
echo "  STEP 1 — Find backend port"
echo "=============================="

# Check listening ports for Python/uvicorn/gunicorn processes
echo ""
echo "--- Processes listening on network ports ---"
ss -tlnp 2>/dev/null | grep -E "python|uvicorn|gunicorn|LISTEN" || \
  netstat -tlnp 2>/dev/null | grep -E "python|uvicorn|gunicorn"

echo ""
echo "--- All listening TCP ports ---"
ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null

echo ""
echo "--- Docker containers and their ports ---"
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}" 2>/dev/null

echo ""
echo "--- Docker compose services ---"
docker compose ps 2>/dev/null || docker-compose ps 2>/dev/null

echo ""
echo "=============================="
echo "  STEP 2 — Try common ports"
echo "=============================="

PAYLOAD="{\"username\":\"$USER\",\"password\":\"$PASS\"}"

for PORT in 8000 8001 8080 8888 5000 5001 3000 4000 9000; do
  URL="http://localhost:$PORT/auth/login"
  STATUS=$(curl -s -o /tmp/resp.json -w "%{http_code}" -X POST "$URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" --connect-timeout 2 2>/dev/null)
  if [ "$STATUS" != "000" ]; then
    echo "  Port $PORT → HTTP $STATUS"
    if [ "$STATUS" = "200" ] || [ "$STATUS" = "201" ]; then
      echo "  ✅ LOGIN SUCCESS on port $PORT"
      echo "  Response: $(cat /tmp/resp.json)"
      echo ""
      echo "  Use this URL: http://localhost:$PORT"
      TOKEN=$(cat /tmp/resp.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null)
      if [ -n "$TOKEN" ]; then
        echo ""
        echo "=============================="
        echo "  STEP 3 — Check SMTP endpoint"
        echo "=============================="
        SMTP=$(curl -s -X GET "http://localhost:$PORT/system/smtp" \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json")
        echo "  GET /system/smtp → $SMTP"
        
        KEYS=$(echo "$SMTP" | python3 -c "
import sys,json
try:
  d=json.loads(sys.stdin.read())
  print('Keys:', list(d.keys()))
  if d.get('smtp_host'): print('  ✅ Returns smtp_host =', d['smtp_host'])
  elif d.get('host'):    print('  ⚠️  Returns host =', d['host'], '(short key — frontend needs to match)')
  elif not any(d.values()): print('  ⚠️  All empty — SMTP never saved to DB')
except: print('  Could not parse response')
" 2>/dev/null)
        echo "  $KEYS"
      fi
      break
    elif [ "$STATUS" = "401" ]; then
      echo "  ⚠️  Port $PORT responded but wrong credentials"
    fi
  fi
done

echo ""
echo "=============================="
echo "  STEP 4 — Check .env / config"
echo "=============================="
echo "--- .env files ---"
find /opt/riskuw -name ".env" -o -name "*.env" 2>/dev/null | head -10 | while read f; do
  echo "  $f:"
  grep -i "port\|host\|backend\|api_url" "$f" 2>/dev/null | grep -v "PASSWORD\|SECRET\|KEY" | head -10
done

echo ""
echo "--- docker-compose port mappings ---"
grep -i "ports\|8000\|8080\|5000" /opt/riskuw/docker-compose*.yml 2>/dev/null | head -20

