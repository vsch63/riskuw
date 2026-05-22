"""
routers/uw_scales.py
────────────────────
UW Scales & Premium Rate Scales — CRUD endpoints.

Mount in main.py:
    from routers.uw_scales import router as uw_scales_router
    app.include_router(uw_scales_router, prefix="/uw-scales", tags=["UW Scales"])
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator

from app.db import get_conn          # your existing pool helper
from app.auth import require_roles   # your existing auth dependency

router = APIRouter()

# ──────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────

VALID_PARAMETERS = [
    "age", "gender", "smoker", "bmi",
    "bp_systolic", "bp_diastolic", "occupation_class",
    "policy_term", "sum_assured", "urine_albumin", "family_history",
]


class ParameterIn(BaseModel):
    parameter_name: str
    parameter_type: str = "RANGE"       # RANGE | DISCRETE
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    sort_order: int = 0

    @field_validator("parameter_name")
    @classmethod
    def valid_param(cls, v: str) -> str:
        if v not in VALID_PARAMETERS:
            raise ValueError(f"parameter_name must be one of {VALID_PARAMETERS}")
        return v

    @field_validator("parameter_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in ("RANGE", "DISCRETE"):
            raise ValueError("parameter_type must be RANGE or DISCRETE")
        return v


class DetailIn(BaseModel):
    age_from: int
    age_to: int
    value: float
    sort_order: int = 0

    @model_validator(mode="after")
    def age_order(self) -> "DetailIn":
        if self.age_to < self.age_from:
            raise ValueError("age_to must be >= age_from")
        return self


class TrancheIn(BaseModel):
    description: str
    effective_date: date
    expiry_date: Optional[date] = None
    parameter_logic: str = "AND"
    sort_order: int = 0
    parameters: list[ParameterIn] = []
    details: list[DetailIn] = []

    @field_validator("parameter_logic")
    @classmethod
    def valid_logic(cls, v: str) -> str:
        if v not in ("AND", "OR"):
            raise ValueError("parameter_logic must be AND or OR")
        return v

    @model_validator(mode="after")
    def date_order(self) -> "TrancheIn":
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiry_date must be after effective_date")
        return self


class ScaleIn(BaseModel):
    name: str
    description: Optional[str] = None
    scale_type: str                          # UW | PREMIUM
    premium_output_type: Optional[str] = None  # RATE_PER_THOUSAND | MULTIPLIER
    is_active: bool = True
    tranches: list[TrancheIn] = []

    @field_validator("scale_type")
    @classmethod
    def valid_scale_type(cls, v: str) -> str:
        if v not in ("UW", "PREMIUM"):
            raise ValueError("scale_type must be UW or PREMIUM")
        return v

    @model_validator(mode="after")
    def premium_needs_output_type(self) -> "ScaleIn":
        if self.scale_type == "PREMIUM" and not self.premium_output_type:
            raise ValueError("premium_output_type required when scale_type is PREMIUM")
        if self.premium_output_type and self.premium_output_type not in (
            "RATE_PER_THOUSAND", "MULTIPLIER"
        ):
            raise ValueError("premium_output_type must be RATE_PER_THOUSAND or MULTIPLIER")
        return self


class ProductScaleIn(BaseModel):
    product_code: str
    scale_id: str
    effective_from: date = date.today()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _row(r: Any) -> dict:
    """Convert psycopg2 RealDictRow to plain dict."""
    return dict(r) if r else {}


def _rows(rs: Any) -> list[dict]:
    return [dict(r) for r in rs]


async def _get_tenant(conn, username: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT tenant_id FROM uw_user WHERE username=%s", (username,))
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(status_code=403, detail="User tenant not found")
    return str(row["tenant_id"])


# ──────────────────────────────────────────────────────────────
# Scale CRUD
# ──────────────────────────────────────────────────────────────

@router.get("/", summary="List all scales")
async def list_scales(
    scale_type: Optional[str] = None,
    active_only: bool = True,
    user=Depends(require_roles(["admin", "super_admin", "senior_underwriter"])),
    conn=Depends(get_conn),
):
    tenant_id = await _get_tenant(conn, user["sub"])
    cur = conn.cursor()
    q = """
        SELECT s.*,
               COUNT(t.id) AS tranche_count
        FROM uw_rate_scale s
        LEFT JOIN uw_scale_tranche t ON t.scale_id = s.id
        WHERE s.tenant_id = %s::uuid
    """
    params: list = [tenant_id]
    if scale_type:
        q += " AND s.scale_type = %s"
        params.append(scale_type)
    if active_only:
        q += " AND s.is_active = true"
    q += " GROUP BY s.id ORDER BY s.created_at DESC"
    cur.execute(q, params)
    rows = _rows(cur.fetchall())
    cur.close()
    return rows


@router.get("/{scale_id}", summary="Get scale with full tranche tree")
async def get_scale(
    scale_id: str,
    user=Depends(require_roles(["admin", "super_admin", "senior_underwriter"])),
    conn=Depends(get_conn),
):
    tenant_id = await _get_tenant(conn, user["sub"])
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM uw_rate_scale WHERE id=%s::uuid AND tenant_id=%s::uuid",
        (scale_id, tenant_id),
    )
    scale = _row(cur.fetchone())
    if not scale:
        raise HTTPException(status_code=404, detail="Scale not found")

    cur.execute(
        "SELECT * FROM uw_scale_tranche WHERE scale_id=%s::uuid ORDER BY sort_order, effective_date",
        (scale_id,),
    )
    tranches = _rows(cur.fetchall())

    for t in tranches:
        tid = str(t["id"])
        cur.execute(
            "SELECT * FROM uw_tranche_parameter WHERE tranche_id=%s::uuid ORDER BY sort_order",
            (tid,),
        )
        t["parameters"] = _rows(cur.fetchall())

        cur.execute(
            "SELECT * FROM uw_tranche_detail WHERE tranche_id=%s::uuid ORDER BY sort_order, age_from",
            (tid,),
        )
        t["details"] = _rows(cur.fetchall())

    scale["tranches"] = tranches
    cur.close()
    return scale


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create scale with tranches")
async def create_scale(
    body: ScaleIn,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    tenant_id = await _get_tenant(conn, user["sub"])
    actor = user["sub"]
    cur = conn.cursor()
    conn.autocommit = False

    try:
        # Insert scale
        scale_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO uw_rate_scale
                (id, tenant_id, name, description, scale_type,
                 premium_output_type, is_active, created_by, updated_by)
            VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                scale_id, tenant_id, body.name, body.description,
                body.scale_type, body.premium_output_type,
                body.is_active, actor, actor,
            ),
        )

        for tranche in body.tranches:
            tranche_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO uw_scale_tranche
                    (id, scale_id, description, effective_date,
                     expiry_date, parameter_logic, sort_order)
                VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
                """,
                (
                    tranche_id, scale_id, tranche.description,
                    tranche.effective_date, tranche.expiry_date,
                    tranche.parameter_logic, tranche.sort_order,
                ),
            )

            for p in tranche.parameters:
                cur.execute(
                    """
                    INSERT INTO uw_tranche_parameter
                        (id, tranche_id, parameter_name, parameter_type,
                         min_value, max_value, sort_order)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
                    """,
                    (
                        str(uuid.uuid4()), tranche_id,
                        p.parameter_name, p.parameter_type,
                        p.min_value, p.max_value, p.sort_order,
                    ),
                )

            for d in tranche.details:
                cur.execute(
                    """
                    INSERT INTO uw_tranche_detail
                        (id, tranche_id, age_from, age_to, value, sort_order)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s)
                    """,
                    (
                        str(uuid.uuid4()), tranche_id,
                        d.age_from, d.age_to, d.value, d.sort_order,
                    ),
                )

        conn.commit()
        cur.close()
        return {"scale_id": scale_id, "message": "Scale created successfully"}

    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{scale_id}", summary="Update scale header (name/description/active)")
