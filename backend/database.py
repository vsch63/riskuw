"""
backend/database.py
────────────────────
PostgreSQL connection pool.
Every router does:
    conn = get_conn()
    try:
        cur = conn.cursor()
        ...
        conn.commit()
    finally:
        release_conn(conn)

Uses psycopg2.extras.RealDictCursor so rows come back as dicts,
matching the existing Streamlit code's pattern.
"""
from __future__ import annotations

import logging
import threading

import psycopg2
import psycopg2.extras
import psycopg2.pool

from config import cfg

logger = logging.getLogger("uw_platform")

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_lock = threading.Lock()


def _init_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=cfg.db_pool_min,
                maxconn=cfg.db_pool_max,
                dsn=cfg.database_url,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            logger.info(
                "DB pool created",
                extra={"min": cfg.db_pool_min, "max": cfg.db_pool_max},
            )
    return _pool


def get_conn() -> psycopg2.extensions.connection:
    """Borrow a connection from the pool."""
    pool = _pool or _init_pool()
    conn = pool.getconn()
    conn.autocommit = False
    return conn


def release_conn(conn: psycopg2.extensions.connection) -> None:
    """Return a connection to the pool.  Always call in a finally block."""
    if _pool and conn:
        try:
            _pool.putconn(conn)
        except Exception as exc:
            logger.warning("release_conn failed", exc_info=exc)


def close_pool() -> None:
    """Called on app shutdown."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("DB pool closed")


def health_check() -> bool:
    """Returns True if the DB is reachable."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        release_conn(conn)
        return True
    except Exception as exc:
        logger.error("DB health check failed", exc_info=exc)
        return False
