"""
backend/services/uw_engine.py
──────────────────────────────
Core underwriting rules engine.
Called by routers/underwriting.py:  run_evaluation(payload, actor, tenant_id)

Rule catalogue (mirrors uw_platform.py logic):
  R001  Age loading
  R005  Tobacco status
  R010  Build / BMI
  R015  Diabetes
  R020  Cardiac history
  R025  Blood pressure / hypertension
  R030  Medical flags (HIV, cirrhosis, stroke, kidney, depression, epilepsy, COPD)
  R040  Alcohol use
  R045  Hazardous activity (flat extra)
  R050  Family history
  R055  Occupation class
  R060  Driving record (DUI / major violations)
  R070  Financial underwriting (income multiple)
  R080  Lab values (cholesterol, eGFR)

Decision thresholds are loaded from product_decision_thresholds table.
Falls back to system defaults if table row is missing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("uw_platform")

# ── Default thresholds (overridden per-product from DB) ───────────────────────
DEFAULT_STP_THRESHOLD     = 75
DEFAULT_REFER_THRESHOLD   = 150
DEFAULT_DECLINE_THRESHOLD = 200


def _get_thresholds(product_code: str) -> dict:
    try:
        from database import get_conn, release_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT stp_threshold, refer_threshold, decline_threshold "
            "FROM product_decision_thresholds "
            "WHERE product_code=%s ORDER BY created_at DESC LIMIT 1",
            (product_code,),
        )
        row = cur.fetchone()
        cur.close()
        release_conn(conn)
        if row:
            d = dict(row) if hasattr(row, "keys") else dict(
                zip(["stp_threshold", "refer_threshold", "decline_threshold"], row)
            )
            return d
    except Exception as exc:
        logger.warning("Could not load thresholds from DB", exc_info=exc)
    return {
        "stp_threshold":     DEFAULT_STP_THRESHOLD,
        "refer_threshold":   DEFAULT_REFER_THRESHOLD,
        "decline_threshold": DEFAULT_DECLINE_THRESHOLD,
    }


def _get_product(product_code: str) -> dict:
    try:
        from database import get_conn, release_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT min_age, max_age, min_face, max_face, is_gi "
            "FROM product WHERE product_code=%s AND is_active=true LIMIT 1",
            (product_code,),
        )
        row = cur.fetchone()
        cur.close()
        release_conn(conn)
        if row:
            return dict(row) if hasattr(row, "keys") else dict(
                zip(["min_age","max_age","min_face","max_face","is_gi"], row)
            )
    except Exception as exc:
        logger.warning("Could not load product from DB", exc_info=exc)
    return {"min_age": 18, "max_age": 70, "min_face": 0, "max_face": 0, "is_gi": False}


# ── Helper: safe nested get ───────────────────────────────────────────────────

def _g(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d if d is not None else default


# ── Main entry point ──────────────────────────────────────────────────────────

def run_evaluation(payload: dict, actor: str, tenant_id: str | None) -> dict:
    """
    Run the full UW rules engine against payload.
    Returns a UWDecisionResponse-compatible dict.
    """
    product_code = payload.get("product_code", "")
    age          = int(payload.get("age", 0))
    face_amount  = float(payload.get("face_amount", 0))
    gender       = payload.get("gender", "MALE")
    applicant_ref= payload.get("applicant_ref", "APP")

    thresholds = _get_thresholds(product_code)
    product    = _get_product(product_code)

    debits:  int = 0
    credits: int = 0
    rules_fired: list[dict] = []

    def fire(rule_id: str, name: str, pts: int, category: str,
             desc: str = "", hard_stop: bool = False,
             requires_aps: bool = False, aps_reason: str = ""):
        nonlocal debits, credits
        if pts > 0:
            debits += pts
        elif pts < 0:
            credits += abs(pts)
        rules_fired.append({
            "rule_id":      rule_id,
            "rule_name":    name,
            "debit_points": max(pts, 0),
            "credit_points": max(-pts, 0),
            "category":     category,
            "description":  desc,
            "hard_stop":    hard_stop,
            "requires_aps": requires_aps,
            "aps_reason":   aps_reason,
        })

    # ── Hard stop checks ─────────────────────────────────────────────────────

    if payload.get("hiv_positive"):
        return _hard_decline("HIV positive — hard stop on all individual life products",
                             applicant_ref, rules_fired)

    if payload.get("cirrhosis"):
        return _hard_decline("Liver cirrhosis — hard stop",
                             applicant_ref, rules_fired)

    occ_class = str(payload.get("occupation_class", "1"))
    if occ_class == "D":
        return _hard_decline("Declined occupation class (Class D)",
                             applicant_ref, rules_fired)

    driving = payload.get("driving_record") or {}
    if _g(driving, "dui_dwi_count_5yr", default=0) >= 2:
        return _hard_decline("2 or more DUI/DWI convictions in last 5 years",
                             applicant_ref, rules_fired)

    if _g(driving, "license_suspended", default=False):
        fire("R060", "Licence suspended", 100, "DRIVING",
             "Driving licence currently suspended")

    # ── Product eligibility ───────────────────────────────────────────────────

    min_age = product.get("min_age") or 18
    max_age = product.get("max_age") or 70
    if age < min_age or age > max_age:
        return _hard_decline(
            f"Age {age} outside product eligibility range {min_age}–{max_age}",
            applicant_ref, rules_fired,
        )

    # ── R001 Age loading ──────────────────────────────────────────────────────

    if age >= 61:
        fire("R001", "Age loading 61+", 40, "AGE", f"Age {age}")
    elif age >= 56:
        fire("R001", "Age loading 56–60", 25, "AGE", f"Age {age}")
    elif age >= 46:
        fire("R001", "Age loading 46–55", 15, "AGE", f"Age {age}")

    # ── R005 Tobacco ──────────────────────────────────────────────────────────

    tobacco = payload.get("tobacco_status", "NEVER")
    if tobacco == "SMOKER":
        fire("R005", "Current smoker", 75, "TOBACCO",
             "Active cigarette smoker — standard smoker rates apply")
    elif tobacco in ("CIGAR", "PIPE"):
        fire("R005", "Cigar/pipe user", 50, "TOBACCO")
    elif tobacco in ("CHEW", "VAPE"):
        fire("R005", "Smokeless/vape tobacco", 50, "TOBACCO")
    elif tobacco == "NON_SMOKER":
        quit_yrs = float(payload.get("tobacco_quit_years") or 0)
        if quit_yrs < 1:
            fire("R005", "Recent tobacco cessation <1yr", 50, "TOBACCO",
                 "Quit less than 12 months ago — tobacco rates still apply")
        elif quit_yrs < 2:
            fire("R005", "Tobacco cessation 1–2yr", 25, "TOBACCO")

    # ── R010 Build / BMI ──────────────────────────────────────────────────────

    build = payload.get("build") or {}
    h = float(build.get("height_inches") or payload.get("height_inches") or 0)
    w = float(build.get("weight_lbs")    or payload.get("weight_lbs")    or 0)
    if h > 0 and w > 0:
        bmi = (w / (h ** 2)) * 703
        if bmi >= 40:
            fire("R010", "Severe obesity BMI ≥40", 100, "BUILD",
                 f"BMI {bmi:.1f}", requires_aps=True, aps_reason="Severe obesity — APS required")
        elif bmi >= 35:
            fire("R010", "Obesity BMI 35–39.9", 75, "BUILD", f"BMI {bmi:.1f}")
        elif bmi >= 30:
            fire("R010", "Overweight BMI 30–34.9", 25, "BUILD", f"BMI {bmi:.1f}")
        elif bmi < 17:
            fire("R010", "Underweight BMI <17", 50, "BUILD", f"BMI {bmi:.1f}",
                 requires_aps=True, aps_reason="Underweight — APS required")

    # ── R015 Diabetes ─────────────────────────────────────────────────────────

    diabetes = payload.get("diabetes_type", "NONE")
    if diabetes == "TYPE1":
        a1c = float(payload.get("a1c") or 7.0)
        pts = 150 if a1c > 9 else 100 if a1c > 7.5 else 75
        fire("R015", f"Type 1 diabetes A1c={a1c}%", pts, "DIABETES",
             requires_aps=True, aps_reason="Type 1 diabetes — APS and latest labs required")
    elif diabetes == "TYPE2":
        a1c = float(payload.get("a1c") or 7.0)
        dx_age = int(payload.get("diabetes_dx_age") or age)
        duration = max(0, age - dx_age)
        pts = 75 if a1c > 9 else 50 if a1c > 7.5 else 25
        if duration > 10:
            pts += 25
        fire("R015", f"Type 2 diabetes A1c={a1c}%", pts, "DIABETES",
             f"Duration {duration}yr, A1c {a1c}%")
    elif diabetes == "PRE_DIABETIC":
        fire("R015", "Pre-diabetic", 15, "DIABETES")

    # ── R020 Cardiac ──────────────────────────────────────────────────────────

    heart = payload.get("heart_condition", "NONE")
    heart_yrs = float(payload.get("heart_event_years_ago") or 0)
    if heart == "MI":
        if heart_yrs < 1:
            return _hard_decline("MI within last 12 months — postpone minimum 12 months",
                                 applicant_ref, rules_fired)
        pts = 150 if heart_yrs < 2 else 100 if heart_yrs < 5 else 50
        fire("R020", f"Myocardial infarction {heart_yrs:.1f}yr ago", pts, "CARDIAC",
             requires_aps=True, aps_reason="Post-MI — full cardiac APS required")
    elif heart in ("CABG", "STENT"):
        pts = 125 if heart_yrs < 2 else 75 if heart_yrs < 5 else 40
        fire("R020", f"{heart} {heart_yrs:.1f}yr ago", pts, "CARDIAC",
             requires_aps=True, aps_reason="Post cardiac procedure — APS required")
    elif heart == "ANGINA":
        fire("R020", "Angina", 75, "CARDIAC")
    elif heart == "ARRHYTHMIA":
        fire("R020", "Arrhythmia", 50, "CARDIAC")
    elif heart in ("HYPERTENSION_UNCONTROLLED",):
        fire("R020", "Uncontrolled hypertension (cardiac)", 50, "CARDIAC")
    elif heart == "HYPERTENSION":
        fire("R020", "Hypertension (controlled)", 20, "CARDIAC")

    # ── R025 Blood pressure ───────────────────────────────────────────────────

    bp = payload.get("blood_pressure") or {}
    systolic  = int(bp.get("systolic")  or payload.get("systolic_bp")  or 0)
    diastolic = int(bp.get("diastolic") or payload.get("diastolic_bp") or 0)
    bp_meds   = bool(bp.get("on_medication", False))

    if systolic >= 180 or diastolic >= 110:
        fire("R025", "Severe hypertension BP ≥180/110", 100, "BP",
             f"{systolic}/{diastolic}", requires_aps=True, aps_reason="Severe BP — APS required")
    elif systolic >= 160 or diastolic >= 100:
        pts = 50 if not bp_meds else 35
        fire("R025", "Stage 2 hypertension", pts, "BP", f"{systolic}/{diastolic}")
    elif systolic >= 140 or diastolic >= 90:
        pts = 25 if not bp_meds else 15
        fire("R025", "Stage 1 hypertension", pts, "BP", f"{systolic}/{diastolic}")

    # ── R030 Medical flags ────────────────────────────────────────────────────

    if payload.get("stroke_history"):
        fire("R030", "Stroke / TIA history", 100, "MEDICAL",
             requires_aps=True, aps_reason="Stroke history — neurological APS required")

    if payload.get("kidney_disease"):
        labs = payload.get("lab_values") or {}
        egfr = float(labs.get("egfr") or 60)
        if egfr < 30:
            return _hard_decline(f"Kidney disease eGFR {egfr} — Stage 4/5 CKD",
                                 applicant_ref, rules_fired)
        pts = 75 if egfr < 45 else 40
        fire("R030", f"Chronic kidney disease eGFR {egfr}", pts, "MEDICAL")

    if payload.get("depression_history"):
        pts = 75 if payload.get("depression_hospitalized") else 30
        fire("R030", "Depression history" + (" (hospitalised)" if payload.get("depression_hospitalized") else ""),
             pts, "MEDICAL")

    if payload.get("epilepsy"):
        fire("R030", "Epilepsy / seizure disorder", 50, "MEDICAL",
             requires_aps=True, aps_reason="Epilepsy — neurology APS required")

    if payload.get("copd"):
        fire("R030", "COPD", 50, "MEDICAL",
             requires_aps=True, aps_reason="COPD — pulmonary APS required")

    # ── R040 Alcohol ──────────────────────────────────────────────────────────

    drinks = int(payload.get("alcohol_drinks_week") or 0)
    if drinks >= 28:
        fire("R040", "Heavy alcohol use ≥28 units/week", 75, "LIFESTYLE", f"{drinks} units/wk")
    elif drinks >= 21:
        fire("R040", "Moderate-heavy alcohol use 21–27 units/week", 40, "LIFESTYLE")

    # ── R045 Hazardous activity (flat extra) ──────────────────────────────────

    if payload.get("hazardous_activity"):
        hazard_types = payload.get("hazard_types") or []
        high_hazard = {"BASE_JUMPING", "MOTOR_RACING", "PRIVATE_PILOT"}
        pts = 50 if any(h in high_hazard for h in hazard_types) else 30
        fire("R045", "Hazardous activity flat extra", pts, "LIFESTYLE",
             f"Activities: {', '.join(hazard_types) or 'unspecified'}")

    # ── R050 Family history ───────────────────────────────────────────────────

    fh = payload.get("family_history") or {}
    if _g(fh, "cardiovascular_before_60"):
        fire("R050", "Family history CVD before age 60", 15, "FAMILY_HISTORY")
    if _g(fh, "stroke_before_65"):
        fire("R050", "Family history stroke before age 65", 10, "FAMILY_HISTORY")
    if _g(fh, "cancer_history"):
        fire("R050", "Family history cancer", 10, "FAMILY_HISTORY")

    # ── R055 Occupation ───────────────────────────────────────────────────────

    occ_pts = {"1": 0, "2": 10, "3": 25, "4": 50}
    pts = occ_pts.get(occ_class, 0)
    if pts > 0:
        fire("R055", f"Occupation class {occ_class}", pts, "OCCUPATION")

    # ── R060 Driving record ───────────────────────────────────────────────────

    dui = _g(driving, "dui_dwi_count_5yr", default=0)
    major_vio = _g(driving, "major_violations_3yr", default=0)
    if dui == 1:
        fire("R060", "1 DUI/DWI in last 5 years", 50, "DRIVING")
    if major_vio >= 3:
        fire("R060", f"{major_vio} major driving violations in last 3 years", 50, "DRIVING")
    elif major_vio == 2:
        fire("R060", "2 major driving violations in last 3 years", 25, "DRIVING")

    # ── R070 Financial underwriting ───────────────────────────────────────────

    fin = payload.get("financial") or {}
    income   = float(fin.get("annual_income") or payload.get("annual_income") or 0)
    existing = float(fin.get("existing_life_coverage") or payload.get("existing_coverage") or 0)
    if income > 0:
        max_coverage = income * 20
        total_coverage = face_amount + existing
        if total_coverage > max_coverage:
            fire("R070", "Financial underwriting — coverage exceeds 20× income",
                 30, "FINANCIAL",
                 f"Total coverage ₹{total_coverage:,.0f} vs max ₹{max_coverage:,.0f}",
                 requires_aps=True, aps_reason="Excess coverage — financial justification required")

    # ── R080 Lab values ───────────────────────────────────────────────────────

    labs = payload.get("lab_values") or {}
    total_chol = float(labs.get("total_cholesterol") or 0)
    hdl        = float(labs.get("hdl") or 0)
    ldl        = float(labs.get("ldl") or 0)

    if total_chol >= 260:
        fire("R080", f"High total cholesterol {total_chol} mg/dL", 25, "LABS")
    if hdl > 0 and total_chol > 0:
        ratio = total_chol / hdl
        if ratio > 6:
            fire("R080", f"High cholesterol ratio {ratio:.1f}", 25, "LABS")
    if ldl >= 190:
        fire("R080", f"Very high LDL {ldl} mg/dL", 25, "LABS")

    # ── Gender credit (females lower mortality at most ages) ──────────────────

    if gender == "FEMALE" and age <= 55:
        credits += 5  # minor mortality credit

    # ── Determine final outcome ───────────────────────────────────────────────

    stp_t     = int(thresholds.get("stp_threshold", DEFAULT_STP_THRESHOLD))
    refer_t   = int(thresholds.get("refer_threshold", DEFAULT_REFER_THRESHOLD))
    decline_t = int(thresholds.get("decline_threshold", DEFAULT_DECLINE_THRESHOLD))

    net = debits - credits

    if net > decline_t:
        outcome    = "DECLINED"
        risk_class = "DECLINE"
        is_stp     = False
        pathway    = "INSTANT_DECLINE"
        adverse    = _top_reasons(rules_fired)
    elif net > refer_t:
        outcome    = "REFERRED"
        risk_class = "SUBSTANDARD"
        is_stp     = False
        pathway    = "REFERRED"
        adverse    = None
    elif net > stp_t:
        # Rated but approvable
        table = min(8, max(1, (net - stp_t) // 15))
        outcome    = "APPROVED_RATED"
        risk_class = f"TABLE_{table}"
        is_stp     = False
        pathway    = "ACCELERATED"
        adverse    = None
    else:
        outcome    = "APPROVED_STP"
        risk_class = "PREFERRED" if net <= 15 else "STANDARD"
        is_stp     = True
        pathway    = "STRAIGHT_THROUGH"
        adverse    = None

    # Check if any rule requires APS — bump STP to REFERRED
    aps_needed = any(r.get("requires_aps") for r in rules_fired)
    if aps_needed and is_stp:
        is_stp   = False
        outcome  = "REFERRED"
        pathway  = "REFERRED"
        risk_class = "SUBSTANDARD"

    # ── Premium calculation ──────────────────────────────────────────
    approved_premium = None
    premium_detail   = None
    if outcome in ('APPROVED_STP', 'APPROVED_RATED'):
        try:
            from database import get_conn, release_conn
            from services.premium_engine import PremiumEngine
            prem_conn = get_conn()
            try:
                engine = PremiumEngine(prem_conn)
                prem = engine.calculate(
                    product_code = payload.get('product_code'),
                    applicant    = payload,
                    uw_result    = {'net_debit_points': net, 'risk_class': risk_class},
                    mode         = 'ANNUAL',
                    formula_type = 'BASE_PREMIUM',
                )
                if not prem.get('error') and prem.get('formula_found'):
                    approved_premium = prem.get('annual_premium')
                    premium_detail = {
                        'annual_premium':      prem.get('annual_premium'),
                        'monthly_premium':     prem.get('all_modes', {}).get('MONTHLY',     {}).get('modal_premium'),
                        'quarterly_premium':   prem.get('all_modes', {}).get('QUARTERLY',   {}).get('modal_premium'),
                        'half_yearly_premium': prem.get('all_modes', {}).get('HALF_YEARLY', {}).get('modal_premium'),
                        'total_first_year':    prem.get('all_modes', {}).get('ANNUAL',      {}).get('total_first_year'),
                        'total_renewal':       prem.get('all_modes', {}).get('ANNUAL',      {}).get('total_renewal'),
                        'gst_first_year':      prem.get('gst_first_year'),
                        'gst_renewal':         prem.get('gst_renewal'),
                        'all_modes':           prem.get('all_modes'),
                        'steps':               prem.get('steps_executed'),
                        'formula_name':        prem.get('formula_name'),
                    }
                else:
                    premium_detail = {'error': prem.get('error', 'Formula not found')}
            finally:
                release_conn(prem_conn)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f'Premium calc failed: {e}', exc_info=True)
            premium_detail = {'error': str(e)}

    now = datetime.now(timezone.utc).isoformat()

    return {
        "outcome":           outcome,
        "risk_class":        risk_class,
        "net_debit_points":  net,
        "total_debits":      debits,
        "total_credits":     credits,
        "rules_fired":       rules_fired,
        "is_stp":            is_stp,
        "pathway":           pathway,
        "adverse_action_text": adverse,
        "application_id":    applicant_ref,
        "evaluated_at":      now,
        "rules_version":     "engine-2.0",
        "approved_premium":  approved_premium,
        "premium_detail":    premium_detail,
    }


def _hard_decline(reason: str, applicant_ref: str, rules_fired: list) -> dict:
    rules_fired.append({
        "rule_id": "HARD_STOP", "rule_name": reason,
        "debit_points": 999, "category": "HARD_STOP",
        "hard_stop": True,
    })
    return {
        "outcome":           "DECLINED",
        "risk_class":        "DECLINE",
        "net_debit_points":  999,
        "total_debits":      999,
        "total_credits":     0,
        "rules_fired":       rules_fired,
        "is_stp":            False,
        "pathway":           "INSTANT_DECLINE",
        "adverse_action_text": reason,
        "application_id":    applicant_ref,
        "evaluated_at":      datetime.now(timezone.utc).isoformat(),
        "rules_version":     "engine-2.0",
        "approved_premium":  None,
        "premium_detail":    None,
    }


def _top_reasons(rules_fired: list, n: int = 3) -> str:
    top = sorted(
        [r for r in rules_fired if r.get("debit_points", 0) > 0],
        key=lambda r: r.get("debit_points", 0),
        reverse=True,
    )[:n]
    return "; ".join(r["rule_name"] for r in top) if top else "Underwriting criteria not met"
