"""
backend/routers/system.py
──────────────────────────
GET  /system/config                      — list all system_config rows for tenant
POST /system/config                      — upsert a config key
GET  /system/smtp                        — smtp_config as dict
POST /system/smtp                        — save smtp_config key-value pairs
POST /system/smtp/test                   — send test email
POST /system/smtp/test-connection        — test SMTP connection only (no email)
GET  /system/states                      — state_codes list
GET  /system/error-codes                 — error_codes table
POST /system/error-codes                 — add error code
GET  /system/rates/products              — rated products list
GET  /system/rates                       — rates for a product
POST /system/rates/add                   — add single rate
DELETE /system/rates/product/{code}      — delete all rates for product
POST /system/rates/upload-csv            — bulk upload rates from CSV
GET  /system/letter-templates            — list letter templates
POST /system/letter-templates            — create letter template
PUT  /system/letter-templates/{id}       — update letter template
PATCH /system/letter-templates/{id}      — partial update (e.g. set active)
DELETE /system/letter-templates/{id}     — delete letter template
GET  /system/output-interface            — get output interface config
POST /system/output-interface            — save output interface config
GET  /system/output-interface/stats      — queue stats
GET  /system/output-interface/failed     — failed push records
POST /system/output-interface/test       — test webhook with sample payload
POST /system/output-interface/push       — push all pending to PAS
POST /system/output-interface/push/{id}  — retry single failed record
POST /system/output-interface/extract    — CSV/Excel file extract download
GET  /system/output-interface/preview    — preview unprocessed records

Tables: system_config · smtp_config · state_codes · error_codes
        premium_rates · letter_templates · policy_admin_queue
"""
from __future__ import annotations
import io
import json
import csv
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from deps import CurrentUser

router = APIRouter(prefix="/system", tags=["system"])


def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn


def _row(r) -> dict:
    return dict(r) if hasattr(r, "keys") else {}


def _rows(rs) -> list:
    return [_row(r) for r in rs]


# ── system_config ──────────────────────────────────────────────────────────────

