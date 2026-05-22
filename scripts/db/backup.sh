#!/usr/bin/env bash
# scripts/db/backup.sh — daily DB backup to /opt/riskuw/backups/
set -euo pipefail
BACKUP_DIR="/opt/riskuw/backups"
mkdir -p "$BACKUP_DIR"
FNAME="$BACKUP_DIR/riskuw_$(date +%Y%m%d_%H%M%S).sql.gz"
pg_dump "$DATABASE_URL" | gzip > "$FNAME"
echo "Backup written: $FNAME ($(du -sh "$FNAME" | cut -f1))"
# Keep last 14 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +14 -delete
