"""
routers/analytics.py
─────────────────────────────────────────────────────────────────────────────
GET /analytics/summary        — platform analytics summary
GET /underwriting/analytics   — underwriting-specific analytics
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from deps import CurrentUser

router = APIRouter(tags=["analytics"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


@router.get("/analytics/summary")
def analytics_summary(
    date_from: str = Query(default="2000-01-01"),
    date_to:   str = Query(default="2099-12-31"),
    current:   CurrentUser = None,
):
    """Platform analytics — decisions, STP rate, volumes, trends."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # ── Core decision counts ──────────────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*)                                                        AS total_cases,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%APPROVED%%')            AS approved,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%DECLINED%%')            AS declined,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%REFERRED%%')            AS referred,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%STP%%')                 AS stp_count,
                COUNT(*) FILTER (WHERE status = 'ERROR')                        AS errored,
                ROUND(AVG(processing_ms))                                       AS avg_processing_ms
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND created_at BETWEEN %s AND %s
        """, (date_from, date_to + " 23:59:59"))
        core = dict(cur.fetchone() or {})

        total = core.get("total_cases") or 0
        stp   = core.get("stp_count") or 0

        # ── Daily volume trend (last 30 days within range) ────────────────────
        cur.execute("""
            SELECT
                DATE(created_at)                                                AS day,
                COUNT(*)                                                        AS total,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%APPROVED%%')            AS approved,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%DECLINED%%')            AS declined,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%REFERRED%%')            AS referred
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND created_at BETWEEN %s AND %s
            GROUP BY DATE(created_at)
            ORDER BY day DESC
            LIMIT 30
        """, (date_from, date_to + " 23:59:59"))
        daily_trend = [dict(r) for r in cur.fetchall()]
        for row in daily_trend:
            if row.get("day"):
                row["day"] = str(row["day"])

        # ── Outcome distribution ──────────────────────────────────────────────
        cur.execute("""
            SELECT
                CASE
                    WHEN outcome ILIKE '%%APPROVED_STP%%' THEN 'APPROVED_STP'
                    WHEN outcome ILIKE '%%APPROVED%%'     THEN 'APPROVED'
                    WHEN outcome ILIKE '%%DECLINED%%'     THEN 'DECLINED'
                    WHEN outcome ILIKE '%%REFERRED%%'     THEN 'REFERRED'
                    ELSE 'OTHER'
                END                                                             AS outcome,
                CASE
                    WHEN outcome ILIKE '%%STP%%'      THEN 'STRAIGHT_THROUGH'
                    WHEN outcome ILIKE '%%DECLINED%%' THEN 'INSTANT_DECLINE'
                    ELSE 'REFERRED_UW'
                END                                                             AS uw_pathway,
                COUNT(*)                                                        AS count
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND created_at BETWEEN %s AND %s
            GROUP BY 1, 2
            ORDER BY count DESC
        """, (date_from, date_to + " 23:59:59"))
        outcome_dist = [dict(r) for r in cur.fetchall()]

        # ── Risk class distribution ───────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(NULLIF(risk_class,''), 'UNKNOWN')                      AS risk_class,
                COUNT(*)                                                        AS count
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND outcome ILIKE '%%APPROVED%%'
              AND created_at BETWEEN %s AND %s
            GROUP BY risk_class
            ORDER BY count DESC
        """, (date_from, date_to + " 23:59:59"))
        risk_dist = [dict(r) for r in cur.fetchall()]

        # ── Top products ──────────────────────────────────────────────────────
        cur.execute("""
            SELECT
                product_code,
                COUNT(*)                                                        AS total,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%APPROVED%%')            AS approved,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%DECLINED%%')            AS declined
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND created_at BETWEEN %s AND %s
              AND product_code IS NOT NULL
            GROUP BY product_code
            ORDER BY total DESC
            LIMIT 10
        """, (date_from, date_to + " 23:59:59"))
        top_products = [dict(r) for r in cur.fetchall()]

        # ── Top decline reasons ───────────────────────────────────────────────
        cur.execute("""
            SELECT
                COALESCE(NULLIF(primary_reason,''), 'Unknown') AS reason,
                COUNT(*)                                       AS count
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND outcome ILIKE '%%DECLINED%%'
              AND created_at BETWEEN %s AND %s
              AND primary_reason IS NOT NULL AND primary_reason != ''
            GROUP BY primary_reason
            ORDER BY count DESC
            LIMIT 10
        """, (date_from, date_to + " 23:59:59"))
        top_declines = [dict(r) for r in cur.fetchall()]

        # ── Batch job stats ───────────────────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*)                                                        AS total_jobs,
                SUM(total_records)                                              AS total_records,
                SUM(processed_count)                                            AS total_processed,
                SUM(approved_count)                                             AS total_approved,
                SUM(declined_count)                                             AS total_declined,
                SUM(errored_count)                                              AS total_errored,
                COUNT(*) FILTER (WHERE status='COMPLETED')                      AS completed_jobs,
                COUNT(*) FILTER (WHERE status='FAILED')                         AS failed_jobs
            FROM batch_jobs
            WHERE submitted_at BETWEEN %s AND %s
              AND dry_run = false
        """, (date_from, date_to + " 23:59:59"))
        batch_stats = dict(cur.fetchone() or {})

        # ── Premium stats ─────────────────────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE premium IS NOT NULL AND premium > 0)     AS cases_with_premium,
                ROUND(AVG(premium) FILTER (WHERE premium > 0), 2)               AS avg_premium,
                ROUND(SUM(premium) FILTER (WHERE premium > 0), 2)               AS total_premium
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND outcome ILIKE '%%APPROVED%%'
              AND created_at BETWEEN %s AND %s
        """, (date_from, date_to + " 23:59:59"))
        premium_stats = dict(cur.fetchone() or {})

        cur.close()

        approved_count = int(core.get("approved") or 0)
        declined_count = int(core.get("declined") or 0)
        referred_count = int(core.get("referred") or 0)
        stp_int        = int(stp)
        total_int      = int(total)

        return {
            # Legacy fields (direct)
            "date_from":      date_from,
            "date_to":        date_to,
            "total_cases":    total_int,
            "approved":       approved_count,
            "declined":       declined_count,
            "referred":       referred_count,
            "errored":        int(core.get("errored") or 0),
            "stp_count":      stp_int,
            "stp_rate":       round(stp_int / total_int * 100, 1) if total_int > 0 else 0,
            "approval_rate":  round(approved_count / total_int * 100, 1) if total_int > 0 else 0,
            "avg_processing_ms": int(core.get("avg_processing_ms") or 0),

            # Component-compatible fields
            "period": {
                "from": date_from,
                "to":   date_to,
            },
            "outcomes": outcome_dist,   # [{outcome_group, count}]
            "trend":    list(reversed(daily_trend)),  # oldest first
            "risk_classes": risk_dist,
            "top_products": top_products,
            "top_declines": top_declines,

            # SLA stats (from queue/cases if available, else zeros)
            "sla": {
                "open_cases":    0,
                "breached":      0,
                "avg_sla_hours": 0,
            },

            # Batch stats mapped to component field names
            "batch": {
                "total_jobs":      int(batch_stats.get("total_jobs") or 0),
                "total_records":   int(batch_stats.get("total_records") or 0),
                "total_processed": int(batch_stats.get("total_processed") or 0),
                "error":           None,
            },

            # Premium
            "premium": {
                "cases":   int(premium_stats.get("cases_with_premium") or 0),
                "average": float(premium_stats.get("avg_premium") or 0),
                "total":   float(premium_stats.get("total_premium") or 0),
            },
        }
    finally:
        release(conn)