async def update_scale(
    scale_id: str,
    body: ScaleIn,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    tenant_id = await _get_tenant(conn, user["sub"])
    cur = conn.cursor()
    conn.autocommit = False

    try:
        cur.execute(
            "SELECT id FROM uw_rate_scale WHERE id=%s::uuid AND tenant_id=%s::uuid",
            (scale_id, tenant_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Scale not found")

        cur.execute(
            """
            UPDATE uw_rate_scale
            SET name=%s, description=%s, scale_type=%s,
                premium_output_type=%s, is_active=%s, updated_by=%s
            WHERE id=%s::uuid
            """,
            (
                body.name, body.description, body.scale_type,
                body.premium_output_type, body.is_active,
                user["sub"], scale_id,
            ),
        )
        conn.commit()
        cur.close()
        return {"message": "Scale updated"}
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{scale_id}", summary="Delete scale (cascades to tranches)")
async def delete_scale(
    scale_id: str,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    tenant_id = await _get_tenant(conn, user["sub"])
    cur = conn.cursor()
    conn.autocommit = False
    try:
        cur.execute(
            "DELETE FROM uw_rate_scale WHERE id=%s::uuid AND tenant_id=%s::uuid",
            (scale_id, tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Scale not found")
        conn.commit()
        cur.close()
        return {"message": "Scale deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


# ──────────────────────────────────────────────────────────────
# Tranche CRUD
# ──────────────────────────────────────────────────────────────

@router.post("/{scale_id}/tranches", status_code=201, summary="Add tranche to scale")
async def add_tranche(
    scale_id: str,
    body: TrancheIn,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    tenant_id = await _get_tenant(conn, user["sub"])
    cur = conn.cursor()
    conn.autocommit = False

    try:
        cur.execute(
            "SELECT id FROM uw_rate_scale WHERE id=%s::uuid AND tenant_id=%s::uuid",
            (scale_id, tenant_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Scale not found")

        tranche_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO uw_scale_tranche
                (id, scale_id, description, effective_date,
                 expiry_date, parameter_logic, sort_order)
            VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
            """,
            (
                tranche_id, scale_id, body.description,
                body.effective_date, body.expiry_date,
                body.parameter_logic, body.sort_order,
            ),
        )

        for p in body.parameters:
            cur.execute(
                """
                INSERT INTO uw_tranche_parameter
                    (id, tranche_id, parameter_name, parameter_type,
                     min_value, max_value, sort_order)
                VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s)
                """,
                (
                    str(uuid.uuid4()), tranche_id,
                    p.parameter_name, p.parameter_type,
                    p.min_value, p.max_value, p.sort_order,
                ),
            )

        for d in body.details:
            cur.execute(
                """
                INSERT INTO uw_tranche_detail
                    (id, tranche_id, age_from, age_to, value, sort_order)
                VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s)
                """,
                (
                    str(uuid.uuid4()), tranche_id,
                    d.age_from, d.age_to, d.value, d.sort_order,
                ),
            )

        conn.commit()
        cur.close()
        return {"tranche_id": tranche_id, "message": "Tranche added"}
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{scale_id}/tranches/{tranche_id}", summary="Delete tranche")
async def delete_tranche(
    scale_id: str,
    tranche_id: str,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    cur = conn.cursor()
    conn.autocommit = False
    try:
        cur.execute(
            "DELETE FROM uw_scale_tranche WHERE id=%s::uuid AND scale_id=%s::uuid",
            (tranche_id, scale_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Tranche not found")
        conn.commit()
        cur.close()
        return {"message": "Tranche deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


# ──────────────────────────────────────────────────────────────
# Product ↔ Scale attachment
# ──────────────────────────────────────────────────────────────

@router.get("/product-attachments/", summary="List product-scale attachments")
async def list_attachments(
    product_code: Optional[str] = None,
    user=Depends(require_roles(["admin", "super_admin", "senior_underwriter"])),
    conn=Depends(get_conn),
):
    cur = conn.cursor()
    q = """
        SELECT ps.*, s.name AS scale_name, s.scale_type, s.premium_output_type
        FROM uw_product_scale ps
        JOIN uw_rate_scale s ON s.id = ps.scale_id
        WHERE 1=1
    """
    params: list = []
    if product_code:
        q += " AND ps.product_code = %s"
        params.append(product_code)
    q += " ORDER BY ps.created_at DESC"
    cur.execute(q, params)
    rows = _rows(cur.fetchall())
    cur.close()
    return rows


@router.post("/product-attachments/", status_code=201, summary="Attach scale to product")
async def attach_to_product(
    body: ProductScaleIn,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    cur = conn.cursor()
    conn.autocommit = False
    try:
        cur.execute(
            """
            INSERT INTO uw_product_scale (id, product_code, scale_id, effective_from, created_by)
            VALUES (%s::uuid, %s, %s::uuid, %s, %s)
            ON CONFLICT (product_code, scale_id) DO NOTHING
            """,
            (
                str(uuid.uuid4()), body.product_code,
                body.scale_id, body.effective_from, user["sub"],
            ),
        )
        conn.commit()
        cur.close()
        return {"message": "Scale attached to product"}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/product-attachments/{attachment_id}", summary="Remove product-scale attachment")
async def detach_from_product(
    attachment_id: str,
    user=Depends(require_roles(["admin", "super_admin"])),
    conn=Depends(get_conn),
):
    cur = conn.cursor()
    conn.autocommit = False
    try:
        cur.execute(
            "DELETE FROM uw_product_scale WHERE id=%s::uuid", (attachment_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Attachment not found")
        conn.commit()
        cur.close()
        return {"message": "Attachment removed"}
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


# ──────────────────────────────────────────────────────────────
# Evaluation endpoint (used by UW engine)
# ──────────────────────────────────────────────────────────────

@router.post("/evaluate/", summary="Evaluate a scale against applicant data")
async def evaluate_scale(
    body: dict,
    user=Depends(require_roles(["admin", "super_admin", "senior_underwriter", "underwriter"])),
    conn=Depends(get_conn),
):
    """
    body: {
      "scale_id": "uuid",
      "applicant": { "age": 35, "gender": "M", "smoker": 1, "bmi": 28.5 }
    }
    Returns the matching tranche and its output value.
    Raises 409 if multiple tranches match (config error).
    """
    scale_id = body.get("scale_id")
    applicant = body.get("applicant", {})
    today = date.today()

    cur = conn.cursor()

    # Get all active tranches for this scale valid today
    cur.execute(
        """
        SELECT t.*
        FROM uw_scale_tranche t
        JOIN uw_rate_scale s ON s.id = t.scale_id
        WHERE t.scale_id = %s::uuid
          AND t.effective_date <= %s
          AND (t.expiry_date IS NULL OR t.expiry_date >= %s)
        ORDER BY t.sort_order
        """,
        (scale_id, today, today),
    )
    tranches = _rows(cur.fetchall())

    matched = []
    for tranche in tranches:
        tid = str(tranche["id"])
        cur.execute(
            "SELECT * FROM uw_tranche_parameter WHERE tranche_id=%s::uuid",
            (tid,),
        )
        params = _rows(cur.fetchall())

        results = []
        for p in params:
            pname = p["parameter_name"]
            app_val = applicant.get(pname)
            if app_val is None:
                results.append(False)
                continue
            app_val = float(app_val)
            min_v = float(p["min_value"]) if p["min_value"] is not None else None
            max_v = float(p["max_value"]) if p["max_value"] is not None else None
            match = True
            if min_v is not None and app_val < min_v:
                match = False
            if max_v is not None and app_val > max_v:
                match = False
            results.append(match)

        logic = tranche["parameter_logic"]
        tranche_matched = all(results) if logic == "AND" else any(results)
        if tranche_matched:
            matched.append(tranche)

    if len(matched) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Multiple tranches matched ({len(matched)}). "
                "Please fix overlapping tranche configurations."
            ),
        )

    if not matched:
        cur.close()
        return {"matched": False, "message": "No tranche matched"}

    tranche = matched[0]
    tid = str(tranche["id"])
    age = applicant.get("age")

    output = None
    if age is not None:
        cur.execute(
            """
            SELECT * FROM uw_tranche_detail
            WHERE tranche_id=%s::uuid AND age_from <= %s AND age_to >= %s
            ORDER BY sort_order LIMIT 1
            """,
            (tid, age, age),
        )
        detail = _row(cur.fetchone())
        if detail:
            output = float(detail["value"])

    cur.close()
    return {
        "matched": True,
        "tranche_id": str(tranche["id"]),
        "tranche_description": tranche["description"],
        "output_value": output,
    }
