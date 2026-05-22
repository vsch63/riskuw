#!/usr/bin/env bash
# scripts/deploy/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
# Full deployment pipeline for riskuw.online (Hetzner Ubuntu)
# Run as the deploy user (not root).
#
# Usage:
#   ./scripts/deploy/deploy.sh              # deploy latest main
#   ./scripts/deploy/deploy.sh --skip-fe    # skip frontend build (backend only)
#   ./scripts/deploy/deploy.sh --skip-be    # skip backend restart (frontend only)
#   ./scripts/deploy/deploy.sh --tag v1.2.0 # deploy specific tag
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

APP_DIR="/opt/riskuw"
VENV_DIR="$APP_DIR/venv"
FRONTEND_DIR="$APP_DIR/frontend"
STATIC_DIR="/var/www/riskuw"
BACKEND_SERVICE="riskuw-api"
STREAMLIT_SERVICE="riskuw-streamlit"
LOG_FILE="/var/log/riskuw/deploy.log"
TAG=""
SKIP_FE=false
SKIP_BE=false

# ── Parse args ───────────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --skip-fe)  SKIP_FE=true ;;
    --skip-be)  SKIP_BE=true ;;
    --tag=*)    TAG="${arg#*=}" ;;
    --tag)      shift; TAG="$1" ;;
  esac
done

mkdir -p /var/log/riskuw
echo "──────────────────────────────────────────" | tee -a "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S')  deploy started" | tee -a "$LOG_FILE"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
echo "📥  Pulling latest code…"
cd "$APP_DIR"
git fetch --all --tags

if [[ -n "$TAG" ]]; then
  echo "   → Checking out tag $TAG"
  git checkout "$TAG"
else
  git checkout main
  git pull origin main
fi

COMMIT=$(git rev-parse --short HEAD)
echo "   → Commit: $COMMIT" | tee -a "$LOG_FILE"

# ── 2. Backend ────────────────────────────────────────────────────────────────
if [[ "$SKIP_BE" == false ]]; then
  echo "🐍  Installing Python dependencies…"
  "$VENV_DIR/bin/pip" install -q --upgrade pip
  "$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"

  # Run pending migrations (V001, V002, ... in order)
  echo "🗄️   Running migrations…"
  for mig in "$APP_DIR"/migrations/V*.sql; do
    fname=$(basename "$mig")
    echo "   + $fname"
    psql "$DATABASE_URL" -f "$mig" >> "$LOG_FILE" 2>&1 || {
      echo "⚠️   Migration $fname failed — check $LOG_FILE" >&2
    }
  done

  echo "🔄  Restarting backend service…"
  sudo systemctl restart "$BACKEND_SERVICE"
  sleep 2

  # Health check
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health || echo "000")
  if [[ "$STATUS" == "200" ]]; then
    echo "✅  Backend healthy (HTTP $STATUS)"
  else
    echo "❌  Backend health check failed (HTTP $STATUS) — rolling back!" >&2
    sudo systemctl rollback "$BACKEND_SERVICE" 2>/dev/null || true
    exit 1
  fi
fi

# ── 3. Frontend ───────────────────────────────────────────────────────────────
if [[ "$SKIP_FE" == false ]]; then
  echo "⚛️   Building React frontend…"
  cd "$FRONTEND_DIR"
  npm ci --silent
  npm run build

  echo "📦  Copying dist to nginx root…"
  sudo rsync -a --delete "$FRONTEND_DIR/dist/" "$STATIC_DIR/"
  echo "✅  Frontend deployed"

  # Reload nginx (non-destructive — no downtime)
  sudo nginx -t && sudo systemctl reload nginx
fi

# ── 4. Streamlit (optional, keep alive) ───────────────────────────────────────
if systemctl is-active --quiet "$STREAMLIT_SERVICE" 2>/dev/null; then
  echo "📊  Reloading Streamlit service…"
  sudo systemctl restart "$STREAMLIT_SERVICE"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "🎉  Deployment complete  commit=$COMMIT  $(date '+%H:%M:%S')" | tee -a "$LOG_FILE"
echo ""
