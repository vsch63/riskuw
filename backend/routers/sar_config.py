"""
routers/sar_config.py
─────────────────────
SAR configuration management (Sum-at-Risk framework):
  * UW_BENEFIT_MASTER        — per-benefit SAR config (+ risk-group map)
  * UW_RISK_GROUP            — actuarial aggregation buckets
  * UW_EXPOSURE_GROUP        — underwriting-treatment buckets
  * UW_AGGREGATION_RULE      — per (risk_group, exposure_group, product) method
  * UW_FCL_CONFIG            — Free Cover Limit rules
  * UW_NML_CONFIG            — Non-Medical Limit bands

All endpoints are tenant-scoped (CurrentUser.tenant_id). Config changes take
effect immediately for subsequent proposal evaluations.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deps import CurrentUser

router = APIRouter(prefix="/sar-config", tags=["SAR Config"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


def _row(r) -> dict:
    return dict(r) if r else {}


# Tables that support append-versioning (every config save = a new row).
# Keys are the natural-identity columns used to compute the next version.
_VERSIONED_TABLES = {
    "uw_benefit_master":         ("tenant_id", "benefit_code"),
    "uw_risk_group":             ("tenant_id", "group_code"),
    "uw_exposure_group":         ("tenant_id", "exposure_code"),
    "uw_aggregation_rule":       ("tenant_id", "risk_group_id", "product_code", "exposure_group"),
    "uw_fcl_config":             ("tenant_id", "product_code", "scheme_id", "exposure_group"),
    "uw_nml_config":             ("tenant_id", "product_code", "age_min", "age_max", "sar_min", "sar_max"),
    "uw_formula":                ("formula_name",),
    "uw_medical_standard":       ("product_code",),
    "uw_medical_standard_rule":  ("medical_standard_id",),
    "uw_medical_standard_range": ("medical_standard_id",),
}


def _next_version(cur, table: str, identity: dict) -> int:
    """Compute the next version for an append-version config row.

    identity maps the table's natural-identity columns to their values,
    e.g. {"tenant_id": t, "benefit_code": "LIFE"}.
    """
    cols = _VERSIONED_TABLES.get(table, ("id",))
    if set(cols) == {"id"}:
        # No natural key → single row per entity; use max version overall
        cur.execute(f"SELECT COALESCE(MAX(version), 0) AS version FROM {table}")
        r = cur.fetchone()
        return int((r["version"] if hasattr(r, "keys") else r[0]) or 0) + 1

    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in cols)
    params = [identity.get(c) for c in cols]
    cur.execute(f"SELECT COALESCE(MAX(version), 0) AS version FROM {table} WHERE {where}", params)
    r = cur.fetchone()
    return int((r["version"] if hasattr(r, "keys") else r[0]) or 0) + 1


# Tables that carry effective/expiry dates → supersede sets expiry_date.
# Tables without dates (reference data) → supersede deactivates old versions.
_EXPIRY_DATED = {
    "uw_benefit_master", "uw_aggregation_rule", "uw_fcl_config", "uw_nml_config",
}


def _supersede_previous(cur, table: str, identity: dict, new_version: int, new_effective) -> None:
    """End the previously-active version when a new one is saved.

    Saving a new version supersedes the prior one: tables with effective-dating
    get their expiry_date set to the day before the new effective date (a
    future-dated change leaves the current version active until it takes
    effect — scheduling). Reference tables without dates are simply
    deactivated.
    """
    cols = _VERSIONED_TABLES.get(table, ("id",))
    if set(cols) == {"id"}:
        return  # no natural key → nothing to supersede
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in cols)
    params = [identity.get(c) for c in cols] + [new_version]

    if table in _EXPIRY_DATED:
        # None → COALESCE(%s::date, CURRENT_DATE) resolves to today in SQL.
        eff = new_effective
        # Placeholder order follows the SQL text: SET date, WHERE identity cols,
        # version, date again.
        cur.execute(
            f"""
            UPDATE {table}
            SET expiry_date = (COALESCE(%s::date, CURRENT_DATE) - interval '1 day')::date
            WHERE {where} AND version <> %s
              AND (expiry_date IS NULL
                   OR expiry_date > (COALESCE(%s::date, CURRENT_DATE) - interval '1 day')::date)
            """,
            [eff] + params + [eff],
        )
    else:
        cur.execute(f"UPDATE {table} SET is_active = false WHERE {where} AND version <> %s", params)


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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class BenefitMasterIn(BaseModel):
    benefit_code:       str
    benefit_type:       str = "BASE"
    risk_type:          str = "MORTALITY"
    uw_exposure_group:  str | None = None
    risk_group:         str | None = None
    premium_payer:      str = "ANY"
    underwriting_required: bool = True
    include_in_sar:     bool = True
    sar_formula:        str = "FACE_AMOUNT"
    sar_percentage:     float | None = None
    sar_expression:     str | None = None
    processing_sequence: int = 0
    is_active:          bool = True
    effective_date:     str | None = None
    expiry_date:        str | None = None
    # risk-group memberships: [{risk_group_code, weight_pct, priority}]
    group_maps:         list[dict] = Field(default_factory=list)


class RiskGroupIn(BaseModel):
    group_code:             str
    group_name:             str
    aggregation_method:     str = "SUM"
    uw_threshold_basis:     str = "INDIVIDUAL"
    include_existing_policies: bool = True
    include_pending_proposals: bool = True
    auto_refer_threshold:   float | None = None
    senior_uw_threshold:    float | None = None
    ri_approval_threshold:  float | None = None
    decline_threshold:      float | None = None
    description:            str | None = None
    is_active:              bool = True


class ExposureGroupIn(BaseModel):
    exposure_code: str
    exposure_name: str
    description:   str | None = None
    is_active:     bool = True


class AggregationRuleIn(BaseModel):
    risk_group_code:    str
    product_code:       str | None = None
    exposure_group:     str | None = None
    aggregation_method: str = "SUM"
    is_active:          bool = True


class FclConfigIn(BaseModel):
    product_code:           str
    scheme_id:              str | None = None
    exposure_group:         str | None = None
    fcl_basis:              str = "FLAT"
    flat_fcl_amount:        float | None = None
    formula_id:             str | None = None   # required when fcl_basis = FORMULA
    apply_fcl_per_benefit:  bool = False
    premium_payer_filter:   str = "ANY"
    is_active:              bool = True
    effective_date:         str | None = None
    expiry_date:            str | None = None


class NmlConfigIn(BaseModel):
    product_code:               str
    age_min:                    int | None = None
    age_max:                    int | None = None
    sar_min:                    float = 0
    sar_max:                    float | None = None
    nml_category:               str = "NON_MEDICAL"
    medical_tests_required:     list[str] = Field(default_factory=list)
    reinsurer_approval_required: bool = False
    is_active:                  bool = True
    effective_date:             str | None = None
    expiry_date:                str | None = None


# ---------------------------------------------------------------------------
# Benefits
# ---------------------------------------------------------------------------

@router.get("/benefits")
def list_benefits(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, benefit_code, benefit_type, risk_type, uw_exposure_group,
                   risk_group, premium_payer, underwriting_required, include_in_sar,
                   sar_formula, sar_percentage, sar_expression, processing_sequence,
                   is_active, effective_date, expiry_date, version
            FROM uw_benefit_master
            WHERE tenant_id = %s::uuid
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
              AND (effective_date IS NULL OR effective_date <= CURRENT_DATE)
            ORDER BY processing_sequence, benefit_code, version DESC
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.get("/benefit-options")
def list_benefit_options(current: CurrentUser = CurrentUser):
    """Dropdown source for the Benefit tab's "Benefit / Product Code" field.

    Union of the two Product-Config sources a SAR benefit can attach to:
      * products.product_code            — base plans (benefit_type BASE)
      * product_benefit_config.rider_product_code — compatible riders

    A typed code can silently create a phantom benefit (a SAR row with no
    backing product), so the UI must present these instead of free text.
    products has no canonical tenant_id (V001) — mirror list_products' unscoped
    read rather than reference the dev-only column.
    """
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT product_code AS benefit_code, product_name, 'BASE' AS benefit_type
            FROM products
            WHERE is_active = true
            UNION
            SELECT pbc.rider_product_code, COALESCE(p.product_name, pbc.rider_product_code),
                   pbc.benefit_type
            FROM product_benefit_config pbc
            LEFT JOIN products p ON p.product_code = pbc.rider_product_code
            WHERE pbc.tenant_id = %s::uuid AND pbc.is_active = true
            ORDER BY benefit_code
            """,
            (current.tenant_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        release(conn)


@router.get("/benefits/versions")
def list_benefit_versions(benefit_code: str, current: CurrentUser = CurrentUser):
    """Full version history for one benefit code — every version with its
    effective/expiry window, who changed it, and when."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, version, benefit_type, risk_type, uw_exposure_group,
                   risk_group, premium_payer, underwriting_required, include_in_sar,
                   sar_formula, sar_percentage, sar_expression, processing_sequence,
                   is_active, effective_date, expiry_date, created_by,
                   updated_by, created_at, updated_at
            FROM uw_benefit_master
            WHERE tenant_id = %s::uuid AND benefit_code = %s
            ORDER BY version DESC
        """, (current.tenant_id, benefit_code))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["is_current"] = (
                r["is_active"]
                and (r["expiry_date"] is None or r["expiry_date"] >= date.today())
                and (r["effective_date"] is None or r["effective_date"] <= date.today())
            )
        return {"benefit_code": benefit_code, "versions": rows}
    finally:
        release(conn)