@router.get("/config")
def list_config(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        if current.tenant_id:
            cur.execute(
                "SELECT config_key, config_value, config_type, description "
                "FROM system_config WHERE tenant_id=%s::uuid ORDER BY config_key",
                (current.tenant_id,),
            )
        else:
            cur.execute(
                "SELECT config_key, config_value, config_type, description "
                "FROM system_config ORDER BY config_key"
            )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


class ConfigUpsert(BaseModel):
    config_key: str
    config_value: str
    config_type: Optional[str] = "string"
    description: Optional[str] = None


@router.post("/config")
def upsert_config(body: ConfigUpsert, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        if current.tenant_id:
            cur.execute(
                """
                INSERT INTO system_config
                    (id, tenant_id, config_key, config_value, config_type, description, updated_by)
                VALUES (gen_random_uuid(), %s::uuid, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, config_key) DO UPDATE
                    SET config_value=%s, updated_by=%s, updated_at=now()
                """,
                (current.tenant_id, body.config_key, body.config_value,
                 body.config_type, body.description, current.username,
                 body.config_value, current.username),
            )
        else:
            cur.execute(
                """
                INSERT INTO system_config (config_key, config_value, updated_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (config_key) DO UPDATE
                    SET config_value=%s, updated_by=%s, updated_at=now()
                """,
                (body.config_key, body.config_value, current.username,
                 body.config_value, current.username),
            )
        conn.commit()
        cur.close()
        return {"status": "saved", "key": body.config_key}
    finally:
        release(conn)


# ── smtp_config ────────────────────────────────────────────────────────────────

@router.get("/smtp")
def get_smtp(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM smtp_config")
        rows = cur.fetchall()
        cur.close()
        result = {}
        for r in rows:
            k, v = (r[0], r[1]) if isinstance(r, tuple) else (r["key"], r["value"])
            result[k] = v
        return result
    finally:
        release(conn)


class SmtpSave(BaseModel):
    smtp_host:      Optional[str] = None
    smtp_port:      Optional[str] = None
    smtp_user:      Optional[str] = None
    smtp_password:  Optional[str] = None
    smtp_from:      Optional[str] = None
    smtp_from_name: Optional[str] = None
    smtp_use_tls:   Optional[bool] = True


@router.post("/smtp")
def save_smtp(body: SmtpSave, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        fields = {k: str(v) for k, v in body.model_dump(exclude_none=True).items()}
        for key, value in fields.items():
            cur.execute(
                "INSERT INTO smtp_config (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value=%s",
                (key, value, value),
            )
        conn.commit()
        cur.close()
        return {"status": "saved", "keys": list(fields.keys())}
    finally:
        release(conn)


class TestEmail(BaseModel):
    to_email: str


@router.post("/smtp/test")
def test_smtp(body: TestEmail, current: CurrentUser):
    conn, release = _get_db()
    try:
        from services.notification import send_email
        ok, msg = send_email(
            conn, body.to_email,
            subject="RiskUW — SMTP Test",
            html_body="<p>Your RiskUW SMTP configuration is working correctly.</p>",
            event="SMTP_TEST",
        )
        if not ok:
            raise HTTPException(400, msg)
        return {"status": "sent", "message": msg}
    finally:
        release(conn)


@router.post("/smtp/test-connection")
def test_smtp_connection(current: CurrentUser):
    """Test SMTP connection without sending email."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM smtp_config")
        rows = cur.fetchall()
        cur.close()
        cfg = {(r[0] if isinstance(r, tuple) else r["key"]): (r[1] if isinstance(r, tuple) else r["value"]) for r in rows}
        release(conn)

        import smtplib
        host = cfg.get("smtp_host", "")
        port = int(cfg.get("smtp_port", 587))
        use_tls = cfg.get("smtp_use_tls", "True").lower() not in ("false", "0")
        user = cfg.get("smtp_user", "")
        pwd  = cfg.get("smtp_password", "")

        if not host:
            raise HTTPException(400, "SMTP host not configured")

        if use_tls:
            srv = smtplib.SMTP(host, port, timeout=10)
            srv.starttls()
        else:
            srv = smtplib.SMTP_SSL(host, port, timeout=10)
        if user and pwd:
            srv.login(user, pwd)
        srv.quit()
        return {"status": "ok", "message": "SMTP connection successful"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"SMTP connection failed: {e}")


# ── state_codes ────────────────────────────────────────────────────────────────

@router.get("/states")
def list_states(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, state_code, state_name, is_active, country_code "
            "FROM state_codes WHERE is_active=true ORDER BY state_code"
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


# ── error_codes ────────────────────────────────────────────────────────────────

@router.get("/error-codes")
def list_error_codes(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM error_codes ORDER BY error_code")
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    finally:
        release(conn)


class ErrorCodeCreate(BaseModel):
    code:       str
    category:   str
    severity:   str = "ERROR"
    message:    str
    resolution: Optional[str] = None


@router.post("/error-codes", status_code=201)
def create_error_code(body: ErrorCodeCreate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO error_codes (code, category, severity, description, resolution_hint, is_active)
            VALUES (%s, %s, %s, %s, %s, true)
            ON CONFLICT (code) DO UPDATE SET
                category=EXCLUDED.category, severity=EXCLUDED.severity,
                description=EXCLUDED.description, resolution_hint=EXCLUDED.resolution_hint
            """,
            (body.code.upper(), body.category, body.severity, body.message, body.resolution),
        )
        conn.commit()
        cur.close()
        return {"status": "saved", "code": body.code.upper()}
    finally:
        release(conn)


# ── premium_rates ──────────────────────────────────────────────────────────────

@router.get("/rates/products")
def list_rated_products(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT product_code, COUNT(*) as rate_count "
            "FROM premium_rates GROUP BY product_code ORDER BY product_code"
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) if hasattr(r, "keys") else {"product_code": r[0], "rate_count": r[1]} for r in rows]
    except Exception:
        return []
    finally:
        release(conn)


@router.get("/rates")
def get_rates(product_code: str = Query(...), current: CurrentUser = None):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM premium_rates WHERE product_code=%s ORDER BY gender, tobacco_status, age_min",
            (product_code.upper(),)
        )
        rows = cur.fetchall()
        cur.close()
        return [_row(r) for r in rows]
    except Exception:
        return []
    finally:
        release(conn)


class RateAdd(BaseModel):
    product_code:   str
    gender:         str
    tobacco_status: str = "NON_TOBACCO"
    age_min:        int
    age_max:        int
    term_years:     Optional[int] = None
    risk_class:     str = "STANDARD"
    table_rating:   int = 0
    rate_per_thou:  float
    flat_extra_rate:float = 0.0
    rate_label:     Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date:    Optional[str] = None


@router.post("/rates/add", status_code=201)
def add_rate(body: RateAdd, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO premium_rates
                (product_code, gender, tobacco_status, age_min, age_max, term_years,
                 risk_class, table_rating, rate_per_thou, flat_extra_rate,
                 rate_label, effective_date, expiry_date, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date,%s::date,now())
            RETURNING id
            """,
            (body.product_code.upper(), body.gender, body.tobacco_status,
             body.age_min, body.age_max, body.term_years,
             body.risk_class, body.table_rating, body.rate_per_thou, body.flat_extra_rate,
             body.rate_label, body.effective_date or None, body.expiry_date or None),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return {"status": "added", "id": row[0] if row else None}
    finally:
        release(conn)


@router.delete("/rates/product/{code}")
def delete_product_rates(code: str, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM premium_rates WHERE product_code=%s", (code.upper(),))
        rows_deleted = cur.rowcount
        conn.commit()
        cur.close()
        return {"status": "deleted", "rows_deleted": rows_deleted, "product_code": code.upper()}
    finally:
        release(conn)


@router.post("/rates/upload-csv")
async def upload_rates_csv(
    file: UploadFile = File(...),
    product_code: str = Query(...),
    replace_existing: bool = Query(True),
    effective_date: Optional[str] = Query(None),
    expiry_date: Optional[str] = Query(None),
    current: CurrentUser = None,
):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    content = await file.read()
    text    = content.decode("utf-8")
    reader  = csv.DictReader(io.StringIO(text))
    code    = product_code.upper()
    inserted = 0
    errors: list = []

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        if replace_existing:
            cur.execute("DELETE FROM premium_rates WHERE product_code=%s", (code,))

        for i, row in enumerate(reader):
            try:
                cur.execute(
                    """
                    INSERT INTO premium_rates
                        (product_code, gender, tobacco_status, age_min, age_max, term_years,
                         risk_class, table_rating, rate_per_thou, flat_extra_rate,
                         rate_label, effective_date, expiry_date, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date,%s::date,now())
                    """,
                    (
                        code,
                        row.get("gender", "MALE"),
                        row.get("tobacco_status", "NON_TOBACCO"),
                        int(row.get("age_min", 0)),
                        int(row.get("age_max", 99)),
                        int(row["term_years"]) if row.get("term_years") else None,
                        row.get("risk_class", "STANDARD"),
                        int(row.get("table_rating", 0)),
                        float(row.get("rate_per_thou", 0)),
                        float(row.get("flat_extra_rate", 0)),
                        row.get("rate_label") or None,
                        row.get("effective_date") or effective_date or None,
                        row.get("expiry_date") or expiry_date or None,
                    ),
                )
                inserted += 1
            except Exception as e:
                errors.append(f"Row {i+2}: {e}")

        conn.commit()
        cur.close()
        return {"status": "ok", "product_code": code, "inserted": inserted, "errors": errors}
    finally:
        release(conn)


# ── letter_templates ───────────────────────────────────────────────────────────

def _ensure_letter_templates_table(conn):
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS letter_templates (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                template_name   VARCHAR NOT NULL,
                outcome         VARCHAR NOT NULL,
                is_active       BOOLEAN DEFAULT false,
                version         INTEGER DEFAULT 1,
                header_company_name VARCHAR,
                header_tagline  VARCHAR,
                contact_email   VARCHAR,
                contact_phone   VARCHAR,
                body_text       TEXT,
                next_steps      JSONB,
                footer_text     TEXT,
                created_at      TIMESTAMP DEFAULT now(),
                updated_at      TIMESTAMP DEFAULT now()
            )
        """)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()


@router.get("/letter-templates")
def list_letter_templates(current: CurrentUser):
    conn, release = _get_db()
    try:
        _ensure_letter_templates_table(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, template_name, outcome, is_active, version,
                   header_company_name, header_tagline, contact_email, contact_phone,
                   body_text, next_steps, footer_text,
                   created_at, updated_at
            FROM letter_templates ORDER BY outcome, version DESC
        """)
        rows = cur.fetchall()
        cur.close()
        cols = ["id","template_name","outcome","is_active","version",
                "header_company_name","header_tagline","contact_email","contact_phone",
                "body_text","next_steps","footer_text","created_at","updated_at"]
        result = []
        for r in rows:
            d = dict(zip(cols, r)) if not hasattr(r, "keys") else dict(r)
            d["is_active"] = bool(d.get("is_active", False))
            if d.get("next_steps") and isinstance(d["next_steps"], str):
                try: d["next_steps"] = json.loads(d["next_steps"])
                except: d["next_steps"] = []
            for k in ("created_at","updated_at"):
                if d.get(k): d[k] = str(d[k])[:10]
            result.append(d)
        return result
    finally:
        release(conn)


class LetterTemplateCreate(BaseModel):
    template_name:       str
    outcome:             str
    is_active:           bool = True
    header_company_name: Optional[str] = None
    header_tagline:      Optional[str] = None
    contact_email:       Optional[str] = None
    contact_phone:       Optional[str] = None
    body_text:           Optional[str] = None
    next_steps:          Optional[list] = None
    footer_text:         Optional[str] = None


class LetterTemplateUpdate(BaseModel):
    template_name:       Optional[str] = None
    outcome:             Optional[str] = None
    is_active:           Optional[bool] = None
    header_company_name: Optional[str] = None
    header_tagline:      Optional[str] = None
    contact_email:       Optional[str] = None
    contact_phone:       Optional[str] = None
    body_text:           Optional[str] = None
    next_steps:          Optional[list] = None
    footer_text:         Optional[str] = None


@router.post("/letter-templates", status_code=201)
def create_letter_template(body: LetterTemplateCreate, current: CurrentUser):
    conn, release = _get_db()
    try:
        _ensure_letter_templates_table(conn)
        cur = conn.cursor()
        if body.is_active:
            cur.execute(
                "UPDATE letter_templates SET is_active=false WHERE outcome=%s",
                (body.outcome,)
            )
        cur.execute(
            """
            INSERT INTO letter_templates
                (id, template_name, outcome, is_active, version,
                 header_company_name, header_tagline, contact_email, contact_phone,
                 body_text, next_steps, footer_text)
            VALUES (gen_random_uuid(),%s,%s,%s,1,%s,%s,%s,%s,%s,%s::jsonb,%s)
            RETURNING id::text, template_name, outcome
            """,
            (body.template_name, body.outcome, body.is_active,
             body.header_company_name, body.header_tagline,
             body.contact_email, body.contact_phone,
             body.body_text, json.dumps(body.next_steps or []), body.footer_text),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return _row(row) if hasattr(row, "keys") else {"id": row[0], "template_name": row[1], "outcome": row[2]}
    finally:
        release(conn)


@router.put("/letter-templates/{tid}")
def update_letter_template(tid: str, body: LetterTemplateUpdate, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        if body.is_active:
            outcome = body.outcome
            if not outcome:
                cur.execute("SELECT outcome FROM letter_templates WHERE id=%s::uuid", (tid,))
                row = cur.fetchone()
                outcome = (row[0] if isinstance(row, tuple) else row["outcome"]) if row else None
            if outcome:
                cur.execute("UPDATE letter_templates SET is_active=false WHERE outcome=%s AND id!=%s::uuid", (outcome, tid))
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if "next_steps" in updates:
            updates["next_steps"] = json.dumps(updates["next_steps"])
        if not updates:
            raise HTTPException(400, "No fields to update")
        sets = ", ".join(f"{k}=%s" for k in updates)
        cur.execute(
            f"UPDATE letter_templates SET {sets}, version=version+1, updated_at=now() WHERE id=%s::uuid",
            (*updates.values(), tid)
        )
        conn.commit()
        cur.close()
        return {"status": "updated", "id": tid}
    finally:
        release(conn)


@router.patch("/letter-templates/{tid}")
def patch_letter_template(tid: str, body: LetterTemplateUpdate, current: CurrentUser):
    return update_letter_template(tid, body, current)


@router.delete("/letter-templates/{tid}")
def delete_letter_template(tid: str, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM letter_templates WHERE id=%s::uuid", (tid,))
        conn.commit()
        cur.close()
        return {"status": "deleted"}
    finally:
        release(conn)


# ── output_interface ───────────────────────────────────────────────────────────

OIC_KEY = "output_interface_config"


def _load_oic(conn) -> dict:
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT config_value FROM system_config WHERE config_key=%s LIMIT 1",
            (OIC_KEY,)
        )
        row = cur.fetchone()
        cur.close()
        if row:
            val = row[0] if isinstance(row, tuple) else row["config_value"]
            return json.loads(val) if val else {}
    except Exception:
        pass
    return {}


def _save_oic(conn, data: dict, username: str):
    cur = conn.cursor()
    val = json.dumps(data)
    cur.execute(
        """
        INSERT INTO system_config (config_key, config_value, updated_by)
        VALUES (%s, %s, %s)
        ON CONFLICT (config_key) DO UPDATE SET config_value=%s, updated_by=%s, updated_at=now()
        """,
        (OIC_KEY, val, username, val, username)
    )
    conn.commit()
    cur.close()


@router.get("/output-interface")
def get_output_interface(current: CurrentUser):
    conn, release = _get_db()
    try:
        cfg = _load_oic(conn)
        # Parse JSON sub-fields
        if isinstance(cfg.get("columns"), str):
            try: cfg["columns"] = json.loads(cfg["columns"])
            except: cfg["columns"] = []
        if isinstance(cfg.get("webhook_field_map"), str):
            try: cfg["webhook_field_map"] = json.loads(cfg["webhook_field_map"])
            except: cfg["webhook_field_map"] = {}
        return cfg
    finally:
        release(conn)


@router.post("/output-interface")
def save_output_interface(body: dict, current: CurrentUser):
    conn, release = _get_db()
    try:
        _save_oic(conn, body, current.username)
        return {"status": "saved"}
    finally:
        release(conn)


@router.get("/output-interface/stats")
def output_interface_stats(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                            AS total,
                COUNT(*) FILTER(WHERE push_status='PUSHED')       AS pushed,
                COUNT(*) FILTER(WHERE push_status='PENDING')      AS pending,
                COUNT(*) FILTER(WHERE push_status='PUSH_FAILED')  AS failed,
                COUNT(*) FILTER(WHERE status='UNPROCESSED')       AS unprocessed
            FROM policy_admin_queue
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return {"total":0,"pushed":0,"pending":0,"failed":0,"unprocessed":0}
        if hasattr(row, "keys"):
            return dict(row)
        return {"total":row[0],"pushed":row[1],"pending":row[2],"failed":row[3],"unprocessed":row[4]}
    except Exception:
        return {"total":0,"pushed":0,"pending":0,"failed":0,"unprocessed":0}
    finally:
        release(conn)


@router.get("/output-interface/failed")
def output_interface_failed(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, applicant_ref, applicant_name, outcome,
                   push_attempts, push_last_error, push_last_at, created_at
            FROM policy_admin_queue
            WHERE push_status='PUSH_FAILED'
            ORDER BY push_last_at DESC NULLS LAST LIMIT 30
        """)
        rows = cur.fetchall()
        cur.close()
        cols = ["id","applicant_ref","applicant_name","outcome","push_attempts","push_last_error","push_last_at","created_at"]
        result = []
        for r in rows:
            d = dict(zip(cols, r)) if not hasattr(r, "keys") else dict(r)
            for k in ("push_last_at","created_at"):
                if d.get(k): d[k] = str(d[k])[:16]
            result.append(d)
        return result
    except Exception:
        return []
    finally:
        release(conn)


@router.get("/output-interface/preview")
def output_interface_preview(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT applicant_ref, applicant_name, product_code,
                   outcome, decision_date, push_status, source, created_at
            FROM policy_admin_queue
            WHERE status='UNPROCESSED'
            ORDER BY created_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()
        cols = ["applicant_ref","applicant_name","product_code","outcome","decision_date","push_status","source","created_at"]
        result = []
        for r in rows:
            d = dict(zip(cols, r)) if not hasattr(r, "keys") else dict(r)
            for k in ("decision_date","created_at"):
                if d.get(k): d[k] = str(d[k])[:16]
            result.append(d)
        return result
    except Exception:
        return []
    finally:
        release(conn)


@router.post("/output-interface/test")
def test_output_interface(body: dict, current: CurrentUser):
    conn, release = _get_db()
    try:
        cfg = _load_oic(conn)
        release(conn)
        url = cfg.get("webhook_url", "").strip()
        if not url:
            raise HTTPException(400, "No webhook URL configured")
        import requests as _req
        method    = cfg.get("webhook_method", "POST").upper()
        auth_type = cfg.get("webhook_auth_type", "NONE")
        auth_val  = cfg.get("webhook_auth_value", "")
        timeout   = int(cfg.get("webhook_timeout", 15))
        key_hdr   = cfg.get("webhook_api_key_header", "X-API-Key")
        envelope  = cfg.get("webhook_envelope_key", "").strip()
        custom_h  = {}
        try: custom_h = json.loads(cfg.get("webhook_custom_headers", "{}") or "{}")
        except: pass
        headers = {"Content-Type": "application/json", **custom_h}
        if auth_type == "BEARER":
            headers["Authorization"] = f"Bearer {auth_val}"
        elif auth_type == "API_KEY":
            headers[key_hdr] = auth_val
        elif auth_type == "BASIC":
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(auth_val.encode()).decode()
        payload = body if not envelope else {envelope: body}
        fn = _req.post if method == "POST" else _req.put
        resp = fn(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code < 400:
            return {"status": "ok", "http_status": resp.status_code}
        raise HTTPException(400, f"Webhook returned {resp.status_code}: {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Test failed: {e}")


@router.post("/output-interface/push")
def push_to_pas(current: CurrentUser):
    conn, release = _get_db()
    try:
        cfg = _load_oic(conn)
        url = cfg.get("webhook_url", "").strip()
        if not url:
            raise HTTPException(400, "No webhook URL configured")

        import requests as _req
        method    = cfg.get("webhook_method", "POST").upper()
        auth_type = cfg.get("webhook_auth_type", "NONE")
        auth_val  = cfg.get("webhook_auth_value", "")
        timeout   = int(cfg.get("webhook_timeout", 15))
        key_hdr   = cfg.get("webhook_api_key_header", "X-API-Key")
        envelope  = cfg.get("webhook_envelope_key", "").strip()
        max_retry = int(cfg.get("webhook_max_retries", 3))
        try: field_map = json.loads(cfg.get("webhook_field_map", "{}") or "{}")
        except: field_map = {}
        custom_h = {}
        try: custom_h = json.loads(cfg.get("webhook_custom_headers", "{}") or "{}")
        except: pass
        headers = {"Content-Type": "application/json", **custom_h}
        if auth_type == "BEARER":  headers["Authorization"] = f"Bearer {auth_val}"
        elif auth_type == "API_KEY": headers[key_hdr] = auth_val
        elif auth_type == "BASIC":
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(auth_val.encode()).decode()

        cur = conn.cursor()
        cur.execute("""
            SELECT id, applicant_ref, applicant_name, applicant_email,
                   case_id, job_id, product_code, face_amount, age, gender, state,
                   outcome, risk_class, net_debit_points, approved_premium,
                   effective_date, expire_date, decision_date, reason, source
            FROM policy_admin_queue
            WHERE push_status IN ('PENDING','PUSH_FAILED') AND push_attempts < %s
            ORDER BY created_at LIMIT 200
        """, (max_retry,))
        records = cur.fetchall()
        cols = ["id","applicant_ref","applicant_name","applicant_email","case_id","job_id",
                "product_code","face_amount","age","gender","state","outcome","risk_class",
                "net_debit_points","approved_premium","effective_date","expire_date",
                "decision_date","reason","source"]

        pushed = 0; failed = 0
        for row in records:
            rec = dict(zip(cols, row)) if not hasattr(row, "keys") else dict(row)
            rid = rec.pop("id")
            # Apply field mapping
            mapped = {field_map.get(k, k): v for k, v in rec.items()}
            payload = {envelope: mapped} if envelope else mapped
            fn = _req.post if method == "POST" else _req.put
            try:
                resp = fn(url, json=payload, headers=headers, timeout=timeout)
                ok = resp.status_code < 400
            except Exception as e:
                ok = False; err = str(e)
            if ok:
                cur.execute("""
                    UPDATE policy_admin_queue SET push_status='PUSHED', status='PROCESSED',
                        push_attempts=push_attempts+1, push_last_at=now(), push_last_error=NULL,
                        processed_at=now()
                    WHERE id=%s
                """, (rid,)); pushed += 1
            else:
                err = resp.text[:500] if ok is False and 'resp' in dir() else err
                cur.execute("""
                    UPDATE policy_admin_queue SET push_status='PUSH_FAILED',
                        push_attempts=push_attempts+1, push_last_at=now(), push_last_error=%s
                    WHERE id=%s
                """, (err[:500], rid)); failed += 1
        conn.commit(); cur.close()
        return {"pushed": pushed, "failed": failed}
    finally:
        release(conn)


@router.post("/output-interface/push/{record_id}")
def repush_single(record_id: int, current: CurrentUser):
    conn, release = _get_db()
    try:
        cfg = _load_oic(conn)
        url = cfg.get("webhook_url", "").strip()
        if not url:
            raise HTTPException(400, "No webhook URL configured")
        import requests as _req
        method   = cfg.get("webhook_method", "POST").upper()
        auth_type= cfg.get("webhook_auth_type", "NONE")
        auth_val = cfg.get("webhook_auth_value", "")
        timeout  = int(cfg.get("webhook_timeout", 15))
        key_hdr  = cfg.get("webhook_api_key_header", "X-API-Key")
        envelope = cfg.get("webhook_envelope_key", "").strip()
        try: field_map = json.loads(cfg.get("webhook_field_map", "{}") or "{}")
        except: field_map = {}
        custom_h = {}
        try: custom_h = json.loads(cfg.get("webhook_custom_headers", "{}") or "{}")
        except: pass
        headers = {"Content-Type": "application/json", **custom_h}
        if auth_type == "BEARER":  headers["Authorization"] = f"Bearer {auth_val}"
        elif auth_type == "API_KEY": headers[key_hdr] = auth_val
        elif auth_type == "BASIC":
            import base64
            headers["Authorization"] = "Basic " + base64.b64encode(auth_val.encode()).decode()

        cur = conn.cursor()
        cur.execute("""
            SELECT applicant_ref, applicant_name, applicant_email, case_id, job_id,
                   product_code, face_amount, age, gender, state, outcome, risk_class,
                   net_debit_points, approved_premium, effective_date, expire_date,
                   decision_date, reason, source
            FROM policy_admin_queue WHERE id=%s
        """, (record_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Record not found")
        cols = ["applicant_ref","applicant_name","applicant_email","case_id","job_id",
                "product_code","face_amount","age","gender","state","outcome","risk_class",
                "net_debit_points","approved_premium","effective_date","expire_date",
                "decision_date","reason","source"]
        rec = dict(zip(cols, row)) if not hasattr(row, "keys") else dict(row)
        mapped  = {field_map.get(k, k): v for k, v in rec.items()}
        payload = {envelope: mapped} if envelope else mapped
        fn = _req.post if method == "POST" else _req.put
        try:
            resp = fn(url, json=payload, headers=headers, timeout=timeout)
            ok = resp.status_code < 400
            err = None if ok else resp.text[:500]
        except Exception as e:
            ok = False; err = str(e)
        if ok:
            cur.execute("""
                UPDATE policy_admin_queue SET push_status='PUSHED', status='PROCESSED',
                    push_attempts=push_attempts+1, push_last_at=now(), push_last_error=NULL, processed_at=now()
                WHERE id=%s
            """, (record_id,))
        else:
            cur.execute("""
                UPDATE policy_admin_queue SET push_status='PUSH_FAILED',
                    push_attempts=push_attempts+1, push_last_at=now(), push_last_error=%s
                WHERE id=%s
            """, (err, record_id))
        conn.commit(); cur.close()
        if ok:
            return {"status": "pushed", "http_status": resp.status_code}
        raise HTTPException(400, f"Push failed: {err}")
    finally:
        release(conn)


@router.post("/output-interface/extract")
def extract_to_file(body: dict, current: CurrentUser):
    """Generate CSV or Excel extract of unprocessed records."""
    conn, release = _get_db()
    try:
        cfg         = _load_oic(conn)
        file_format = body.get("file_format", cfg.get("file_format", "csv"))
        delim       = body.get("delimiter",   cfg.get("delimiter",   ","))
        fn_prefix   = body.get("filename_prefix", cfg.get("filename_prefix", "policy_admin"))
        try: cols_sel = json.loads(cfg.get("columns", "[]") or "[]")
        except: cols_sel = []
        if not cols_sel:
            cols_sel = ["applicant_ref","applicant_name","product_code","outcome",
                        "risk_class","face_amount","approved_premium","decision_date","source"]
        try: field_map = json.loads(cfg.get("webhook_field_map", "{}") or "{}")
        except: field_map = {}

        cur = conn.cursor()
        cur.execute(f"""
            SELECT {', '.join(cols_sel)}
            FROM policy_admin_queue WHERE status='UNPROCESSED'
            ORDER BY created_at DESC LIMIT 10000
        """)
        rows = cur.fetchall()

        # Mark as processed
        cur.execute("UPDATE policy_admin_queue SET status='PROCESSED', processed_at=now() WHERE status='UNPROCESSED'")
        conn.commit()
        cur.close()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        headers_out = [field_map.get(c, c) for c in cols_sel]

        if file_format == "excel":
            try:
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.append(headers_out)
                for row in rows:
                    ws.append([str(v) if v is not None else "" for v in row])
                buf = io.BytesIO()
                wb.save(buf)
                buf.seek(0)
                filename = f"{fn_prefix}_{ts}.xlsx"
                return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
            except ImportError:
                raise HTTPException(400, "openpyxl not installed — pip install openpyxl")
        else:
            buf = io.StringIO()
            writer = csv.writer(buf, delimiter=delim)
            writer.writerow(headers_out)
            for row in rows:
                writer.writerow([str(v) if v is not None else "" for v in row])
            buf.seek(0)
            filename = f"{fn_prefix}_{ts}.csv"
            return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    finally:
        release(conn)
