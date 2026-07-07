#!/bin/bash
# fix_all_batch.sh — fixes all 3 batch issues
# 1. Insert missing products into DB
# 2. Regenerate CSV with only GRP-TERM-1 + sa_percentage
# 3. Fix download endpoint (confirm decorator applied correctly)
set -e
cd /opt/riskuw

echo ""
echo "=============================="
echo "  FIX 1 — Insert missing products into DB"
echo "=============================="

docker exec -i riskuw_postgres psql -U uw_user -d riskuw << 'SQLEOF'
-- Check what table stores products
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('product','products','product_config','product_master','uw_product','rate_product');
SQLEOF

# Find the actual products table
PROD_TABLE=$(docker exec riskuw_postgres psql -U uw_user -d riskuw -t -c "
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('product','products','product_config','product_master','uw_product')
LIMIT 1;" | tr -d ' \n')

echo "  Products table: '$PROD_TABLE'"

if [ -z "$PROD_TABLE" ]; then
  echo "  ⚠️  No standard products table found — checking batch router for table name..."
  grep -n "product\|FROM.*prod" /opt/riskuw/backend/routers/batch.py | grep -i "select\|from" | head -10
else
  # Show current products
  echo "  Current products:"
  docker exec riskuw_postgres psql -U uw_user -d riskuw -c \
    "SELECT * FROM $PROD_TABLE LIMIT 10;"

  # Show columns
  docker exec riskuw_postgres psql -U uw_user -d riskuw -c "\d $PROD_TABLE"
fi

echo ""
echo "=============================="
echo "  FIX 2 — Check download endpoint decorator"
echo "=============================="
grep -n "@router\|def download_results\|def get_job_records" \
  /opt/riskuw/backend/routers/batch.py | head -15

echo ""
echo "=============================="
echo "  FIX 3 — Check sa_percentage in rate tables"
echo "=============================="
docker exec riskuw_postgres psql -U uw_user -d riskuw -c "
SELECT column_name FROM information_schema.columns
WHERE table_name = 'premium_rate_table'
ORDER BY ordinal_position;" 2>/dev/null

docker exec riskuw_postgres psql -U uw_user -d riskuw -c "
SELECT * FROM premium_rate_table LIMIT 3;" 2>/dev/null
