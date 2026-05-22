#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — RiskUW Docker deployment
# Docker Hub: vsch63/riskuw-backend, vsch63/riskuw-frontend
#
# LOCAL  — build + push to Docker Hub
# SERVER — pull + start containers
#
# Usage:
#   ./deploy.sh build    # build images locally
#   ./deploy.sh push     # push to Docker Hub
#   ./deploy.sh start    # pull latest + start on server
#   ./deploy.sh update   # build + push + restart (full cycle)
#   ./deploy.sh restart  # restart containers without rebuild
#   ./deploy.sh status   # show container status
#   ./deploy.sh logs     # tail all logs
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.yml"
DOCKERHUB_USER="vsch63"
BACKEND_IMAGE="$DOCKERHUB_USER/riskuw-backend:latest"
FRONTEND_IMAGE="$DOCKERHUB_USER/riskuw-frontend:latest"
VITE_API_BASE="${VITE_API_BASE:-https://riskuw.online}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; exit 1; }

CMD="${1:-help}"

# ── Help ──────────────────────────────────────────────────────────────────────
if [[ "$CMD" == "help" || "$CMD" == "--help" ]]; then
  echo -e "${BOLD}RiskUW Docker Deployment${NC} (DockerHub: $DOCKERHUB_USER)"
  echo ""
  echo "  ${CYAN}./deploy.sh build${NC}    — Build images locally"
  echo "  ${CYAN}./deploy.sh push${NC}     — Push images to Docker Hub"
  echo "  ${CYAN}./deploy.sh start${NC}    — Pull latest images + start on this machine"
  echo "  ${CYAN}./deploy.sh update${NC}   — Full cycle: build → push → restart server"
  echo "  ${CYAN}./deploy.sh restart${NC}  — Restart containers without rebuild"
  echo "  ${CYAN}./deploy.sh status${NC}   — Show all container status"
  echo "  ${CYAN}./deploy.sh logs${NC}     — Tail all logs"
  echo "  ${CYAN}./deploy.sh stop${NC}     — Stop all RiskUW containers"
  echo ""
  exit 0
fi

# ── Pre-flight ────────────────────────────────────────────────────────────────
preflight() {
  command -v docker >/dev/null 2>&1 || fail "Docker not installed"
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 not found"
}

# ── BUILD — run on local machine ──────────────────────────────────────────────
if [[ "$CMD" == "build" || "$CMD" == "update" ]]; then
  preflight
  [[ -f "$PROJECT_DIR/.env" ]] || fail ".env not found"

  log "Building backend image: $BACKEND_IMAGE"
  docker build \
    -f "$PROJECT_DIR/Dockerfile.backend" \
    -t "$BACKEND_IMAGE" \
    "$PROJECT_DIR"
  ok "Backend image built"

  log "Building frontend image: $FRONTEND_IMAGE"
  log "VITE_API_BASE=$VITE_API_BASE"
  docker build \
    -f "$PROJECT_DIR/Dockerfile.frontend" \
    --build-arg VITE_API_BASE="$VITE_API_BASE" \
    -t "$FRONTEND_IMAGE" \
    "$PROJECT_DIR"
  ok "Frontend image built"

  # Show image sizes
  echo ""
  echo -e "${BOLD}── Built images ──────────────────────────────────${NC}"
  docker images | grep "vsch63/riskuw"
  echo ""

  [[ "$CMD" == "build" ]] && exit 0
fi

# ── PUSH — push to Docker Hub ─────────────────────────────────────────────────
if [[ "$CMD" == "push" || "$CMD" == "update" ]]; then
  preflight
  log "Logging in to Docker Hub as $DOCKERHUB_USER..."
  docker login -u "$DOCKERHUB_USER" || fail "Docker Hub login failed"

  log "Pushing $BACKEND_IMAGE..."
  docker push "$BACKEND_IMAGE"
  ok "Backend pushed → hub.docker.com/r/$DOCKERHUB_USER/riskuw-backend"

  log "Pushing $FRONTEND_IMAGE..."
  docker push "$FRONTEND_IMAGE"
  ok "Frontend pushed → hub.docker.com/r/$DOCKERHUB_USER/riskuw-frontend"

  [[ "$CMD" == "push" ]] && exit 0
