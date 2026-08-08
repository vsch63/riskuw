"""
backend/routers/underwriting.py
─────────────────────────────────
POST /underwriting/evaluate   — single-application decision
GET  /underwriting/cases      — paginated case history

Tables: application · uw_case · uw_decision · policy_admin_queue
        audit_trail

The evaluate endpoint delegates the actual rules engine to
services/uw_engine.py.  This router handles HTTP, DB persistence,
and audit logging.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import CurrentUser
from api_key_auth import FlexibleAuth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/underwriting", tags=["underwriting"])


def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn


# ── Evaluate request schema ───────────────────────────────────────────────────

class BuildInfo(BaseModel):
    height_inches: float | None = None
    weight_lbs: float | None = None

class BloodPressure(BaseModel):
    systolic: int | None = None
    diastolic: int | None = None
    on_medication: bool = False
    medication_count: int = 0

class FinancialInfo(BaseModel):
    annual_income: float = 0
    existing_life_coverage: float = 0

class FamilyHistory(BaseModel):
    cardiovascular_before_60: bool = False
    stroke_before_65: bool = False
    cancer_history: bool = False
    diabetes_history: bool = False

class DrivingRecord(BaseModel):
    dui_dwi_count_5yr: int = 0
    major_violations_3yr: int = 0
    minor_violations_3yr: int = 0
    at_fault_accidents_3yr: int = 0
    license_suspended: bool = False

class LabValues(BaseModel):
    total_cholesterol: float | None = None
    hdl: float | None = None
    ldl: float | None = None
    egfr: float | None = None

class EvaluateRequest(BaseModel):
    model_config = {"extra": "allow"}   # allow user-label fields (sa_percentage etc.)
    applicant_ref: str = "APP-001"
    age: int
    gender: str
    state: str = "MH"
    product_type: str = "INDIVIDUAL_TERM"
    product_code: str
    face_amount: float
    coverage_term_yrs: int = 20
    policy_effective_date: str | None = None
    policy_expire_date: str | None = None
    # Medical
    tobacco_status: str = "NEVER"
    tobacco_quit_years: float | None = None
    heart_condition: str = "NONE"
    heart_event_years_ago: float | None = None
    diabetes_type: str = "NONE"
    diabetes_dx_age: int | None = None
    a1c: float | None = None
    hiv_positive: bool = False
    cirrhosis: bool = False
    stroke_history: bool = False
    kidney_disease: bool = False
    depression_history: bool = False
    depression_hospitalized: bool = False
    epilepsy: bool = False
    copd: bool = False
    occupation_class: str = "1"
    occupation_title: str = ""
    alcohol_drinks_week: int = 0
    hazardous_activity: bool = False
    hazard_types: list[str] = []
    # Nested
    build: BuildInfo | None = None
    blood_pressure: BloodPressure | None = None
    lab_values: LabValues | None = None
    financial: FinancialInfo | None = None
    family_history: FamilyHistory | None = None
    driving_record: DrivingRecord | None = None
    # height/weight at top level (legacy format)
    height_inches: float | None = None
    weight_lbs: float | None = None
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    annual_income: float | None = None
    existing_coverage: float | None = None
    # Premium mode
    premium_mode:  str = "ANNUAL"   # ANNUAL | HALF_YEARLY | QUARTERLY | MONTHLY
    # Contact / demographic fields (used for notifications + applicant_master upsert)
    first_name:    str | None = None
    middle_name:   str | None = None
    last_name:     str | None = None
    email:         str | None = None
    mobile:        str | None = None
    address_line1: str | None = None
    city:          str | None = None
    pincode:       str | None = None


# ── UW Scale evaluation helper ────────────────────────────────────────────────

def _evaluate_uw_scales(conn, product_code: str, applicant: dict) -> tuple[int, list]:
    """
    Look up all UW-type scales attached to this product.
    For each scale, find the matching tranche (by parameter conditions),
    then look up the age-band output value (debit points).

    Returns (total_scale_debits, scale_rules_fired).
    Failure in scale lookup never breaks the decision — errors are logged
    as zero-debit rule entries.
    """
    today = date.today()
    total = 0
    fired = []

    try:
        cur = conn.cursor()

        # Get all active UW scales attached to this product
        cur.execute(
            """
            SELECT s.id::text, s.name
            FROM uw_product_scale ps
            JOIN uw_rate_scale s ON s.id = ps.scale_id
            WHERE ps.product_code = %s
              AND s.scale_type = 'UW'
              AND s.is_active = true
            ORDER BY s.name
            """,
            (product_code,),
        )
        scales = cur.fetchall()

        for scale_row in scales:
            scale_id   = str(scale_row[0])
            scale_name = str(scale_row[1])

            # Get tranches valid today
            cur.execute(
                """
                SELECT id::text, description, parameter_logic
                FROM uw_scale_tranche
                WHERE scale_id = %s::uuid
                  AND effective_date <= %s
                  AND (expiry_date IS NULL OR expiry_date >= %s)
                ORDER BY sort_order
                """,
                (scale_id, today, today),
            )
            tranches = cur.fetchall()

            matched = []
            for t in tranches:
                tid   = str(t[0])
                tdesc = str(t[1])
                logic = str(t[2])

                # Get parameters for this tranche
                cur.execute(
                    """
                    SELECT parameter_name, min_value, max_value
                    FROM uw_tranche_parameter
                    WHERE tranche_id = %s::uuid
                    ORDER BY sort_order
                    """,
                    (tid,),
                )
                params  = cur.fetchall()
                results = []

                for p in params:
                    pname   = str(p[0])
                    min_v   = float(p[1]) if p[1] is not None else None
                    max_v   = float(p[2]) if p[2] is not None else None

                    # Map applicant fields to parameter names
                    app_val = applicant.get(pname)

                    # Handle nested/aliased fields
                    if app_val is None:
                        aliases = {
                            "gender":           lambda a: 1 if str(a.get("gender","")).upper() in ("M","MALE") else 2,
                            "smoker":           lambda a: 1 if a.get("tobacco_status","NEVER") not in ("NEVER","NON_TOBACCO") else 0,
                            "bmi":              lambda a: _calc_bmi(a),
                            "bp_systolic":      lambda a: a.get("systolic_bp") or (a.get("blood_pressure") or {}).get("systolic"),
                            "bp_diastolic":     lambda a: a.get("diastolic_bp") or (a.get("blood_pressure") or {}).get("diastolic"),
                            "occupation_class": lambda a: int(a.get("occupation_class", 1)) if str(a.get("occupation_class","1")).isdigit() else 1,
                            "policy_term":      lambda a: a.get("coverage_term_yrs"),
                            "sum_assured":      lambda a: a.get("face_amount"),
                            "family_history":   lambda a: 1 if (a.get("family_history") or {}).get("cardiovascular_before_60") else 0,
                        }
                        if pname in aliases:
                            try:
                                app_val = aliases[pname](applicant)
                            except Exception:
                                app_val = None

                    if app_val is None:
                        results.append(False)
                        continue

                    try:
                        app_val = float(app_val)
                    except (TypeError, ValueError):
                        results.append(False)
                        continue

                    ok = True
                    if min_v is not None and app_val < min_v: ok = False
                    if max_v is not None and app_val > max_v: ok = False
                    results.append(ok)

                if not results:
                    continue

                tranche_matched = all(results) if logic == "AND" else any(results)
                if tranche_matched:
                    matched.append((tid, tdesc))

            # Multiple matches = config error
            if len(matched) > 1:
                fired.append({
                    "rule_id":      f"SCALE-CFG-ERR",
                    "rule_name":    f"Scale config error: {len(matched)} tranches matched in '{scale_name}' — fix overlapping tranches",
                    "debit_points": 0,
                    "category":     "SCALE_CONFIG_ERROR",
                })
                continue

            # Single match — look up age-band output
            if len(matched) == 1:
                tid, tdesc = matched[0]
                age = applicant.get("age")
                if age is not None:
                    cur.execute(
                        """
                        SELECT value FROM uw_tranche_detail
                        WHERE tranche_id = %s::uuid
                          AND age_from <= %s AND age_to >= %s
                        ORDER BY sort_order LIMIT 1
                        """,
                        (tid, int(age), int(age)),
                    )
                    detail = cur.fetchone()
                    if detail:
                        pts = int(float(detail[0]))
                        total += pts
                        fired.append({
                            "rule_id":      f"SCALE-{scale_name[:25]}",
                            "rule_name":    f"UW Scale: {scale_name} → {tdesc}",
                            "debit_points": pts,
                            "category":     "UW_SCALE",
                        })

        cur.close()

    except Exception as e:
        # Scale failure must never crash the decision
        fired.append({
            "rule_id":      "SCALE-ERROR",
            "rule_name":    f"UW Scale lookup error: {str(e)[:100]}",
            "debit_points": 0,
            "category":     "SCALE_ERROR",
        })

    return total, fired


def _calc_bmi(applicant: dict) -> float | None:
    """Calculate BMI from height/weight fields."""
    build = applicant.get("build") or {}
    h = applicant.get("height_inches") or build.get("height_inches")
    w = applicant.get("weight_lbs")    or build.get("weight_lbs")
    if h and w and float(h) > 0:
        return round((float(w) / (float(h) ** 2)) * 703, 1)
    return None


# ── Evaluate ──────────────────────────────────────────────────────────────────

@router.post("/evaluate")
def evaluate(body: EvaluateRequest, current: FlexibleAuth):
    """
    Run the underwriting rules engine and persist the decision.
    Delegates to services.uw_engine.run_evaluation() if available,
    otherwise uses the built-in fallback engine with UW scale integration.
    """
    if current.role not in ("underwriter","senior_underwriter","admin","super_admin","api_client"):
        raise HTTPException(403, "Underwriters only")
    try:
        from services.uw_engine import run_evaluation
        result = run_evaluation(body.model_dump(), current.username, current.tenant_id)
    except ImportError:
        result = _fallback_evaluate(body, current)

    # Apply ICD-10 extra debit points
    extra_debits = getattr(body, 'extra_debit_points', 0) or 0
    icd10_codes  = getattr(body, 'icd10_codes', []) or []
    if extra_debits > 0 and icd10_codes:
        original_debits = result.get("net_debit_points", 0) or 0
        new_debits = original_debits + extra_debits
        result["net_debit_points"]   = new_debits
        result["icd10_codes"]        = icd10_codes
        result["icd10_debit_points"] = extra_debits
        conn2, release2 = _get_db()
        try:
            import psycopg2.extras
            conn2.cursor_factory = psycopg2.extras.RealDictCursor
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT stp_threshold, refer_threshold, decline_threshold FROM products WHERE product_code=%s",
                (body.product_code,)
            )
            row2 = cur2.fetchone()
            thresh = dict(row2) if row2 else {}
            cur2.close()
        finally:
            release2(conn2)
        stp     = thresh.get("stp_threshold", 75)
        refer   = thresh.get("refer_threshold", 175)
        decline = thresh.get("decline_threshold", 350)
        if new_debits >= decline:
            result["outcome"] = "DECLINED"
        elif new_debits >= refer:
            result["outcome"] = "REFERRED"
        elif new_debits > stp:
            result["outcome"] = "APPROVED_RATED"


    case_number = _persist_decision(body, result, current)
    if case_number:
        result["case_number"] = case_number

    # Echo request context so the letter/PDF generators can render it. The
    # engine already returns product_code/face_amount on the normal path; this
    # also covers hard-decline and fallback returns.
    result["product_code"] = body.product_code
    result["face_amount"]  = body.face_amount

    _persist_to_queue(body, result, current)

    # ── Send decision email if applicant email is available ───────────────────
    try:
        from services.notification import send_decision_email
        from database import get_conn, release_conn
        _conn = get_conn()
        _cur  = _conn.cursor()
        # Look up applicant email from member master
        _cur.execute(
            "SELECT email, full_name AS name FROM applicant_master WHERE applicant_ref = %s LIMIT 1",
            (body.applicant_ref,)
        )
        member = _cur.fetchone()
        _cur.close()
        if member:
            m = dict(member) if hasattr(member, "keys") else \
                dict(zip(["email", "name"], member))
            if m.get("email"):
                send_decision_email(
                    conn=_conn,
                    to_email=m["email"],
                    applicant_name=m.get("name") or body.applicant_ref,
                    outcome=result.get("outcome", ""),
                    applicant_ref=body.applicant_ref,
                    risk_class=result.get("risk_class"),
                    premium=result.get("approved_premium"),
                )
        release_conn(_conn)
    except Exception as _email_err:
        logger.warning(f"Decision email skipped: {_email_err}")

    return result


def _persist_decision(body: "EvaluateRequest", result: dict, current) -> str | None:
    """
    Persist an evaluation to application -> uw_case -> uw_decision.
    Returns the case_number, or None if persistence failed (non-fatal).
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        outcome = (result.get("outcome") or "REFERRED").upper()
        username = current.username
        tenant_id = current.tenant_id

        # ── Map outcome -> case status + decision pathway ──────────────────────
        if "APPROVED_STP" in outcome or "INSTANT" in outcome and "DECLINE" not in outcome:
            status, pathway, by_type = "APPROVED", "STRAIGHT_THROUGH", "AUTOMATED"
        elif "APPROVED" in outcome:
            status, pathway, by_type = "APPROVED", "ACCELERATED", "AUTOMATED"
        elif "DECLINED" in outcome:
            status, pathway, by_type = "DECLINED", "INSTANT_DECLINE", "AUTOMATED"
        elif "REFERRED" in outcome:
            status, pathway, by_type = "IN_REVIEW", "REFERRED", "AUTOMATED"
        else:
            status, pathway, by_type = "IN_REVIEW", "REFERRED", "AUTOMATED"

        # application.status and uw_case.status use different allowed vocabularies
        case_status_map = {"IN_REVIEW": "PENDING_REVIEW"}
        case_status = case_status_map.get(status, status)

        app_id = str(_uuid.uuid4())
        case_id = str(_uuid.uuid4())
        dec_id = str(_uuid.uuid4())

        # ── application_number / case_number ────────────────────────────────────
        ts = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S%f")[:14]
        app_number = f"APP-{ts}"
        case_number = f"CASE-{ts}"

        # ── 1. application ───────────────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO application (
                id, application_number, product_type, product_code, channel,
                applicant_ref, age, gender, state, citizenship,
                face_amount, coverage_term_yrs, is_replacement, status,
                submitted_at, raw_payload,
                created_by, updated_by, version, is_deleted, tenant_id
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                now(), %s,
                %s, %s, 1, false, %s
            )
            """,
            (
                app_id, app_number, "INDIVIDUAL", body.product_code, "DIRECT",
                body.applicant_ref, body.age, body.gender, body.state, "IN",
                body.face_amount, getattr(body, "coverage_term_yrs", None) or getattr(body, "term_yrs", None),
                False, status,
                __import__("json").dumps(body.model_dump(), default=str),
                username, username, tenant_id,
            ),
        )

        # ── 2. uw_case ────────────────────────────────────────────────────────────
        sla_hours = 48
        cur.execute(
            """
            INSERT INTO uw_case (
                id, case_number, application_id, product_type, status,
                decision_pathway, sla_due_at, sla_breached,
                auto_decision_at, final_decision_at,
                reinsurance_required,
                created_by, updated_by, version, is_deleted, tenant_id,
                product_code, applicant_age, face_amount
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, now() + interval '%s hours', false,
                now(), CASE WHEN %s THEN now() ELSE NULL END,
                false,
                %s, %s, 1, false, %s,
                %s, %s, %s
            )
            """,
            (
                case_id, case_number, app_id, "INDIVIDUAL", case_status,
                pathway, sla_hours,
                status in ("APPROVED", "DECLINED"),
                username, username, tenant_id,
                body.product_code, body.age, body.face_amount,
            ),
        )

        # ── 3. uw_decision ────────────────────────────────────────────────────────
        findings = {
            "rules_fired": result.get("rules_fired", []),
            "error_codes": result.get("error_codes", []),
            "raw_result": {k: v for k, v in result.items()
                            if k not in ("rules_fired", "error_codes")},
        }

        cur.execute(
            """
            INSERT INTO uw_decision (
                id, case_id, application_id, decision_sequence, is_final,
                outcome, risk_class,
                total_debit_points, total_credit_points, net_debit_points,
                approved_face_amount, approved_premium,
                decline_reason_code, adverse_action_text,
                findings_json, is_override,
                decided_by_type, decided_by_id, decided_at,
                primary_reason,
                created_by, updated_by, version, is_deleted, tenant_id
            ) VALUES (
                %s, %s, %s, 1, true,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, false,
                %s, NULL, now(),
                %s,
                %s, %s, 1, false, %s
            )
            """,
            (
                dec_id, case_id, app_id,
                outcome, result.get("risk_class"),
                result.get("total_debit_points", result.get("net_debit_points", 0)) or 0,
                result.get("total_credit_points", 0) or 0,
                result.get("net_debit_points", 0) or 0,
                body.face_amount if status == "APPROVED" else None,
                result.get("approved_premium") or result.get("premium"),
                result.get("decline_reason_code"),
                result.get("adverse_action_text") or result.get("primary_reason"),
                __import__("json").dumps(findings, default=str),
                by_type,
                result.get("primary_reason"),
                username, username, tenant_id,
            ),
        )

        conn.commit()
        cur.close()
        return case_number

    except Exception as e:
        conn.rollback()
        logger.warning(f"Could not persist decision for {body.applicant_ref}: {e}")
        return None
    finally:
        release(conn)




def _upsert_applicant_master(cur, applicant_ref: str, body: dict, source: str = "ONLINE", uploaded_by: str = None):
    """
    Upsert demographic/contact data into applicant_master.
    Safe to call with partial data - only updates fields that are present and non-empty.
    Never overwrites existing data with blanks.
    """
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
                f"UPDATE applicant_master SET {chr(39).join([chr(44).join(sets)])} WHERE applicant_ref=%s".replace("'", ""),
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



def _upsert_applicant_master(cur, applicant_ref: str, body: dict, source: str = "ONLINE", uploaded_by: str = None):
    """
    Upsert demographic/contact data into applicant_master.
    Safe to call with partial data - only updates fields that are present and non-empty.
    Never overwrites existing data with blanks.
    """
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
                f"UPDATE applicant_master SET {chr(39).join([chr(44).join(sets)])} WHERE applicant_ref=%s".replace("'", ""),
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

def _fallback_evaluate(body: EvaluateRequest, current: CurrentUser) -> dict:
    """
    Built-in rules evaluation with UW Scale integration.
    1. Runs hardcoded medical/lifestyle rules → base debit points
    2. Looks up UW scales attached to product → scale debit points
    3. Sums both → compares against product thresholds → decision
    """
    conn, release = _get_db()
    try:
        import psycopg2.extras
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        cur = conn.cursor()

        # ── Load thresholds ───────────────────────────────────────────────────
        cur.execute(
            """
            SELECT stp_threshold, refer_threshold, decline_threshold
            FROM product_decision_thresholds
            WHERE product_code = %s ORDER BY created_at DESC LIMIT 1
            """,
            (body.product_code,),
        )
        row = cur.fetchone()
        if row:
            thresholds = dict(row)
        else:
            # Fall back to product-level thresholds
            cur.execute(
                "SELECT stp_threshold, refer_threshold, decline_threshold FROM products WHERE product_code=%s",
                (body.product_code,),
            )
            row2 = cur.fetchone()
            thresholds = dict(row2) if row2 else {
                "stp_threshold": 75, "refer_threshold": 150, "decline_threshold": 200
            }
        cur.close()

        debits      = 0
        rules_fired = []

        # ── Hard stops ────────────────────────────────────────────────────────
        if body.hiv_positive:
            return _hard_decline("HIV positive — hard stop on all individual products", body, "INSTANT_DECLINE")
        if body.cirrhosis:
            return _hard_decline("Liver cirrhosis — hard stop", body, "INSTANT_DECLINE")
        if body.occupation_class == "D":
            return _hard_decline("Declined occupation class", body, "INSTANT_DECLINE")

        # Age check
        cur2 = conn.cursor()
        cur2.execute("SELECT min_age, max_age FROM products WHERE product_code=%s", (body.product_code,))
        prod = cur2.fetchone()
        cur2.close()
        if prod:
            min_age = prod.get("min_age", 18) if hasattr(prod, "get") else prod[0]
            max_age = prod.get("max_age", 70) if hasattr(prod, "get") else prod[1]
            if body.age < min_age or body.age > max_age:
                return _hard_decline(
                    f"Age {body.age} outside product eligibility ({min_age}–{max_age})",
                    body, "INSTANT_DECLINE",
                )

        # ── Hardcoded medical rules ───────────────────────────────────────────
        if body.tobacco_status in ("SMOKER", "CIGAR", "CHEW", "VAPE"):
            debits += 50
            rules_fired.append({"rule_id": "R005", "rule_name": "Tobacco user", "debit_points": 50, "category": "MEDICAL"})

        bmi = _calc_bmi(body.model_dump())
        if bmi:
            if bmi > 35:
                debits += 75
                rules_fired.append({"rule_id": "R010", "rule_name": f"Elevated BMI ({bmi:.1f})", "debit_points": 75, "category": "BUILD"})
            elif bmi > 30:
                debits += 25
                rules_fired.append({"rule_id": "R010", "rule_name": f"Elevated BMI ({bmi:.1f})", "debit_points": 25, "category": "BUILD"})

        if body.diabetes_type == "TYPE1":
            debits += 100
            rules_fired.append({"rule_id": "R015", "rule_name": "Type 1 diabetes", "debit_points": 100, "category": "MEDICAL"})
        elif body.diabetes_type == "TYPE2":
            debits += 50
            rules_fired.append({"rule_id": "R015", "rule_name": "Type 2 diabetes", "debit_points": 50, "category": "MEDICAL"})

        if body.heart_condition in ("MI", "CABG", "STENT"):
            yrs = body.heart_event_years_ago or 0
            pts = 125 if yrs < 2 else 75 if yrs < 5 else 40
            debits += pts
            rules_fired.append({"rule_id": "R020", "rule_name": f"Cardiac: {body.heart_condition}", "debit_points": pts, "category": "MEDICAL"})

        bp  = body.blood_pressure
        sys = (bp.systolic if bp else None) or body.systolic_bp
        if sys and sys >= 160:
            debits += 50
            rules_fired.append({"rule_id": "R025", "rule_name": "Uncontrolled hypertension", "debit_points": 50, "category": "MEDICAL"})
        elif sys and sys >= 140:
            debits += 25
            rules_fired.append({"rule_id": "R025", "rule_name": "Stage 2 hypertension", "debit_points": 25, "category": "MEDICAL"})

        if (body.driving_record.dui_dwi_count_5yr if body.driving_record else 0) >= 2:
            return _hard_decline("2+ DUI/DWI convictions in last 5 years", body, "INSTANT_DECLINE")

        if body.alcohol_drinks_week and body.alcohol_drinks_week >= 22:
            debits += 50
            rules_fired.append({"rule_id": "R040", "rule_name": "Heavy alcohol use", "debit_points": 50, "category": "LIFESTYLE"})

        if body.hazardous_activity:
            debits += 30
            rules_fired.append({"rule_id": "R045", "rule_name": "Hazardous activity", "debit_points": 30, "category": "LIFESTYLE"})

        fh = body.family_history
        if fh and fh.cardiovascular_before_60:
            debits += 15
            rules_fired.append({"rule_id": "R050", "rule_name": "Family history CVD", "debit_points": 15, "category": "FAMILY"})

        if body.age > 55:
            debits += 30
            rules_fired.append({"rule_id": "R001", "rule_name": "Age loading 56+", "debit_points": 30, "category": "AGE"})
        elif body.age > 45:
            debits += 15
            rules_fired.append({"rule_id": "R001", "rule_name": "Age loading 46–55", "debit_points": 15, "category": "AGE"})

        # ── UW Scale integration ──────────────────────────────────────────────
        # Build applicant dict for scale parameter matching
        applicant_dict = body.model_dump()
        applicant_dict["age"] = body.age

        scale_debits, scale_rules = _evaluate_uw_scales(conn, body.product_code, applicant_dict)
        debits      += scale_debits
        rules_fired += scale_rules

        # ── Determine outcome ─────────────────────────────────────────────────
        stp_t     = thresholds.get("stp_threshold",     75)
        refer_t   = thresholds.get("refer_threshold",  150)
        decline_t = thresholds.get("decline_threshold", 200)

        if debits > decline_t:
            outcome    = "DECLINED"
            risk_class = "DECLINE"
            is_stp     = False
            pathway    = "INSTANT_DECLINE"
        elif debits > refer_t:
            outcome    = "REFERRED"
            risk_class = "SUBSTANDARD"
            is_stp     = False
            pathway    = "REFERRED"
        elif debits > stp_t:
            outcome    = "APPROVED_RATED"
            risk_class = "SUBSTANDARD"
            is_stp     = False
            pathway    = "ACCELERATED"
        else:
            outcome    = "APPROVED_STP"
            risk_class = "STANDARD" if debits > 25 else "PREFERRED"
            is_stp     = True
            pathway    = "STRAIGHT_THROUGH"

        now = datetime.now(timezone.utc).isoformat()

        # ── Premium calculation ───────────────────────────────────────────────
        approved_premium = None
        premium_detail   = None

        if outcome in ("APPROVED_STP", "APPROVED_RATED"):
            try:
                from services.premium_engine import PremiumEngine
                engine    = PremiumEngine(conn)
                prem      = engine.calculate(
                    product_code = body.product_code,
                    applicant    = body.model_dump(exclude_none=False),
                    uw_result    = {
                        "net_debit_points": debits,
                        "risk_class":       risk_class,
                    },
                    mode         = getattr(body, "premium_mode", "ANNUAL") or "ANNUAL",
                    formula_type = "BASE_PREMIUM",
                )
                if not prem.get("error") and prem.get("formula_found"):
                    approved_premium = prem.get("annual_premium")
                    premium_detail   = {
                        "annual_premium":    prem.get("annual_premium"),
                        "monthly_premium":   prem.get("all_modes", {}).get("MONTHLY", {}).get("modal_premium"),
                        "quarterly_premium": prem.get("all_modes", {}).get("QUARTERLY", {}).get("modal_premium"),
                        "half_yearly_premium": prem.get("all_modes", {}).get("HALF_YEARLY", {}).get("modal_premium"),
                        "total_first_year":  prem.get("all_modes", {}).get("ANNUAL", {}).get("total_first_year"),
                        "total_renewal":     prem.get("all_modes", {}).get("ANNUAL", {}).get("total_renewal"),
                        "all_modes":         prem.get("all_modes"),
                        "steps":             prem.get("steps_executed"),
                        "formula_name":      prem.get("formula_name"),
                    }
            except Exception as e:
                logger.warning(f"Premium calculation failed: {e}")
                premium_detail = {"error": str(e)}

        return {
            "outcome":            outcome,
            "risk_class":         risk_class,
            "net_debit_points":   debits,
            "base_debit_points":  debits - scale_debits,
            "scale_debit_points": scale_debits,
            "rules_fired":        rules_fired,
            "is_stp":             is_stp,
            "pathway":            pathway,
            "application_id":     body.applicant_ref,
            "evaluated_at":       now,
            "rules_version":      "fallback-2.0-with-scales",
            "thresholds_used":    thresholds,
            "approved_premium":   approved_premium,
            "premium_detail":     premium_detail,
        }
    finally:
        release(conn)


def _hard_decline(reason: str, body: EvaluateRequest, pathway: str) -> dict:
    return {
        "outcome":             "DECLINED",
        "risk_class":          "DECLINE",
        "net_debit_points":    999,
        "base_debit_points":   999,
        "scale_debit_points":  0,
        "rules_fired":         [{"rule_name": reason, "debit_points": 999, "category": "HARD_STOP"}],
        "is_stp":              False,
        "pathway":             pathway,
        "adverse_action_text": reason,
        "application_id":      body.applicant_ref,
        "evaluated_at":        datetime.now(timezone.utc).isoformat(),
        "rules_version":       "fallback-2.0-with-scales",
    }


def _persist_to_queue(body: EvaluateRequest, result: dict, current: CurrentUser):
    """Write result to policy_admin_queue so dashboard and cases page show it."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO policy_admin_queue
                (applicant_ref, product_code, face_amount, age, gender, state,
                 outcome, risk_class, net_debit_points, approved_premium,
                 premium_mode, decision_date, source, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), 'ONLINE', 'UNPROCESSED')
            RETURNING id
            """,
            (
                body.applicant_ref, body.product_code, body.face_amount,
                body.age, body.gender, body.state,
                result.get("outcome"), result.get("risk_class"),
                result.get("net_debit_points", 0),
                result.get("approved_premium"),
                getattr(body, "premium_mode", "ANNUAL") or "ANNUAL",
            ),
        )
        row      = cur.fetchone()
        case_id  = str(dict(row).get("id") if hasattr(row, "keys") else row[0]) if row else body.applicant_ref
        conn.commit()
        cur.close()


        # ── Upsert applicant_master with contact details ─────────────────────
        try:
            full_name_parts = [p for p in [
                getattr(body, "first_name", None),
                getattr(body, "middle_name", None),
                getattr(body, "last_name", None)
            ] if p]
            full_name = " ".join(full_name_parts) if full_name_parts else None
            ucur = conn.cursor()
            ucur.execute("""
                INSERT INTO applicant_master (
                    applicant_ref, full_name, email, mobile, phone,
                    gender, address_line1, city, state, pincode,
                    annual_income, source
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ONLINE')
                ON CONFLICT (applicant_ref) DO UPDATE SET
                    full_name    = COALESCE(EXCLUDED.full_name,    applicant_master.full_name),
                    email        = COALESCE(EXCLUDED.email,        applicant_master.email),
                    mobile       = COALESCE(EXCLUDED.mobile,       applicant_master.mobile),
                    phone        = COALESCE(EXCLUDED.phone,        applicant_master.phone),
                    gender       = COALESCE(EXCLUDED.gender,       applicant_master.gender),
                    address_line1= COALESCE(EXCLUDED.address_line1,applicant_master.address_line1),
                    city         = COALESCE(EXCLUDED.city,         applicant_master.city),
                    state        = COALESCE(EXCLUDED.state,        applicant_master.state),
                    pincode      = COALESCE(EXCLUDED.pincode,      applicant_master.pincode),
                    annual_income= COALESCE(EXCLUDED.annual_income,applicant_master.annual_income),
                    updated_at   = now()
            """, (
                body.applicant_ref,
                full_name,
                getattr(body,"email",None) or None,
                getattr(body,"mobile",None) or None,
                getattr(body,"mobile",None) or None,
                body.gender or None,
                getattr(body,"address_line1",None) or None,
                getattr(body,"city",None) or None,
                body.state or None,
                getattr(body,"pincode",None) or None,
                getattr(body,"annual_income",None) or None,
            ))
            conn.commit()
            ucur.close()
        except Exception as am_err:
            logger.warning(f"applicant_master upsert failed for {body.applicant_ref}: {am_err}")
            try: conn.rollback()
            except: pass

        # ── STP decision email notification ───────────────────────────────────
        outcome = result.get("outcome", "")
        # Resolve outcome here so email block and RI trigger both use it
        outcome = result.get("outcome", "")

        if "APPROVED" in outcome and "STP" in outcome:
            try:
                from services.notification import send_decision_email
                from database import get_conn, release_conn
                nconn = get_conn()
                try:
                    ncur = nconn.cursor()
                    ncur.execute(
                        "SELECT full_name, email FROM applicant_master WHERE applicant_ref=%s LIMIT 1",
                        (body.applicant_ref,)
                    )
                    arow = ncur.fetchone()
                    ncur.close()
                    if arow:
                        adict = dict(arow) if hasattr(arow,"keys") else {"full_name":arow[0],"email":arow[1]}
                        if adict.get("email"):
                            send_decision_email(
                                nconn,
                                to_email=adict["email"],
                                applicant_name=adict.get("full_name",""),
                                outcome=outcome,
                                applicant_ref=body.applicant_ref,
                                product_name=body.product_code,
                                premium=result.get("approved_premium"),
                                risk_class=result.get("risk_class"),
                                premium_detail=result.get("premium_detail"),
                            )
                    else:
                        from services.notification import log_missing_email_warning
                        log_missing_email_warning(nconn, body.applicant_ref, outcome)
                finally:
                    release_conn(nconn)
            except Exception as notif_err:
                logger.warning(f"STP decision email failed for {body.applicant_ref}: {notif_err}")

        # ── Reinsurance trigger ───────────────────────────────────────────────
        if "APPROVED" in outcome:
            try:
                from services.ri_trigger import check_and_trigger_reinsurance
                ri = check_and_trigger_reinsurance(
                    conn=conn,
                    case_id=case_id,
                    application_id=body.applicant_ref,
                    product_code=body.product_code,
                    face_amount=float(body.face_amount or 0),
                    approved_premium=float(result.get("approved_premium") or 0),
                    applicant_ref=body.applicant_ref,
                    submitted_by=current.username,
                )
                if ri["triggered"]:
                    logger.info(
                        f"RI triggered for {body.applicant_ref}: "
                        f"{ri['cession_ref']} — ceded ₹{ri['ceded_amount']:,.0f} "
                        f"to {ri['reinsurer_name']}"
                    )
            except Exception as ri_err:
                logger.warning(f"RI trigger failed for {body.applicant_ref}: {ri_err}")

    except Exception as e:
        logger.warning(f"_persist_to_queue failed: {e}", exc_info=True)
        # queue write failure must never break the decision response
    finally:
        release(conn)


# ── Case history ──────────────────────────────────────────────────────────────

@router.get("/cases")
def list_cases(current: CurrentUser, page_size: int = 50, page: int = 1):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        offset = (page - 1) * page_size
        cur.execute(
            """
            SELECT id, applicant_ref, product_code, face_amount, age, gender,
                   outcome, risk_class, net_debit_points, status,
                   decision_date AS created_at
            FROM policy_admin_queue
            ORDER BY decision_date DESC
            LIMIT %s OFFSET %s
            """,
            (page_size, offset),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    finally:
        release(conn)


@router.get("/dashboard-stats")
def dashboard_stats(current: CurrentUser):
    """
    Aggregate decision counts across BOTH single-evaluate (policy_admin_queue)
    and batch-processed (batch_job_records) records, for the main Dashboard.
    Excludes DRY_RUN and ERROR-status rows to match Performance Analytics.
    """
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                              AS total,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%APPROVED%%')  AS approved,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%DECLIN%%')    AS declined,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%REFER%%')     AS referred,
                COUNT(*) FILTER (WHERE outcome ILIKE '%%ERROR%%'
                                   OR outcome = 'PRODUCT_NOT_FOUND')  AS errored
            FROM (
                SELECT outcome, status FROM policy_admin_queue

                UNION ALL

                SELECT outcome, status FROM batch_job_records
            ) combined
            WHERE status NOT IN ('DRY_RUN', 'ERROR')
        """)
        row = cur.fetchone()
        cur.close()
        d = dict(row) if row else {
            "total": 0, "approved": 0, "declined": 0, "referred": 0, "errored": 0
        }
        for k in d:
            d[k] = int(d[k] or 0)

        # STP rate = approved / (approved + declined + referred), excluding errors
        decided = d["approved"] + d["declined"] + d["referred"]
        d["stp_rate"] = round((d["approved"] / decided) * 100, 1) if decided > 0 else 0

        return d
    except Exception as e:
        logger.error(f"dashboard_stats failed: {e}", exc_info=True)
        return {"total": 0, "approved": 0, "declined": 0, "referred": 0, "errored": 0, "stp_rate": 0}
    finally:
        release(conn)


