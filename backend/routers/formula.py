"""
routers/formula.py
──────────────────
System-level Business Formula Engine (V025):
  * uw_formula / uw_formula_step — formulas usable by ANY formula_type
    (PREMIUM, FCL, SAR, MEDICAL, ...). product_code NULL = system-level
    (shared across products); non-NULL = product-specific override.
  * uw_reference_table / uw_reference_table_row — reusable BAND/EXACT
    lookups referenced by formula steps (FCL age/salary/member-count/
    employer scales, ...).

This is the generalization of the product-scoped Premium Formula Builder:
the same engine now serves FCL, SAR and (future) medical / RI formulas.
"""
from __future__ import annotations

import psycopg2.extras

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deps import CurrentUser

router = APIRouter(prefix="/formulas", tags=["Formula Engine"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


def _row(r) -> dict:
    return dict(r) if r else {}


def _log(conn, current, entity_type: str, entity_id: str, event_type: str,
         after: dict | None = None, before: dict | None = None,
         entity_ref: str | None = None) -> None:
    """Record a CONFIG change in the audit trail. Silent on failure."""
    try:
        from services.audit import log_event
        log_event(
            conn, event_category="CONFIG", event_type=event_type,
            actor_username=current.username, actor_role=current.role,
            tenant_id=str(current.tenant_id),
            entity_type=entity_type, entity_id=entity_id,
            entity_ref=entity_ref or entity_id,
            before_state=before, after_state=after,
        )
    except Exception:
        pass


class FormulaIn(BaseModel):
    formula_name:  str
    description:   str | None = None
    formula_type:  str = "FCL"           # PREMIUM / FCL / SAR / MEDICAL / FINANCIAL / REINSURANCE / DECISION
    product_code:  str | None = None      # NULL = system-level (shared)
    is_active:     bool = True
    effective_date: str | None = None
    expiry_date:   str | None = None


class StepIn(BaseModel):
    seq_no:             int
    operator:           str                # +  -  *  /  %  |  IF  ELSE  ENDIF
    factor:             float = 1.0
    parameter_type:     str                # USER_VALUE / AGE / ANNUAL_SALARY / SCHEME_MEMBER_COUNT / EMPLOYER_CODE / REFERENCE_TABLE
    user_value:         float | None = None
    user_label:         str | None = None  # INPUT field key for REFERENCE_TABLE / USER_LABEL
    scale_id:           str | None = None
    reference_table_id: str | None = None
    condition:          dict | None = None  # Phase B — typed condition tree on IF steps


class ReferenceTableIn(BaseModel):
    table_code: str
    table_name: str
    description: str | None = None
    key_field:  str | None = None   # applicant field this table is keyed on (age, annual_salary, ...)
    is_active:  bool = True


class ReferenceTableRowIn(BaseModel):
    match_type:   str = "BAND"             # BAND / EXACT
    band_min:     float | None = None
    band_max:     float | None = None
    match_value:  str | None = None
    output_value: float = 0
    is_active:    bool = True
    sort_order:   int = 0


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------

@router.get("")
def list_formulas(formula_type: str | None = None,
                  product_code: str | None = None,
                  current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sql = """
            SELECT id::text, formula_name, description, formula_type, product_code,
                   is_active, effective_date, expiry_date, version,
                   (SELECT COUNT(*) FROM uw_formula_step s WHERE s.formula_id = f.id) AS step_count
            FROM uw_formula f
            WHERE tenant_id = %s::uuid
        """
        params: list = [current.tenant_id]
        if formula_type:
            sql += " AND formula_type = %s"
            params.append(formula_type)
        if product_code is not None:
            sql += " AND (product_code = %s OR product_code IS NULL)"
            params.append(product_code)
        sql += " ORDER BY formula_type, formula_name"
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.post("", status_code=201)
def create_formula(body: FormulaIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM uw_formula "
            "WHERE formula_name = %s AND tenant_id = %s::uuid",
            (body.formula_name, current.tenant_id))
        r = cur.fetchone()
        version = int((r["version"] if hasattr(r, "keys") else r[0]) or 0) + 1
        cur.execute("""
            INSERT INTO uw_formula
                (tenant_id, formula_name, description, formula_type, product_code,
                 is_active, effective_date, expiry_date, version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, COALESCE(%s::date, CURRENT_DATE), %s, %s, %s, %s)
            RETURNING id
        """, (
            current.tenant_id, body.formula_name, body.description, body.formula_type,
            body.product_code, body.is_active, body.effective_date, body.expiry_date,
            version, current.username, current.username,
        ))
        row = cur.fetchone()
        conn.commit()
        fid = dict(row)["id"] if hasattr(row, "keys") else row[0]
        _log(conn, current, "uw_formula", str(fid), "formula.create",
             after={"formula_name": body.formula_name, "formula_type": body.formula_type,
                    "product_code": body.product_code, "is_active": body.is_active})
        return {"ok": True, "id": fid}
    finally:
        release(conn)


@router.get("/reference-tables")
def list_reference_tables(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, table_code, table_name, description, key_field, is_active,
                   (SELECT COUNT(*) FROM uw_reference_table_row r WHERE r.reference_table_id = t.id) AS row_count
            FROM uw_reference_table t
            WHERE tenant_id = %s::uuid ORDER BY table_code
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.get("/user-labels")
def list_formula_user_labels(product_code: str | None = None,
                             current: CurrentUser = CurrentUser):
    """User labels for the formula builder dropdown.

    User labels live at tenant level (system_user_label). The label set a
    product "knows" is derived from the labels its active formulas already
    reference. Every label carries `used_by_product` so the UI can prefer
    product-associated labels but fall back to the full list (a fresh
    product/formula may legitimately introduce a label no formula uses yet).
    """
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT label_key, label_name, data_type, default_value, prefix, suffix, description
            FROM system_user_label
            WHERE tenant_id = %s::uuid
              AND is_active = true
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY sort_order, label_key
        """, (current.tenant_id,))
        labels = [dict(r) for r in cur.fetchall()]
        used: set = set()
        if product_code:
            cur.execute("""
                SELECT DISTINCT s.user_label
                FROM uw_formula_step s
                JOIN uw_formula f ON f.id = s.formula_id
                WHERE f.product_code = %s
                  AND s.parameter_type = 'USER_LABEL'
                  AND s.user_label IS NOT NULL
            """, (product_code.upper(),))
            used = {r["user_label"] for r in cur.fetchall()}
        for l in labels:
            l["used_by_product"] = l["label_key"] in used
        return labels
    finally:
        release(conn)


@router.get("/{formula_id}")
def get_formula(formula_id: str, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, formula_name, description, formula_type, product_code,
                   is_active, effective_date, expiry_date
            FROM uw_formula WHERE id = %s::uuid AND tenant_id = %s::uuid
        """, (formula_id, current.tenant_id))
        header = _row(cur.fetchone())
        if not header:
            raise HTTPException(404, "Formula not found")
        cur.execute("""
            SELECT id::text, seq_no, description, operator, factor,
                   parameter_type, user_value, user_label, scale_id::text, reference_table_id::text,
                   condition
            FROM uw_formula_step
            WHERE formula_id = %s::uuid ORDER BY seq_no
        """, (formula_id,))
        header["steps"] = [dict(r) for r in cur.fetchall()]
        return header
    finally:
        release(conn)


@router.put("/{formula_id}")
def update_formula(formula_id: str, body: FormulaIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT formula_name, formula_type, product_code, is_active
            FROM uw_formula WHERE id = %s::uuid AND tenant_id = %s::uuid
        """, (formula_id, current.tenant_id))
        before = _row(cur.fetchone())
        cur.execute("""
            UPDATE uw_formula SET
                formula_name = %s, description = %s, formula_type = %s, product_code = %s,
                is_active = %s, effective_date = COALESCE(%s::date, effective_date), expiry_date = %s,
                version = version + 1,
                updated_by = %s, updated_at = now()
            WHERE id = %s::uuid AND tenant_id = %s::uuid
        """, (
            body.formula_name, body.description, body.formula_type, body.product_code,
            body.is_active, body.effective_date, body.expiry_date,
            current.username, formula_id, current.tenant_id,
        ))
        conn.commit()
        _log(conn, current, "uw_formula", formula_id, "formula.update",
             before=before,
             after={"formula_name": body.formula_name, "formula_type": body.formula_type,
                    "product_code": body.product_code, "is_active": body.is_active})
        return {"ok": True}
    finally:
        release(conn)


@router.delete("/{formula_id}")
def delete_formula(formula_id: str, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT formula_name, formula_type FROM uw_formula
            WHERE id = %s::uuid AND tenant_id = %s::uuid
        """, (formula_id, current.tenant_id))
        before = _row(cur.fetchone())
        cur.execute("DELETE FROM uw_formula WHERE id = %s::uuid AND tenant_id = %s::uuid",
                    (formula_id, current.tenant_id))
        conn.commit()
        _log(conn, current, "uw_formula", formula_id, "formula.delete",
             before=before)
        return {"ok": True}
    finally:
        release(conn)


@router.post("/{formula_id}/steps", status_code=201)
def add_step(formula_id: str, body: StepIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO uw_formula_step
                (formula_id, seq_no, description, operator, factor,
                 parameter_type, user_value, user_label, scale_id, reference_table_id,
                 condition)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s::uuid, %s::jsonb)
            ON CONFLICT (formula_id, seq_no) DO UPDATE SET
                operator = EXCLUDED.operator, factor = EXCLUDED.factor,
                parameter_type = EXCLUDED.parameter_type, user_value = EXCLUDED.user_value,
                user_label = EXCLUDED.user_label, scale_id = EXCLUDED.scale_id,
                reference_table_id = EXCLUDED.reference_table_id,
                condition = EXCLUDED.condition
        """, (
            formula_id, body.seq_no, f"Step {body.seq_no}", body.operator, body.factor,
            body.parameter_type, body.user_value, body.user_label,
            body.scale_id, body.reference_table_id,
            psycopg2.extras.Json(body.condition) if body.condition else None,
        ))
        conn.commit()
        _log(conn, current, "uw_formula_step", f"{formula_id}:{body.seq_no}",
             "formula.step.upsert",
             after={"seq_no": body.seq_no, "operator": body.operator,
                    "parameter_type": body.parameter_type, "factor": body.factor,
                    "condition": body.condition})
        return {"ok": True}
    finally:
        release(conn)


@router.delete("/{formula_id}/steps/{step_id}")
def delete_step(formula_id: str, step_id: str, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT seq_no, operator FROM uw_formula_step WHERE id = %s::uuid",
            (step_id,))
        before = _row(cur.fetchone())
        cur.execute(
            "DELETE FROM uw_formula_step WHERE id = %s::uuid AND formula_id = %s::uuid",
            (step_id, formula_id))
        conn.commit()
        _log(conn, current, "uw_formula_step", str(step_id), "formula.step.delete",
             before=before, entity_ref=str(formula_id))
        return {"ok": True}
    finally:
        release(conn)


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

@router.post("/reference-tables", status_code=201)
def create_reference_table(body: ReferenceTableIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO uw_reference_table (tenant_id, table_code, table_name, description, key_field, is_active, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, table_code) DO UPDATE SET
                table_name = EXCLUDED.table_name, description = EXCLUDED.description,
                key_field = EXCLUDED.key_field, is_active = EXCLUDED.is_active,
                updated_by = EXCLUDED.updated_by, updated_at = now()
            RETURNING id
        """, (
            current.tenant_id, body.table_code, body.table_name, body.description,
            body.key_field, body.is_active, current.username, current.username,
        ))
        row = cur.fetchone()
        conn.commit()
        tid = dict(row)["id"] if hasattr(row, "keys") else row[0]
        return {"ok": True, "id": tid}
    finally:
        release(conn)


@router.get("/reference-tables/{ref_table_id}")
def get_reference_table(ref_table_id: str, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, table_code, table_name, description, key_field, is_active
            FROM uw_reference_table WHERE id = %s::uuid AND tenant_id = %s::uuid
        """, (ref_table_id, current.tenant_id))
        header = _row(cur.fetchone())
        if not header:
            raise HTTPException(404, "Reference table not found")
        cur.execute("""
            SELECT id::text, match_type, band_min, band_max, match_value,
                   output_value, is_active, sort_order
            FROM uw_reference_table_row
            WHERE reference_table_id = %s::uuid ORDER BY sort_order, band_min NULLS LAST
        """, (ref_table_id,))
        header["rows"] = [dict(r) for r in cur.fetchall()]
        return header
    finally:
        release(conn)


@router.post("/reference-tables/{ref_table_id}/rows", status_code=201)
def add_reference_row(ref_table_id: str, body: ReferenceTableRowIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO uw_reference_table_row
                (reference_table_id, match_type, band_min, band_max, match_value,
                 output_value, is_active, sort_order)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
        """, (
            ref_table_id, body.match_type, body.band_min, body.band_max, body.match_value,
            body.output_value, body.is_active, body.sort_order,
        ))
        conn.commit()
        return {"ok": True}
    finally:
        release(conn)


@router.delete("/reference-tables/{ref_table_id}/rows/{row_id}")
def delete_reference_row(ref_table_id: str, row_id: str, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM uw_reference_table_row WHERE id = %s::uuid AND reference_table_id = %s::uuid",
            (row_id, ref_table_id))
        conn.commit()
        return {"ok": True}
    finally:
        release(conn)
