#!/bin/bash
# RiskUW Automated Test Runner
# Usage: ./run_tests.sh [options]
#   --smoke       Run smoke tests only
#   --auth        Run auth tests only
#   --uw          Run underwriting tests only
#   --agent       Run agent portal tests only
#   --security    Run security tests only
#   --all         Run all tests (default)
#   --html        Generate HTML report

set -e
BASE_URL="${RISKUW_BASE_URL:-http://localhost:8001}"

echo ""
echo "=========================================="
echo "  RiskUW Automated Test Suite"
echo "  Target: $BASE_URL"
echo "=========================================="
echo ""

# Check platform is up
echo "Checking platform health..."
HEALTH=$(curl -s "$BASE_URL/health" 2>/dev/null)
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "✅ Platform is healthy"
else
    echo "❌ Platform health check failed. Is RiskUW running?"
    echo "   Start with: cd /opt/riskuw && docker compose up -d"
    exit 1
fi

echo ""

ARGS=""
HTML_REPORT=""

for arg in "$@"; do
    case $arg in
        --smoke)     ARGS="-m smoke" ;;
        --auth)      ARGS="test_auth.py" ;;
        --uw)        ARGS="test_underwriting.py" ;;
        --batch)     ARGS="test_batch.py" ;;
        --agent)     ARGS="test_agent_portal.py" ;;
        --workbench) ARGS="test_workbench.py" ;;
        --security)  ARGS="test_security.py" ;;
        --policy)    ARGS="test_policy.py" ;;
        --analytics) ARGS="test_analytics.py" ;;
        --html)      HTML_REPORT="--html=report.html --self-contained-html" ;;
        --all|*)     ARGS="" ;;
    esac
done

export RISKUW_BASE_URL="$BASE_URL"
#python3 -m pytest $ARGS $HTML_REPORT "$@"
python3 -m pytest $ARGS $HTML_REPORT

echo ""
echo "=========================================="
echo "  Test run complete"
echo "=========================================="