# ── AI Score endpoint ─────────────────────────────────────────────────────────

class AIScoreRequest(BaseModel):
    engine:       str = "xgboost"   # xgboost | claude | ollama
    ollama_model: str | None = None  # override ollama model
    # All underwriting fields
    applicant_ref:        str   = "AI-SCORE"
    product_code:         str   = ""
    age:                  int   = 35
    gender:               str   = "MALE"
    state:                str   = "MH"
    face_amount:          float = 0
    coverage_term_yrs:    int   = 20
    tobacco_status:       str   = "NON_TOBACCO"
    height_inches:        float | None = None
    weight_lbs:           float | None = None
    systolic_bp:          int   = 120
    diastolic_bp:         int   = 80
    diabetes_type:        str   = "NONE"
    heart_condition:      str   = "NONE"
    hiv_positive:         bool  = False
    cirrhosis:            bool  = False
    stroke_history:       bool  = False
    kidney_disease:       bool  = False
    depression_history:   bool  = False
    depression_hospitalized: bool = False
    epilepsy:             bool  = False
    copd:                 bool  = False
    alcohol_drinks_week:  int   = 0
    hazardous_activity:   bool  = False
    occupation_class:     int   = 1
    annual_income:        float = 0
    existing_coverage:    float = 0
    # Pass UW decision context for richer AI assessment
    uw_outcome:           str   = ""
    net_debit_points:     int   = 0


