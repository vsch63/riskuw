"""
backend/routers/reinsurance.py
────────────────────────────────
GET  /reinsurance/stats                  — summary metrics
GET  /reinsurance/cases                  — RI-flagged cases with cession status
GET  /reinsurance/reinsurers             — list reinsurers
POST /reinsurance/reinsurers             — add reinsurer
PUT  /reinsurance/reinsurers/{id}        — update reinsurer
GET  /reinsurance/cessions               — cession history
POST /reinsurance/cessions               — create/submit cession
PATCH /reinsurance/cessions/{id}         — update cession (submit / record decision)
POST /reinsurance/slips                  — record slip generation

Tables: ri_reinsurer · ri_cession · uw_case · application · uw_decision · applicant_master
"""
from __future__ import annotations
import secrets
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from deps import CurrentUser

router = APIRouter(prefix="/reinsurance", tags=["reinsurance"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


def _str(v) -> str:
    return str(v)[:10] if v else ""


# ── Schemas ────────────────────────────────────────────────────────────────────

class ReinsurerCreate(BaseModel):
    reinsurer_name:        str
    reinsurer_code:        str
    treaty_code:           Optional[str] = None
    treaty_type:           str = "FACULTATIVE"
    contact_email:         Optional[str] = None
    retention_limit:       Optional[float] = None
    currency:              str = "INR"
    is_active:             bool = True
    notes:                 Optional[str] = None
    product_codes:         Optional[List[str]] = None
    treaty_effective_date: Optional[str] = None
    treaty_expiry_date:    Optional[str] = None


class ReinsurerUpdate(BaseModel):
    reinsurer_name:        Optional[str] = None
    reinsurer_code:        Optional[str] = None
    treaty_code:           Optional[str] = None
    treaty_type:           Optional[str] = None
    contact_email:         Optional[str] = None
    retention_limit:       Optional[float] = None
    currency:              Optional[str] = None
    is_active:             Optional[bool] = None
    notes:                 Optional[str] = None
    product_codes:         Optional[List[str]] = None
    treaty_effective_date: Optional[str] = None
    treaty_expiry_date:    Optional[str] = None


class CessionCreate(BaseModel):
    case_id:                 str
    reinsurer_id:            str
    cession_type:            str = "FACULTATIVE"
    gross_face_amount:       float
    retention_amount:        float = 0
    ceded_amount:            float
    gross_premium:           float = 0
    ri_premium:              float = 0
    net_retained_premium:    float = 0
    status:                  str = "SUBMITTED"
    cession_effective_date:  Optional[str] = None
    cession_expiry_date:     Optional[str] = None
    notes:                   Optional[str] = None


class CessionPatch(BaseModel):
    status:               Optional[str] = None
    ri_decision:          Optional[str] = None
    ri_reference:         Optional[str] = None
    ri_modified_terms:    Optional[str] = None
    ri_decision_date:     Optional[str] = None
    submitted_at:         Optional[str] = None
    notes:                Optional[str] = None


class SlipRecord(BaseModel):
    case_id:                str
    reinsurer_id:           Optional[str] = None
    treaty:                 Optional[str] = None
    retention_amount:       float = 0
    ceded_amount:           float = 0
    ri_premium:             float = 0
    cession_effective_date: Optional[str] = None
    cession_expiry_date:    Optional[str] = None


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                                        AS total_flagged,
                COUNT(*) FILTER(WHERE ri.id IS NULL)                            AS pending_submission,
                COUNT(*) FILTER(WHERE ri.status='SUBMITTED')                    AS submitted,
                COUNT(*) FILTER(WHERE ri.status='DECISION_RECEIVED'
                                  AND ri.ri_decision='ACCEPTED')                AS accepted,
                COUNT(*) FILTER(WHERE ri.status='DECISION_RECEIVED'
                                  AND ri.ri_decision='DECLINED')                AS ri_declined,
                COALESCE(SUM(COALESCE(c.face_amount, 0)), 0)                   AS total_exposure,
                COALESCE(SUM(ri.ceded_amount), 0)                               AS total_ceded,
                COALESCE(SUM(ri.ri_premium), 0)                                 AS total_ri_prem
            FROM uw_case c
            LEFT JOIN ri_cession ri  ON ri.case_id = c.id::text
            WHERE COALESCE(c.reinsurance_required, FALSE) = TRUE
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return {"total_flagged":0,"pending_submission":0,"submitted":0,"accepted":0,"ri_declined":0,"total_exposure":0,"total_ceded":0,"total_ri_prem":0}
        d = dict(row)
        for k in ("total_exposure","total_ceded","total_ri_prem"):
            d[k] = float(d[k] or 0)
        return d
    except Exception as e:
        return {"total_flagged":0,"pending_submission":0,"submitted":0,"accepted":0,"ri_declined":0,"total_exposure":0,"total_ceded":0,"total_ri_prem":0,"_error":str(e)}
    finally:
        release(conn)




# ── Summary alias (backwards compat with old frontend) ────────────────────────

@router.get("/summary")
def get_summary(current: CurrentUser):
    return get_stats(current)

# ── RI Cases ───────────────────────────────────────────────────────────────────

@router.get("/cases")
def get_ri_cases(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        # Try full join first, fall back to simpler query if columns missing
        try:
            cur.execute("SELECT 1 FROM uw_decision LIMIT 0")
            has_uw_decision = True
        except Exception:
            conn.rollback()
            has_uw_decision = False
        cur.execute("""
            SELECT
                c.id::text                          AS case_id,
                c.case_number,
                c.status                            AS case_status,
                COALESCE(a.applicant_ref, '')       AS applicant_ref,
                COALESCE(c.face_amount, 0)          AS face_amount,
                COALESCE(c.product_code, '')        AS product_code,
                COALESCE(c.applicant_age, 0)        AS age,
                COALESCE(am.gender, '')             AS gender,
                COALESCE(d.outcome, '')             AS outcome,
                COALESCE(d.approved_premium, 0)     AS approved_premium,
                COALESCE(d.risk_class, '')          AS risk_class,
                COALESCE(d.table_rating, 0)         AS table_rating,
                COALESCE(d.flat_extra_per_thou, 0)  AS flat_extra,
                COALESCE(d.net_debit_points, 0)     AS net_debit_points,
                COALESCE(am.full_name, a.applicant_ref, '') AS applicant_name,
                ri.id::text                         AS cession_id,
                ri.cession_ref,
                COALESCE(ri.status, 'NOT_SUBMITTED') AS ri_status,
                ri.reinsurer_id::text,
                COALESCE(ri.ceded_amount, 0)        AS ceded_amount,
                COALESCE(ri.ri_premium, 0)          AS ri_premium,
                COALESCE(ri.ri_decision, '')        AS ri_decision,
                COALESCE(rr.reinsurer_name, '')     AS reinsurer_name
            FROM uw_case c
            LEFT JOIN application a       ON a.id = c.application_id
            LEFT JOIN uw_decision d       ON d.case_id = c.id::text
                                         AND d.is_final = TRUE
                                         AND COALESCE(d.is_deleted, FALSE) = FALSE
            LEFT JOIN applicant_master am ON am.applicant_ref = a.applicant_ref
            LEFT JOIN ri_cession ri       ON ri.case_id = c.id::text
            LEFT JOIN ri_reinsurer rr     ON rr.id = ri.reinsurer_id
            WHERE COALESCE(c.reinsurance_required, FALSE) = TRUE
            ORDER BY
                CASE WHEN ri.id IS NULL THEN 0 ELSE 1 END,
                c.face_amount DESC NULLS LAST
        """)
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = dict(r)
            d["case_id"]        = str(d.get("case_id") or "")
            d["cession_id"]     = str(d.get("cession_id") or "") if d.get("cession_id") else None
            d["face_amount"]    = float(d.get("face_amount") or 0)
            d["approved_premium"] = float(d.get("approved_premium") or 0)
            d["ceded_amount"]   = float(d.get("ceded_amount") or 0)
            d["ri_premium"]     = float(d.get("ri_premium") or 0)
            d["flat_extra"]     = float(d.get("flat_extra") or 0)
            d["table_rating"]   = int(d.get("table_rating") or 0)
            d["net_debit_points"] = int(d.get("net_debit_points") or 0)
            d["ri_status"]      = d.get("ri_status") or "NOT_SUBMITTED"
            d["ri_decision"]    = d.get("ri_decision") or ""
            d["reinsurer_name"] = d.get("reinsurer_name") or ""
            d["applicant_name"] = d.get("applicant_name") or ""
            result.append(d)
        return result
    except Exception as e:
        # If the detailed query fails, return basic case info
        try:
            conn.rollback()
            cur2 = conn.cursor()
            cur2.execute("""
                SELECT c.id::text, c.case_number, c.status,
                       COALESCE(c.face_amount, 0), COALESCE(c.product_code, ''),
                       COALESCE(c.applicant_age, 0),
                       ri.id::text, ri.cession_ref,
                       COALESCE(ri.status, 'NOT_SUBMITTED'),
                       ri.reinsurer_id::text,
                       COALESCE(ri.ceded_amount, 0), COALESCE(ri.ri_premium, 0),
                       COALESCE(ri.ri_decision, ''),
                       COALESCE(rr.reinsurer_name, '')
                FROM uw_case c
                LEFT JOIN ri_cession ri   ON ri.case_id = c.id::text
                LEFT JOIN ri_reinsurer rr ON rr.id = ri.reinsurer_id
                WHERE COALESCE(c.reinsurance_required, FALSE) = TRUE
                ORDER BY CASE WHEN ri.id IS NULL THEN 0 ELSE 1 END
            """)
            rows2 = cur2.fetchall()
            cur2.close()
            return [{
                "case_id": str(r[0] or ""), "case_number": r[1] or "",
                "case_status": r[2] or "", "applicant_ref": "",
                "face_amount": float(r[3] or 0), "product_code": r[4] or "",
                "age": int(r[5] or 0), "gender": "", "outcome": "",
                "approved_premium": 0, "risk_class": "", "table_rating": 0,
                "flat_extra": 0, "net_debit_points": 0, "applicant_name": "",
                "cession_id": str(r[6]) if r[6] else None,
                "cession_ref": r[7] or "", "ri_status": r[8] or "NOT_SUBMITTED",
                "reinsurer_id": str(r[9]) if r[9] else None,
                "ceded_amount": float(r[10] or 0), "ri_premium": float(r[11] or 0),
                "ri_decision": r[12] or "", "reinsurer_name": r[13] or "",
            } for r in rows2]
        except Exception as e2:
            raise HTTPException(500, f"Failed to load RI cases: {e} | fallback: {e2}")
    finally:
        release(conn)


# ── Reinsurers ─────────────────────────────────────────────────────────────────

@router.get("/reinsurers")
def list_reinsurers(active_only: bool = False, current: CurrentUser = None):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        q = """
            SELECT id::text, reinsurer_code AS code, reinsurer_name AS name,
                   treaty_code, treaty_type, contact_email AS email,
                   retention_limit, product_codes, currency,
                   is_active, notes,
                   treaty_effective_date, treaty_expiry_date
            FROM ri_reinsurer
        """
        if active_only:
            q += " WHERE is_active = TRUE"
        q += " ORDER BY reinsurer_name"
        cur.execute(q)
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = dict(r)
            d["retention_limit"] = float(d.get("retention_limit") or 0)
            d["is_active"]       = bool(d.get("is_active", True))
            d["product_codes"]   = list(d.get("product_codes") or [])
            d["treaty_effective_date"] = _str(d.get("treaty_effective_date"))
            d["treaty_expiry_date"]    = _str(d.get("treaty_expiry_date"))
            result.append(d)
        return result
    finally:
        release(conn)


@router.post("/reinsurers", status_code=201)
def add_reinsurer(body: ReinsurerCreate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ri_reinsurer
                (reinsurer_name, reinsurer_code, treaty_code, treaty_type,
                 contact_email, retention_limit, currency, is_active, notes,
                 product_codes, treaty_effective_date, treaty_expiry_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date,%s::date)
            RETURNING id::text, reinsurer_name
        """, (
            body.reinsurer_name.strip(),
            body.reinsurer_code.strip().upper(),
            body.treaty_code or None,
            body.treaty_type,
            body.contact_email or None,
            body.retention_limit or None,
            body.currency,
            body.is_active,
            body.notes or None,
            body.product_codes or None,
            body.treaty_effective_date or None,
            body.treaty_expiry_date or None,
        ))
        row = cur.fetchone()
        conn.commit(); cur.close()
        return {"status": "created", "id": row["id"], "name": row["reinsurer_name"]}
    finally:
        release(conn)


@router.put("/reinsurers/{rid}")
def update_reinsurer(rid: str, body: ReinsurerUpdate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")

    # Map frontend field names to DB column names
    col_map = {
        "reinsurer_name":        "reinsurer_name",
        "reinsurer_code":        "reinsurer_code",
        "treaty_code":           "treaty_code",
        "treaty_type":           "treaty_type",
        "contact_email":         "contact_email",
        "retention_limit":       "retention_limit",
        "currency":              "currency",
        "is_active":             "is_active",
        "notes":                 "notes",
        "product_codes":         "product_codes",
        "treaty_effective_date": "treaty_effective_date",
        "treaty_expiry_date":    "treaty_expiry_date",
    }
    sets  = ", ".join(f"{col_map[k]}=%s" for k in updates)
    vals  = list(updates.values())

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE ri_reinsurer SET {sets} WHERE id=%s::uuid RETURNING id::text",
            (*vals, rid)
        )
        row = cur.fetchone()
        conn.commit(); cur.close()
        if not row:
            raise HTTPException(404, "Reinsurer not found")
        return {"status": "updated", "id": rid}
    finally:
        release(conn)


# ── Cessions ───────────────────────────────────────────────────────────────────

@router.get("/cessions")
def list_cessions(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                ri.id::text             AS cession_id,
                ri.cession_ref,
                c.case_number,
                rr.reinsurer_name,
                ri.cession_type,
                ri.status,
                ri.ri_decision,
                ri.gross_face_amount,
                ri.ceded_amount,
                ri.gross_premium,
                ri.ri_premium,
                ri.net_retained_premium,
                ri.submitted_at,
                ri.ri_decision_date,
                ri.submitted_by,
                ri.ri_reference,
                ri.cession_effective_date,
                ri.cession_expiry_date
            FROM ri_cession ri
            LEFT JOIN uw_case c      ON c.id::text = ri.case_id
            LEFT JOIN ri_reinsurer rr ON rr.id = ri.reinsurer_id
            ORDER BY ri.created_at DESC
            LIMIT 200
        """)
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = dict(r)
            for k in ("gross_face_amount","ceded_amount","gross_premium","ri_premium","net_retained_premium"):
                d[k] = float(d.get(k) or 0)
            for k in ("submitted_at","ri_decision_date","cession_effective_date","cession_expiry_date"):
                if d.get(k): d[k] = str(d[k])[:16]
            result.append(d)
        return result
    except Exception as e:
        raise HTTPException(500, f"Failed to load cessions: {e}")
    finally:
        release(conn)


@router.post("/cessions", status_code=201)
def create_cession(body: CessionCreate, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Get application_id from case
        cur.execute("SELECT application_id FROM uw_case WHERE id=%s::uuid", (body.case_id,))
        row = cur.fetchone()
        app_id = str(row["application_id"]) if row else None

        # Get treaty_code from reinsurer
        cur.execute("SELECT treaty_code FROM ri_reinsurer WHERE id=%s::uuid", (body.reinsurer_id,))
        ri_row = cur.fetchone()
        treaty = ri_row["treaty_code"] if ri_row else None

        # Generate cession ref
        cession_ref = f"RI-{date.today().strftime('%Y%m%d')}-{secrets.randbelow(9000)+1000}"

        cur.execute("""
            INSERT INTO ri_cession (
                case_id, application_id, reinsurer_id,
                cession_ref, treaty_code, cession_type,
                gross_face_amount, retention_amount, ceded_amount,
                gross_premium, ri_premium, net_retained_premium,
                status, submitted_at, submitted_by,
                cession_effective_date, cession_expiry_date, notes,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s::uuid,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, NOW(), %s,
                %s::date, %s::date, %s,
                NOW(), NOW()
            )
            RETURNING id::text, cession_ref
        """, (
            body.case_id, app_id, body.reinsurer_id,
            cession_ref, treaty, body.cession_type,
            body.gross_face_amount, body.retention_amount, body.ceded_amount,
            body.gross_premium, body.ri_premium, body.net_retained_premium,
            body.status, current.username,
            body.cession_effective_date or None,
            body.cession_expiry_date or None,
            body.notes,
        ))
        row = cur.fetchone()
        conn.commit(); cur.close()
        return {"status": "created", "id": row["id"], "cession_ref": row["cession_ref"]}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Failed to create cession: {e}")
    finally:
        release(conn)


@router.patch("/cessions/{cid}")
def patch_cession(cid: str, body: CessionPatch, current: CurrentUser):
    updates: dict = {}

    if body.status == "SUBMITTED":
        updates["status"]       = "SUBMITTED"
        updates["submitted_at"] = body.submitted_at or "NOW()"
        if body.notes:
            updates["_notes_append"] = body.notes

    elif body.ri_decision:
        updates["ri_decision"]          = body.ri_decision
        updates["ri_reference"]         = body.ri_reference or ""
        updates["ri_modified_terms"]    = body.ri_modified_terms
        updates["ri_decision_date"]     = body.ri_decision_date or str(date.today())
        updates["status"]               = "DECISION_RECEIVED"
        updates["decision_received_at"] = "NOW()"

    else:
        # Generic patch
        for k, v in body.model_dump(exclude_none=True).items():
            updates[k] = v

    if not updates:
        raise HTTPException(400, "Nothing to update")

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Handle notes append separately
        notes_append = updates.pop("_notes_append", None)
        if notes_append:
            cur.execute(
                "UPDATE ri_cession SET notes = COALESCE(notes || ' | ', '') || %s WHERE id=%s::uuid",
                (notes_append, cid)
            )

        # Remove pseudo-values
        now_fields = {k for k, v in updates.items() if v == "NOW()"}
        plain = {k: v for k, v in updates.items() if k not in now_fields}

        set_parts = []
        vals      = []
        for k, v in plain.items():
            set_parts.append(f"{k}=%s")
            vals.append(v)
        for k in now_fields:
            set_parts.append(f"{k}=NOW()")

        if set_parts:
            set_parts.append("updated_at=NOW()")
            cur.execute(
                f"UPDATE ri_cession SET {', '.join(set_parts)} WHERE id=%s::uuid RETURNING id::text",
                (*vals, cid)
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise HTTPException(404, "Cession not found")

        conn.commit(); cur.close()
        return {"status": "updated", "id": cid}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Failed to update cession: {e}")
    finally:
        release(conn)


# ── Slip generation record ─────────────────────────────────────────────────────

@router.post("/slips")
def record_slip(body: SlipRecord, current: CurrentUser):
    """Record that a slip was generated — creates or updates cession to SLIP_GENERATED."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Check if cession already exists for this case
        cur.execute(
            "SELECT id::text FROM ri_cession WHERE case_id=%s ORDER BY created_at DESC LIMIT 1",
            (body.case_id,)
        )
        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE ri_cession
                SET slip_generated_at = NOW(),
                    retention_amount  = %s,
                    ceded_amount      = %s,
                    ri_premium        = %s,
                    cession_effective_date = %s::date,
                    cession_expiry_date    = %s::date,
                    updated_at        = NOW()
                WHERE id = %s::uuid
            """, (
                body.retention_amount, body.ceded_amount, body.ri_premium,
                body.cession_effective_date or None,
                body.cession_expiry_date or None,
                existing["id"],
            ))
        else:
            # Create a new SLIP_GENERATED cession
            cession_ref = f"RI-{date.today().strftime('%Y%m%d')}-{secrets.randbelow(9000)+1000}"
            cur.execute("""
                INSERT INTO ri_cession (
                    case_id, reinsurer_id, cession_ref, cession_type,
                    gross_face_amount, retention_amount, ceded_amount,
                    ri_premium, net_retained_premium,
                    status, slip_generated_at, submitted_by,
                    cession_effective_date, cession_expiry_date,
                    created_at, updated_at
                ) VALUES (
                    %s, %s::uuid, %s, 'FACULTATIVE',
                    %s, %s, %s, %s, %s,
                    'SLIP_GENERATED', NOW(), %s,
                    %s::date, %s::date,
                    NOW(), NOW()
                )
            """, (
                body.case_id,
                body.reinsurer_id or None,
                cession_ref,
                body.ceded_amount + body.retention_amount,  # gross = ceded + retention
                body.retention_amount, body.ceded_amount,
                body.ri_premium, 0,
                current.username,
                body.cession_effective_date or None,
                body.cession_expiry_date or None,
            ))

        conn.commit(); cur.close()
        return {"status": "ok"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Failed to record slip: {e}")
    finally:
        release(conn)
