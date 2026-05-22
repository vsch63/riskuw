"""
backend/services/audit.py
──────────────────────────
Centralised audit logging helper.
audit_trail has an immutable DB trigger — only INSERT is allowed.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("uw_platform")


def log_event(
    conn,
    event_category: str,
    event_type: str,
    actor_username: str,
    entity_type: str,
    entity_id: str,
    after_state: Optional[dict] = None,
    before_state: Optional[dict] = None,
    actor_role: Optional[str] = None,
    actor_ip: Optional[str] = None,
    tenant_id: Optional[str] = None,
    entity_ref: Optional[str] = None,
    outcome: str = "SUCCESS",
    failure_reason: Optional[str] = None,
    source: str = "API",
) -> None:
    """
    Write one row to audit_trail.
    Silent on failure — audit failure must never break the primary operation.
    """
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_trail
                (event_category, event_type, actor_username, actor_role,
                 actor_ip, tenant_id, entity_type, entity_id, entity_ref,
                 before_state, after_state, outcome, failure_reason, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                event_category, event_type, actor_username, actor_role,
                actor_ip, tenant_id, entity_type, entity_id, entity_ref,
                json.dumps(before_state) if before_state else None,
                json.dumps(after_state)  if after_state  else None,
                outcome, failure_reason, source,
            ),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.warning("audit log_event failed — suppressed", exc_info=exc)


def log_login(conn, username: str, success: bool,
              ip: Optional[str] = None, reason: Optional[str] = None) -> None:
    log_event(
        conn,
        event_category="AUTH",
        event_type="LOGIN_SUCCESS" if success else "LOGIN_FAILED",
        actor_username=username,
        entity_type="uw_user",
        entity_id=username,
        after_state={"ip": ip},
        actor_ip=ip,
        outcome="SUCCESS" if success else "FAILURE",
        failure_reason=reason,
        source="API",
    )


def log_decision(conn, actor: str, applicant_ref: str,
                 outcome: str, product_code: str,
                 tenant_id: Optional[str] = None) -> None:
    log_event(
        conn,
        event_category="UNDERWRITING",
        event_type="DECISION_MADE",
        actor_username=actor,
        entity_type="uw_decision",
        entity_id=applicant_ref,
        entity_ref=applicant_ref,
        after_state={"outcome": outcome, "product_code": product_code},
        tenant_id=tenant_id,
        source="API",
    )
