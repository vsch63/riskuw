"""
backend/services/premium_calculator.py
────────────────────────────────────────
Calculates approved premium from:
  1. premium_rate_table  (rate per ₹1,000 face amount)
  2. table_rating        (percentage loading on base rate)
  3. flat_extra          (₹ per ₹1,000 face amount per year)

Called by:  routers/queue.py GET /queue/premium/calculate
            services/uw_engine.py (when computing approved_premium)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("uw_platform")


def calculate_premium(
    product_code: str,
    age: int,
    gender: str,
    tobacco_status: str,
    face_amount: float,
    term_years: int,
    risk_class: str,
    table_rating: int = 0,
    flat_extra_per_thou: float = 0.0,
    tenant_id: Optional[str] = None,
) -> dict:
    """
    Returns:
        {
            "base_rate":        float,   # per ₹1,000 face amount per year
            "table_rate":       float,   # loading from table rating
            "flat_extra":       float,   # flat extra loading
            "total_rate":       float,   # combined rate per ₹1,000
            "annual_premium":   float,   # ₹ per year
            "monthly_premium":  float,   # ₹ per month
            "source":           str,     # "rate_table" or "estimated"
        }
    """
    base_rate = _lookup_rate(
        product_code, age, gender, tobacco_status, term_years, risk_class, tenant_id
    )
    source = "rate_table" if base_rate else "estimated"

    # If no rate table entry, estimate from mortality tables
    if not base_rate:
        base_rate = _mortality_estimate(age, gender, tobacco_status, risk_class)

    # Table rating loading (table 1 = 25%, table 2 = 50%, ... table 8 = 200%)
    table_pct  = table_rating * 25 / 100          # table 4 → +100%
    table_rate = base_rate * table_pct

    total_rate       = base_rate + table_rate + flat_extra_per_thou
    face_in_thousands = face_amount / 1_000
    annual_premium   = round(total_rate * face_in_thousands, 2)
    monthly_premium  = round(annual_premium / 12, 2)

    return {
        "base_rate":       round(base_rate, 4),
        "table_rate":      round(table_rate, 4),
        "flat_extra":      round(flat_extra_per_thou, 4),
        "total_rate":      round(total_rate, 4),
        "annual_premium":  annual_premium,
        "monthly_premium": monthly_premium,
        "source":          source,
    }


def _lookup_rate(
    product_code: str,
    age: int,
    gender: str,
    tobacco_status: str,
    term_years: int,
    risk_class: str,
    tenant_id: Optional[str],
) -> Optional[float]:
    """Query premium_rate_table for an exact or interpolated rate."""
    try:
        from database import get_conn, release_conn
        conn = get_conn()
        cur  = conn.cursor()

        tob_status = "TOBACCO" if tobacco_status in ("SMOKER","CIGAR","CHEW","VAPE") else "NON_TOBACCO"

        cur.execute(
            """
            SELECT rate_per_thou
            FROM premium_rate_table
            WHERE product_code   = %s
              AND gender          = %s
              AND tobacco_status  = %s
              AND age_min        <= %s
              AND age_max        >= %s
              AND (term_years = %s OR term_years IS NULL)
              AND (tenant_id  = %s::uuid OR tenant_id IS NULL)
              AND (expiry_date IS NULL OR expiry_date > now())
              AND risk_class = %s
            ORDER BY effective_date DESC
            LIMIT 1
            """,
            (product_code, gender, tob_status, age, age,
             term_years, tenant_id or "00000000-0000-0000-0000-000000000001",
             risk_class),
        )
        row = cur.fetchone()
        cur.close()
        release_conn(conn)
        if row:
            return float(row[0] if isinstance(row, tuple) else row.get("rate_per_thou", 0))
    except Exception as exc:
        logger.debug("premium rate lookup failed", exc_info=exc)
    return None


def _mortality_estimate(
    age: int,
    gender: str,
    tobacco_status: str,
    risk_class: str,
) -> float:
    """
    Rough Indian LIC-style mortality estimate when no rate table entry exists.
    Returns rate per ₹1,000 face amount per year.
    These are illustrative — replace with actual carrier rates.
    """
    # Base rate from age band
    if age < 25:    base = 0.80
    elif age < 30:  base = 0.90
    elif age < 35:  base = 1.10
    elif age < 40:  base = 1.40
    elif age < 45:  base = 2.00
    elif age < 50:  base = 2.80
    elif age < 55:  base = 4.00
    elif age < 60:  base = 5.50
    elif age < 65:  base = 7.50
    else:           base = 10.00

    # Gender adjustment
    if gender == "FEMALE":
        base *= 0.82

    # Tobacco loading
    if tobacco_status in ("SMOKER", "CIGAR", "CHEW", "VAPE"):
        base *= 2.5

    # Risk class loading
    multipliers = {
        "PREFERRED":    0.80,
        "STANDARD":     1.00,
        "SUBSTANDARD":  1.50,
        "TABLE_2":      1.50,
        "TABLE_4":      2.00,
        "TABLE_6":      2.50,
        "TABLE_8":      3.00,
    }
    base *= multipliers.get(risk_class.upper(), 1.00)

    return round(base, 4)