@router.post("/benefits")
def upsert_benefit(body: BenefitMasterIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Append-version: new row with next version (effective/expiry control when active)
        version = _next_version(cur, "uw_benefit_master",
                                {"tenant_id": current.tenant_id, "benefit_code": body.benefit_code})
        cur.execute("""
            INSERT INTO uw_benefit_master
                (tenant_id, benefit_code, benefit_type, risk_type, uw_exposure_group,
                 risk_group, premium_payer, underwriting_required, include_in_sar,
                 sar_formula, sar_percentage, sar_expression, processing_sequence,
                 is_active, effective_date, expiry_date, version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            current.tenant_id, body.benefit_code, body.benefit_type, body.risk_type,
            body.uw_exposure_group, body.risk_group, body.premium_payer,
            body.underwriting_required, body.include_in_sar, body.sar_formula,
            body.sar_percentage, body.sar_expression, body.processing_sequence,
            body.is_active, body.effective_date, body.expiry_date,
            version, current.username, current.username,
        ))
        row = cur.fetchone()
        benefit_id = dict(row)["id"] if hasattr(row, "keys") else row[0]

        # Replace risk-group memberships (re-applied on the new version)
        cur.execute("DELETE FROM uw_benefit_group_map WHERE benefit_id = %s::uuid", (benefit_id,))
        for gm in (body.group_maps or []):
            cur.execute(
                "SELECT id FROM uw_risk_group WHERE tenant_id=%s::uuid AND group_code=%s "
                "ORDER BY version DESC LIMIT 1",
                (current.tenant_id, gm.get("risk_group_code")))
            rg = cur.fetchone()
            if not rg:
                continue
            rg_id = dict(rg)["id"] if hasattr(rg, "keys") else rg[0]
            cur.execute("""
                INSERT INTO uw_benefit_group_map (benefit_id, risk_group_id, weight_pct, priority, is_active)
                VALUES (%s::uuid, %s::uuid, %s, %s, true)
            """, (benefit_id, rg_id, gm.get("weight_pct", 100.0), gm.get("priority", 100)))

        _supersede_previous(cur, "uw_benefit_master",
                            {"tenant_id": current.tenant_id, "benefit_code": body.benefit_code},
                            version, body.effective_date)
        conn.commit()
        _log(conn, current, "uw_benefit_master", str(benefit_id),
             "sar.benefit.upsert",
             after={"benefit_code": body.benefit_code, "benefit_type": body.benefit_type,
                    "uw_exposure_group": body.uw_exposure_group,
                    "risk_group": body.risk_group, "sar_formula": body.sar_formula,
                    "include_in_sar": body.include_in_sar,
                    "group_maps": body.group_maps})
        return {"ok": True, "benefit_code": body.benefit_code, "id": benefit_id}
    finally:
        release(conn)


# ---------------------------------------------------------------------------
# Risk groups / exposure groups
# ---------------------------------------------------------------------------

@router.get("/risk-groups")
def list_risk_groups(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (group_code)
                   id::text, group_code, group_name, aggregation_method,
                   uw_threshold_basis, include_existing_policies,
                   include_pending_proposals,
                   auto_refer_threshold, senior_uw_threshold,
                   ri_approval_threshold, decline_threshold,
                   description, is_active, version
            FROM uw_risk_group
            WHERE tenant_id = %s::uuid
            ORDER BY group_code, version DESC
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.post("/risk-groups")
def upsert_risk_group(body: RiskGroupIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        version = _next_version(cur, "uw_risk_group",
                                {"tenant_id": current.tenant_id, "group_code": body.group_code})
        cur.execute("""
            INSERT INTO uw_risk_group
                (tenant_id, group_code, group_name, aggregation_method, uw_threshold_basis,
                 include_existing_policies, include_pending_proposals,
                 auto_refer_threshold, senior_uw_threshold,
                 ri_approval_threshold, decline_threshold,
                 description, is_active, version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            current.tenant_id, body.group_code, body.group_name, body.aggregation_method,
            body.uw_threshold_basis, body.include_existing_policies,
            body.include_pending_proposals,
            body.auto_refer_threshold, body.senior_uw_threshold,
            body.ri_approval_threshold, body.decline_threshold,
            body.description, body.is_active, version, current.username, current.username,
        ))
        _supersede_previous(cur, "uw_risk_group",
                            {"tenant_id": current.tenant_id, "group_code": body.group_code},
                            version, None)
        conn.commit()
        _log(conn, current, "uw_risk_group", body.group_code, "sar.risk_group.upsert",
             after={"group_code": body.group_code, "group_name": body.group_name,
                    "aggregation_method": body.aggregation_method,
                    "auto_refer_threshold": body.auto_refer_threshold,
                    "decline_threshold": body.decline_threshold})
        return {"ok": True, "group_code": body.group_code}
    finally:
        release(conn)


@router.get("/exposure-groups")
def list_exposure_groups(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (exposure_code)
                   id::text, exposure_code, exposure_name, description, is_active, version
            FROM uw_exposure_group WHERE tenant_id = %s::uuid
            ORDER BY exposure_code, version DESC
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.post("/exposure-groups")
def upsert_exposure_group(body: ExposureGroupIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        version = _next_version(cur, "uw_exposure_group",
                                {"tenant_id": current.tenant_id, "exposure_code": body.exposure_code})
        cur.execute("""
            INSERT INTO uw_exposure_group
                (tenant_id, exposure_code, exposure_name, description, is_active, version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
        """, (
            current.tenant_id, body.exposure_code, body.exposure_name,
            body.description, body.is_active, version, current.username, current.username,
        ))
        _supersede_previous(cur, "uw_exposure_group",
                            {"tenant_id": current.tenant_id, "exposure_code": body.exposure_code},
                            version, None)
        conn.commit()
        _log(conn, current, "uw_exposure_group", body.exposure_code,
             "sar.exposure_group.upsert",
             after={"exposure_code": body.exposure_code,
                    "exposure_name": body.exposure_name,
                    "is_active": body.is_active})
        return {"ok": True, "exposure_code": body.exposure_code}
    finally:
        release(conn)


# ---------------------------------------------------------------------------
# Aggregation rules
# ---------------------------------------------------------------------------

@router.get("/aggregation-rules")
def list_aggregation_rules(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (rg.group_code, ar.product_code, ar.exposure_group)
                   ar.id::text, rg.group_code AS risk_group_code, ar.product_code,
                   ar.exposure_group, ar.aggregation_method, ar.is_active, ar.version
            FROM uw_aggregation_rule ar
            JOIN uw_risk_group rg ON rg.id = ar.risk_group_id
            WHERE ar.tenant_id = %s::uuid
              AND (ar.expiry_date IS NULL OR ar.expiry_date >= CURRENT_DATE)
              AND (ar.effective_date IS NULL OR ar.effective_date <= CURRENT_DATE)
            ORDER BY rg.group_code, ar.product_code, ar.exposure_group, ar.version DESC
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.post("/aggregation-rules")
def create_aggregation_rule(body: AggregationRuleIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM uw_risk_group WHERE tenant_id=%s::uuid AND group_code=%s "
                    "ORDER BY version DESC LIMIT 1",
                    (current.tenant_id, body.risk_group_code))
        rg = cur.fetchone()
        if not rg:
            raise HTTPException(400, f"Unknown risk group {body.risk_group_code}")
        rg_id = dict(rg)["id"] if hasattr(rg, "keys") else rg[0]
        aggr_id = {"tenant_id": current.tenant_id, "risk_group_id": rg_id,
                   "product_code": body.product_code, "exposure_group": body.exposure_group}
        version = _next_version(cur, "uw_aggregation_rule", aggr_id)
        cur.execute("""
            INSERT INTO uw_aggregation_rule
                (tenant_id, risk_group_id, product_code, exposure_group, aggregation_method, is_active, version, created_by, updated_by)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s)
        """, (
            current.tenant_id, rg_id, body.product_code, body.exposure_group,
            body.aggregation_method, body.is_active, version, current.username, current.username,
        ))
        _supersede_previous(cur, "uw_aggregation_rule", aggr_id, version, None)
        conn.commit()
        _log(conn, current, "uw_aggregation_rule", body.risk_group_code,
             "sar.aggregation_rule.create",
             after={"risk_group_code": body.risk_group_code,
                    "product_code": body.product_code,
                    "exposure_group": body.exposure_group,
                    "aggregation_method": body.aggregation_method})
        return {"ok": True}
    finally:
        release(conn)


# ---------------------------------------------------------------------------
# FCL config
# ---------------------------------------------------------------------------

@router.get("/fcl")
def list_fcl(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, product_code, scheme_id, exposure_group, fcl_basis,
                   flat_fcl_amount, formula_id::text, apply_fcl_per_benefit,
                   premium_payer_filter, is_active, effective_date, expiry_date, version
            FROM uw_fcl_config WHERE tenant_id = %s::uuid
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
              AND (effective_date IS NULL OR effective_date <= CURRENT_DATE)
            ORDER BY product_code, version DESC
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.post("/fcl")
def upsert_fcl(body: FclConfigIn, current: CurrentUser = CurrentUser):
    if body.fcl_basis == "FORMULA" and not body.formula_id:
        raise HTTPException(400, "fcl_basis=FORMULA requires formula_id")
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        fcl_id = {"tenant_id": current.tenant_id, "product_code": body.product_code,
                  "scheme_id": body.scheme_id, "exposure_group": body.exposure_group}
        version = _next_version(cur, "uw_fcl_config", fcl_id)
        cur.execute("""
            INSERT INTO uw_fcl_config
                (tenant_id, product_code, scheme_id, exposure_group, fcl_basis,
                 flat_fcl_amount, formula_id, apply_fcl_per_benefit, premium_payer_filter,
                 is_active, effective_date, expiry_date, version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            current.tenant_id, body.product_code, body.scheme_id, body.exposure_group,
            body.fcl_basis, body.flat_fcl_amount, body.formula_id,
            body.apply_fcl_per_benefit, body.premium_payer_filter, body.is_active,
            body.effective_date, body.expiry_date, version, current.username, current.username,
        ))
        _supersede_previous(cur, "uw_fcl_config", fcl_id, version, body.effective_date)
        conn.commit()
        _log(conn, current, "uw_fcl_config", body.product_code, "sar.fcl.upsert",
             after={"product_code": body.product_code, "fcl_basis": body.fcl_basis,
                    "flat_fcl_amount": body.flat_fcl_amount,
                    "formula_id": body.formula_id,
                    "apply_fcl_per_benefit": body.apply_fcl_per_benefit})
        return {"ok": True}
    finally:
        release(conn)


# ---------------------------------------------------------------------------
# NML config
# ---------------------------------------------------------------------------

@router.get("/nml")
def list_nml(current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id::text, product_code, age_min, age_max, sar_min, sar_max,
                   nml_category, medical_tests_required, reinsurer_approval_required,
                   is_active, effective_date, expiry_date, version
            FROM uw_nml_config WHERE tenant_id = %s::uuid
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
              AND (effective_date IS NULL OR effective_date <= CURRENT_DATE)
            ORDER BY product_code, sar_min, version DESC
        """, (current.tenant_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        release(conn)


@router.post("/nml")
def upsert_nml(body: NmlConfigIn, current: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        nml_id = {"tenant_id": current.tenant_id, "product_code": body.product_code,
                  "age_min": body.age_min, "age_max": body.age_max,
                  "sar_min": body.sar_min, "sar_max": body.sar_max}
        version = _next_version(cur, "uw_nml_config", nml_id)
        cur.execute("""
            INSERT INTO uw_nml_config
                (tenant_id, product_code, age_min, age_max, sar_min, sar_max,
                 nml_category, medical_tests_required, reinsurer_approval_required,
                 is_active, effective_date, expiry_date, version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::text[], %s, %s, %s, %s, %s, %s, %s)
        """, (
            current.tenant_id, body.product_code, body.age_min, body.age_max,
            body.sar_min, body.sar_max, body.nml_category,
            body.medical_tests_required, body.reinsurer_approval_required,
            body.is_active, body.effective_date, body.expiry_date,
            version, current.username, current.username,
        ))
        _supersede_previous(cur, "uw_nml_config", nml_id, version, body.effective_date)
        conn.commit()
        _log(conn, current, "uw_nml_config",
             f"{body.product_code}:{body.age_min}-{body.age_max}",
             "sar.nml.upsert",
             after={"product_code": body.product_code, "age_min": body.age_min,
                    "age_max": body.age_max, "sar_min": body.sar_min,
                    "sar_max": body.sar_max, "nml_category": body.nml_category,
                    "medical_tests_required": body.medical_tests_required})
        return {"ok": True}
    finally:
        release(conn)


# ---------------------------------------------------------------------------
# RI Retention (Phase 4) — reinsurer retention limits
# ---------------------------------------------------------------------------

class RIReinsurerIn(BaseModel):
    reinsurer_code:        str
    reinsurer_name:        str
    retention_limit:       float | None = None
    product_codes:         list[str] = []
    treaty_code:           str | None = None
    treaty_type:           str = "FACULTATIVE"
    contact_name:          str | None = None
    contact_email:         str | None = None
    currency:              str = "INR"
    is_active:             bool = True
    notes:                 str | None = None
    treaty_effective_date: str | None = None
    treaty_expiry_date:    str | None = None


@router.get("/ri")
def list_ri_reinsurers(current: CurrentUser = CurrentUser):
    """List reinsurer retention limits (used by SAR engine step 10)."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, reinsurer_code, reinsurer_name, retention_limit,
                   product_codes, treaty_code, treaty_type, contact_name,
                   contact_email, currency, is_active, notes,
                   treaty_effective_date, treaty_expiry_date
            FROM ri_reinsurer
            ORDER BY retention_limit NULLS LAST, reinsurer_name
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["product_codes"] = list(r.get("product_codes") or [])
            for k in ("treaty_effective_date", "treaty_expiry_date"):
                v = r.get(k)
                r[k] = v.isoformat() if v else None
            v = r.get("retention_limit")
            r["retention_limit"] = float(v) if v is not None else None
        return rows
    finally:
        release(conn)


@router.post("/ri")
def upsert_ri_reinsurer(body: RIReinsurerIn, current: CurrentUser = CurrentUser):
    """Create or update a reinsurer by reinsurer_code (unique)."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ri_reinsurer
                (reinsurer_code, reinsurer_name, retention_limit, product_codes,
                 treaty_code, treaty_type, contact_name, contact_email,
                 currency, is_active, notes, treaty_effective_date, treaty_expiry_date)
            VALUES (%s, %s, %s, %s::text[], %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (reinsurer_code) DO UPDATE SET
                reinsurer_name = EXCLUDED.reinsurer_name,
                retention_limit = EXCLUDED.retention_limit,
                product_codes = EXCLUDED.product_codes,
                treaty_code = EXCLUDED.treaty_code,
                treaty_type = EXCLUDED.treaty_type,
                contact_name = EXCLUDED.contact_name,
                contact_email = EXCLUDED.contact_email,
                currency = EXCLUDED.currency,
                is_active = EXCLUDED.is_active,
                notes = EXCLUDED.notes,
                treaty_effective_date = EXCLUDED.treaty_effective_date,
                treaty_expiry_date = EXCLUDED.treaty_expiry_date,
                updated_at = now()
        """, (
            body.reinsurer_code, body.reinsurer_name, body.retention_limit,
            body.product_codes, body.treaty_code, body.treaty_type,
            body.contact_name, body.contact_email, body.currency,
            body.is_active, body.notes,
            body.treaty_effective_date, body.treaty_expiry_date,
        ))
        conn.commit()
        _log(conn, current, "ri_reinsurer", body.reinsurer_code, "ri.reinsurer.upsert",
             after={"reinsurer_code": body.reinsurer_code,
                    "reinsurer_name": body.reinsurer_name,
                    "retention_limit": body.retention_limit,
                    "product_codes": body.product_codes,
                    "treaty_type": body.treaty_type})
        return {"ok": True, "reinsurer_code": body.reinsurer_code}
    finally:
        release(conn)
