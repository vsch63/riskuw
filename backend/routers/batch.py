# ── PATCH for batch.py ───────────────────────────────────────────────────────
# Replace the existing download_template endpoint with this version
# It accepts an optional product_code query param and adds USER_LABEL columns

from fastapi import APIRouter
from deps import CurrentUser

router = APIRouter()        # define first
@router.get("/template")
def download_template(
    current: CurrentUser,
    product_code: str = "IND-TERM-20",
):
    """
    Returns a CSV template with required columns + any USER_LABEL columns
    defined in the product's active BASE_PREMIUM formula.
    Pass ?product_code=IND-TERM-20 to get product-specific template.
    """
    # Standard columns always present
    standard_headers = [
        "applicant_ref", "product_code", "age", "gender", "state",
        "face_amount", "coverage_term_yrs", "tobacco_status",
        "height_inches", "weight_lbs", "systolic_bp", "diastolic_bp",
        "diabetes_type", "heart_condition", "annual_income", "existing_coverage",
    ]

    # Sample row values
    sample_row = {
        "applicant_ref":    "APP-001",
        "product_code":     product_code,
        "age":              "35",
        "gender":           "MALE",
        "state":            "MH",
        "face_amount":      "1000000",
        "coverage_term_yrs":"20",
        "tobacco_status":   "NEVER",
        "height_inches":    "68",
        "weight_lbs":       "170",
        "systolic_bp":      "120",
        "diastolic_bp":     "78",
        "diabetes_type":    "NONE",
        "heart_condition":  "NONE",
        "annual_income":    "800000",
        "existing_coverage":"0",
    }

    # Get USER_LABEL columns from product formula
    user_label_cols = []
    conn, release = _get_db()
    try:
        import psycopg2.extras
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.user_label, s.user_value AS default_value, s.description
            FROM premium_formula_step s
            JOIN premium_formula f ON f.id = s.formula_id
            WHERE f.product_code = %s
              AND f.formula_type = 'BASE_PREMIUM'
              AND f.is_active = true
              AND f.effective_date <= CURRENT_DATE
              AND (f.expiry_date IS NULL OR f.expiry_date >= CURRENT_DATE)
              AND s.parameter_type = 'USER_LABEL'
              AND s.user_label IS NOT NULL
            ORDER BY s.seq_no
            """,
            (product_code,),
        )
        user_label_cols = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception:
        pass  # If formula not found, just use standard columns
    finally:
        release(conn)

    # Build headers
    extra_headers = [col["user_label"] for col in user_label_cols]
    all_headers   = standard_headers + extra_headers

    # Build sample row
    for col in user_label_cols:
        sample_row[col["user_label"]] = str(col["default_value"] or "")

    # Build CSV content
    import io
    buf = io.StringIO()
    buf.write(",".join(all_headers) + "\n")
    buf.write(",".join(sample_row.get(h, "") for h in all_headers) + "\n")

    # Add comment row explaining USER_LABEL columns
    if user_label_cols:
        buf.write(
            "# USER_LABEL columns: " +
            ", ".join(f"{c['user_label']} ({c['description'] or 'formula input'})"
                      for c in user_label_cols) + "\n"
        )

    buf.seek(0)
    filename = f"riskuw_batch_template_{product_code}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

