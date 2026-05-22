"""
services/premium_engine.py
───────────────────────────
Configurable premium calculation engine.

Executes a product's premium formula steps sequentially:
    result = 0
    for step in formula_steps ordered by seq_no:
        operand = resolve_parameter(step, applicant, uw_result)
        operand = operand * step.factor
        result  = apply_operator(result, step.operator, operand)

    annual_premium = result
    apply modal factor → monthly/quarterly/half-yearly
    apply GST → first_year and renewal amounts

Usage:
    from services.premium_engine import PremiumEngine
    engine = PremiumEngine(conn)
    result = engine.calculate(
        product_code = "IND-TERM-20",
        applicant    = { "age": 35, "gender": "M", "face_amount": 5000000, ... },
        uw_result    = { "net_debit_points": 50, "risk_class": "STANDARD" },
        mode         = "ANNUAL",   # ANNUAL | HALF_YEARLY | QUARTERLY | MONTHLY
    )
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

OPERATORS = {
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '/': lambda a, b: a / b if b != 0 else a,
    '%': lambda a, b: a * (b / 100),
}


class PremiumEngine:
    def __init__(self, conn):
        self.conn = conn

    def calculate(
        self,
        product_code: str,
        applicant: dict,
        uw_result: dict,
        mode: str = "ANNUAL",
        formula_type: str = "BASE_PREMIUM",
    ) -> dict:
        """
        Calculate premium for an approved applicant.
        Returns full breakdown including GST and modal amounts.
        """
        result = {
            "product_code":      product_code,
            "mode":              mode,
            "formula_type":      formula_type,
            "steps_executed":    [],
            "base_result":       0.0,
            "annual_premium":    0.0,
            "modal_premium":     0.0,
            "modal_factor":      1.0,
            "gst_first_year":    0.0,
            "gst_renewal":       0.0,
            "total_first_year":  0.0,
            "total_renewal":     0.0,
            "formula_found":     False,
            "error":             None,
        }

        try:
            # ── Get active formula ────────────────────────────────────────────
            formula = self._get_formula(product_code, formula_type)
            if not formula:
                result["error"] = f"No active {formula_type} formula for {product_code}"
                return result

            result["formula_found"] = True
            result["formula_name"]  = formula["formula_name"]

            # ── Execute steps ─────────────────────────────────────────────────
            steps       = self._get_steps(str(formula["id"]))
            accumulated = 0.0

            for step in steps:
                try:
                    operand = self._resolve_parameter(step, applicant, uw_result, accumulated)
                    operand = operand * float(step["factor"])
                    prev    = accumulated
                    accumulated = OPERATORS[step["operator"]](accumulated, operand)

                    result["steps_executed"].append({
                        "seq_no":      step["seq_no"],
                        "description": step["description"] or f"Step {step['seq_no']}",
                        "operator":    step["operator"],
                        "factor":      float(step["factor"]),
                        "parameter":   step["parameter_type"],
                        "operand":     round(operand, 4),
                        "result":      round(accumulated, 4),
                    })
                except Exception as e:
                    logger.warning(f"Step {step['seq_no']} failed: {e}")
                    result["steps_executed"].append({
                        "seq_no":      step["seq_no"],
                        "description": step["description"] or f"Step {step['seq_no']}",
                        "error":       str(e),
                    })

            result["base_result"]    = round(accumulated, 2)
            result["annual_premium"] = round(accumulated, 2)

            # ── Apply modal factor ────────────────────────────────────────────
            modal_factor = self._get_modal_factor(product_code, mode)
            result["modal_factor"]  = modal_factor
            result["modal_premium"] = round(accumulated * modal_factor, 2)

            # ── Apply GST ─────────────────────────────────────────────────────
            gst = self._get_gst_config(product_code)
            fy_gst_rate  = float(gst["first_year_rate"]) / 100 if gst else 0.18
            ren_gst_rate = float(gst["renewal_rate"])    / 100 if gst else 0.05

            result["gst_first_year"]   = round(result["modal_premium"] * fy_gst_rate, 2)
            result["gst_renewal"]      = round(result["modal_premium"] * ren_gst_rate, 2)
            result["total_first_year"] = round(result["modal_premium"] + result["gst_first_year"], 2)
            result["total_renewal"]    = round(result["modal_premium"] + result["gst_renewal"], 2)

            # Convenience: all modal amounts
            result["all_modes"] = self._calc_all_modes(accumulated, product_code, gst)

        except Exception as e:
            logger.error(f"PremiumEngine error: {e}", exc_info=True)
            result["error"] = str(e)

        return result

    # ── Parameter resolver ────────────────────────────────────────────────────

    def _resolve_parameter(
        self,
        step: dict,
        applicant: dict,
        uw_result: dict,
        previous_result: float,
    ) -> float:
        ptype = step["parameter_type"]

        if ptype == "USER_VALUE":
            return float(step["user_value"] or 0)

        if ptype == "USER_LABEL":
            label = step.get("user_label")
            if not label:
                raise ValueError("USER_LABEL step has no user_label defined")
            # Look up from proposal inputs (flat field on applicant dict)
            val = applicant.get(label)
            if val is None:
                # Fall back to user_value as default
                val = step.get("user_value")
            if val is None:
                raise ValueError(f"USER_LABEL '{label}' not found in proposal inputs and no default set")
            return float(val)

        if ptype in ("SUM_ASSURED", "FACE_AMOUNT"):
            return float(applicant.get("face_amount") or applicant.get("sum_assured") or 0)

        if ptype == "DEBIT_POINTS":
            return float(uw_result.get("net_debit_points") or 0)

        if ptype == "POLICY_TERM":
            return float(applicant.get("coverage_term_yrs") or applicant.get("policy_term") or 0)

        if ptype == "ANNUAL_INCOME":
            return float(applicant.get("annual_income") or 0)

        if ptype == "AGE":
            return float(applicant.get("age") or 0)

        if ptype == "PREVIOUS_RESULT":
            return previous_result

        if ptype == "RATE_SCALE":
            scale_id = step.get("scale_id")
            if not scale_id:
                raise ValueError("RATE_SCALE step has no scale_id")
            return self._lookup_scale_value(str(scale_id), applicant)

        raise ValueError(f"Unknown parameter_type: {ptype}")

    # ── Scale lookup ──────────────────────────────────────────────────────────

    def _lookup_scale_value(self, scale_id: str, applicant: dict) -> float:
        """
        Look up the output value from a UW/Premium scale for this applicant.
        Matches tranches by parameters, then age-band for the value.
        """
        today = date.today()
        cur   = self.conn.cursor()

        try:
            # Get valid tranches
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
                tid   = str(t[0] if isinstance(t, tuple) else t["id"])
                logic = str(t[2] if isinstance(t, tuple) else t["parameter_logic"])

                cur.execute(
                    "SELECT parameter_name, min_value, max_value FROM uw_tranche_parameter WHERE tranche_id=%s::uuid",
                    (tid,),
                )
                params  = cur.fetchall()
                results = []

                for p in params:
                    pname   = p[0] if isinstance(p, tuple) else p["parameter_name"]
                    min_v   = float(p[1]) if (p[1] if isinstance(p, tuple) else p.get("min_value")) is not None else None
                    max_v   = float(p[2]) if (p[2] if isinstance(p, tuple) else p.get("max_value")) is not None else None
                    app_val = self._map_applicant_value(pname, applicant)

                    if app_val is None:
                        results.append(False)
                        continue

                    ok = True
                    if min_v is not None and float(app_val) < min_v: ok = False
                    if max_v is not None and float(app_val) > max_v: ok = False
                    results.append(ok)

                if not results:
                    continue
                if (all(results) if logic == "AND" else any(results)):
                    matched.append(tid)

            if len(matched) != 1:
                raise ValueError(
                    f"Scale {scale_id}: expected 1 matching tranche, got {len(matched)}"
                )

            tid = matched[0]
            age = applicant.get("age")
            if age is None:
                raise ValueError("age required for scale lookup")

            cur.execute(
                """
                SELECT value FROM uw_tranche_detail
                WHERE tranche_id = %s::uuid AND age_from <= %s AND age_to >= %s
                ORDER BY sort_order LIMIT 1
                """,
                (tid, int(age), int(age)),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"No age-band detail found for age {age} in tranche {tid}")

            return float(row[0] if isinstance(row, tuple) else row["value"])

        finally:
            cur.close()

    def _map_applicant_value(self, pname: str, applicant: dict):
        """Map parameter names to applicant field values."""
        direct = applicant.get(pname)
        if direct is not None:
            return direct

        aliases = {
            "gender":           lambda a: 1 if str(a.get("gender","")).upper() in ("M","MALE") else 2,
            "smoker":           lambda a: 1 if a.get("tobacco_status","NEVER") not in ("NEVER","NON_TOBACCO") else 0,
            "bmi":              lambda a: self._calc_bmi(a),
            "bp_systolic":      lambda a: a.get("systolic_bp"),
            "bp_diastolic":     lambda a: a.get("diastolic_bp"),
            "occupation_class": lambda a: int(a.get("occupation_class", 1)) if str(a.get("occupation_class","1")).isdigit() else 1,
            "policy_term":      lambda a: a.get("coverage_term_yrs"),
            "sum_assured":      lambda a: a.get("face_amount"),
            "family_history":   lambda a: 1 if (a.get("family_history") or {}).get("cardiovascular_before_60") else 0,
        }
        if pname in aliases:
            try:
                return aliases[pname](applicant)
            except Exception:
                return None
        return None

    def _calc_bmi(self, applicant: dict):
        h = applicant.get("height_inches")
        w = applicant.get("weight_lbs")
        if h and w and float(h) > 0:
            return round((float(w) / (float(h) ** 2)) * 703, 1)
        return None

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _get_formula(self, product_code: str, formula_type: str) -> Optional[dict]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, formula_name, description
                FROM premium_formula
                WHERE product_code = %s
                  AND formula_type = %s
                  AND is_active = true
                  AND effective_date <= CURRENT_DATE
                  AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
                ORDER BY effective_date DESC LIMIT 1
                """,
                (product_code, formula_type),
            )
            row = cur.fetchone()
            if not row:
                return None
            if isinstance(row, tuple):
                return {"id": row[0], "formula_name": row[1], "description": row[2]}
            return dict(row)
        finally:
            cur.close()

    def _get_steps(self, formula_id: str) -> list[dict]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                SELECT seq_no, description, operator, factor,
                       parameter_type, user_value, user_label, scale_id::text
                FROM premium_formula_step
                WHERE formula_id = %s::uuid
                ORDER BY seq_no
                """,
                (formula_id,),
            )
            rows = cur.fetchall()
            keys = ["seq_no","description","operator","factor",
                    "parameter_type","user_value","user_label","scale_id"]
            return [dict(zip(keys, r)) if isinstance(r, tuple) else dict(r) for r in rows]
        finally:
            cur.close()

    def _get_modal_factor(self, product_code: str, mode: str) -> float:
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT factor FROM premium_modal_factor WHERE product_code=%s AND mode=%s",
                (product_code, mode),
            )
            row = cur.fetchone()
            if row:
                return float(row[0] if isinstance(row, tuple) else row["factor"])
            # Default factors
            defaults = {"ANNUAL": 1.0, "HALF_YEARLY": 0.51, "QUARTERLY": 0.26, "MONTHLY": 0.09}
            return defaults.get(mode, 1.0)
        finally:
            cur.close()

    def _get_gst_config(self, product_code: str) -> Optional[dict]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT first_year_rate, renewal_rate FROM premium_gst_config WHERE product_code=%s AND is_active=true",
                (product_code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if isinstance(row, tuple):
                return {"first_year_rate": row[0], "renewal_rate": row[1]}
            return dict(row)
        finally:
            cur.close()

    def _calc_all_modes(self, annual_base: float, product_code: str, gst: Optional[dict]) -> dict:
        modes = {}
        fy_rate  = float(gst["first_year_rate"]) / 100 if gst else 0.18
        ren_rate = float(gst["renewal_rate"])    / 100 if gst else 0.05

        for mode in ("ANNUAL", "HALF_YEARLY", "QUARTERLY", "MONTHLY"):
            mf      = self._get_modal_factor(product_code, mode)
            modal   = round(annual_base * mf, 2)
            fy_gst  = round(modal * fy_rate, 2)
            ren_gst = round(modal * ren_rate, 2)
            modes[mode] = {
                "modal_premium":  modal,
                "total_first_year": round(modal + fy_gst, 2),
                "total_renewal":    round(modal + ren_gst, 2),
            }
        return modes
