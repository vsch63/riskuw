"""
backend/services/reinsurance.py
────────────────────────────────
Python-side helper for RI cession logic.
The primary trigger is the DB-level function in V002__ri_cession_trigger.sql.
These helpers are used for:
  - Manual cession creation
  - Backfill script
  - Unit tests (can run without DB trigger)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("uw_platform")

DEFAULT_RETENTION_LIMIT = 5_000_000  # ₹50 lakhs


def get_active_reinsurer(conn, tenant_id: str) -> Optional[dict]:
    """Return the first active reinsurer for this tenant, or None."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, reinsurer_name, reinsurer_code, retention_limit
            FROM ri_reinsurer
            WHERE is_active = true
              AND (tenant_id = %s::uuid OR tenant_id IS NULL)
              AND (treaty_expiry_date IS NULL OR treaty_expiry_date > CURRENT_DATE)
            ORDER BY retention_limit ASC
            LIMIT 1
            """,
            (tenant_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row and hasattr(row, "keys") else None
    except Exception as exc:
        logger.warning("get_active_reinsurer failed", exc_info=exc)
        return None


def check_cession_required(face_amount: float, tenant_id: str, conn) -> tuple[bool, float]:
    """
    Returns (cession_required: bool, cession_amount: float).
    Checks the retention limit of the active reinsurer.
    """
    reinsurer = get_active_reinsurer(conn, tenant_id)
    limit = float(reinsurer.get("retention_limit") or DEFAULT_RETENTION_LIMIT) if reinsurer else DEFAULT_RETENTION_LIMIT
    if face_amount > limit:
        return True, face_amount - limit
    return False, 0.0


def create_manual_cession(
    conn,
    case_id: str,
    reinsurer_id: int,
    face_amount: float,
    cession_amount: float,
    risk_class: Optional[str] = None,
    treaty_reference: Optional[str] = None,
    actor: str = "system",
) -> Optional[str]:
    """
    Insert a manual ri_cession row.  Returns the new cession id or None on failure.
    """
    import json
    from datetime import datetime, timezone

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ri_cession
                (case_id, reinsurer_id, cession_type, face_amount,
                 cession_amount, risk_class, treaty_reference, status, created_at)
            VALUES (%s, %s, 'MANUAL', %s, %s, %s, %s, 'PENDING', now())
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (case_id, reinsurer_id, face_amount, cession_amount,
             risk_class, treaty_reference),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None
        new_id = str(row[0] if isinstance(row, tuple) else row.get("id"))

        cur.execute(
            """
            INSERT INTO audit_trail
                (event_category, event_type, actor_username,
                 entity_type, entity_id, after_state, source)
            VALUES ('REINSURANCE', 'MANUAL_CESSION_CREATED', %s,
                    'ri_cession', %s, %s::jsonb, 'API')
            """,
            (
                actor, new_id,
                json.dumps({
                    "case_id": case_id,
                    "face_amount": face_amount,
                    "cession_amount": cession_amount,
                    "reinsurer_id": reinsurer_id,
                }),
            ),
        )
        conn.commit()
        cur.close()
        return new_id
    except Exception as exc:
        logger.error("create_manual_cession failed", exc_info=exc)
        conn.rollback()
        return None