@router.post("/ai-score")
def ai_score(body: AIScoreRequest, current: CurrentUser):
    """
    Get AI risk assessment from chosen engine.
    Engines: xgboost (local ML), claude (Anthropic API), ollama (local LLM)
    """
    from services.ai_score import get_ai_score, log_ai_decision
    conn, release = _get_db()
    try:
        payload = body.model_dump()
        result  = get_ai_score(payload, engine=body.engine, conn=conn)

        # ── AI Audit Trail ──────────────────────────────────────────────────
        if not result.get("error"):
            case_ref_id = None
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id FROM policy_admin_queue
                    WHERE applicant_ref=%s ORDER BY decision_date DESC LIMIT 1
                """, (body.applicant_ref,))
                row = cur.fetchone()
                cur.close()
                if row:
                    case_ref_id = (dict(row) if hasattr(row, "keys") else {"id": row[0]}).get("id")
            except Exception:
                conn.rollback()

            log_ai_decision(
                conn,
                ai_result=result,
                input_payload=payload,
                source="EVALUATE",
                case_ref_id=case_ref_id,
                applicant_ref=body.applicant_ref,
                product_code=body.product_code,
                requested_by=current.username,
            )

        return result
    except Exception as e:
        logger.error(f"AI score failed: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        release(conn)


# ── AI Audit Trail endpoint ───────────────────────────────────────────────────

@router.get("/ai-audit")
def ai_audit(
    current: CurrentUser,
    case_ref_id: int | None = None,
    applicant_ref: str | None = None,
    job_id: str | None = None,
    engine: str = "ALL",
    source: str = "ALL",
    page_size: int = 50,
    page: int = 1,
):
    """
    List AI-assist decision logs for explainability/regulatory review.
    Filter by case_ref_id, applicant_ref, job_id, engine, or source.
    """
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where, params = [], []
        if case_ref_id is not None:
            where.append("case_ref_id = %s"); params.append(case_ref_id)
        if applicant_ref:
            where.append("applicant_ref = %s"); params.append(applicant_ref)
        if job_id:
            where.append("job_id = %s"); params.append(job_id)
        if engine != "ALL":
            where.append("ai_engine = %s"); params.append(engine)
        if source != "ALL":
            where.append("source = %s"); params.append(source)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        offset = (page - 1) * page_size

        cur.execute(f"""
            SELECT id, case_ref_id, job_id, applicant_ref, product_code, source,
                   ai_engine, ai_model, risk_tier, risk_score, confidence,
                   recommendation, primary_concerns, positive_factors,
                   narrative, loading_suggestion, rules_outcome, rules_ndp,
                   human_decision, human_decided_by, human_decided_at, matches_ai,
                   requested_by, created_at
            FROM ai_decision_log
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])
        rows = [dict(r) for r in cur.fetchall()]

        cur.execute(f"SELECT COUNT(*) AS cnt FROM ai_decision_log {where_sql}", params)
        total = dict(cur.fetchone())["cnt"]

        # ── Summary stats: how often does human decision match AI? ───────────
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE matches_ai IS NOT NULL)              AS reviewed,
                COUNT(*) FILTER (WHERE matches_ai = true)                   AS matched,
                COUNT(*) FILTER (WHERE matches_ai = false)                  AS overridden
            FROM ai_decision_log
            {where_sql}
        """, params)
        agreement = dict(cur.fetchone())

        cur.close()

        for r in rows:
            r["risk_score"]  = float(r["risk_score"]) if r["risk_score"] is not None else None
            r["confidence"]  = float(r["confidence"]) if r["confidence"] is not None else None
            r["created_at"]  = str(r["created_at"]) if r["created_at"] else None
            r["human_decided_at"] = str(r["human_decided_at"]) if r["human_decided_at"] else None

        agreement_rate = (
            round((agreement["matched"] or 0) / agreement["reviewed"] * 100, 1)
            if agreement["reviewed"] else None
        )

        return {
            "logs": rows,
            "total": total,
            "agreement": {**agreement, "agreement_rate": agreement_rate},
        }
    except Exception as e:
        logger.error(f"ai_audit failed: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to load AI audit log: {e}")
    finally:
        release(conn)


# ══════════════════════════════════════════════════════════════════════════════
# BENEFIT GROUPING — Rider config + Multi-benefit proposal evaluation
# ══════════════════════════════════════════════════════════════════════════════

class BenefitLine(BaseModel):
    benefit_type:      str            # BASE | RIDER_CI | RIDER_ADB | RIDER_WOP | RIDER_ATPD
    product_code:      str
    face_amount:       float
    coverage_term_yrs: int = 20
    premium_mode:      str = "ANNUAL"
    # SAR inputs (optional — used by MORTALITY_PORTION / NET_AMOUNT_AT_RISK)
    policy_reserve:    float | None = None
    fund_value:        float | None = None


class ProposalRequest(BaseModel):
    model_config = {"extra": "allow"}
    proposal_ref:  str = "PROP-001"
    applicant_ref: str = "APP-001"
    age:           int
    gender:        str
    state:         str = "MH"
    annual_income: float = 100000
    # SAR / group-scheme context (optional)
    annual_salary:        float | None = None
    scheme_id:            str | None = None
    scheme_member_count:  int | None = None
    employer_code:        str | None = None
    # Medical fields — shared across all benefits
    tobacco_status:       str = "NEVER"
    heart_condition:      str = "NONE"
    diabetes_type:        str = "NONE"
    a1c:                  float | None = None
    hiv_positive:         bool = False
    cirrhosis:            bool = False
    stroke_history:       bool = False
    kidney_disease:       bool = False
    occupation_class:     str = "1"
    # Benefits list — first must be BASE
    benefits:             list[BenefitLine] = []


@router.get("/rider-config")
def get_rider_config(base_product_code: str, current: CurrentUser):
    """Return compatible riders for a given base product."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pbc.benefit_type, pbc.rider_product_code, pbc.inherits_medical,
                   pbc.max_rider_sa_pct, p.product_name AS rider_name
            FROM product_benefit_config pbc
            JOIN products p ON p.product_code = pbc.rider_product_code
            WHERE pbc.tenant_id = %s::uuid
              AND pbc.base_product_code = %s
              AND pbc.is_active = true
            ORDER BY pbc.benefit_type
        """, (current.tenant_id, base_product_code))
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = dict(r) if hasattr(r, "keys") else {
                "benefit_type": r[0], "rider_product_code": r[1],
                "inherits_medical": r[2], "max_rider_sa_pct": r[3], "rider_name": r[4]
            }
            if d.get("max_rider_sa_pct"):
                d["max_rider_sa_pct"] = float(d["max_rider_sa_pct"])
            result.append(d)
        return result
    except Exception as e:
        raise HTTPException(500, f"Rider config lookup failed: {e}")
    finally:
        release(conn)


@router.post("/evaluate-proposal")
def evaluate_proposal(body: ProposalRequest, current: FlexibleAuth):
    """
    Multi-benefit proposal evaluation.
    Evaluates base product + all rider lines using shared medical context.
    Applies cross-benefit rules (if BASE declined, all riders declined).
    Returns per-benefit decisions + composite overall_status + total premium.
    """
    if current.role not in ("underwriter","senior_underwriter","admin","super_admin","api_client"):
        raise HTTPException(403, "Underwriters only")

    if not body.benefits:
        raise HTTPException(400, "At least one benefit (BASE) is required")

    base = next((b for b in body.benefits if b.benefit_type == "BASE"), None)
    if not base:
        raise HTTPException(400, "First benefit must have benefit_type='BASE'")

    import time
    conn, release = _get_db()
    try:
        # Build shared medical payload from proposal request
        shared = body.model_dump(exclude={"benefits"})
        shared["applicant_ref"] = body.applicant_ref

        # ── Sum-at-Risk (SAR) pre-computation (Phase 1/2) ──────────────
        # Runs the configurable SAR engine: individual SAR per benefit,
        # risk-group aggregation, exposure-group split, FCL check. Used to
        # auto-approve benefits fully covered by a Free Cover Limit and to
        # surface medical requirements from the NML bands. Non-fatal — if
        # SAR config is missing/errors, proposal evaluation proceeds as today.
        sar           = None
        sar_benefits  = []
        proposal_id   = None
        try:
            from services.sar_service import run_sar
            sar_benefits = [
                {**benefit.model_dump(), "_idx": i}
                for i, benefit in enumerate(body.benefits)
            ]
            sar = run_sar(
                conn, str(current.tenant_id), base.product_code,
                applicant={
                    "applicant_ref": body.applicant_ref,
                    "age":           body.age,
                    "annual_salary": body.annual_salary,
                },
                benefits=sar_benefits,
                scheme_id=body.scheme_id,
                scheme_member_count=body.scheme_member_count,
                employer_code=body.employer_code,
            )
        except Exception as se:
            logger.warning(f"SAR computation failed (non-fatal): {se}")

        benefit_results = []
        base_outcome    = None
        base_debits     = 0
        total_premium   = 0.0

        for i, benefit in enumerate(body.benefits):
            t0 = time.time()
            is_base = benefit.benefit_type == "BASE"

            # Build per-benefit payload
            payload = {
                **shared,
                "product_code":      benefit.product_code,
                "face_amount":       benefit.face_amount,
                "coverage_term_yrs": benefit.coverage_term_yrs,
                "premium_mode":      benefit.premium_mode,
            }

            # Cross-benefit rule: if BASE was DECLINED, all riders are declined (linked)
            linked_decline = False

            # SAR: benefit whose exposure bucket is fully covered by a Free
            # Cover Limit (excess SAR = 0) is auto-approved without running
            # the medical rules engine (SAR pipeline step 5 + 9).
            if sar and str(i) in (sar.get("auto_approve_benefit_ids") or []):
                benefit_results.append({
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "APPROVED_STP",
                    "risk_class":       "STANDARD",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [{
                        "rule":   "SAR_FCL_AUTO_APPROVE",
                        "reason": "Covered by Free Cover Limit — gross SAR within FCL, no medical underwriting required",
                    }],
                    "exclusions":       None,
                    "linked_decline":   False,
                    "processing_ms":    0,
                    "sar_auto_approve": True,
                })
                if is_base:
                    base_outcome = "APPROVED_STP"
                continue

            # SAR cumulative escalation (Phase 3, V029): a cumulative-SAR
            # decision overrides the per-benefit engine result for benefits
            # NOT already covered by a Free Cover Limit (excess SAR > 0).
            #   DECLINE     -> benefit declined (cumulative SAR over the cap)
            #   RI_APPROVAL / ri_approval_required -> referred to reinsurer
            #   SENIOR_UW   -> escalated to senior underwriter
            #   REFER       -> auto-referred to a human underwriter
            sar_esc = (sar or {}).get("escalation")
            sar_ri  = (sar or {}).get("ri_approval_required", False)
            if sar_esc == "DECLINE":
                benefit_results.append({
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "DECLINED",
                    "risk_class":       "DECLINE",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [{"rule": "SAR_CUMULATIVE_DECLINE",
                        "reason": "Cumulative Sum-at-Risk across existing policies + this proposal exceeds the decline threshold"}],
                    "exclusions":       None,
                    "linked_decline":   True,
                    "processing_ms":    0,
                    "sar_escalation":   "DECLINE",
                })
                if is_base:
                    base_outcome = "DECLINED"
                continue
            if sar_esc in ("RI_APPROVAL", "SENIOR_UW", "REFER") or sar_ri:
                _esc_label = "RI approval required" if (sar_esc == "RI_APPROVAL" or sar_ri) else ("Senior UW review required" if sar_esc == "SENIOR_UW" else "Auto-refer (cumulative SAR)")
                _esc_rule  = "SAR_RI_APPROVAL" if (sar_esc == "RI_APPROVAL" or sar_ri) else ("SAR_SENIOR_UW" if sar_esc == "SENIOR_UW" else "SAR_AUTO_REFER")
                benefit_results.append({
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "REFERRED",
                    "risk_class":       "REFERRED",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [{"rule": _esc_rule, "reason": _esc_label + " — cumulative Sum-at-Risk over the configured threshold"}],
                    "exclusions":       None,
                    "linked_decline":   False,
                    "processing_ms":    0,
                    "sar_escalation":   sar_esc or "RI_APPROVAL",
                })
                if is_base:
                    base_outcome = "REFERRED"
                continue

            if not is_base and base_outcome and "DECLIN" in base_outcome:
                result_row = {
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "DECLINED",
                    "risk_class":       "DECLINE",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [],
                    "exclusions":       None,
                    "linked_decline":   True,
                    "processing_ms":    0,
                }
                benefit_results.append(result_row)
                continue

            # Cross-benefit rule: if BASE debits > 300, CI rider auto-declined
            if benefit.benefit_type == "RIDER_CI" and base_debits > 300:
                result_row = {
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "DECLINED",
                    "risk_class":       "DECLINE",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [{"rule": "CROSS_BENEFIT_CI_BLOCK", "reason": f"Base debit score {base_debits} exceeds CI rider threshold (300)"}],
                    "exclusions":       None,
                    "linked_decline":   True,
                    "processing_ms":    0,
                }
                benefit_results.append(result_row)
                continue

            # Cross-benefit rule: if BASE debits 150-300, CI rider auto-referred
            if benefit.benefit_type == "RIDER_CI" and base_debits >= 150:
                result_row = {
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "REFERRED",
                    "risk_class":       "SUBSTANDARD",
                    "net_debit_points": base_debits,
                    "annual_premium":   None,
                    "rules_fired":      [{"rule": "CROSS_BENEFIT_CI_REFER", "reason": f"Base debit score {base_debits} triggers CI rider referral (150-300 range)"}],
                    "exclusions":       None,
                    "linked_decline":   False,
                    "processing_ms":    0,
                }
                benefit_results.append(result_row)
                continue

            # Run the actual UW engine for this benefit
            try:
                from services.uw_engine import run_evaluation
                uw_result = run_evaluation(payload, current.username, current.tenant_id)
            except ImportError:
                uw_result = _fallback_evaluate(
                    type("B", (), payload)(), current  # type: ignore
                )

            outcome          = uw_result.get("outcome", "ERROR")
            net_debits       = uw_result.get("net_debit_points", 0)
            _prem_detail     = uw_result.get("premium_detail") or {}
            annual_premium   = uw_result.get("approved_premium") or _prem_detail.get("annual_premium")
            processing_ms    = int((time.time() - t0) * 1000)

            # Track base outcome/debits for cross-benefit rules
            if is_base:
                base_outcome = outcome
                base_debits  = net_debits or 0

            # Rider flat rate fallback if no premium returned
            if annual_premium is None and "APPROVED" in outcome and not is_base:
                flat_rates = {
                    "RIDER_CI":   2.50,
                    "RIDER_ADB":  0.50,
                    "RIDER_WOP":  0.30,
                    "RIDER_ATPD": 0.80,
                }
                rate = flat_rates.get(benefit.benefit_type, 1.0)
                age_loading = max(0, (body.age - 35) * 0.02)
                effective_rate = rate * (1 + age_loading)
                annual_premium = round(effective_rate * benefit.face_amount / 1000, 2)

            # Accumulate premium only for approved benefits
            if annual_premium and "APPROVED" in outcome:
                total_premium += float(annual_premium)

            # Build exclusions for CI rider if approved with medical conditions
            exclusions = None
            if benefit.benefit_type == "RIDER_CI" and "APPROVED" in outcome:
                exc_list = []
                if body.diabetes_type not in ("NONE", None):
                    exc_list.append({"condition": "DIABETES", "text": "No CI benefit payable for diabetes or diabetes-related complications", "permanent": True})
                if body.heart_condition not in ("NONE", None):
                    exc_list.append({"condition": "CARDIAC", "text": "No CI benefit payable for cardiac conditions", "permanent": True})
                if exc_list:
                    exclusions = exc_list
                    outcome = "APPROVED_EXCLUDED"

            result_row = {
                "benefit_type":     benefit.benefit_type,
                "product_code":     benefit.product_code,
                "face_amount":      benefit.face_amount,
                "outcome":          outcome,
                "risk_class":       uw_result.get("risk_class"),
                "net_debit_points": net_debits,
                "annual_premium":   round(float(annual_premium), 2) if annual_premium else None,
                "rules_fired":      uw_result.get("rules_fired", [])[:5],  # trim for response size
                "exclusions":       exclusions,
                "linked_decline":   False,
                "processing_ms":    processing_ms,
            }
            benefit_results.append(result_row)

        # Compute overall_status
        outcomes  = [b["outcome"] for b in benefit_results]
        all_clean = all(o in ("APPROVED_STP","APPROVED","APPROVED_RATED") for o in outcomes)
        any_appr  = any("APPROVED" in o for o in outcomes)
        all_decl  = all("DECLIN" in o for o in outcomes)
        any_excl  = any(o == "APPROVED_EXCLUDED" for o in outcomes)
        any_ref   = any("REFER" in o for o in outcomes)

        any_decl  = any("DECLIN" in o for o in outcomes)

        if all_decl:
            overall = "ALL_DECLINED"
        elif all_clean and not any_excl:
            overall = "ALL_APPROVED"
        elif any_appr and (any_excl or any_ref or any_decl):
            overall = "PARTIALLY_APPROVED"
        elif any_ref:
            overall = "REFERRED"
        else:
            overall = "PARTIALLY_APPROVED"

        # Persist to proposal + proposal_benefit tables
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO proposal
                    (proposal_ref, tenant_id, applicant_ref, overall_status,
                     total_annual_premium, premium_mode, source, submitted_by)
                VALUES (%s, %s::uuid, %s, %s, %s, %s, 'ONLINE', %s)
                ON CONFLICT (tenant_id, proposal_ref) DO UPDATE
                SET overall_status = EXCLUDED.overall_status,
                    total_annual_premium = EXCLUDED.total_annual_premium,
                    updated_at = now()
                RETURNING id
            """, (
                body.proposal_ref, current.tenant_id, body.applicant_ref,
                overall, round(total_premium, 2),
                base.premium_mode if base else "ANNUAL",
                current.username,
            ))
            _prow = cur.fetchone()
            proposal_id = dict(_prow)["id"] if hasattr(_prow,"keys") else _prow[0]

            for br in benefit_results:
                cur.execute("""
                    INSERT INTO proposal_benefit
                        (proposal_id, benefit_type, product_code, face_amount,
                         outcome, risk_class, net_debit_points, annual_premium,
                         exclusions, rules_fired, linked_decline)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """, (
                    proposal_id, br["benefit_type"], br["product_code"], br["face_amount"],
                    br["outcome"], br["risk_class"], br["net_debit_points"], br["annual_premium"],
                    __import__("json").dumps(br["exclusions"]) if br["exclusions"] else None,
                    __import__("json").dumps(br["rules_fired"]) if br["rules_fired"] else None,
                    br["linked_decline"],
                ))
            conn.commit()
            cur.close()
        except Exception as pe:
            logger.warning(f"Proposal persistence failed: {pe}")
            conn.rollback()

        # Persist the SAR breakdown now that the proposal row exists
        # (best-effort; never fails the proposal evaluation).
        if sar and sar.get("configured") and proposal_id:
            try:
                from services.sar_service import persist_sar
                if persist_sar(conn, str(current.tenant_id), str(proposal_id), sar, sar_benefits):
                    conn.commit()
                else:
                    conn.rollback()
            except Exception as _sar_err:
                logger.warning(f"SAR result persistence skipped: {_sar_err}")
                conn.rollback()

        # Send ONE consolidated email covering all benefits
        try:
            from services.notification import send_proposal_decision_email
            from database import get_conn as _gc, release_conn as _rc
            _c2 = _gc()
            _cur2 = _c2.cursor()
            _cur2.execute(
                "SELECT email, full_name FROM applicant_master WHERE applicant_ref=%s LIMIT 1",
                (body.applicant_ref,))
            _row = _cur2.fetchone()
            _cur2.close()
            if _row:
                _m = dict(_row) if hasattr(_row,"keys") else {"email":_row[0],"full_name":_row[1]}
                if _m.get("email"):
                    send_proposal_decision_email(
                        conn=_c2,
                        to_email=_m["email"],
                        applicant_name=_m.get("full_name") or body.applicant_ref,
                        applicant_ref=body.applicant_ref,
                        proposal_ref=body.proposal_ref,
                        overall_status=overall,
                        benefit_decisions=[{
                            "product_code":      br["product_code"],
                            "benefit_label":     br.get("benefit_type",""),
                            "outcome":           br["outcome"],
                            "risk_class":        br.get("risk_class"),
                            "annual_premium":    br.get("annual_premium"),
                            "face_amount":       br.get("face_amount"),
                            "coverage_term_yrs": br.get("coverage_term_yrs", 20),
                            "linked_decline":    br.get("linked_decline", False),
                        } for br in benefit_results])
            _rc(_c2)
        except Exception as _email_err:
            logger.warning(f"Proposal email skipped: {_email_err}")

        return {
            "proposal_ref":        body.proposal_ref,
            "applicant_ref":       body.applicant_ref,
            "overall_status":      overall,
            "total_annual_premium": round(total_premium, 2),
            "benefits":            benefit_results,
            "benefit_count":       len(benefit_results),
            # Sum-at-Risk breakdown (Phase 1/2): per-benefit + per-risk-group
            # + per-exposure-group SAR, FCL applied, excess SAR, and NML
            # medical requirements. None when SAR config is absent.
            "sar":                 sar,
            "sar_escalation":      (sar or {}).get("escalation"),
            "medical_requirements": (sar or {}).get("medical_requirements", []),
            "evaluated_at":        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"evaluate_proposal failed: {e}", exc_info=True)
        raise HTTPException(500, f"Proposal evaluation failed: {e}")
    finally:
        release(conn)