fi

# ── START — run on server (pull + up) ─────────────────────────────────────────
if [[ "$CMD" == "start" || "$CMD" == "update" ]]; then
  preflight
  [[ -f "$PROJECT_DIR/.env" ]] || fail ".env not found at $PROJECT_DIR/.env"

  # Warn if default passwords still set
  grep -q "CHANGE_THIS" "$PROJECT_DIR/.env" && \
    warn ".env still has placeholder values — update before production use"

  # Port conflict check
  log "Checking ports..."
  for port in 3002 5433 6380 8001; do
    if ss -tlnp 2>/dev/null | grep -q ":$port " && \
       ! docker ps --filter "name=riskuw_" --format "{{.Ports}}" 2>/dev/null | grep -q ":$port->"; then
      warn "Port $port already in use — may conflict"
    fi
  done

  log "Pulling latest images from Docker Hub..."
  $COMPOSE pull
  ok "Images pulled"

  # Clean Zone.Identifier files (Windows upload artifacts)
  find "$PROJECT_DIR/migrations/" -name "*.Identifier" -delete 2>/dev/null || true

  log "Starting RiskUW containers..."
  $COMPOSE up -d
  ok "Containers started"

  # Wait for health
  wait_healthy() {
    local name=$1 max=${2:-60} waited=0
    log "Waiting for $name..."
    while [[ $waited -lt $max ]]; do
      status=$(docker inspect --format='{{.State.Health.Status}}' \
        "riskuw_$name" 2>/dev/null || echo "starting")
      [[ "$status" == "healthy" ]] && { ok "$name healthy"; return 0; }
      sleep 3; waited=$((waited+3)); echo -n "."
    done
    echo ""; warn "$name timed out — check: docker logs riskuw_$name"
  }

  wait_healthy postgres 60
  wait_healthy redis    30
  wait_healthy fastapi  90
  wait_healthy frontend 60

  # API smoke test
  sleep 3
  curl -sf http://127.0.0.1:8001/health > /dev/null 2>&1 && \
    ok "API responding on :8001" || \
    warn "API not responding yet — check: docker logs riskuw_fastapi"

  # Summary
  echo ""
  echo -e "${BOLD}── RiskUW containers ─────────────────────────────${NC}"
  $COMPOSE ps
  echo ""
  echo -e "${BOLD}── Port map ──────────────────────────────────────${NC}"
  echo -e "  Frontend : ${CYAN}http://localhost:3002${NC}"
  echo -e "  FastAPI  : ${CYAN}http://localhost:8001${NC}"
  echo -e "  API docs : ${CYAN}http://localhost:8001/docs${NC}"
  echo -e "  Postgres : ${CYAN}localhost:5433${NC}"
  echo -e "  Redis    : ${CYAN}localhost:6380${NC}"
  echo ""
  ok "RiskUW is live"
fi

# ── RESTART ───────────────────────────────────────────────────────────────────
if [[ "$CMD" == "restart" ]]; then
  preflight
  log "Restarting RiskUW containers..."
  $COMPOSE restart
  ok "All RiskUW containers restarted"
  $COMPOSE ps
fi

# ── STATUS ────────────────────────────────────────────────────────────────────
if [[ "$CMD" == "status" ]]; then
  echo -e "\n${BOLD}── RiskUW (vsch63) ───────────────────────────────${NC}"
  $COMPOSE ps 2>/dev/null || echo "RiskUW not running"
  echo -e "\n${BOLD}── DNB (running alongside) ───────────────────────${NC}"
  docker ps --filter "name=dnb_" \
    --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}" 2>/dev/null || true
fi

# ── LOGS ──────────────────────────────────────────────────────────────────────
if [[ "$CMD" == "logs" ]]; then
  $COMPOSE logs -f
fi

# ── STOP ──────────────────────────────────────────────────────────────────────
if [[ "$CMD" == "stop" ]]; then
  log "Stopping RiskUW containers (data preserved)..."
  $COMPOSE down
  ok "RiskUW stopped — DNB still running"
fi
