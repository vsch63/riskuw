"""
routers/agent_portal.py
────────────────────────────────────────────────────────
GET  /agent/dashboard          — agent dashboard stats
GET  /agent/submissions        — agent's own submissions
POST /agent/submit             — submit a new proposal
GET  /agent/submissions/{ref}  — get submission status
GET  /agent/products           — list available products (limited info)
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from deps import CurrentUser
import json

router = APIRouter(prefix="/agent", tags=["agent-portal"])

AGENT_ROLES = ("agent", "broker")

def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


def _upsert_applicant_master(cur, applicant_ref: str, body: dict, source: str = "AGENT", uploaded_by: str = None):
    """Upsert demographic/contact data into applicant_master. Never overwrites with blanks."""
    if not applicant_ref:
        return
    full_name  = body.get("applicant_name") or body.get("full_name")
    email      = body.get("applicant_email") or body.get("email")
    phone      = body.get("applicant_phone") or body.get("phone") or body.get("mobile")
    dob        = body.get("date_of_birth") or body.get("dob")
    gender     = body.get("gender")
    state      = body.get("state")
    occupation = body.get("occupation_title") or body.get("occupation")
    income     = body.get("annual_income")

    cur.execute("SELECT id FROM applicant_master WHERE applicant_ref=%s", (applicant_ref,))
    existing = cur.fetchone()

    if existing:
        sets = []
        params = []
        field_map = {
            "full_name": full_name, "email": email, "phone": phone,
            "mobile": phone, "dob": dob, "gender": gender, "state": state,
            "occupation": occupation, "annual_income": income,
        }
        for col, val in field_map.items():
            if val not in (None, ""):
                sets.append(f"{col}=%s")
                params.append(val)
        if sets:
            sets.append("updated_at=now()")
            params.append(applicant_ref)
            cur.execute(
                f"UPDATE applicant_master SET {', '.join(sets)} WHERE applicant_ref=%s",
                params
            )
    else:
        cur.execute("""
            INSERT INTO applicant_master
                (applicant_ref, full_name, email, phone, mobile, dob, gender,
                 state, occupation, annual_income, source, uploaded_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (applicant_ref) DO NOTHING
        """, (applicant_ref, full_name, email, phone, phone, dob, gender,
              state, occupation, income, source, uploaded_by))


@router.get("/dashboard")
def agent_dashboard(current: CurrentUser):
    if current.role not in AGENT_ROLES:
        raise HTTPException(403, "Agent/Broker access only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        # Get submission stats for this agent
        cur.execute("""
            SELECT
                COUNT(*)                                            AS total_submitted,
                COUNT(*) FILTER (WHERE d.outcome ILIKE '%%APPROVED%%') AS approved,
                COUNT(*) FILTER (WHERE d.outcome ILIKE '%%DECLINED%%') AS declined,
                COUNT(*) FILTER (WHERE d.outcome ILIKE '%%REFERRED%%') AS pending,
                COUNT(*) FILTER (WHERE d.outcome IS NULL)           AS in_progress
            FROM application a
            LEFT JOIN uw_case c ON c.application_id = a.id
            LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = true
            WHERE a.submitted_by_agent = %s
        """, (current.username,))
        stats = dict(cur.fetchone() or {})

        # Recent submissions
        cur.execute("""
            SELECT
                a.application_number, a.applicant_ref, a.applicant_name, a.product_code,
                a.face_amount, a.age, a.gender, a.created_at,
                COALESCE(d.outcome, c.status, 'PENDING') AS status,
                c.case_number
            FROM application a
            LEFT JOIN uw_case c ON c.application_id = a.id
            LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = true
            WHERE a.submitted_by_agent = %s
            ORDER BY a.created_at DESC
            LIMIT 5
        """, (current.username,))
        recent = []
        for r in cur.fetchall():
            d = dict(r)
            for k in ("created_at",):
                if d.get(k): d[k] = str(d[k])[:19]
            recent.append(d)

        cur.close()
        return {
            "agent":   current.username,
            "stats":   {k: int(v or 0) for k, v in stats.items()},
            "recent":  recent,
        }
    finally:
        release(conn)


@router.get("/products")
def list_products_agent(current: CurrentUser):
    """Return limited product info for agents — no internal UW config."""
    if current.role not in AGENT_ROLES:
        raise HTTPException(403, "Agent/Broker access only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT product_code, product_name, product_type, category,
                   min_age, max_age, min_face_amount, max_face_amount,
                   available_terms, description
            FROM products WHERE is_active = true
            ORDER BY product_name
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


class AgentSubmission(BaseModel):
    applicant_ref:    str
    product_code:     str
    age:              int
    gender:           str
    state:            str
    face_amount:      float
    coverage_term_yrs: Optional[int] = None
    tobacco_status:   str = "NON_TOBACCO"
    height_inches:    Optional[float] = None
    weight_lbs:       Optional[float] = None
    systolic_bp:      Optional[int] = None
    diastolic_bp:     Optional[int] = None
    diabetes_type:    str = "NONE"
    heart_condition:  str = "NONE"
    annual_income:    Optional[float] = None
    existing_coverage: float = 0
    applicant_name:   Optional[str] = None
    applicant_email:  Optional[str] = None
    applicant_phone:  Optional[str] = None
    agent_notes:      Optional[str] = None


@router.post("/submit")
def agent_submit(body: AgentSubmission, current: CurrentUser):
    """Agent submits a proposal — runs UW evaluation and persists."""
    if current.role not in AGENT_ROLES:
        raise HTTPException(403, "Agent/Broker access only")

    # Build evaluate payload
    payload = {
        "applicant_ref":    body.applicant_ref,
        "product_code":     body.product_code,
        "age":              body.age,
        "gender":           body.gender,
        "state":            body.state,
        "face_amount":      body.face_amount,
        "coverage_term_yrs": body.coverage_term_yrs or 20,
        "tobacco_status":   body.tobacco_status,
        "height_inches":    body.height_inches or 68,
        "weight_lbs":       body.weight_lbs or 170,
        "systolic_bp":      body.systolic_bp or 120,
        "diastolic_bp":     body.diastolic_bp or 80,
        "diabetes_type":    body.diabetes_type,
        "heart_condition":  body.heart_condition,
        "annual_income":    body.annual_income or 0,
        "existing_coverage": body.existing_coverage,
        "hazardous_activity": False,
    }

    # ── Sum-at-Risk pre-check (Phase 1/2) ─────────────────────────────
    # The SAR engine decides first: a base benefit fully covered by a Free
    # Cover Limit is auto-approved (STP) with no medical UW, and a
    # cumulative-SAR escalation refers or declines the case. Non-fatal —
    # falls through to the UW engine if SAR config is absent or errors.
    sar = None
    sar_decision = None  # None | APPROVED_STP | DECLINED | REFERRED
    try:
        from services.sar_service import run_sar
        _conn, _release = _get_db()
        try:
            sar = run_sar(
                _conn, '00000000-0000-0000-0000-000000000001', body.product_code,
                applicant={
                    "applicant_ref": body.applicant_ref,
                    "age":           body.age,
                    "annual_salary": body.annual_income,
                },
                benefits=[{
                    "_idx": 0, "benefit_code": body.product_code,
                    "product_code": body.product_code, "benefit_type": "BASE",
                    "face_amount": body.face_amount,
                }],
            )
        finally:
            _release(_conn)
        if str(0) in (sar.get("auto_approve_benefit_ids") or []):
            sar_decision = "APPROVED_STP"
        elif sar.get("escalation") == "DECLINE":
            sar_decision = "DECLINED"
        elif sar.get("escalation") in ("RI_APPROVAL", "SENIOR_UW", "REFER") \
                or sar.get("ri_approval_required"):
            sar_decision = "REFERRED"
    except Exception as se:
        import logging
        logging.getLogger("uw_platform").warning(f"Agent SAR pre-check skipped: {se}")

    if sar_decision == "APPROVED_STP":
        result = {
            "outcome": "APPROVED_STP", "risk_class": "STANDARD",
            "approved_premium": None, "net_debit_points": 0,
            "rules_fired": [{"rule": "SAR_FCL_AUTO_APPROVE",
                "reason": "Covered by Free Cover Limit — gross SAR within FCL, no medical underwriting required"}],
            "sar": sar,
        }
    elif sar_decision == "DECLINED":
        result = {
            "outcome": "DECLINED", "risk_class": "DECLINE",
            "approved_premium": None, "net_debit_points": 0,
            "rules_fired": [{"rule": "SAR_CUMULATIVE_DECLINE",
                "reason": "Cumulative Sum-at-Risk across existing policies + this proposal exceeds the decline threshold"}],
            "sar": sar,
        }
    elif sar_decision == "REFERRED":
        result = {
            "outcome": "REFERRED", "risk_class": "REFERRED",
            "approved_premium": None, "net_debit_points": 0,
            "rules_fired": [{"rule": "SAR_ESCALATION",
                "reason": f"Cumulative SAR escalation: {sar.get('escalation') or 'RI_APPROVAL'}"}],
            "sar": sar,
        }
    else:
        # Run UW engine
        try:
            from services.uw_engine import run_evaluation
            result = run_evaluation(payload, current.username, '00000000-0000-0000-0000-000000000001')
        except ImportError:
            raise HTTPException(500, "UW engine not available")
        except Exception as e:
            raise HTTPException(500, f"Evaluation failed: {str(e)}")
        if sar:
            result["sar"] = sar

    # Persist decision
    from routers.underwriting import _persist_decision, _persist_to_queue
    import types
    body_obj = types.SimpleNamespace(**payload)
    body_obj.model_dump = lambda: payload

    case_number = _persist_decision(body_obj, result, current)
    if case_number:
        result["case_number"] = case_number

    # Upsert applicant contact/demographic data
    try:
        conn4, release4 = _get_db()
        try:
            cur4 = conn4.cursor()
            _upsert_applicant_master(cur4, body.applicant_ref, body.model_dump(), "AGENT", current.username)
            conn4.commit()
            cur4.close()
        finally:
            release4(conn4)
    except Exception as e:
        import logging
        logging.getLogger("uw_platform").warning(f"applicant_master upsert failed: {e}")

    # Push REFERRED cases to the UW Workbench queue
    try:
        _persist_to_queue(body_obj, result, current)
    except Exception as e:
        import logging
        logging.getLogger("uw_platform").warning(f"agent _persist_to_queue failed: {e}")

    # Update application with agent info
    if case_number:
        conn, release = _get_db()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE application
                SET submitted_by_agent = %s,
                    agent_name = %s,
                    agent_id = %s,
                    applicant_name = %s
                WHERE applicant_ref = %s
            """, (current.username, current.username,
                  current.username, body.applicant_name, body.applicant_ref))
            conn.commit()
            cur.close()
        finally:
            release(conn)

    # Return agent-friendly response (hide internal UW details)
    return {
        "applicant_ref":  body.applicant_ref,
        "case_number":    result.get("case_number"),
        "outcome":        result.get("outcome"),
        "risk_class":     result.get("risk_class"),
        "approved_premium": result.get("approved_premium"),
        "sar":              result.get("sar"),
        "medical_requirements": (result.get("sar") or {}).get("medical_requirements", []),
        "message": {
            "APPROVED_STP": "✅ Proposal approved! Policy will be issued shortly.",
            "APPROVED":     "✅ Proposal approved with rating.",
            "DECLINED":     "❌ Proposal declined. Please contact underwriter for details.",
            "REFERRED":     "⏳ Proposal referred for manual underwriting review.",
        }.get(result.get("outcome", ""), "Processing complete."),
        "next_steps": {
            "APPROVED_STP": "Policy document will be generated. Premium payment link will be sent.",
            "APPROVED":     "Rated premium applied. Applicant must accept terms before policy issuance.",
            "DECLINED":     "You may appeal within 60 days or explore alternative products.",
            "REFERRED":     "Underwriter will review within 48 hours. You will be notified.",
        }.get(result.get("outcome", ""), ""),
    }


