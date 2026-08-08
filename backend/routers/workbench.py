"""
backend/routers/workbench.py
─────────────────────────────
Underwriter Workbench — manages REFERRED cases that need human review.

Endpoints:
  GET    /workbench/queue                       — list REFERRED cases with assignment/SLA info
  GET    /workbench/cases/{id}                  — full case detail (applicant data + assignment + notes + requirements)
  POST   /workbench/cases/{id}/assign           — assign case to an underwriter
  POST   /workbench/cases/{id}/status           — update workbench_status / priority
  POST   /workbench/cases/{id}/notes            — add a note
  GET    /workbench/cases/{id}/notes            — list notes
  POST   /workbench/cases/{id}/requirements     — add a requirement
  PATCH  /workbench/requirements/{rid}          — update requirement status
  POST   /workbench/cases/{id}/decision         — record final UW decision (overrides outcome)
  GET    /workbench/underwriters                — list assignable underwriters
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_conn, release_conn
from routers.auth import CurrentUser
from services.inapp_notify import emit, emit_to_case_owner

logger = logging.getLogger("uw_platform")
router = APIRouter(prefix="/workbench", tags=["workbench"])


def _get_db():
    conn = get_conn()
    return conn, lambda c: release_conn(c)


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else dict(r)


WORKBENCH_STATUSES = [
    "OPEN", "IN_PROGRESS", "PENDING_REQUIREMENTS",
    "READY_FOR_DECISION", "APPROVED", "DECLINED", "CLOSED",
]
PRIORITIES = ["LOW", "NORMAL", "HIGH", "URGENT"]
REQUIREMENT_TYPES = ["MEDICAL_TEST", "APS", "FINANCIAL_DOC", "ID_PROOF", "OTHER"]
REQUIREMENT_STATUSES = ["REQUESTED", "RECEIVED", "WAIVED"]


# ── Request models ────────────────────────────────────────────────────────────

class AssignRequest(BaseModel):
    assigned_to: str


class StatusUpdateRequest(BaseModel):
    workbench_status: Optional[str] = None
    priority: Optional[str] = None
    sla_hours: Optional[int] = None


class NoteRequest(BaseModel):
    note: str


class RequirementCreate(BaseModel):
    requirement_type: str
    description: str = ""


class RequirementUpdate(BaseModel):
    status: str
    notes: str = ""


class DecisionRequest(BaseModel):
    final_outcome: str   # APPROVED | APPROVED_RATED | DECLINED | POSTPONED
    final_reason: str


# ── Helper: ensure a case_assignments row exists ──────────────────────────────

def _ensure_assignment(cur, case_ref_id: int):
    cur.execute("SELECT * FROM case_assignments WHERE case_ref_id=%s", (case_ref_id,))
    row = cur.fetchone()
    if row:
        return _row(row)
    sla_due = datetime.now(timezone.utc) + timedelta(hours=48)
    cur.execute("""
        INSERT INTO case_assignments (case_ref_id, workbench_status, priority, sla_hours, sla_due_at)
        VALUES (%s, 'OPEN', 'NORMAL', 48, %s)
        RETURNING *
    """, (case_ref_id, sla_due))
    return _row(cur.fetchone())


# ── Queue ─────────────────────────────────────────────────────────────────────

@router.get("/queue")
def get_queue(
    current: CurrentUser,
    status: str = "ALL",
    assigned_to: str = "ALL",
    priority: str = "ALL",
):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Auto-create assignment rows for any REFERRED cases not yet tracked
        cur.execute("""
            SELECT pq.id FROM policy_admin_queue pq
            LEFT JOIN case_assignments ca ON ca.case_ref_id = pq.id
            WHERE pq.outcome ILIKE '%%REFER%%' AND ca.id IS NULL
        """)
        new_ids = [r["id"] if hasattr(r, "keys") else r[0] for r in cur.fetchall()]
        for cid in new_ids:
            _ensure_assignment(cur, cid)
        if new_ids:
            conn.commit()

        # Build filtered query
        where = ["pq.outcome ILIKE '%%REFER%%'"]
        params: list = []
        if status != "ALL":
            where.append("ca.workbench_status = %s")
            params.append(status)
        if assigned_to != "ALL":
            if assigned_to == "UNASSIGNED":
                where.append("(ca.assigned_to IS NULL OR ca.assigned_to = '')")
            else:
                where.append("ca.assigned_to = %s")
                params.append(assigned_to)
        if priority != "ALL":
            where.append("ca.priority = %s")
            params.append(priority)

        where_sql = " AND ".join(where)
        cur.execute(f"""
            SELECT
                pq.id AS case_ref_id,
                pq.applicant_ref, pq.applicant_name, pq.product_code,
                pq.face_amount, pq.age, pq.gender, pq.outcome, pq.risk_class,
                pq.net_debit_points, pq.reason, pq.decision_date,
                ca.id AS assignment_id, ca.assigned_to, ca.workbench_status,
                ca.priority, ca.sla_due_at, ca.final_outcome,
                (SELECT COUNT(*) FROM case_notes WHERE case_ref_id = pq.id) AS note_count,
                (SELECT COUNT(*) FROM case_requirements
                    WHERE case_ref_id = pq.id AND status = 'REQUESTED') AS pending_requirements
            FROM policy_admin_queue pq
            LEFT JOIN case_assignments ca ON ca.case_ref_id = pq.id
            WHERE {where_sql}
            ORDER BY
                CASE ca.priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1
                                 WHEN 'NORMAL' THEN 2 ELSE 3 END,
                ca.sla_due_at ASC NULLS LAST
            LIMIT 500
        """, params)
        rows = [_row(r) for r in cur.fetchall()]
        cur.close()

        now = datetime.now(timezone.utc)
        for r in rows:
            r["face_amount"]    = float(r.get("face_amount") or 0)
            r["net_debit_points"] = int(r.get("net_debit_points") or 0)
            sla = r.get("sla_due_at")
            r["sla_breached"] = bool(sla and sla < now)
            r["workbench_status"] = r.get("workbench_status") or "OPEN"
            r["priority"] = r.get("priority") or "NORMAL"

        return {"cases": rows, "total": len(rows)}
    except Exception as e:
        logger.error(f"get_queue failed: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to load workbench queue: {e}")
    finally:
        release(conn)


# ── SLA Dashboard ────────────────────────────────────────────────────────────

@router.get("/sla-dashboard")
def sla_dashboard(current: CurrentUser):
    """Aggregate SLA health for the workbench: breach counts, avg TAT by
    product, the breached queue, and a status breakdown."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc)

        # Core counts + avg TAT
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE ca.sla_due_at IS NOT NULL AND ca.sla_due_at < now())
                    AS sla_breached,
                COUNT(*) FILTER (WHERE ca.sla_due_at IS NOT NULL AND ca.sla_due_at >= now())
                    AS within_sla,
                COUNT(*) FILTER (WHERE ca.sla_due_at IS NULL) AS no_sla,
                COUNT(*) FILTER (WHERE ca.workbench_status = 'OPEN') AS open_cases,
                COUNT(*) FILTER (WHERE ca.workbench_status IN ('APPROVED','DECLINED'))
                    AS decided_cases,
                COALESCE(AVG(EXTRACT(EPOCH FROM (coalesce(ca.decided_at, now())
                    - pq.decision_date)) / 3600.0), 0) AS avg_tat_hours
            FROM case_assignments ca
            LEFT JOIN policy_admin_queue pq ON pq.id = ca.case_ref_id
        """)
        stats = _row(cur.fetchone())

        # Avg TAT by product (last 90 days, decided cases only)
        cur.execute("""
            SELECT pq.product_code AS product_code,
                   COUNT(*) AS cases,
                   ROUND(AVG(EXTRACT(EPOCH FROM (ca.decided_at - pq.decision_date)) / 3600.0), 1)
                       AS avg_tat_hours
            FROM case_assignments ca
            JOIN policy_admin_queue pq ON pq.id = ca.case_ref_id
            WHERE ca.decided_at IS NOT NULL
              AND pq.decision_date >= now() - interval '90 days'
            GROUP BY pq.product_code
            ORDER BY avg_tat_hours DESC
        """)
        tat_by_product = [_row(r) for r in cur.fetchall()]

        # Breached queue (most overdue first)
        cur.execute("""
            SELECT pq.id AS case_ref_id, pq.applicant_ref, pq.applicant_name,
                   pq.product_code, ca.assigned_to, ca.workbench_status, ca.priority,
                   ca.sla_due_at
            FROM case_assignments ca
            JOIN policy_admin_queue pq ON pq.id = ca.case_ref_id
            WHERE ca.sla_due_at IS NOT NULL AND ca.sla_due_at < now()
              AND ca.workbench_status NOT IN ('APPROVED','DECLINED','CLOSED')
            ORDER BY ca.sla_due_at ASC
            LIMIT 100
        """)
        breached = []
        for r in cur.fetchall():
            d = _row(r)
            d["sla_breached"] = True
            breached.append(d)

        cur.close()
        return {
            "stats": {
                "sla_breached":  int(stats.get("sla_breached") or 0),
                "within_sla":    int(stats.get("within_sla") or 0),
                "no_sla":        int(stats.get("no_sla") or 0),
                "open_cases":    int(stats.get("open_cases") or 0),
                "decided_cases": int(stats.get("decided_cases") or 0),
                "avg_tat_hours": round(float(stats.get("avg_tat_hours") or 0), 1),
            },
            "tat_by_product": tat_by_product,
            "breached_cases": breached,
        }
    except Exception as e:
        logger.error(f"sla_dashboard failed: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to load SLA dashboard: {e}")
    finally:
        release(conn)


# ── Case detail ───────────────────────────────────────────────────────────────

@router.get("/cases/{case_id}")
def get_case_detail(case_id: int, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT * FROM policy_admin_queue WHERE id=%s", (case_id,))
        case = cur.fetchone()
        if not case:
            raise HTTPException(404, "Case not found")
        case = _row(case)
        case["face_amount"]      = float(case.get("face_amount") or 0)
        case["approved_premium"] = float(case.get("approved_premium") or 0)

        assignment = _ensure_assignment(cur, case_id)
        conn.commit()

        cur.execute("""
            SELECT id, author, note, created_at
            FROM case_notes WHERE case_ref_id=%s ORDER BY created_at DESC
        """, (case_id,))
        notes = [_row(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT id, requirement_type, description, status,
                   requested_by, requested_at, received_at, notes
            FROM case_requirements WHERE case_ref_id=%s ORDER BY requested_at DESC
        """, (case_id,))
        requirements = [_row(r) for r in cur.fetchall()]

        # AI Audit Trail — from ai_decision_log (preferred), fallback to batch_job_records
        ai_history = []
        try:
            cur.execute("""
                SELECT id, source, ai_engine AS engine, ai_model AS model,
                       recommendation AS decision, risk_tier, risk_score, confidence,
                       narrative, loading_suggestion,
                       primary_concerns, positive_factors,
                       human_decision, human_decided_by, human_decided_at, matches_ai,
                       requested_by, created_at
                FROM ai_decision_log
                WHERE case_ref_id = %s OR applicant_ref = %s
                ORDER BY created_at DESC LIMIT 10
            """, (case_id, case.get("applicant_ref")))
            ai_history = [_row(r) for r in cur.fetchall()]
            for h in ai_history:
                h["risk_score"] = float(h["risk_score"]) if h.get("risk_score") is not None else None
                h["confidence"] = float(h["confidence"]) if h.get("confidence") is not None else None
                h["created_at"] = str(h["created_at"]) if h.get("created_at") else None
                h["human_decided_at"] = str(h["human_decided_at"]) if h.get("human_decided_at") else None
        except Exception:
            conn.rollback()
            cur = conn.cursor()

        # Legacy fallback: batch AI columns (for rows scored before ai_decision_log existed)
        if not ai_history:
            try:
                cur.execute("""
                    SELECT ai_engine AS engine, ai_decision AS decision, ai_risk_tier AS risk_tier,
                           ai_risk_score AS risk_score, ai_narrative AS narrative, created_at
                    FROM batch_job_records
                    WHERE applicant_ref = %s AND tenant_id = %s AND ai_engine IS NOT NULL
                    ORDER BY created_at DESC LIMIT 5
                """, (case.get("applicant_ref"), current.tenant_id))
                ai_history = [_row(r) for r in cur.fetchall()]
                for h in ai_history:
                    h["risk_score"] = float(h["risk_score"]) if h.get("risk_score") is not None else None
                    h["created_at"] = str(h["created_at"]) if h.get("created_at") else None
            except Exception:
                conn.rollback()
                cur = conn.cursor()

        cur.close()

        return {
            "case": case,
            "assignment": assignment,
            "notes": notes,
            "requirements": requirements,
            "ai_history": ai_history,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_case_detail failed: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to load case: {e}")
    finally:
        release(conn)


# ── Assign ────────────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/assign")
def assign_case(case_id: int, body: AssignRequest, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        _ensure_assignment(cur, case_id)
        cur.execute("""
            UPDATE case_assignments
            SET assigned_to=%s, assigned_by=%s,
                workbench_status = CASE WHEN workbench_status='OPEN' THEN 'IN_PROGRESS' ELSE workbench_status END,
                updated_at=now()
            WHERE case_ref_id=%s
            RETURNING *
        """, (body.assigned_to, current.username, case_id))
        row = _row(cur.fetchone())
        # ── Event trigger: notify the newly assigned underwriter ──
        if body.assigned_to and body.assigned_to != current.username:
            emit(conn, tenant_id=current.tenant_id, recipient=body.assigned_to,
                 event_type="ASSIGNMENT",
                 title=f"Case {case_id} assigned to you",
                 body=f"Case {case_id} was assigned by {current.username}.",
                 case_ref_id=case_id)
        conn.commit()
        cur.close()
        return row
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Assign failed: {e}")
    finally:
        release(conn)


# ── Status / priority / SLA update ────────────────────────────────────────────

@router.post("/cases/{case_id}/status")
def update_status(case_id: int, body: StatusUpdateRequest, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        _ensure_assignment(cur, case_id)

        if body.workbench_status and body.workbench_status not in WORKBENCH_STATUSES:
            raise HTTPException(400, f"Invalid status. Must be one of {WORKBENCH_STATUSES}")
        if body.priority and body.priority not in PRIORITIES:
            raise HTTPException(400, f"Invalid priority. Must be one of {PRIORITIES}")

        sets, params = [], []
        if body.workbench_status:
            sets.append("workbench_status=%s"); params.append(body.workbench_status)
        if body.priority:
            sets.append("priority=%s"); params.append(body.priority)
        if body.sla_hours:
            sets.append("sla_hours=%s"); params.append(body.sla_hours)
            sets.append("sla_due_at=created_at + (%s || ' hours')::interval")
            params.append(body.sla_hours)

        if not sets:
            raise HTTPException(400, "Nothing to update")

        sets.append("updated_at=now()")
        params.append(case_id)
        cur.execute(f"""
            UPDATE case_assignments SET {", ".join(sets)}
            WHERE case_ref_id=%s RETURNING *
        """, params)
        row = _row(cur.fetchone())
        conn.commit()
        cur.close()
        return row
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Status update failed: {e}")
    finally:
        release(conn)


# ── Notes ─────────────────────────────────────────────────────────────────────

@router.get("/cases/{case_id}/notes")
def list_notes(case_id: int, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, author, note, created_at
            FROM case_notes WHERE case_ref_id=%s ORDER BY created_at DESC
        """, (case_id,))
        rows = [_row(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release(conn)


@router.post("/cases/{case_id}/notes")
def add_note(case_id: int, body: NoteRequest, current: CurrentUser):
    if not body.note.strip():
        raise HTTPException(400, "Note cannot be empty")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        _ensure_assignment(cur, case_id)
        cur.execute("""
            INSERT INTO case_notes (case_ref_id, author, note)
            VALUES (%s, %s, %s) RETURNING id, author, note, created_at
        """, (case_id, current.username, body.note.strip()))
        row = _row(cur.fetchone())
        cur.execute("UPDATE case_assignments SET updated_at=now() WHERE case_ref_id=%s", (case_id,))
        # ── Event trigger: notify the case owner when someone else notes ──
        emit_to_case_owner(conn, case_id, event_type="NOTE",
                           title=f"New note on case {case_id}",
                           body=body.note.strip()[:200],
                           except_actor=current.username,
                           tenant_id=current.tenant_id)
        conn.commit()
        cur.close()
        return row
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Add note failed: {e}")
    finally:
        release(conn)


# ── Requirements ──────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/requirements")
def add_requirement(case_id: int, body: RequirementCreate, current: CurrentUser):
    if body.requirement_type not in REQUIREMENT_TYPES:
        raise HTTPException(400, f"Invalid type. Must be one of {REQUIREMENT_TYPES}")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        _ensure_assignment(cur, case_id)
        cur.execute("""
            INSERT INTO case_requirements (case_ref_id, requirement_type, description, requested_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id, requirement_type, description, status, requested_by, requested_at, received_at, notes
        """, (case_id, body.requirement_type, body.description, current.username))
        row = _row(cur.fetchone())
        # Move case to PENDING_REQUIREMENTS if currently IN_PROGRESS
        cur.execute("""
            UPDATE case_assignments
            SET workbench_status = CASE WHEN workbench_status IN ('OPEN','IN_PROGRESS')
                                         THEN 'PENDING_REQUIREMENTS' ELSE workbench_status END,
                updated_at=now()
            WHERE case_ref_id=%s
        """, (case_id,))
        # ── Event trigger: notify the case owner a requirement was requested ──
        emit_to_case_owner(conn, case_id, event_type="REQUIREMENT",
                           title=f"Requirement requested — case {case_id}",
                           body=f"{body.requirement_type} requested by {current.username}: "
                                f"{(body.description or '').strip()[:160]}",
                           except_actor=current.username,
                           tenant_id=current.tenant_id)
        conn.commit()
        cur.close()
        return row
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Add requirement failed: {e}")
    finally:
        release(conn)


@router.patch("/requirements/{req_id}")
def update_requirement(req_id: int, body: RequirementUpdate, current: CurrentUser):
    if body.status not in REQUIREMENT_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of {REQUIREMENT_STATUSES}")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        received_at_sql = "now()" if body.status in ("RECEIVED", "WAIVED") else "NULL"
        cur.execute(f"""
            UPDATE case_requirements
            SET status=%s, notes=%s, received_at={received_at_sql}
            WHERE id=%s
            RETURNING id, case_ref_id, requirement_type, description, status,
                      requested_by, requested_at, received_at, notes
        """, (body.status, body.notes, req_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Requirement not found")
        row = _row(row)
        case_ref_id = row["case_ref_id"]

        # If no more outstanding requirements, move case to READY_FOR_DECISION
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM case_requirements
            WHERE case_ref_id=%s AND status='REQUESTED'
        """, (case_ref_id,))
        remaining = _row(cur.fetchone())["cnt"]
        if remaining == 0:
            cur.execute("""
                UPDATE case_assignments
                SET workbench_status = CASE WHEN workbench_status='PENDING_REQUIREMENTS'
                                             THEN 'READY_FOR_DECISION' ELSE workbench_status END,
                    updated_at=now()
                WHERE case_ref_id=%s
            """, (case_ref_id,))

        # ── Event trigger: notify the requester that their item arrived ──
        if body.status in ("RECEIVED", "WAIVED") and row.get("requested_by") \
                and row["requested_by"] != current.username:
            emit(conn, tenant_id=current.tenant_id, recipient=row["requested_by"],
                 event_type="REQUIREMENT",
                 title=f"Requirement {body.status.lower()} — case {case_ref_id}",
                 body=f"{row['requirement_type']} was marked {body.status} by {current.username}.",
                 case_ref_id=case_ref_id)

        conn.commit()
        cur.close()
        return row
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Update requirement failed: {e}")
    finally:
        release(conn)


# ── Final decision ────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/decision")
def record_decision(case_id: int, body: DecisionRequest, current: CurrentUser):
    if not body.final_reason.strip():
        raise HTTPException(400, "A reason is required for the final decision")

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        _ensure_assignment(cur, case_id)

        new_wb_status = "APPROVED" if "APPROVED" in body.final_outcome.upper() else (
            "DECLINED" if "DECLIN" in body.final_outcome.upper() else "CLOSED"
        )

        # ── Gate: pending requirements must be resolved before a final decision ──
        if new_wb_status in ("APPROVED", "DECLINED"):
            cur.execute("""
                SELECT COUNT(*) FROM case_requirements
                WHERE case_ref_id=%s AND status='REQUESTED'
            """, (case_id,))
            pending_reqs = cur.fetchone()
            pending_reqs = (pending_reqs[0] if isinstance(pending_reqs, tuple) else pending_reqs.get("count")) or 0
            if pending_reqs > 0:
                raise HTTPException(
                    400,
                    f"Cannot finalize decision: {pending_reqs} pending requirement(s) still REQUESTED. "
                    "Mark them RECEIVED or WAIVED first.",
                )

        cur.execute("""
            UPDATE case_assignments
            SET final_outcome=%s, final_reason=%s,
                decided_by=%s, decided_at=now(),
                workbench_status=%s,
                updated_at=now()
            WHERE case_ref_id=%s
            RETURNING *
        """, (body.final_outcome, body.final_reason.strip(), current.username, new_wb_status, case_id))
        assignment = _row(cur.fetchone())

        # Update the source-of-truth outcome on policy_admin_queue
        cur.execute("""
            UPDATE policy_admin_queue
            SET outcome=%s, reason=%s, status='PROCESSED', processed_at=now()
            WHERE id=%s
        """, (body.final_outcome, body.final_reason.strip(), case_id))

        # Add an audit note
        cur.execute("""
            INSERT INTO case_notes (case_ref_id, author, note)
            VALUES (%s, %s, %s)
        """, (case_id, current.username,
              f"[DECISION] Outcome changed to {body.final_outcome}. Reason: {body.final_reason.strip()}"))

        # ── AI Audit Trail: record whether human decision matched latest AI rec ──
        try:
            cur.execute("""
                SELECT id, recommendation FROM ai_decision_log
                WHERE case_ref_id=%s ORDER BY created_at DESC LIMIT 1
            """, (case_id,))
            ai_row = cur.fetchone()
            if ai_row:
                ai_row = _row(ai_row)
                ai_rec = (ai_row.get("recommendation") or "").upper()
                human  = body.final_outcome.upper()
                # APPROVED/APPROVED_RATED both count as "approve" for comparison
                human_norm = "APPROVE" if "APPROVED" in human else (
                    "DECLINE" if "DECLIN" in human else ("REFER" if "POSTPON" in human else human))
                matches = (ai_rec == human_norm) if ai_rec else None
                cur.execute("""
                    UPDATE ai_decision_log
                    SET human_decision=%s, human_decided_by=%s, human_decided_at=now(), matches_ai=%s
                    WHERE id=%s
                """, (body.final_outcome, current.username, matches, ai_row["id"]))
        except Exception as ai_audit_err:
            logger.warning(f"AI audit backfill failed for case {case_id}: {ai_audit_err}")

        conn.commit()

        # ── Reinsurance trigger for newly-approved override ──────────────────
        if "APPROVED" in body.final_outcome.upper():
            try:
                cur.execute("SELECT * FROM policy_admin_queue WHERE id=%s", (case_id,))
                pq = _row(cur.fetchone())
                from services.ri_trigger import check_and_trigger_reinsurance
                check_and_trigger_reinsurance(
                    conn=conn,
                    case_id=str(case_id),
                    application_id=pq.get("applicant_ref"),
                    product_code=pq.get("product_code"),
                    face_amount=float(pq.get("face_amount") or 0),
                    approved_premium=float(pq.get("approved_premium") or 0),
                    applicant_ref=pq.get("applicant_ref"),
                    submitted_by=current.username,
                )
            except Exception as ri_err:
                logger.warning(f"RI trigger failed for workbench decision {case_id}: {ri_err}")

        # ── Event trigger: notify the case owner when someone else decides ──
        try:
            emit_to_case_owner(conn, case_id, event_type="DECISION",
                               title=f"Decision recorded — case {case_id}",
                               body=f"Case {case_id} decided by {current.username}: "
                                    f"{body.final_outcome} — {body.final_reason.strip()[:140]}",
                               except_actor=current.username,
                               tenant_id=current.tenant_id)
            conn.commit()
        except Exception as notif_err:
            logger.warning(f"Decision notification failed for case {case_id}: {notif_err}")

        cur.close()
        return assignment
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"record_decision failed: {e}", exc_info=True)
        raise HTTPException(500, f"Decision failed: {e}")
    finally:
        release(conn)


# ── Assignable underwriters ───────────────────────────────────────────────────

@router.get("/underwriters")
def list_underwriters(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT username, full_name, role
            FROM uw_user
            WHERE role IN ('underwriter','senior_underwriter','admin','super_admin')
              AND is_active = true
            ORDER BY role, username
        """)
        rows = [_row(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception:
        conn.rollback()
        return []
    finally:
        release(conn)
