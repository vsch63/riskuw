# RiskUW Platform — Quickstart

Complete setup guide from a fresh Hetzner server to a live demo at riskuw.online.

---

## First-time server setup (run once)

```bash
# 1. Create app user and directory
sudo useradd -m -s /bin/bash uw_user
sudo mkdir -p /opt/riskuw /var/www/riskuw /var/log/riskuw
sudo chown -R uw_user:uw_user /opt/riskuw /var/www/riskuw /var/log/riskuw

# 2. Clone repo
sudo -u uw_user git clone https://github.com/your-org/riskuw.git /opt/riskuw

# 3. Python venv
sudo -u uw_user python3 -m venv /opt/riskuw/venv
sudo -u uw_user /opt/riskuw/venv/bin/pip install -r /opt/riskuw/requirements.txt

# 4. Environment
sudo -u uw_user cp /opt/riskuw/.env.example /opt/riskuw/.env
sudo chmod 600 /opt/riskuw/.env
# → edit /opt/riskuw/.env  (DB password, JWT secret, SMTP)

# 5. Database
sudo -u postgres psql -c "CREATE USER uw_user WITH PASSWORD 'CHANGE_ME';"
sudo -u postgres psql -c "CREATE DATABASE riskuw OWNER uw_user;"
sudo -u postgres psql -c "GRANT ALL ON SCHEMA public TO uw_user;"
psql $DATABASE_URL -f /opt/riskuw/migrations/V001__initial_schema.sql
psql $DATABASE_URL -f /opt/riskuw/migrations/V002__ri_cession_trigger.sql
```

---

## Bootstrap tenant and admin user

```bash
cd /opt/riskuw

# Step 1 — Create tenant (copy the printed tenant ID)
python scripts/admin/create_tenant.py \
  --name "Your Insurance Co." \
  --code YOUR_CODE \
  --email admin@yourco.com

# Step 2 — Create admin user (paste tenant ID from step 1)
python scripts/admin/create_user.py \
  --username admin \
  --email admin@yourco.com \
  --password "S3cur3Pass!" \
  --role admin \
  --tenant-id <TENANT_UUID_FROM_STEP_1> \
  --mfa

# Step 3 — Seed demo data for pitch
python scripts/db/seed_demo_data.py --tenant-id <TENANT_UUID>
```

---

## Start services

```bash
# Install systemd units
sudo cp /opt/riskuw/systemd/riskuw-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now riskuw-api

# Verify
sudo systemctl status riskuw-api
curl http://127.0.0.1:8000/health   # → {"status": "ok"}

# Install nginx config
sudo ln -s /opt/riskuw/nginx/riskuw.conf /etc/nginx/sites-enabled/riskuw.conf
sudo nginx -t && sudo systemctl reload nginx

# TLS (first time only)
sudo certbot --nginx -d riskuw.online -d www.riskuw.online
```

---

## Deploy updates

```bash
./scripts/deploy/deploy.sh              # full deploy (backend + frontend)
./scripts/deploy/deploy.sh --skip-fe    # backend only
./scripts/deploy/deploy.sh --skip-be    # frontend only
./scripts/deploy/deploy.sh --tag v1.2.0 # specific release
```

---

## Known issues / immediate TODOs

| Priority | File | Issue |
|---|---|---|
| 🔴 CRITICAL | `backend/deps.py` | `TokenData.username` was missing — **fixed in this PR** |
| 🔴 CRITICAL | `scripts/admin/create_tenant.py` | Run this before ANY user login or API call |
| 🟡 HIGH | `migrations/V002__ri_cession_trigger.sql` | Run to activate auto RI cession on high face-amount approvals |
| 🟡 HIGH | `scripts/db/seed_demo_data.py` | Run before carrier demos to have realistic data |
| 🟠 MEDIUM | `backend/routers/reinsurance.py` | Manual RI cession route still needs building (auto-trigger is now in V002) |
| 🟠 MEDIUM | `backend/services/batch_processor.py` | Batch job worker — extract from Streamlit into FastAPI background task |

---

## Architecture quick reference

```
riskuw.online (HTTPS)
    │
    ├── / → nginx → /var/www/riskuw/    React SPA (Vite build)
    ├── /auth /products /underwriting
    │   /queue /batch /tenants  → uvicorn :8000  FastAPI
    │                                    │
    │                              PostgreSQL :5432
    │                              (37 tables, owner: uw_user)
    │
    └── /streamlit/ → Streamlit :8501   (legacy, running in parallel)
```

---

## Table → router mapping (quick lookup)

| Table(s) | Router file |
|---|---|
| `uw_user` · `mfa_config` · `login_attempts` | `routers/auth.py` |
| `application` · `applicant_master` | `routers/underwriting.py` |
| `uw_case` · `uw_decision` · `aps_request` | `routers/queue.py` |
| `product` · `product_rules` · `product_decision_thresholds` | `routers/products.py` |
| `batch_jobs` · `batch_job_records` · `batch_recurring_schedules` | `routers/batch.py` |
| `tenant` · `system_config` · `tenant_rule_config` | `routers/tenants.py` |
| `aps_request` · `letter_templates` · `physicians` | `routers/aps.py` |
| `ri_cession` · `ri_reinsurer` | `routers/reinsurance.py` |
| `user_authority_limits` | `routers/users.py` |
