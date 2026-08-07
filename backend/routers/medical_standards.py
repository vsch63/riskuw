"""
routers/medical_standards.py
────────────────────────────
Admin API for the data-driven underwriting standards (Phase 2, V034):

  uw_medical_standard        — standard group (system level: tenant/product NULL)
  uw_medical_standard_rule   — FLAT (condition → fixed points) or RANGE (param)
  uw_medical_standard_range  — point bands for RANGE rules

GET  /medical-standards            effective standards (system + product override)
PUT  /medical-standards/{code}     upsert one standard scope (rules+ranges replaced)
DELETE /medical-standards/{code}   drop one standard scope

Writes are tenant-scoped (CurrentUser.tenant_id) and audited as CONFIG events so
every tuning decision is attributable.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deps import CurrentUser

router = APIRouter(prefix="/medical-standards", tags=["Medical Standards"])


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


def _log(conn, current, entity_id: str, event_type: str, after: dict | None = None,
         before: dict | None = None) -> None:
    """Record a CONFIG change in the audit trail. Silent on failure."""
    try:
        from services.audit import log_event
        log_event(
            conn, event_category="CONFIG", event_type=event_type,
            actor_username=current.username, actor_role=current.role,
            tenant_id=str(current.tenant_id),
            entity_type="medical_standard", entity_id=entity_id,
            entity_ref=entity_id,
            before_state=before, after_state=after,
        )
    except Exception:
        pass


# ── Schemas ───────────────────────────────────────────────────────────────────

class StandardRangeIn(BaseModel):
    min_value: float | None = None
    max_value: float | None = None
    min_exclusive: bool = False
    max_exclusive: bool = False
    name: str | None = None
    description: str | None = None
    debit_points: int = 0
    credit_points: int = 0
    rating_class: str | None = None
    requires_aps: bool = False
    aps_reason: str | None = None


class StandardRuleIn(BaseModel):
    rule_type: str = Field(default="FLAT", pattern="^(FLAT|RANGE)$")
    condition: dict | None = None
    param: str | None = None
    name: str | None = None
    description: str | None = None
    debit_points: int = 0
    credit_points: int = 0
    rating_class: str | None = None
    requires_aps: bool = False
    aps_reason: str | None = None
    ranges: list[StandardRangeIn] = []


class StandardIn(BaseModel):
    family: str
    name: str
    category: str
    product_code: str | None = None
    is_active: bool = True
    effective_date: str | None = None
    expiry_date: str | None = None
    rules: list[StandardRuleIn] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

_STANDARD_COLS = [
    "standard_code", "family", "name", "category", "tenant_scoped", "product_scoped",
    "rule_id", "rule_type", "param", "condition", "rule_name", "rule_desc",
    "rule_debit", "rule_credit", "rule_rating", "rule_aps", "rule_aps_reason",
    "rule_seq", "min_value", "max_value", "min_exclusive", "max_exclusive",
    "band_name", "band_desc", "band_debit", "band_credit", "band_aps",
    "band_aps_reason", "band_seq",
]


def _effective_standards(tenant_id, product_code) -> list[dict]:
    """Return the effective (merged, most-specific-scope) standards with
    rules/ranges, matching the engine's loader. Imported here to keep the
    merge logic in exactly one place."""
    from services.uw_engine import _load_standards
    return _load_standards(tenant_id, product_code)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_standards(current: CurrentUser, product_code: str | None = None):
    """Effective standards for the caller's tenant + optional product.
    When no product is given, system-level standards apply."""
    return _effective_standards(current.tenant_id, product_code)


@router.get("/{code}")
def get_standard(code: str, current: CurrentUser, product_code: str | None = None):
    standards = _effective_standards(current.tenant_id, product_code)
    for s in standards:
        if s["code"] == code.upper():
            return s
    raise HTTPException(status_code=404, detail=f"Standard '{code}' not configured")


@router.put("/{code}")
def upsert_standard(code: str, body: StandardIn, current: CurrentUser):
    """Create or replace a standard scope (tenant, optional product). Rules
    and ranges are replaced wholesale — the body is the full definition."""
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

    standard_code = code.upper()
    tenant_id = current.tenant_id
    product_code = body.product_code or None
    standard_id = str(uuid.uuid4())

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        # Upsert the standard row; the unique scope index keyed on
        # (standard_code, tenant, product) drives the conflict target.
        cur.execute(
            """
            INSERT INTO uw_medical_standard
                (id, tenant_id, product_code, standard_code, family, name, category,
                 is_active, effective_date, expiry_date, created_by, updated_by, version)
            VALUES
                (%s, %s::uuid, %s, %s, %s, %s, %s,
                 %s, COALESCE(%s::date, CURRENT_DATE), %s::date, %s, %s, 1)
            ON CONFLICT (standard_code, COALESCE(tenant_id::text, ''), COALESCE(product_code, ''))
            DO UPDATE SET family=EXCLUDED.family, name=EXCLUDED.name, category=EXCLUDED.category,
                          is_active=EXCLUDED.is_active, effective_date=EXCLUDED.effective_date,
                          expiry_date=EXCLUDED.expiry_date, updated_by=EXCLUDED.updated_by,
                          version=uw_medical_standard.version + 1,
                          updated_at=now()
            RETURNING id::text
            """,
            (
                standard_id, tenant_id, product_code, standard_code,
                body.family, body.name, body.category,
                body.is_active, body.effective_date or None, body.expiry_date or None,
                current.username, current.username,
            ),
        )
        row = cur.fetchone()
        standard_id = row["id"] if hasattr(row, "keys") else row[0]

        # Replace rules + ranges wholesale
        cur.execute("DELETE FROM uw_medical_standard_rule WHERE standard_id=%s", (standard_id,))
        for rule in body.rules:
            rule_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO uw_medical_standard_rule
                    (id, standard_id, seq, rule_type, condition, param, name, description,
                     debit_points, credit_points, rating_class, requires_aps, aps_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rule_id, standard_id, 10, rule.rule_type,
                    rule.condition, rule.param, rule.name, rule.description,
                    rule.debit_points, rule.credit_points, rule.rating_class,
                    rule.requires_aps, rule.aps_reason,
                ),
            )
            for i, rng in enumerate(rule.ranges):
                cur.execute(
                    """
                    INSERT INTO uw_medical_standard_range
                        (id, rule_id, seq, min_value, max_value, min_exclusive, max_exclusive,
                         name, description, debit_points, credit_points, rating_class,
                         requires_aps, aps_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()), rule_id, (i + 1) * 10,
                        rng.min_value, rng.max_value, rng.min_exclusive, rng.max_exclusive,
                        rng.name, rng.description, rng.debit_points, rng.credit_points,
                        rng.rating_class, rng.requires_aps, rng.aps_reason,
                    ),
                )
        conn.commit()
        _log(conn, current, standard_code, "medical_standard.upsert", after={
            "standard_code": standard_code, "product_code": product_code,
            "family": body.family, "category": body.category,
            "rules": len(body.rules),
        })
        cur.close()
        return {"ok": True, "standard_code": standard_code, "id": standard_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        release(conn)


@router.delete("/{code}")
def delete_standard(code: str, current: CurrentUser, product_code: str | None = None):
    """Drop one standard scope (tenant, optional product). System-level rows
    from the seed are protected unless explicitly targetable."""
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

    standard_code = code.upper()
    tenant_id = current.tenant_id
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM uw_medical_standard WHERE standard_code=%s "
            "AND tenant_id=%s::uuid AND product_code IS NOT DISTINCT FROM %s RETURNING id::text",
            (standard_code, tenant_id, product_code),
        )
        row = cur.fetchone()
        conn.commit()
        _log(conn, current, standard_code, "medical_standard.delete", after={
            "standard_code": standard_code, "product_code": product_code})
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Standard '{standard_code}' not found for this scope")
        return {"ok": True, "deleted": standard_code}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        release(conn)