@router.get("/underwriting/analytics")
def uw_analytics(
    date_from: str = Query(default="2000-01-01"),
    date_to:   str = Query(default="2099-12-31"),
    current:   CurrentUser = None,
):
    """Underwriting-specific analytics — rules fired, debit points, AI scores."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # ── Top fired error codes ─────────────────────────────────────────────
        cur.execute("""
            SELECT
                UNNEST(STRING_TO_ARRAY(error_codes, ','))                       AS code,
                COUNT(*)                                                        AS count
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND error_codes IS NOT NULL AND error_codes != ''
              AND created_at BETWEEN %s AND %s
            GROUP BY code
            ORDER BY count DESC
            LIMIT 15
        """, (date_from, date_to + " 23:59:59"))
        top_codes = [dict(r) for r in cur.fetchall()]

        # ── Debit point distribution ──────────────────────────────────────────
        cur.execute("""
            SELECT
                CASE
                    WHEN net_debit_points = 0        THEN '0 (Standard)'
                    WHEN net_debit_points <= 50      THEN '1-50'
                    WHEN net_debit_points <= 100     THEN '51-100'
                    WHEN net_debit_points <= 150     THEN '101-150'
                    WHEN net_debit_points <= 200     THEN '151-200'
                    ELSE '200+'
                END                                                             AS band,
                COUNT(*)                                                        AS count
            FROM batch_job_records
            WHERE status NOT IN ('DRY_RUN','ERROR')
              AND created_at BETWEEN %s AND %s
            GROUP BY band
            ORDER BY MIN(net_debit_points)
        """, (date_from, date_to + " 23:59:59"))
        debit_dist = [dict(r) for r in cur.fetchall()]

        # ── AI scoring stats ──────────────────────────────────────────────────
        cur.execute("""
            SELECT
                ai_engine,
                COUNT(*)                                                        AS total,
                COUNT(*) FILTER (WHERE ai_decision = 'APPROVE')                AS ai_approve,
                COUNT(*) FILTER (WHERE ai_decision = 'DECLINE')                AS ai_decline,
                ROUND(AVG(ai_risk_score), 1)                                   AS avg_score
            FROM batch_job_records
            WHERE ai_engine IS NOT NULL
              AND created_at BETWEEN %s AND %s
            GROUP BY ai_engine
            ORDER BY total DESC
        """, (date_from, date_to + " 23:59:59"))
        ai_stats = [dict(r) for r in cur.fetchall()]

        cur.close()
        return {
            "date_from":   date_from,
            "date_to":     date_to,
            "top_codes":   top_codes,
            "debit_dist":  debit_dist,
            "ai_stats":    ai_stats,
        }
    finally:
        release(conn)
