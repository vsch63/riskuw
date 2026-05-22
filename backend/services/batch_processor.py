"""
backend/services/batch_processor.py
─────────────────────────────────────
Processes a queued batch_jobs row:
  1. Read the uploaded CSV / Excel from disk or DB
  2. Validate each row
  3. Call uw_engine.run_evaluation() per record
  4. Write results to batch_job_records
  5. Update batch_jobs counters + status

Called by:  routers/batch.py  (POST /batch/upload triggers background task)
Can also be run as a standalone script for debugging:
    python -m services.batch_processor --job-id <id>
"""
from __future__ import annotations

import io
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("uw_platform")

REQUIRED_COLUMNS = {
    "applicant_ref", "product_code", "age", "gender",
    "face_amount", "state",
}

COLUMN_ALIASES = {
    "ref": "applicant_ref",
    "product": "product_code",
    "sum_insured": "face_amount",
    "sum assured": "face_amount",
    "tobacco": "tobacco_status",
    "smoker": "tobacco_status",
    "height": "height_inches",
    "weight": "weight_lbs",
    "systolic": "systolic_bp",
    "diastolic": "diastolic_bp",
    "income": "annual_income",
}


def _normalise_row(row: dict) -> dict:
    """Lowercase keys, apply aliases, strip whitespace from string values."""
    out = {}
    for k, v in row.items():
        key = k.strip().lower().replace(" ", "_")
        key = COLUMN_ALIASES.get(key, key)
        out[key] = v.strip() if isinstance(v, str) else v
    return out


def _coerce(row: dict) -> dict:
    """Type-coerce string values from CSV into proper Python types."""
    int_fields  = {"age", "coverage_term_yrs", "height_inches", "weight_lbs",
                   "systolic_bp", "diastolic_bp", "alcohol_drinks_week"}
    float_fields = {"face_amount", "annual_income", "existing_coverage", "a1c",
                   "tobacco_quit_years", "heart_event_years_ago"}
    bool_fields  = {"hiv_positive", "cirrhosis", "stroke_history", "kidney_disease",
                   "depression_history", "dep_hosp", "epilepsy", "copd",
                   "hazardous_activity", "fh_cardio", "fh_stroke"}
    truthy = {"true", "1", "yes", "y"}

    result = dict(row)
    for f in int_fields:
        if f in result and result[f] not in (None, ""):
            try:
                result[f] = int(float(str(result[f])))
            except (ValueError, TypeError):
                result.pop(f, None)
    for f in float_fields:
        if f in result and result[f] not in (None, ""):
            try:
                result[f] = float(str(result[f]))
            except (ValueError, TypeError):
                result.pop(f, None)
    for f in bool_fields:
        if f in result:
            result[f] = str(result[f]).lower().strip() in truthy

    return result


def process_batch_job(job_id: str, file_bytes: bytes, filename: str,
                      submitted_by: str, tenant_id: str) -> dict:
    """
    Full batch processing pipeline.
    Returns summary dict: {processed, approved, declined, referred, errored}
    """
    from database import get_conn, release_conn
    from services.uw_engine import run_evaluation

    conn = get_conn()
    summary = {
        "processed": 0, "approved": 0, "declined": 0,
        "referred": 0, "errored": 0,
    }

    try:
        # ── Mark job as RUNNING ──────────────────────────────────────────────
        cur = conn.cursor()
        cur.execute(
            "UPDATE batch_jobs SET status='RUNNING', started_at=now() WHERE id=%s",
            (job_id,),
        )
        conn.commit()
        cur.close()

        # ── Parse file ───────────────────────────────────────────────────────
        import pandas as pd
        buf = io.BytesIO(file_bytes)
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(buf)
        else:
            df = pd.read_excel(buf)

        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        records = df.to_dict(orient="records")
        total = len(records)

        # Update total_records
        cur = conn.cursor()
        cur.execute("UPDATE batch_jobs SET total_records=%s WHERE id=%s", (total, job_id))
        conn.commit()
        cur.close()

        # ── Process each row ─────────────────────────────────────────────────
        for i, raw_row in enumerate(records, start=1):
            row = _coerce(_normalise_row(raw_row))
            row.setdefault("applicant_ref", f"BATCH-{job_id[:6]}-{i:04d}")

            t0 = time.monotonic()
            status = "OK"
            outcome = error_codes = primary_reason = risk_class = None
            net_debits = 0

            # Validate required columns
            missing = REQUIRED_COLUMNS - set(row.keys())
            if missing:
                status = "ERROR"
                error_codes = f"MISSING_COLS:{','.join(sorted(missing))}"
                summary["errored"] += 1
            else:
                try:
                    result = run_evaluation(row, submitted_by, tenant_id)
                    outcome       = result.get("outcome", "UNKNOWN")
                    risk_class    = result.get("risk_class")
                    net_debits    = result.get("net_debit_points", 0)
                    primary_reason = result.get("adverse_action_text")
                    if "APPROVED" in (outcome or ""):
                        summary["approved"] += 1
                    elif "DECLINED" in (outcome or ""):
                        summary["declined"] += 1
                    else:
                        summary["referred"] += 1
                except Exception as exc:
                    logger.warning(f"Row {i} evaluation failed: {exc}")
                    status = "ERROR"
                    error_codes = f"ENGINE_ERROR:{str(exc)[:100]}"
                    summary["errored"] += 1

            processing_ms = int((time.monotonic() - t0) * 1000)
            summary["processed"] += 1

            # Write record
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO batch_job_records
                    (job_id, row_number, applicant_ref, product_code,
                     status, outcome, risk_class, net_debit_points,
                     primary_reason, error_codes, processing_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job_id, i,
                    row.get("applicant_ref"), row.get("product_code"),
                    status, outcome, risk_class, net_debits,
                    primary_reason, error_codes, processing_ms,
                ),
            )
            conn.commit()
            cur.close()

        # ── Mark job COMPLETED ───────────────────────────────────────────────
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE batch_jobs SET
                status='COMPLETED',
                processed_count=%s, approved_count=%s, declined_count=%s,
                referred_count=%s, errored_count=%s,
                completed_at=now()
            WHERE id=%s
            """,
            (
                summary["processed"], summary["approved"], summary["declined"],
                summary["referred"], summary["errored"], job_id,
            ),
        )
        conn.commit()
        cur.close()
        logger.info(f"Batch job {job_id} complete", extra=summary)
        return summary

    except Exception as exc:
        logger.error(f"Batch job {job_id} failed", exc_info=exc)
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE batch_jobs SET status='FAILED', error_message=%s WHERE id=%s",
                (str(exc)[:500], job_id),
            )
            conn.commit()
            cur.close()
        except Exception:
            pass
        raise
    finally:
        release_conn(conn)
