# ─────────────────────────────────────────────────────────────────────────────
# RiskUW Platform — Makefile
# Usage:  make <target>
# ─────────────────────────────────────────────────────────────────────────────

PYTHON   := ./venv/bin/python
PIP      := ./venv/bin/pip
UVICORN  := ./venv/bin/uvicorn
PYTEST   := ./venv/bin/pytest
APP_DIR  := backend

.PHONY: help install dev test test-unit test-api lint fmt \
        migrate seed-demo create-tenant create-user \
        build-frontend deploy backup db-shell

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────

install:        ## Create venv and install all Python dependencies
	python3 -m venv venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "✅  Backend venv ready. Run: source venv/bin/activate"

install-fe:     ## Install frontend npm dependencies
	cd frontend && npm install

# ── Development ───────────────────────────────────────────────────────────────

dev:            ## Start FastAPI with hot-reload (dev mode)
	cd $(APP_DIR) && $(UVICORN) main:app --host 127.0.0.1 --port 8000 --reload

dev-fe:         ## Start Vite dev server (frontend)
	cd frontend && npm run dev

dev-all:        ## Start both backend + frontend (requires two terminals or use tmux)
	@echo "Run in separate terminals:"
	@echo "  Terminal 1: make dev"
	@echo "  Terminal 2: make dev-fe"

# ── Testing ───────────────────────────────────────────────────────────────────

test:           ## Run all tests
	cd $(APP_DIR) && $(PYTEST) tests/ -v

test-unit:      ## Run unit tests only (no DB required)
	cd $(APP_DIR) && $(PYTEST) tests/test_evaluate.py tests/test_reinsurance.py \
	  -v -k "not api"

test-api:       ## Run API integration tests (requires running DB)
	cd $(APP_DIR) && $(PYTEST) tests/ -v -k "api or client"

test-auth:      ## Run auth tests only
	cd $(APP_DIR) && $(PYTEST) tests/test_auth.py -v

test-cov:       ## Run tests with coverage report
	cd $(APP_DIR) && $(PYTEST) tests/ --cov=. --cov-report=html --cov-report=term-missing
	@echo "Coverage report: $(APP_DIR)/htmlcov/index.html"

# ── Code quality ──────────────────────────────────────────────────────────────

lint:           ## Run ruff linter
	$(PYTHON) -m ruff check $(APP_DIR)/

fmt:            ## Auto-format with ruff
	$(PYTHON) -m ruff format $(APP_DIR)/

typecheck:      ## Run mypy type checks
	$(PYTHON) -m mypy $(APP_DIR)/ --ignore-missing-imports

# ── Database ──────────────────────────────────────────────────────────────────

# Edit Makefile, find the migrate target and replace it:
migrate:
	@for f in migrations/V*.sql; do \
	  echo "Applying $$f..."; \
	  psql "$$DATABASE_URL" -f "$$f"; \
	done
	@echo "✅  Migrations complete"

migrate-v002:   ## Apply only V002 (RI cession trigger)
	psql "$$DATABASE_URL" -f migrations/V002__ri_cession_trigger.sql

db-shell:       ## Open psql shell to the configured database
	psql "$$DATABASE_URL"

backup:         ## Backup database to backups/ directory
	./scripts/db/backup.sh

# ── Bootstrap ─────────────────────────────────────────────────────────────────

create-tenant:  ## Create a new tenant (prompts for name/code/email)
	$(PYTHON) scripts/admin/create_tenant.py

create-tenant-demo: ## Create demo tenant with default values
	$(PYTHON) scripts/admin/create_tenant.py --demo

create-user:    ## Create a user (set TENANT_ID env var first)
	@test -n "$$TENANT_ID" || (echo "❌  Set TENANT_ID=<uuid> first"; exit 1)
	$(PYTHON) scripts/admin/create_user.py \
	  --username admin \
	  --email admin@riskuw.online \
	  --password "ChangeMe123!" \
	  --role admin \
	  --tenant-id "$$TENANT_ID" \
	  --mfa

seed-demo:      ## Seed demo products and decisions (set TENANT_ID env var first)
	@test -n "$$TENANT_ID" || (echo "❌  Set TENANT_ID=<uuid> first"; exit 1)
	$(PYTHON) scripts/db/seed_demo_data.py --tenant-id "$$TENANT_ID"

bootstrap:      ## Full bootstrap: create demo tenant + admin user + seed data
	@echo "Step 1/3: Creating demo tenant..."
	$(PYTHON) scripts/admin/create_tenant.py --demo 2>&1 | tee /tmp/riskuw_tenant.txt
	@TENANT_ID=$$(grep "DEFAULT_TENANT_ID=" /tmp/riskuw_tenant.txt | cut -d= -f2); \
	  echo "Step 2/3: Creating admin user (tenant=$$TENANT_ID)..."; \
	  $(PYTHON) scripts/admin/create_user.py \
	    --username admin --email admin@riskuw.online \
	    --password "ChangeMe123!" --role admin \
	    --tenant-id "$$TENANT_ID"; \
	  echo "Step 3/3: Seeding demo data..."; \
	  $(PYTHON) scripts/db/seed_demo_data.py --tenant-id "$$TENANT_ID"; \
	  echo "✅  Bootstrap complete. Visit http://localhost:8000/docs"

# ── Frontend ──────────────────────────────────────────────────────────────────

build-frontend: ## Build React frontend for production
	cd frontend && npm run build
	@echo "✅  Frontend built → frontend/dist/"

deploy-frontend: build-frontend ## Build and copy to nginx root
	sudo rsync -a --delete frontend/dist/ /var/www/riskuw/
	sudo nginx -t && sudo systemctl reload nginx
	@echo "✅  Frontend deployed"

# ── Production deploy ─────────────────────────────────────────────────────────

deploy:         ## Full production deploy (backend + frontend)
	./scripts/deploy/deploy.sh

deploy-be:      ## Backend only deploy
	./scripts/deploy/deploy.sh --skip-fe

deploy-fe:      ## Frontend only deploy
	./scripts/deploy/deploy.sh --skip-be

logs:           ## Tail FastAPI logs
	sudo journalctl -u riskuw-api -f

status:         ## Check service status
	sudo systemctl status riskuw-api
	@echo "---"
	curl -s http://127.0.0.1:8000/health | python3 -m json.tool
