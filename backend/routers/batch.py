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


# ── Batch Jobs CRUD ───────────────────────────────────────────────────────────
import io, uuid, csv
from fastapi import UploadFile, File, Form, BackgroundTasks
from fastapi.responses import StreamingResponse
import psycopg2.extras

def _jobs_db():
    from database import get_conn, release_conn
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn

def _fmt_job(row: dict) -> dict:
    for f in ("submitted_at","started_at","completed_at"):
        if row.get(f): row[f] = str(row[f])
    for f in ("total_records","processed_count","approved_count",
              "declined_count","referred_count","errored_count"):
        if row.get(f) is not None: row[f] = int(row[f])
    if row.get("id"): row["id"] = str(row["id"])
    return row

@router.post("/upload")
async def upload_batch(
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    file: UploadFile = File(...),
    job_name: str = Form(""),
    dry_run: bool = Form(False),
    skip_product_errors: bool = Form(False),
    policy_effective_date: str = Form(""),
    policy_expire_date: str = Form(""),
    auto_assign: bool = Form(False),
    sla_hours: int = Form(48),
):
    file_bytes = await file.read()
    filename   = file.filename or "batch.csv"
    job_id     = str(uuid.uuid4())

    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        # Count rows
        try:
            text = file_bytes.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            total = len(rows)
        except Exception:
            total = 0

        # Generate job_number
        cur.execute("SELECT COALESCE(MAX(CAST(job_number AS INTEGER)), 0) + 1 AS next_num FROM batch_jobs WHERE job_number ~ '^[0-9]+$'")
        next_row = cur.fetchone()
        job_number = str((next_row["next_num"] if next_row else 1) or 1).zfill(6)

        cur.execute("""
            INSERT INTO batch_jobs (
                id, job_number, job_name, status, total_records, dry_run,
                skip_product_errors, policy_effective_date, policy_expire_date,
                input_filename, submitted_by, submitted_at
            ) VALUES (
                %s, %s, %s, 'QUEUED', %s, %s, %s, %s, %s, %s, %s, now()
            ) RETURNING id, job_number
        """, (
            job_id, job_number,
            job_name or filename,
            total, dry_run, skip_product_errors,
            policy_effective_date or None,
            policy_expire_date or None,
            filename, current.username,
        ))
        row = cur.fetchone()
        conn.commit()

        # Store file content in DB for worker
        cur.execute("""
            UPDATE batch_jobs SET file_content = %s WHERE id = %s
        """, (file_bytes.decode("utf-8-sig", errors="replace"), job_id))
        conn.commit()
        cur.close()

        # Trigger background processing
        background_tasks.add_task(
            _run_batch_job, job_id, file_bytes, filename, dry_run,
            skip_product_errors, policy_effective_date, policy_expire_date,
            current.username
        )

        return {
            "job_id":     str(row["id"]),
            "job_number": row.get("job_number", ""),
            "status":     "QUEUED",
            "total_records": total,
            "message":    "Batch job queued for processing",
        }
    finally:
        release(conn)


