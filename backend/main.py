"""
backend/main.py
────────────────
FastAPI application entry point.

Start with:
    uvicorn main:app --host 127.0.0.1 --port 8000 --reload   (dev)
    (production via systemd/riskuw-api.service)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import cfg
from database import close_pool, health_check, _init_pool
from routers.audit import router as audit_router

# ── Structured JSON logger (same pattern as uw_platform.py) ──────────────────
import json
import traceback as _tb

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level":     record.levelname,
            "logger":    record.name,
            "function":  record.funcName,
            "line":      record.lineno,
            "message":   record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", cfg.log_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("uw_platform")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RiskUW API starting up", extra={"env": cfg.environment})
    _init_pool()          # pre-warm the connection pool
    cfg.log_startup_summary()
    yield
    logger.info("RiskUW API shutting down")
    close_pool()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RiskUW Underwriting API",
    description="Automated underwriting engine for Indian insurance carriers.",
    version="1.0.0",
    docs_url="/docs" if not cfg.is_production else None,
    redoc_url="/redoc" if not cfg.is_production else None,
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# In production nginx strips the origin header so only localhost matters here.
# Add your actual domain if calling the API directly from the browser.
_origins = [
    "http://localhost:5173",     # Vite dev server
    "http://localhost:3000",
    "https://riskuw.online",
    "https://www.riskuw.online",
]
if not cfg.is_production:
    _origins.append("*")         # wide open in dev


# ─────────────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["ops"], include_in_schema=False)
def health():
    db_ok = health_check()
    status = "ok" if db_ok else "degraded"
    return JSONResponse(
        content={"status": status, "db": "ok" if db_ok else "error"},
        status_code=200 if db_ok else 503,
    )


# ── Routers ───────────────────────────────────────────────────────────────────
from routers.auth          import router as auth_router
from routers.products      import router as products_router
from routers.underwriting  import router as uw_router
from routers.queue         import router as queue_router
from routers.batch         import router as batch_router
from routers.tenants       import router as tenants_router
from routers.users         import router as users_router
from routers.aps           import router as aps_router
from routers.system        import router as system_router
from routers.uw_scales        import router as uw_scales_router        # ← NEW
from routers.rules            import router as rules_router              # ← NEW
from routers.premium_formula  import router as premium_formula_router
from routers.gst_modal        import router as gst_modal_router
from routers.members          import router as members_router
from routers.gst_modal        import router as gst_modal_router
from routers.members          import router as members_router    # ← NEW
from routers.user_labels      import router as user_labels_router        # ← NEW

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(uw_router)
app.include_router(queue_router)
app.include_router(batch_router)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(aps_router)
app.include_router(system_router)
app.include_router(audit_router)
app.include_router(uw_scales_router,       prefix="/uw-scales",       tags=["UW Scales"])       # ← NEW
app.include_router(rules_router)                                                                 # ← NEW
app.include_router(premium_formula_router)
app.include_router(gst_modal_router)
app.include_router(members_router)
app.include_router(gst_modal_router)
app.include_router(members_router)                                                       # ← NEW
app.include_router(user_labels_router)                                                           # ← NEW

# Optional: reinsurance router (stub until V002 trigger is live)
try:
    from routers.reinsurance import router as ri_router
    app.include_router(ri_router)
except ImportError:
    logger.warning("routers/reinsurance.py not found — RI endpoints disabled")


# ── Global exception handler ──────────────────────────────────────────────────
from fastapi import Request
from fastapi.responses import JSONResponse as _JSONResponse


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    import traceback, sys
    from fastapi import HTTPException as _HTTPEx
    # ✅ Do NOT swallow HTTPExceptions — let FastAPI handle them normally
    if isinstance(exc, _HTTPEx):
        return _JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    tb = traceback.format_exc()
    print(f"[UNHANDLED ERROR] path={request.url} error={tb}", flush=True, file=sys.stdout)
    logger.error(
        "Unhandled exception",
        exc_info=exc,
        extra={"path": str(request.url)},
    )
    return _JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
