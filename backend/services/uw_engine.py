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
    # The live catalog table is `products` (routers/products.py, single-benefit
    # evaluation in underwriting.py). A previous copy read the legacy `product`
    # table which no code writes to, so product eligibility checks silently
    # fell back to defaults. Fixed to read the live table with its column names.
    try:
        from database import get_conn, release_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT min_age, max_age, min_face_amount AS min_face, "
            "max_face_amount AS max_face, is_guaranteed_issue AS is_gi "
            "FROM products WHERE product_code=%s AND is_active=true LIMIT 1",
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


# ─────────────────────────────────────────────────────────────────────────────
# Data-driven underwriting standards (Phase 2)
#
# The R001–R080 catalogue is loaded from uw_medical_standard /
# _standard_rule / _standard_range (V034). Rules are evaluated against a flat
# context built from the payload (nested dicts flattened to dotted keys plus
# derived fields: bmi, chol_hdl_ratio, coverage_multiple, ...). Conditions are
# the typed condition tree the formula engine evaluates. When the DB has no
# rows (or is unavailable — the pure unit path), the built-in catalogue below
# mirrors the V034 system seed exactly.
# ─────────────────────────────────────────────────────────────────────────────

_BUILTIN_STANDARDS = [
    {
        "code": "R001", "family": "Age", "name": "Age loading", "category": "AGE",
        "rules": [{
            "rule_type": "RANGE", "param": "age", "name": "Age loading",
            "description": "Age {age}", "ranges": [
                {"min_value": 61, "max_value": None, "min_exclusive": False, "max_exclusive": False,
                 "name": "Age loading 61+", "description": "Age {age}", "debit_points": 40},
                {"min_value": 56, "max_value": 60, "min_exclusive": False, "max_exclusive": False,
                 "name": "Age loading 56–60", "description": "Age {age}", "debit_points": 25},
                {"min_value": 46, "max_value": 55, "min_exclusive": False, "max_exclusive": False,
                 "name": "Age loading 46–55", "description": "Age {age}", "debit_points": 15},
            ],
        }],
    },
    {
        "code": "R005", "family": "Tobacco", "name": "Tobacco use", "category": "TOBACCO",
        "rules": [
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "tobacco_status", "op": "IN", "value": ["SMOKER"]}], "logic": "AND"},
             "name": "Current smoker", "debit_points": 75},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "tobacco_status", "op": "IN", "value": ["CIGAR", "PIPE"]}], "logic": "AND"},
             "name": "Cigar/pipe user", "debit_points": 50},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "tobacco_status", "op": "IN", "value": ["CHEW", "VAPE"]}], "logic": "AND"},
             "name": "Smokeless/vape tobacco", "debit_points": 50},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "tobacco_status", "op": "EQ", "value": "NON_SMOKER"}, {"field": "tobacco_quit_years", "op": "LT", "value": 1}], "logic": "AND"},
             "name": "Recent tobacco cessation <1yr", "debit_points": 50},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "tobacco_status", "op": "EQ", "value": "NON_SMOKER"}, {"field": "tobacco_quit_years", "op": "GTE", "value": 1}, {"field": "tobacco_quit_years", "op": "LT", "value": 2}], "logic": "AND"},
             "name": "Tobacco cessation 1–2yr", "debit_points": 25},
        ],
    },
    {
        "code": "R010", "family": "Build", "name": "Body mass index", "category": "BUILD",
        "rules": [{
            "rule_type": "RANGE", "param": "bmi", "name": "Body mass index", "description": "BMI {bmi:.1f}",
            "ranges": [
                {"min_value": 40, "max_value": None, "min_exclusive": False, "max_exclusive": False,
                 "name": "Severe obesity BMI ≥40", "description": "BMI {bmi:.1f}", "debit_points": 100,
                 "requires_aps": True, "aps_reason": "Severe obesity — APS required"},
                {"min_value": 35, "max_value": 39.9, "min_exclusive": False, "max_exclusive": False,
                 "name": "Obesity BMI 35–39.9", "description": "BMI {bmi:.1f}", "debit_points": 75},
                {"min_value": 30, "max_value": 34.9, "min_exclusive": False, "max_exclusive": False,
                 "name": "Overweight BMI 30–34.9", "description": "BMI {bmi:.1f}", "debit_points": 25},
                {"min_value": None, "max_value": 16.99, "min_exclusive": False, "max_exclusive": False,
                 "name": "Underweight BMI <17", "description": "BMI {bmi:.1f}", "debit_points": 50,
                 "requires_aps": True, "aps_reason": "Underweight — APS required"},
            ],
        }],
    },
    {
        "code": "R015", "family": "Diabetes", "name": "Diabetes / A1c", "category": "DIABETES",
        "rules": [
            {"rule_type": "RANGE", "condition": {"clauses": [{"field": "diabetes_type", "op": "EQ", "value": "TYPE1"}], "logic": "AND"},
             "param": "a1c", "name": "Type 1 diabetes A1c={a1c}%",
             "requires_aps": True, "aps_reason": "Type 1 diabetes — APS and latest labs required",
             "ranges": [
                 {"min_value": None, "max_value": 7.5, "min_exclusive": False, "max_exclusive": False, "name": "T1 A1c ≤7.5", "debit_points": 75},
                 {"min_value": 7.5, "max_value": 9, "min_exclusive": False, "max_exclusive": False, "name": "T1 A1c 7.5–9", "debit_points": 100},
                 {"min_value": 9, "max_value": None, "min_exclusive": True, "max_exclusive": False, "name": "T1 A1c >9", "debit_points": 150},
             ]},
            {"rule_type": "RANGE", "condition": {"clauses": [{"field": "diabetes_type", "op": "EQ", "value": "TYPE2"}], "logic": "AND"},
             "param": "a1c", "name": "Type 2 diabetes A1c={a1c}%",
             "ranges": [
                 {"min_value": None, "max_value": 7.5, "min_exclusive": False, "max_exclusive": False, "name": "T2 A1c ≤7.5", "debit_points": 25},
                 {"min_value": 7.5, "max_value": 9, "min_exclusive": False, "max_exclusive": False, "name": "T2 A1c 7.5–9", "debit_points": 50},
                 {"min_value": 9, "max_value": None, "min_exclusive": True, "max_exclusive": False, "name": "T2 A1c >9", "debit_points": 75},
             ]},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "diabetes_type", "op": "EQ", "value": "TYPE2"}, {"field": "diabetes_duration_years", "op": "GT", "value": 10}], "logic": "AND"},
             "name": "Type 2 diabetes duration >10yr", "debit_points": 25},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "diabetes_type", "op": "EQ", "value": "PRE_DIABETIC"}], "logic": "AND"},
             "name": "Pre-diabetic", "debit_points": 15},
        ],
    },
    {
        "code": "R020", "family": "Cardiac", "name": "Cardiac history", "category": "CARDIAC",
        "rules": [
            {"rule_type": "RANGE", "condition": {"clauses": [{"field": "heart_condition", "op": "EQ", "value": "MI"}], "logic": "AND"},
             "param": "heart_event_years_ago", "name": "Myocardial infarction {heart_event_years_ago}yr ago",
             "requires_aps": True, "aps_reason": "Post-MI — full cardiac APS required",
             "ranges": [
                 {"min_value": None, "max_value": 2, "min_exclusive": False, "max_exclusive": False, "name": "Post-MI <2yr", "debit_points": 150},
                 {"min_value": 2, "max_value": 5, "min_exclusive": False, "max_exclusive": False, "name": "Post-MI 2–5yr", "debit_points": 100},
                 {"min_value": 5, "max_value": None, "min_exclusive": False, "max_exclusive": False, "name": "Post-MI >5yr", "debit_points": 50},
             ]},
            {"rule_type": "RANGE", "condition": {"clauses": [{"field": "heart_condition", "op": "IN", "value": ["CABG", "STENT"]}], "logic": "AND"},
             "param": "heart_event_years_ago", "name": "{heart_condition} {heart_event_years_ago}yr ago",
             "requires_aps": True, "aps_reason": "Post cardiac procedure — APS required",
             "ranges": [
                 {"min_value": None, "max_value": 2, "min_exclusive": False, "max_exclusive": False, "name": "Post-procedure <2yr", "debit_points": 125},
                 {"min_value": 2, "max_value": 5, "min_exclusive": False, "max_exclusive": False, "name": "Post-procedure 2–5yr", "debit_points": 75},
                 {"min_value": 5, "max_value": None, "min_exclusive": False, "max_exclusive": False, "name": "Post-procedure >5yr", "debit_points": 40},
             ]},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "heart_condition", "op": "EQ", "value": "ANGINA"}], "logic": "AND"},
             "name": "Angina", "debit_points": 75},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "heart_condition", "op": "EQ", "value": "ARRHYTHMIA"}], "logic": "AND"},
             "name": "Arrhythmia", "debit_points": 50},
        ],
    },
    {
        "code": "R030", "family": "Medical", "name": "Medical history", "category": "MEDICAL",
        "rules": [
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "depression_history", "op": "EQ", "value": True}, {"field": "depression_hospitalized", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "Depression history (hospitalised)", "debit_points": 75},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "depression_history", "op": "EQ", "value": True}, {"field": "depression_hospitalized", "op": "NOT_IN", "value": [True]}], "logic": "AND"},
             "name": "Depression history", "debit_points": 30},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "epilepsy", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "Epilepsy / seizure disorder", "debit_points": 50, "requires_aps": True, "aps_reason": "Epilepsy — neurology APS required"},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "copd", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "COPD", "debit_points": 50, "requires_aps": True, "aps_reason": "COPD — pulmonary APS required"},
        ],
    },
    {
        "code": "R040", "family": "Alcohol", "name": "Alcohol use", "category": "LIFESTYLE",
        "rules": [{
            "rule_type": "RANGE", "param": "alcohol_drinks_week", "name": "Alcohol use",
            "ranges": [
                {"min_value": 28, "max_value": None, "min_exclusive": False, "max_exclusive": False,
                 "name": "Heavy alcohol use ≥28 units/week", "description": "{alcohol_drinks_week} units/wk", "debit_points": 75},
                {"min_value": 21, "max_value": 27, "min_exclusive": False, "max_exclusive": False,
                 "name": "Moderate-heavy alcohol use 21–27 units/week", "debit_points": 40},
            ],
        }],
    },
    {
        "code": "R045", "family": "Hazardous", "name": "Hazardous activities", "category": "LIFESTYLE",
        "rules": [
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "hazardous_activity", "op": "EQ", "value": True}, {"field": "hazard_types", "op": "CONTAINS_ANY", "value": ["BASE_JUMPING", "MOTOR_RACING", "PRIVATE_PILOT"]}], "logic": "AND"},
             "name": "Hazardous activity flat extra (high)", "description": "Activities: {hazard_types}", "debit_points": 50},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "hazardous_activity", "op": "EQ", "value": True}, {"field": "hazard_types", "op": "NOT_CONTAINS_ANY", "value": ["BASE_JUMPING", "MOTOR_RACING", "PRIVATE_PILOT"]}], "logic": "AND"},
             "name": "Hazardous activity flat extra", "description": "Activities: {hazard_types}", "debit_points": 30},
        ],
    },
    {
        "code": "R050", "family": "Family History", "name": "Family history", "category": "FAMILY_HISTORY",
        "rules": [
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "family_history.cardiovascular_before_60", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "Family history CVD before age 60", "debit_points": 15},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "family_history.stroke_before_65", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "Family history stroke before age 65", "debit_points": 10},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "family_history.cancer_history", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "Family history cancer", "debit_points": 10},
        ],
    },
    {
        "code": "R055", "family": "Occupation", "name": "Occupation class", "category": "OCCUPATION",
        "rules": [
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "occupation_class", "op": "EQ", "value": "2"}], "logic": "AND"},
             "name": "Occupation class 2", "debit_points": 10},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "occupation_class", "op": "EQ", "value": "3"}], "logic": "AND"},
             "name": "Occupation class 3", "debit_points": 25},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "occupation_class", "op": "EQ", "value": "4"}], "logic": "AND"},
             "name": "Occupation class 4", "debit_points": 50},
        ],
    },
    {
        "code": "R060", "family": "Driving", "name": "Driving record", "category": "DRIVING",
        "rules": [
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "license_suspended", "op": "EQ", "value": True}], "logic": "AND"},
             "name": "Licence suspended", "debit_points": 100},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "dui_dwi_count_5yr", "op": "EQ", "value": 1}], "logic": "AND"},
             "name": "1 DUI/DWI in last 5 years", "debit_points": 50},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "major_violations_3yr", "op": "GTE", "value": 3}], "logic": "AND"},
             "name": "{major_violations_3yr} major driving violations in last 3 years", "debit_points": 50},
            {"rule_type": "FLAT", "condition": {"clauses": [{"field": "major_violations_3yr", "op": "EQ", "value": 2}], "logic": "AND"},
             "name": "2 major driving violations in last 3 years", "debit_points": 25},
        ],
    },
    {
        "code": "R070", "family": "Financial", "name": "Coverage-to-income", "category": "FINANCIAL",
        "rules": [{
            "rule_type": "RANGE", "param": "coverage_multiple", "name": "Financial underwriting — coverage exceeds 20× income",
            "description": "Total coverage {total_coverage:,.0f} vs max {max_coverage:,.0f}",
            "ranges": [
                {"min_value": 20, "max_value": None, "min_exclusive": True, "max_exclusive": False,
                 "name": "Financial underwriting — coverage exceeds 20× income", "debit_points": 30,
                 "requires_aps": True, "aps_reason": "Excess coverage — financial justification required"},
            ],
        }],
    },
    {
        "code": "R080", "family": "Labs", "name": "Lab values", "category": "LABS",
        "rules": [
            {"rule_type": "RANGE", "param": "total_cholesterol", "name": "Total cholesterol",
             "ranges": [{"min_value": 260, "max_value": None, "min_exclusive": False, "max_exclusive": False,
                         "name": "High total cholesterol {total_cholesterol} mg/dL", "debit_points": 25}]},
            {"rule_type": "RANGE", "param": "chol_hdl_ratio", "name": "Cholesterol ratio",
             "ranges": [{"min_value": 6, "max_value": None, "min_exclusive": True, "max_exclusive": False,
                         "name": "High cholesterol ratio {chol_hdl_ratio:.1f}", "debit_points": 25}]},
            {"rule_type": "RANGE", "param": "ldl", "name": "LDL cholesterol",
             "ranges": [{"min_value": 190, "max_value": None, "min_exclusive": False, "max_exclusive": False,
                         "name": "Very high LDL {ldl} mg/dL", "debit_points": 25}]},
        ],
    },
]