def _run_batch_job(job_id, file_bytes, filename, dry_run,
                   skip_product_errors, eff_date, exp_date, username):
    """Background task to process batch job."""
    try:
        from services.batch_processor import process_job
        process_job(job_id)
    except ImportError:
        _fallback_process(job_id, file_bytes, filename, dry_run,
                         skip_product_errors, username)
    except Exception as e:
        logger.error(f"Batch job {job_id} failed: {e}", exc_info=True)
        conn, release = _jobs_db()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE batch_jobs SET status='FAILED', error_message=%s,
                completed_at=now() WHERE id=%s
            """, (str(e), job_id))
            conn.commit()
            cur.close()
        finally:
            release(conn)


def _validate_product(cur, product_code: str) -> dict | None:
    """Returns product row if valid and active, else None."""
    cur.execute(
        "SELECT product_code, product_name, is_active FROM products WHERE product_code = %s",
        (product_code,)
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def _calculate_premium(cur, product_code: str, payload: dict, result: dict) -> dict:
    """
    Calculate premium for an APPROVED case.
    Returns dict with keys:
      - premium: float or None
      - premium_note: info/warning message string
      - user_label_values: dict of {user_label: value} used in formula
    """
    out = {"premium": None, "premium_note": "", "user_label_values": {}}

    # 1. Check if formula exists for this product
    cur.execute("""
        SELECT id FROM premium_formula
        WHERE product_code = %s
          AND formula_type = 'BASE_PREMIUM'
          AND is_active = true
          AND effective_date <= CURRENT_DATE
          AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
        ORDER BY effective_date DESC LIMIT 1
    """, (product_code,))
    formula_row = cur.fetchone()
    if not formula_row:
        out["premium_note"] = "Premium not calculated — no formula attached to product"
        return out

    formula_id = dict(formula_row)["id"]

    # 2. Get formula steps ordered by seq_no
    cur.execute("""
        SELECT seq_no, operator, factor, parameter_type,
               user_value, user_label, scale_id, description
        FROM premium_formula_step
        WHERE formula_id = %s
        ORDER BY seq_no
    """, (formula_id,))
    steps = [dict(r) for r in cur.fetchall()]
    if not steps:
        out["premium_note"] = "Premium not calculated — formula has no steps defined"
        return out

    # 3. Evaluate steps
    running = 0.0
    missing_params = []

    for step in steps:
        ptype    = step["parameter_type"]
        operator = step["operator"]
        factor   = float(step["factor"] or 1)

        # Resolve the step value
        step_val = None

        if ptype == "USER_VALUE":
            step_val = float(step["user_value"] or 0)

        elif ptype == "USER_LABEL":
            label_key = step["user_label"]
            raw = payload.get(label_key) or payload.get(label_key.lower())
            if raw in (None, ""):
                missing_params.append(label_key)
                continue
            try:
                step_val = float(raw)
                out["user_label_values"][label_key] = step_val
            except (ValueError, TypeError):
                missing_params.append(label_key)
                continue

        elif ptype in ("SUM_ASSURED", "FACE_AMOUNT"):
            step_val = float(payload.get("face_amount") or 0)

        elif ptype == "AGE":
            step_val = float(payload.get("age") or 0)

        elif ptype == "ANNUAL_INCOME":
            step_val = float(payload.get("annual_income") or 0)

        elif ptype == "POLICY_TERM":
            step_val = float(payload.get("coverage_term_yrs") or 0)

        elif ptype == "DEBIT_POINTS":
            step_val = float(result.get("net_debit_points") or 0)

        elif ptype == "PREVIOUS_RESULT":
            step_val = running

        elif ptype == "RATE_SCALE":
            # Rate scale lookup — use scale_id to get rate for age/term
            scale_id = step.get("scale_id")
            if not scale_id:
                missing_params.append(f"rate_scale(step {step['seq_no']})")
                continue
            try:
                age  = int(payload.get("age") or 0)
                term = int(payload.get("coverage_term_yrs") or 0)
                cur.execute("""
                    SELECT rate FROM uw_rate_scale
                    WHERE id = %s AND age = %s AND term = %s
                    LIMIT 1
                """, (scale_id, age, term))
                rate_row = cur.fetchone()
                if rate_row:
                    step_val = float(dict(rate_row)["rate"])
                else:
                    missing_params.append(f"rate_scale(age={age},term={term})")
                    continue
            except Exception:
                missing_params.append(f"rate_scale(step {step['seq_no']})")
                continue
        else:
            continue  # Unknown parameter type — skip

        # Apply operator
        val = step_val * factor
        if operator == "+":   running += val
        elif operator == "-": running -= val
        elif operator == "*": running *= val
        elif operator == "/" and val != 0: running /= val
        elif operator == "%": running += running * (val / 100)

    # 4. Build result
    if missing_params:
        out["premium_note"] = (
            f"Premium not calculated — missing parameters: {', '.join(missing_params)}"
        )
    else:
        out["premium"] = round(running, 2)
        out["premium_note"] = ""

    return out


def _get_active_user_labels(cur) -> list[dict]:
    """Returns all active user labels sorted by sort_order."""
    try:
        cur.execute("""
            SELECT label_key, label_name, data_type
            FROM system_user_label
            WHERE is_active = true
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY sort_order, label_name
        """)
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def _fallback_process(job_id, file_bytes, filename, dry_run,
                      skip_product_errors, username):
    """Fallback batch processor if service not available."""
    import csv, io as _io, json
    from services.uw_engine import run_evaluation

    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE batch_jobs SET status='RUNNING', started_at=now()
            WHERE id=%s
        """, (job_id,))
        conn.commit()

        text   = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(_io.StringIO(text))
        rows   = list(reader)

        # Cache valid products to avoid repeated DB hits
        cur.execute("SELECT product_code FROM products WHERE is_active = true")
        valid_products = {dict(r)["product_code"] for r in cur.fetchall()}

        approved = declined = referred = errored = 0

        for i, row in enumerate(rows, 1):
            try:
                payload = {k.strip().lower(): v.strip() for k,v in row.items() if v is not None}

                # ── Requirement 1: Product validation ────────────────────────
                product_code = payload.get("product_code", "").strip().upper()
                if not product_code or product_code not in valid_products:
                    errored += 1
                    err_msg = (
                        f"PROD001 — Product '{product_code}' not found in system"
                        if product_code else "PROD001 — product_code is missing"
                    )
                    cur.execute("""
                        INSERT INTO batch_job_records
                            (job_id, row_number, applicant_ref, product_code,
                             status, outcome, risk_class, net_debit_points,
                             primary_reason, error_codes, processing_ms, created_at)
                        VALUES (%s,%s,%s,%s,'ERROR','ERROR','',0,%s,%s,0,now())
                        ON CONFLICT DO NOTHING
                    """, (
                        job_id, i,
                        payload.get("applicant_ref", ""),
                        product_code,
                        err_msg,
                        "PROD001",
                    ))
                    if i % 50 == 0:
                        conn.commit()
                        cur.execute("""
                            UPDATE batch_jobs SET processed_count=%s,
                            approved_count=%s, declined_count=%s,
                            referred_count=%s, errored_count=%s WHERE id=%s
                        """, (i, approved, declined, referred, errored, job_id))
                        conn.commit()
                    continue  # Skip to next row — do NOT process this record

                # Type coercions
                for int_field in ("age","coverage_term_yrs","alcohol_drinks_week"):
                    if payload.get(int_field):
                        try: payload[int_field] = int(float(payload[int_field]))
                        except: payload.pop(int_field, None)
                for float_field in ("face_amount","a1c","bmi","annual_income","existing_coverage"):
                    if payload.get(float_field):
                        try: payload[float_field] = float(payload[float_field])
                        except: payload.pop(float_field, None)
                for bool_field in ("hiv_positive","cirrhosis","stroke_history",
                                   "kidney_disease","epilepsy","copd","hazardous_activity"):
                    if payload.get(bool_field):
                        payload[bool_field] = str(payload[bool_field]).lower() in ("true","1","yes")

                if not dry_run:
                    result = run_evaluation(payload, username, None)
                    outcome = result.get("outcome","ERROR")
                else:
                    result  = {}
                    outcome = "DRY_RUN"

                # ── Requirement 2: Premium calculation for APPROVED ───────────
                premium      = None
                premium_note = ""
                if not dry_run and "APPROVED" in outcome:
                    prem_result  = _calculate_premium(cur, product_code, payload, result)
                    premium      = prem_result["premium"]
                    premium_note = prem_result["premium_note"]

                if "APPROVED" in outcome:   approved += 1
                elif "DECLINED" in outcome: declined += 1
                elif "REFERRED" in outcome: referred += 1
                else:                       errored  += 1

                # ── Requirement 3: Store input_data (for user label columns) ──
                input_data_json = json.dumps({
                    k: v for k, v in row.items()
                    if k and k.strip()
                })

                cur.execute("""
                    INSERT INTO batch_job_records
                        (job_id, row_number, applicant_ref, product_code,
                         status, outcome, risk_class, net_debit_points,
                         primary_reason, error_codes,
                         premium, premium_note, input_data,
                         processing_ms, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,now())
                    ON CONFLICT DO NOTHING
                """, (
                    job_id, i,
                    payload.get("applicant_ref",""),
                    product_code,
                    "PROCESSED" if not dry_run else "DRY_RUN",
                    outcome,
                    result.get("risk_class","") if not dry_run else "",
                    result.get("net_debit_points",0) if not dry_run else 0,
                    result.get("primary_reason","") if not dry_run else "",
                    ",".join(result.get("error_codes",[]) or []) if not dry_run else "",
                    premium,
                    premium_note,
                    input_data_json,
                ))
                if i % 50 == 0:
                    conn.commit()
                    cur.execute("""
                        UPDATE batch_jobs SET processed_count=%s,
                        approved_count=%s, declined_count=%s,
                        referred_count=%s, errored_count=%s
                        WHERE id=%s
                    """, (i, approved, declined, referred, errored, job_id))
                    conn.commit()

            except Exception as row_err:
                errored += 1
                logger.warning(f"Row {i} error: {row_err}")

        conn.commit()
        cur.execute("""
            UPDATE batch_jobs SET
                status=%s, processed_count=%s, approved_count=%s,
                declined_count=%s, referred_count=%s, errored_count=%s,
                completed_at=now()
            WHERE id=%s
        """, (
            "DRY_RUN_COMPLETE" if dry_run else "COMPLETED",
            len(rows), approved, declined, referred, errored, job_id
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Fallback batch failed: {e}", exc_info=True)
        try:
            cur.execute("""
                UPDATE batch_jobs SET status='FAILED', error_message=%s,
                completed_at=now() WHERE id=%s
            """, (str(e), job_id))
            conn.commit()
        except: pass
    finally:
        release(conn)


@router.get("/jobs")
def list_jobs(current: CurrentUser, limit: int = 50):
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, job_number, job_name, status, total_records,
                   processed_count, approved_count, declined_count,
                   referred_count, errored_count, dry_run,
                   input_filename, error_message, submitted_by,
                   submitted_at, started_at, completed_at
            FROM batch_jobs
            ORDER BY submitted_at DESC LIMIT %s
        """, (limit,))
        rows = [_fmt_job(dict(r)) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release(conn)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, current: CurrentUser):
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, job_number, job_name, status, total_records,
                   processed_count, approved_count, declined_count,
                   referred_count, errored_count, dry_run,
                   input_filename, error_message, submitted_by,
                   submitted_at, started_at, completed_at
            FROM batch_jobs WHERE id=%s
        """, (job_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")

        # Get records
        cur.execute("""
            SELECT row_number, applicant_ref, product_code,
                   status, outcome, risk_class, net_debit_points,
                   primary_reason, error_codes, processing_ms
            FROM batch_job_records WHERE job_id=%s
            ORDER BY row_number LIMIT 500
        """, (job_id,))
        records = [dict(r) for r in cur.fetchall()]
        cur.close()

        result = _fmt_job(dict(row))
        result["records"] = records
        return result
    finally:
        release(conn)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, current: CurrentUser):
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE batch_jobs SET status='CANCELLED', completed_at=now()
            WHERE id=%s AND status IN ('QUEUED','RUNNING')
        """, (job_id,))
        conn.commit()
        cur.close()
        return {"message": "Job cancelled"}
    finally:
        release(conn)


@router.get("/jobs/{job_id}/download/{type}")
def download_results(job_id: str, type: str, fmt: str = "csv", current: CurrentUser = None):
    import json as _json
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()

        # ── Fetch records including premium and input_data ────────────────────
        cur.execute("""
            SELECT r.row_number, r.applicant_ref, r.product_code,
                   r.status, r.outcome, r.risk_class, r.net_debit_points,
                   r.primary_reason, r.error_codes, r.processing_ms,
                   r.premium, r.premium_note, r.input_data
            FROM batch_job_records r
            WHERE r.job_id = %s
            ORDER BY r.row_number
        """, (job_id,))
        rows = [dict(r) for r in cur.fetchall()]

        # ── Get active user labels to include as columns ──────────────────────
        user_labels = _get_active_user_labels(cur)
        cur.close()

        # ── Parse input_data JSON and merge user label values into each row ───
        for row in rows:
            input_data = {}
            if row.get("input_data"):
                try:
                    input_data = _json.loads(row["input_data"])
                    # Normalise keys
                    input_data = {k.strip().lower(): v for k, v in input_data.items()}
                except Exception:
                    pass
            row["_input"] = input_data
            # Populate user label columns
            for ul in user_labels:
                col = ul["label_key"]
                row[f"ul_{col}"] = input_data.get(col, "")

        # ── Filter by download type ───────────────────────────────────────────
        if type == "errors":
            rows = [r for r in rows if (
                r.get("status") == "ERROR"
                or r.get("outcome") in (None, "", "ERROR")
                or r.get("error_codes") not in (None, "")
            )]
        elif type == "summary":
            from collections import Counter
            counts = Counter(r.get("outcome") or "UNKNOWN" for r in rows)
            summary_rows = [{"outcome": k, "count": v} for k, v in counts.items()]
            export_cols  = ["outcome", "count"]

            if fmt == "xlsx":
                import openpyxl, io as _io
                wb = openpyxl.Workbook(); ws = wb.active
                ws.append(export_cols)
                for row in summary_rows:
                    ws.append([row.get(c, "") for c in export_cols])
                buf = _io.BytesIO(); wb.save(buf); buf.seek(0)
                return StreamingResponse(buf,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=batch_summary_{job_id[:8]}.xlsx"})
            else:
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(export_cols)
                for row in summary_rows:
                    writer.writerow([row.get(c, "") for c in export_cols])
                output.seek(0)
                return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=batch_summary_{job_id[:8]}.csv"})

        # ── Build export columns for results / errors ─────────────────────────
        base_cols = [
            "row_number", "applicant_ref", "product_code",
            "outcome", "risk_class", "net_debit_points",
            "primary_reason", "error_codes",
            "premium", "premium_note",
        ]
        # Add one column per active user label
        ul_cols = [f"ul_{ul['label_key']}" for ul in user_labels]
        # Friendly header names: label_name instead of ul_label_key
        ul_headers = [ul["label_name"] for ul in user_labels]

        export_cols    = base_cols + ul_cols
        display_headers = [
            "Row", "Applicant Ref", "Product Code",
            "Outcome", "Risk Class", "Net Debit Points",
            "Primary Reason", "Error Codes",
            "Premium (₹)", "Premium Note",
        ] + ul_headers

        # ── Render xlsx or csv ────────────────────────────────────────────────
        if fmt == "xlsx":
            import openpyxl, io as _io
            from openpyxl.styles import Font, PatternFill, Alignment
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = type.capitalize()

            # Header row with formatting
            ws.append(display_headers)
            for cell in ws[1]:
                cell.font      = Font(bold=True, color="FFFFFF")
                cell.fill      = PatternFill("solid", fgColor="1a2744")
                cell.alignment = Alignment(horizontal="center")

            # Data rows with outcome colour coding
            outcome_colors = {
                "APPROVED": "d4edda", "DECLINED": "f8d7da",
                "REFERRED": "fff3cd", "ERROR": "e2e3e5",
            }
            for row in rows:
                data_row = []
                for col in export_cols:
                    val = row.get(col, "")
                    if val is None: val = ""
                    data_row.append(val)
                ws.append(data_row)
                outcome = str(row.get("outcome",""))
                color   = outcome_colors.get(outcome.split("_")[0] if "_" in outcome else outcome, "")
                if color:
                    for cell in ws[ws.max_row]:
                        cell.fill = PatternFill("solid", fgColor=color)

            # Auto-width columns
            for col_cells in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col_cells), default=10)
                ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 40)

            buf = _io.BytesIO(); wb.save(buf); buf.seek(0)
            return StreamingResponse(buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=batch_{type}_{job_id[:8]}.xlsx"})
        else:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(display_headers)
            for row in rows:
                writer.writerow([
                    "" if row.get(c) is None else row.get(c, "")
                    for c in export_cols
                ])
            output.seek(0)
            return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=batch_{type}_{job_id[:8]}.csv"})
    finally:
        release(conn)

@router.get("/schedules")
def list_schedules(current: CurrentUser):
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM batch_recurring_schedules ORDER BY created_at DESC")
            rows = cur.fetchall()
            result = []
            for r in rows:
                row = dict(r)
                for f in ("created_at","updated_at","last_run_at","next_run_at"):
                    if row.get(f): row[f] = str(row[f])
                result.append(row)
            cur.close()
            return result
        except Exception:
            cur.close()
            return []
    finally:
        release(conn)


@router.post("/schedules")
def create_schedule(body: dict, current: CurrentUser):
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO batch_recurring_schedules
                (schedule_name, cron_expression, is_active, created_by)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (
            body.get("schedule_name"), body.get("cron_expression"),
            body.get("is_active", True), current.username,
        ))
        conn.commit()
        sid = cur.fetchone()[0]
        cur.close()
        return {"id": sid, "message": "Schedule created"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release(conn)


@router.patch("/schedules/{sid}")
def update_schedule(sid: int, body: dict, current: CurrentUser):
    conn, release = _jobs_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE batch_recurring_schedules
            SET is_active=%s, updated_at=now()
            WHERE id=%s
        """, (body.get("is_active"), sid))
        conn.commit()
        cur.close()
        return {"message": "Schedule updated"}
    finally:
        release(conn)

