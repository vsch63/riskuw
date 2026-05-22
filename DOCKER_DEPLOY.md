# RiskUW — Docker Deployment Guide
## (Co-existing with DNB)

---

## Port map — no conflicts

| Service | DNB port | RiskUW port |
|---|---|---|
| PostgreSQL | 5432 | **5433** |
| Redis | 6379 | **6380** |
| FastAPI | 8000 | **8001** |
| Frontend | 3000 | **3002** |
| Grafana | 3001 | — |
| nginx | 80/443 | host nginx (Hetzner only) |

All RiskUW containers run on `riskuw-network` — completely isolated from `dnb_*` containers.

---

## Files to copy into /opt/riskuw/

```
/opt/riskuw/
├── Dockerfile.backend        ← FastAPI + Worker image
├── Dockerfile.frontend       ← React build + nginx image
├── docker-compose.yml        ← RiskUW services (updated ports)
├── deploy.sh                 ← Deployment script
├── docker/
│   └── nginx-frontend.conf   ← nginx inside frontend container
└── nginx/
    └── riskuw.conf           ← Host nginx on Hetzner (SSL)
```

---

## Step 1 — Install Docker (Hetzner server)

```bash
ssh root@5.223.79.197

curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin

docker --version
docker compose version
```

---

## Step 2 — Copy files to Hetzner

From your local machine:

```bash
cd /path/to/riskuw

scp Dockerfile.backend           root@5.223.79.197:/opt/riskuw/
scp Dockerfile.frontend          root@5.223.79.197:/opt/riskuw/
scp docker-compose.yml           root@5.223.79.197:/opt/riskuw/
scp deploy.sh                    root@5.223.79.197:/opt/riskuw/
scp riskuw-nginx-host.conf       root@5.223.79.197:/opt/riskuw/nginx/riskuw.conf

ssh root@5.223.79.197 mkdir -p /opt/riskuw/docker
scp nginx-frontend.conf          root@5.223.79.197:/opt/riskuw/docker/
```

---

## Step 3 — Set up .env on Hetzner

```bash
ssh root@5.223.79.197
cd /opt/riskuw

# Your existing .env is mostly correct.
# Add/update these lines:
cat >> .env << 'ENVEOF'
REDIS_URL=redis://redis:6379/0
VITE_API_BASE=https://riskuw.online
ENVIRONMENT=production
ENVEOF

# Update DATABASE_URL to use container name
sed -i 's|@localhost:5432|@postgres:5432|g' .env
sed -i 's|@127.0.0.1:5432|@postgres:5432|g' .env

# Verify
grep DATABASE_URL .env
# Should show: postgresql://uw-user:password@postgres:5432/uw-platform
```

---

## Step 4 — Migrate existing data to Docker postgres

**Only needed if you have existing data on the server.**

```bash
# 1. Export from bare-metal postgres
export $(grep -v '^#' .env | xargs)
pg_dump $DATABASE_URL > /tmp/riskuw_backup.sql

# 2. Start Docker postgres first
docker compose up -d postgres
sleep 20  # wait for healthy

# 3. Import into Docker postgres (port 5433)
psql postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5433/${DB_NAME} \
  < /tmp/riskuw_backup.sql

# 4. Stop bare-metal postgres
systemctl stop postgresql
systemctl disable postgresql

echo "Migration complete"
```

---

## Step 5 — Stop bare-metal services

```bash
# Stop current bare-metal FastAPI (will be replaced by container)
systemctl stop riskuw-api    2>/dev/null || true
systemctl stop riskuw-worker 2>/dev/null || true

# Free up port 8000 if anything else holds it
fuser -k 8000/tcp 2>/dev/null || true

# Streamlit stays bare-metal for now (accessible at /uw/)
# systemctl status uw_platform_v2  ← leave this running
```

---

## Step 6 — Deploy

```bash
cd /opt/riskuw
chmod +x deploy.sh
./deploy.sh
```

Expected output:
```
✅  Pre-flight passed
✅  No port conflicts found
✅  Backend image built
✅  Frontend image built
✅  postgres healthy
✅  redis healthy
✅  fastapi healthy
✅  frontend healthy
✅  API responding on :8001
✅  RiskUW deployment complete

── Port map ─────────────────────────
  React frontend : http://localhost:3002
  FastAPI        : http://localhost:8001
  FastAPI docs   : http://localhost:8001/docs
  PostgreSQL     : localhost:5433
  Redis          : localhost:6380
```

---

## Step 7 — Update host nginx

```bash
# Apply Docker-compatible nginx config
cp /opt/riskuw/nginx/riskuw.conf /etc/nginx/sites-available/riskuw

# Test and reload
nginx -t && systemctl reload nginx

# Verify
curl -I https://riskuw.online
```

---

## Step 8 — Verify

```bash
# All containers running
docker compose ps

# API health
curl https://riskuw.online/health

# Frontend loads
curl -I https://riskuw.online

# Both DNB and RiskUW running
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
```

---

## Day-to-day operations

```bash
# Status
./deploy.sh --status

# Restart all
./deploy.sh --restart

# Restart one service
docker compose restart fastapi
docker compose restart worker
docker compose restart frontend

# Deploy backend code update
git pull
docker compose build fastapi worker
docker compose up -d fastapi worker

# Deploy frontend code update
git pull
docker compose build frontend
docker compose up -d frontend

# Tail logs
docker compose logs -f               # all
docker compose logs -f fastapi       # API only
docker compose logs -f worker        # job queue only
docker compose logs --tail=100 fastapi

# Database shell
docker exec -it riskuw_postgres psql -U uw_user -d uw_platform

# Database backup
docker exec riskuw_postgres pg_dump -U uw_user uw_platform \
  > /root/backups/riskuw_$(date +%Y%m%d_%H%M).sql

# Scale worker to 2 instances
docker compose up -d --scale worker=2
```

---

## On your laptop (local development)

Both DNB and RiskUW run simultaneously:

```bash
# Terminal 1 — DNB (already running)
cd ~/dnb && docker compose up -d

# Terminal 2 — RiskUW
cd ~/riskuw && docker compose up -d

# Access
# DNB:    http://localhost:3000
# RiskUW: http://localhost:3002
# DNB API:    http://localhost:8000
# RiskUW API: http://localhost:8001
```

---

## Rollback

```bash
# Stop Docker containers
docker compose down

# Restart bare-metal services
systemctl start postgresql
systemctl start riskuw-api
systemctl start riskuw-worker

# Restore old nginx config
systemctl reload nginx
```

---

## Troubleshooting

### Container won't start
```bash
docker compose logs fastapi
docker inspect riskuw_fastapi | grep -A5 Health
```

### 502 Bad Gateway from nginx
```bash
# Check frontend container is up
docker compose ps frontend

# Check it can reach fastapi internally
docker exec riskuw_frontend wget -q -O- http://fastapi:8000/health
```

### Database connection refused
```bash
# Check postgres is healthy
docker compose ps postgres

# Test connection from fastapi container
docker exec riskuw_fastapi python3 -c \
  "import psycopg2; psycopg2.connect('postgresql://uw_user:pass@postgres:5432/uw_platform'); print('OK')"
```

### Port conflict with DNB
```bash
# See what's using a port
ss -tlnp | grep :3002

# Check RiskUW vs DNB containers
./deploy.sh --status
```

### Frontend shows blank page / CORS error
```bash
# Rebuild with correct API URL
docker compose build \
  --build-arg VITE_API_BASE=https://riskuw.online frontend
docker compose up -d frontend
```
