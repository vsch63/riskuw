"""
backend/ai_engine/ai_scoring_panel.py
───────────────────────────────────────
AI-assisted scoring panel.
Called by:  render_ai_scoring_panel(uw_result, applicant_dict)

This module provides:
  1. Risk narrative generation  — plain-English summary of the decision
  2. Anomaly flags              — unusual combinations that a human should check
  3. Similar case lookup        — find historical cases with similar risk profiles
     (requires policy_admin_queue to have enough data)

The actual LLM call is optional — the panel degrades gracefully to
rule-based text if no model is configured.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("uw_platform")

# ── Config ────────────────────────────────────────────────────────────────────
_OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "")
_USE_LLM         = bool(_OPENAI_API_KEY)
_LLM_MODEL       = os.environ.get("AI_MODEL", "gpt-4o-mini")


# ── Public entry point ────────────────────────────────────────────────────────

def render_ai_scoring_panel(uw_result: dict, applicant: dict) -> dict:
    """
    Returns a dict with:
      narrative    — str  plain-English decision summary
      anomaly_flags— list[str]  unusual risk combinations
      similar_cases— list[dict] top 3 historical similar cases
      confidence   — str  HIGH / MEDIUM / LOW
    """
    narrative     = _build_narrative(uw_result, applicant)
    anomaly_flags = _detect_anomalies(uw_result, applicant)
    similar       = _find_similar_cases(uw_result, applicant)
    confidence    = _confidence_level(uw_result)

    return {
        "narrative":     narrative,
        "anomaly_flags": anomaly_flags,
        "similar_cases": similar,
        "confidence":    confidence,
        "ai_powered":    False,   # flip to True when LLM is wired in
    }


# ── Narrative ─────────────────────────────────────────────────────────────────

def _build_narrative(result: dict, applicant: dict) -> str:
    outcome    = result.get("outcome", "UNKNOWN")
    debits     = result.get("net_debit_points", 0)
    risk_class = result.get("risk_class", "—")
    rules      = result.get("rules_fired") or []
    age        = applicant.get("age", "")
    gender     = applicant.get("gender", "")
    product    = applicant.get("product_code", "")
    is_stp     = result.get("is_stp", False)

    top_rules  = sorted(rules, key=lambda r: r.get("debit_points", 0), reverse=True)[:3]
    top_names  = [r.get("rule_name", "") for r in top_rules if r.get("debit_points", 0) > 0]

    if "APPROVED" in outcome and is_stp:
        narrative = (
            f"This {age}-year-old {gender.lower()} applicant for {product} qualifies for "
            f"straight-through processing. Net debit score of {debits} is within the STP "
            f"threshold, resulting in a {risk_class} risk classification."
        )
    elif "APPROVED" in outcome:
        narrative = (
            f"Application approved at {risk_class} rating. Net debit score {debits} "
            f"is above the STP threshold but below the referral limit, indicating "
            f"a substandard risk that is still insurable."
        )
        if top_names:
            narrative += f" Primary contributing factors: {'; '.join(top_names)}."
    elif outcome == "REFERRED":
        narrative = (
            f"Case referred for manual underwriter review. Net debit score {debits} "
            f"exceeds the refer threshold. "
        )
        if top_names:
            narrative += f"Key risk drivers: {'; '.join(top_names)}."
    elif "DECLINED" in outcome:
        adverse = result.get("adverse_action_text") or (top_names[0] if top_names else "criteria not met")
        narrative = (
            f"Application declined. {adverse}. "
            f"Net debit score {debits} exceeds the decline threshold."
        )
    else:
        narrative = f"Decision: {outcome}. Net debit score: {debits}."

    return narrative


# ── Anomaly detection ─────────────────────────────────────────────────────────

def _detect_anomalies(result: dict, applicant: dict) -> list[str]:
    flags = []
    age      = int(applicant.get("age") or 0)
    face     = float(applicant.get("face_amount") or 0)
    income   = float((applicant.get("financial") or {}).get("annual_income") or 0)
    tobacco  = applicant.get("tobacco_status", "NEVER")
    diabetes = applicant.get("diabetes_type", "NONE")
    heart    = applicant.get("heart_condition", "NONE")
    debits   = int(result.get("net_debit_points") or 0)

    # High face amount relative to age
    if age > 60 and face > 10_000_000:
        flags.append(f"High face amount ₹{face:,.0f} for age {age} — verify insurable interest")

    # Multiple serious conditions
    serious = sum([
        tobacco in ("SMOKER", "CIGAR", "CHEW", "VAPE"),
        diabetes in ("TYPE1", "TYPE2"),
        heart not in ("NONE", "HYPERTENSION"),
    ])
    if serious >= 2:
        flags.append("Multiple co-morbidities present — consider requesting comprehensive APS")

    # Income multiple check
    if income > 0 and face > income * 25:
        flags.append(f"Coverage exceeds 25× income — financial justification may be required")

    # Young + high debits
    if age < 35 and debits > 100:
        flags.append(f"Unusual: high debit score {debits} for applicant aged {age}")

    # Approved despite borderline score
    stp_threshold = 75
    if "APPROVED_STP" in result.get("outcome", "") and debits > stp_threshold - 10:
        flags.append(f"Debit score {debits} is close to STP threshold — marginal approval")

    return flags


# ── Similar case lookup ───────────────────────────────────────────────────────

def _find_similar_cases(result: dict, applicant: dict, limit: int = 3) -> list[dict]:
    """Query policy_admin_queue for cases with similar age / outcome / product."""
    try:
        from database import get_conn, release_conn
        conn = get_conn()
        cur = conn.cursor()
        age     = int(applicant.get("age") or 0)
        product = applicant.get("product_code", "")
        outcome = result.get("outcome", "")

        cur.execute(
            """
            SELECT applicant_ref, product_code, age, gender,
                   outcome, risk_class, net_debit_points
            FROM policy_admin_queue
            WHERE product_code = %s
              AND ABS(age - %s) <= 5
              AND outcome LIKE %s
            ORDER BY decision_date DESC
            LIMIT %s
            """,
            (product, age, outcome.split("_")[0] + "%", limit),
        )
        rows = cur.fetchall()
        cur.close()
        release_conn(conn)
        return [
            dict(r) if hasattr(r, "keys") else
            dict(zip(["applicant_ref","product_code","age","gender",
                      "outcome","risk_class","net_debit_points"], r))
            for r in rows
        ]
    except Exception as exc:
        logger.debug("similar case lookup failed", exc_info=exc)
        return []


# ── Confidence level ──────────────────────────────────────────────────────────

def _confidence_level(result: dict) -> str:
    """Simple heuristic: STP with low debits = HIGH, manual = MEDIUM/LOW."""
    if result.get("is_stp") and result.get("net_debit_points", 0) < 50:
        return "HIGH"
    elif result.get("pathway") == "STRAIGHT_THROUGH":
        return "HIGH"
    elif result.get("outcome", "").startswith("APPROVED"):
        return "MEDIUM"
    else:
        return "LOW"
