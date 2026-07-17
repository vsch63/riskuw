#!/bin/bash
set -e
BASE_URL="${RISKUW_BASE_URL:-http://localhost:8001}"

echo ""
echo "=========================================="
echo "  RiskUW Automated Test Suite"
echo "  Target: $BASE_URL"
echo "=========================================="
echo ""

echo "Checking platform health..."
HEALTH=$(curl -s "$BASE_URL/health" 2>/dev/null)
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "✅ Platform is healthy"
else
    echo "❌ Platform health check failed."
    echo "   Start with: cd /opt/riskuw && docker compose up -d"
    exit 1
fi
echo ""

HTML_REPORT=""
for arg in "$@"; do
    case $arg in
        --html) HTML_REPORT="--html=report.html --self-contained-html" ;;
    esac
done

export RISKUW_BASE_URL="$BASE_URL"

case "${1}" in
    --smoke)
        python3 -m pytest -m smoke $HTML_REPORT
        ;;
    --auth)
        python3 -m pytest test_auth.py $HTML_REPORT
        ;;
    --uw)
        python3 -m pytest test_underwriting.py $HTML_REPORT
        ;;
    --batch)
        python3 -m pytest test_batch.py $HTML_REPORT
        ;;
    --agent)
        python3 -m pytest test_agent_portal.py $HTML_REPORT
        ;;
    --workbench)
        python3 -m pytest test_workbench.py $HTML_REPORT
        ;;
    --security)
        python3 -m pytest test_security.py $HTML_REPORT
        ;;
    --policy)
        python3 -m pytest test_policy.py $HTML_REPORT
        ;;
    --analytics)
        python3 -m pytest test_analytics.py $HTML_REPORT
        ;;
    --system)
        python3 -m pytest test_system_config.py $HTML_REPORT
        ;;
    *)
        # Run all — security last, then sleep to clear rate limit before final summary
        python3 -m pytest \
            test_smoke.py \
            test_auth.py \
            test_underwriting.py \
            test_batch.py \
            test_agent_portal.py \
            test_workbench.py \
            test_policy.py \
            test_analytics.py \
            test_system_config.py \
            test_security.py \
            $HTML_REPORT
        ;;
esac

echo ""
echo "=========================================="
echo "  Test run complete"
echo "=========================================="