def _cond_ok(condition, context) -> bool:
    """Evaluate a typed condition tree against the flat context. Reuses the
    formula engine's evaluator (stateless) so ops stay in one place."""
    from services.sar_engine import FormulaEngine
    try:
        return bool(FormulaEngine()._eval_condition(condition, context))
    except Exception:
        return False


def _fmt_template(tpl, context) -> str:
    """Resolve {field} / {field:.1f} templates against the context. Lists are
    joined with ', '. Malformed templates return the raw string."""
    if not tpl or "{" not in tpl:
        return tpl or ""
    vals = {}
    for k, v in context.items():
        vals[k] = ", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else v
    try:
        return tpl.format(**vals)
    except Exception:
        return tpl


def _band_match(ranges, value) -> dict | None:
    """First matching band wins (V034 seed relies on this for the a1c >9 vs
    7.5–9 edge). min/max inclusive unless the *_exclusive flags are set."""
    for rng in ranges:
        lo, hi = rng.get("min_value"), rng.get("max_value")
        lo_ok = True
        if lo is not None:
            lo_ok = value > float(lo) if rng.get("min_exclusive") else value >= float(lo)
        hi_ok = True
        if hi is not None:
            hi_ok = value < float(hi) if rng.get("max_exclusive") else value <= float(hi)
        if lo_ok and hi_ok:
            return rng
    return None