@router.get("/submissions")
def list_submissions(
    page:     int = Query(default=1, ge=1),
    per_page: int = Query(default=20, le=100),
    status:   str = Query(default=""),
    current:  CurrentUser = None,
):
    if current.role not in AGENT_ROLES:
        raise HTTPException(403, "Agent/Broker access only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        offset = (page - 1) * per_page
        status_filter = ""
        params = [current.username]
        if status:
            status_filter = "AND COALESCE(d.outcome, c.status, 'PENDING') ILIKE %s"
            params.append(f"%{status}%")

        cur.execute(f"""
            SELECT
                a.application_number, a.applicant_ref, a.applicant_name, a.product_code,
                a.face_amount, a.age, a.gender,
                a.created_at, a.agent_name,
                COALESCE(d.outcome, c.status, 'PENDING') AS status,
                c.case_number,
                d.approved_premium,
                d.risk_class
            FROM application a
            LEFT JOIN uw_case c ON c.application_id = a.id
            LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = true
            WHERE a.submitted_by_agent = %s {status_filter}
            ORDER BY a.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        rows = []
        for r in cur.fetchall():
            d = dict(r)
            for k in ("created_at",):
                if d.get(k): d[k] = str(d[k])[:19]
            if d.get("face_amount"):
                d["face_amount"] = float(d["face_amount"])
            rows.append(d)

        cur.execute("""
            SELECT COUNT(*) FROM application WHERE submitted_by_agent = %s
        """, (current.username,))
        total = cur.fetchone()["count"]
        cur.close()

        return {"submissions": rows, "total": int(total), "page": page, "per_page": per_page}
    finally:
        release(conn)


@router.get("/submissions/{ref}")
def get_submission(ref: str, current: CurrentUser):
    if current.role not in AGENT_ROLES:
        raise HTTPException(403, "Agent/Broker access only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                a.application_number, a.applicant_ref, a.applicant_name, a.product_code,
                a.face_amount, a.age, a.gender, a.created_at,
                COALESCE(d.outcome, c.status, 'PENDING') AS status,
                c.case_number, c.decision_pathway,
                d.approved_premium, d.risk_class,
                d.primary_reason
            FROM application a
            LEFT JOIN uw_case c ON c.application_id = a.id
            LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = true
            WHERE a.applicant_ref = %s AND a.submitted_by_agent = %s
        """, (ref, current.username))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(404, "Submission not found")
        d = dict(row)
        for k in ("created_at",):
            if d.get(k): d[k] = str(d[k])[:19]
        return d
    finally:
        release(conn)