def _load_standards(tenant_id, product_code) -> list[dict]:
    """Load effective standards for (tenant, product) — most-specific scope
    wins per standard_code; falls back to the built-in catalogue when the DB
    is unavailable or has no rows (pure unit path)."""
    try:
        from database import get_conn, release_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.standard_code, s.family, s.name, s.category,
                   (s.tenant_id IS NOT NULL) AS tenant_scoped,
                   (s.product_code IS NOT NULL) AS product_scoped,
                   r.id AS rule_id, r.rule_type, r.param, r.condition,
                   r.name AS rule_name, r.description AS rule_desc,
                   r.debit_points AS rule_debit, r.credit_points AS rule_credit,
                   r.rating_class AS rule_rating, r.requires_aps AS rule_aps,
                   r.aps_reason AS rule_aps_reason, r.seq AS rule_seq,
                   rg.min_value, rg.max_value, rg.min_exclusive, rg.max_exclusive,
                   rg.name AS band_name, rg.description AS band_desc,
                   rg.debit_points AS band_debit, rg.credit_points AS band_credit,
                   rg.requires_aps AS band_aps, rg.aps_reason AS band_aps_reason,
                   rg.seq AS band_seq
            FROM uw_medical_standard s
            JOIN uw_medical_standard_rule r ON r.standard_id = s.id
            LEFT JOIN uw_medical_standard_range rg ON rg.rule_id = r.id
            WHERE s.is_active = true
              AND s.effective_date <= CURRENT_DATE
              AND (s.expiry_date IS NULL OR s.expiry_date >= CURRENT_DATE)
              AND (s.tenant_id = %s::uuid OR s.tenant_id IS NULL)
              AND (s.product_code = %s OR s.product_code IS NULL)
            ORDER BY s.family, s.standard_code, r.seq, rg.seq
        """, (tenant_id, product_code))
        rows = cur.fetchall()
        cur.close()
        release_conn(conn)
        if rows:
            return _merge_standards(rows)
    except Exception as exc:
        logger.warning("Could not load medical standards from DB — using built-ins", exc_info=exc)
    return _BUILTIN_STANDARDS


def _merge_standards(rows) -> list[dict]:
    """Group DB rows into standards; per standard_code keep only the most
    specific scope (tenant+product > tenant > product > system)."""
    from collections import OrderedDict
    # key rows by standard_code, tracking per-code best scope
    per_code: dict[str, list] = OrderedDict()
    best_scope: dict[str, tuple[int, int]] = {}
    for r in rows:
        d = dict(r) if hasattr(r, "keys") else dict(zip(
            ["standard_code", "family", "name", "category", "tenant_scoped", "product_scoped",
             "rule_id", "rule_type", "param", "condition", "rule_name", "rule_desc",
             "rule_debit", "rule_credit", "rule_rating", "rule_aps", "rule_aps_reason",
             "rule_seq", "min_value", "max_value", "min_exclusive", "max_exclusive",
             "band_name", "band_desc", "band_debit", "band_credit", "band_aps",
             "band_aps_reason", "band_seq"], r))
        code = d["standard_code"]
        scope = (2 if d["tenant_scoped"] else 0) + (1 if d["product_scoped"] else 0)
        if code not in best_scope or scope > best_scope[code]:
            best_scope[code] = scope
        per_code.setdefault(code, []).append(d)
    standards = []
    for code, entries in per_code.items():
        top = best_scope[code]
        chosen = [e for e in entries
                  if (2 if e["tenant_scoped"] else 0) + (1 if e["product_scoped"] else 0) == top]
        standards.append(_assemble_standard(chosen[0], chosen))
    standards.sort(key=lambda s: s["code"])
    return standards


def _assemble_standard(first, rows) -> dict:
    from collections import OrderedDict
    std = {"code": first["standard_code"], "family": first["family"],
           "name": first["name"], "category": first["category"], "rules": []}
    rules: OrderedDict = OrderedDict()
    for d in rows:
        rid = d["rule_id"]
        if rid not in rules:
            rules[rid] = {
                "rule_type": d["rule_type"], "param": d["param"],
                "condition": d["condition"], "name": d["rule_name"],
                "description": d["rule_desc"], "debit_points": d["rule_debit"],
                "credit_points": d["rule_credit"], "rating_class": d["rule_rating"],
                "requires_aps": d["rule_aps"], "aps_reason": d["rule_aps_reason"],
                "seq": d["rule_seq"], "ranges": [],
            }
        if d["band_seq"] is not None:
            rules[rid]["ranges"].append({
                "min_value": d["min_value"], "max_value": d["max_value"],
                "min_exclusive": d["min_exclusive"], "max_exclusive": d["max_exclusive"],
                "name": d["band_name"], "description": d["band_desc"],
                "debit_points": d["band_debit"], "credit_points": d["band_credit"],
                "requires_aps": d["band_aps"], "aps_reason": d["band_aps_reason"],
                "seq": d["band_seq"],
            })
    std["rules"] = sorted(rules.values(), key=lambda r: r["seq"])
    for rule in std["rules"]:
        rule["ranges"].sort(key=lambda b: b["seq"])
    return std


def _build_context(payload: dict) -> dict:
    """Flatten the applicant payload into the flat context the standard
    conditions/ranges evaluate against, plus derived fields."""
    ctx: dict[str, Any] = {}
    for k in ("age", "gender", "face_amount", "occupation_class", "tobacco_status",
              "depression_history", "depression_hospitalized", "epilepsy", "copd",
              "hazardous_activity", "hazard_types", "a1c", "diabetes_type",
              "heart_condition", "heart_event_years_ago"):
        if payload.get(k) is not None:
            ctx[k] = payload[k]

    build = payload.get("build") or {}
    h = float(build.get("height_inches") or payload.get("height_inches") or 0)
    w = float(build.get("weight_lbs") or payload.get("weight_lbs") or 0)
    if h > 0 and w > 0:
        ctx["bmi"] = (w / (h ** 2)) * 703

    driving = payload.get("driving_record") or {}
    for k in ("dui_dwi_count_5yr", "major_violations_3yr", "minor_violations_3yr",
              "license_suspended"):
        if driving.get(k) is not None:
            ctx[k] = driving[k]

    fh = payload.get("family_history") or {}
    for k, v in fh.items():
        if v is not None:
            ctx[f"family_history.{k}"] = v

    labs = payload.get("lab_values") or {}
    for k in ("total_cholesterol", "hdl", "ldl"):
        if labs.get(k) is not None:
            ctx[k] = labs[k]

    age = int(payload.get("age", 0))
    # Defaults mirroring the legacy engine
    ctx.setdefault("tobacco_quit_years", 0)
    ctx.setdefault("a1c", 7.0)
    if ctx.get("diabetes_type") == "TYPE2":
        dx_age = int(payload.get("diabetes_dx_age") or age)
        ctx["diabetes_duration_years"] = max(0, age - dx_age)

    fin = payload.get("financial") or {}
    income = float(fin.get("annual_income") or payload.get("annual_income") or 0)
    existing = float(fin.get("existing_life_coverage") or payload.get("existing_coverage") or 0)
    face = float(payload.get("face_amount") or 0)
    if income > 0:
        total_coverage = face + existing
        ctx["coverage_multiple"] = total_coverage / income
        ctx["total_coverage"] = total_coverage
        ctx["max_coverage"] = income * 20

    chol = float(labs.get("total_cholesterol") or 0)
    hdl_v = float(labs.get("hdl") or 0)
    if hdl_v > 0 and chol > 0:
        ctx["chol_hdl_ratio"] = chol / hdl_v
    return ctx


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

    # Recent MI is a postpone — hard stop below 12 months (also reflected in
    # the R020 data, but the postpone must not accumulate other debits).
    if payload.get("heart_condition") == "MI" and float(payload.get("heart_event_years_ago") or 0) < 1:
        return _hard_decline("MI within last 12 months — postpone minimum 12 months",
                             applicant_ref, rules_fired)

    # ── Product eligibility ───────────────────────────────────────────────────

    min_age = product.get("min_age") or 18
    max_age = product.get("max_age") or 70
    if age < min_age or age > max_age:
        return _hard_decline(
            f"Age {age} outside product eligibility range {min_age}–{max_age}",
            applicant_ref, rules_fired,
        )

    # ── Data-driven standards (R001–R080 from uw_medical_standard / V034) ────
    # The catalogue is loaded per (tenant, product) with system fallback; the
    # built-in defaults mirror the seed so pure-unit runs behave identically.

    standards = _load_standards(tenant_id, product_code)
    ctx = _build_context(payload)

    for std in standards:
        for rule in std.get("rules") or []:
            if rule.get("condition") and not _cond_ok(rule["condition"], ctx):
                continue
            if rule["rule_type"] == "RANGE":
                val = ctx.get(rule.get("param"))
                if val is None:
                    continue
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    continue
                band = _band_match(rule.get("ranges") or [], num)
                if band is None:
                    continue
                name = _fmt_template(band.get("name") or rule.get("name") or std["name"], ctx)
                desc = _fmt_template(band.get("description") or rule.get("description") or "", ctx)
                pts = int(band.get("debit_points") or 0) - int(band.get("credit_points") or 0)
                fire(std["code"], name, pts, std["category"], desc,
                     requires_aps=bool(band.get("requires_aps")),
                     aps_reason=band.get("aps_reason"))
            else:
                name = _fmt_template(rule.get("name") or std["name"], ctx)
                desc = _fmt_template(rule.get("description") or "", ctx)
                pts = int(rule.get("debit_points") or 0) - int(rule.get("credit_points") or 0)
                fire(std["code"], name, pts, std["category"], desc,
                     requires_aps=bool(rule.get("requires_aps")),
                     aps_reason=rule.get("aps_reason"))

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
