"""
services/sar_config.py
──────────────────────
Raw-SQL config loaders for the SAR engine. Read UW_* configuration
(UW_BENEFIT_MASTER, UW_BENEFIT_GROUP_MAP, UW_AGGREGATION_RULE,
UW_FCL_CONFIG, UW_NML_CONFIG, uw_formula / uw_formula_step /
uw_reference_table) into the engine DTOs defined in services.sar_engine.

The engine itself (SAREngine / FormulaEngine) stays stateless and pure —
all configuration is materialised here into DTOs before calling it.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from services.sar_engine import (
    AggregationRule,
    ApplicantPayload,
    BenefitLine,
    CumulativeConfig,
    FclRule,
    Formula,
    FormulaStep,
    NMLConfig,
    ProductConfig,
    RIConfig,
    ReferenceTable,
    ReferenceTableRow,
    PremiumPayer,
    ExposureGroup,
)

logger = logging.getLogger(__name__)

DEMO_TENANT = "00000000-0000-0000-0000-000000000001"

# operator stored in uw_formula_step (+ - * / % IF ELSE ENDIF)
# -> FormulaEngine operator name
_OPERATOR_MAP = {
    "+": "ADD",
    "-": "SUBTRACT",
    "*": "MULTIPLY",
    "/": "DIVIDE",
    "%": "PERCENT",
    "IF": "IF",
    "ELSE": "ELSE",
    "ENDIF": "ENDIF",
}

# parameter_type -> FormulaEngine parameter_source + input field name
_INPUT_FIELD_PARAMS = {
    "AGE":               "age",
    "ANNUAL_SALARY":     "annual_salary",
    "SCHEME_MEMBER_COUNT": "scheme_member_count",
    "EMPLOYER_CODE":     "employer_code",
}


def _row_dict(row):
    return dict(row) if hasattr(row, "keys") else None


def _parse_condition(v) -> Optional[dict]:
    """JSONB condition column -> dict, or None when empty. The column may
    come back already decoded (dict) or as a JSON string depending on the
    connection's cursor factory / type adapters."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v or None
    if isinstance(v, str):
        try:
            import json
            parsed = json.loads(v)
            return parsed if parsed else None
        except Exception:
            return None
    return None


def _dec(v) -> Optional[Decimal]:
    """DB numeric -> Decimal, preserving None."""
    if v is None:
        return None
    return Decimal(str(v))


# ---------------------------------------------------------------------------
# Benefit config
# ---------------------------------------------------------------------------

def load_benefit_lines(
    conn, tenant_id: str, request_benefits: list[dict]
) -> list[BenefitLine]:
    """Join request benefits (product_code, benefit_type, face_amount, ...)
    with UW_BENEFIT_MASTER + UW_BENEFIT_GROUP_MAP into BenefitLine DTOs.

    A benefit with no UW_BENEFIT_MASTER row is skipped from SAR (lenient —
    SAR should never break proposal evaluation for an unconfigured benefit).
    """
    lines: list[BenefitLine] = []
    cur = conn.cursor()
    try:
        for i, rb in enumerate(request_benefits):
            # benefit_id mirrors the caller's original benefit index (the
            # caller injects "_idx") so individual_sar keys map back to the
            # request rows — even when some benefits are skipped.
            benefit_id = str(rb.get("_idx", i))
            product_code = rb.get("product_code") or rb.get("benefit_code")
            if not product_code:
                continue
            cur.execute(
                """
                SELECT bm.id, bm.benefit_code, bm.benefit_type, bm.risk_type,
                       bm.uw_exposure_group, bm.risk_group, bm.premium_payer,
                       bm.underwriting_required, bm.include_in_sar, bm.sar_formula,
                       bm.sar_percentage, bm.sar_expression
                FROM uw_benefit_master bm
                WHERE bm.tenant_id = %s::uuid
                  AND bm.benefit_code = %s
                  AND bm.is_active = true
                  AND (bm.effective_date IS NULL OR bm.effective_date <= CURRENT_DATE)
                  AND (bm.expiry_date IS NULL OR bm.expiry_date >= CURRENT_DATE)
                """,
                (tenant_id, product_code),
            )
            row = _row_dict(cur.fetchone())
            if not row:
                logger.warning("No UW_BENEFIT_MASTER row for %s — excluded from SAR", product_code)
                continue

            # risk-group memberships (weight + priority)
            weights: dict[str, Decimal] = {}
            priorities: dict[str, int] = {}
            cur.execute(
                """
                SELECT rg.group_code, bgm.weight_pct, bgm.priority
                FROM uw_benefit_group_map bgm
                JOIN uw_risk_group rg ON rg.id = bgm.risk_group_id
                WHERE bgm.benefit_id = %s::uuid AND bgm.is_active = true
                """,
                (row["id"],),
            )
            for g in cur.fetchall():
                gd = dict(g)
                weights[gd["group_code"]] = Decimal(str(gd["weight_pct"]))
                priorities[gd["group_code"]] = gd.get("priority") or 100

            # if no explicit membership rows, fall back to the denormalized risk_group
            if not weights and row.get("risk_group"):
                weights[row["risk_group"]] = Decimal("100")

            lines.append(BenefitLine(
                benefit_id=benefit_id,
                benefit_code=row["benefit_code"],
                sum_assured=Decimal(str(rb.get("face_amount") or 0)),
                premium_payer=row["premium_payer"] or PremiumPayer.ANY.value,
                include_in_sar=bool(row["include_in_sar"]),
                sar_formula=row["sar_formula"] or "FACE_AMOUNT",
                sar_percentage=(
                    Decimal(str(row["sar_percentage"])) if row.get("sar_percentage") is not None else None
                ),
                sar_expression=row.get("sar_expression"),
                uw_exposure_group=row.get("uw_exposure_group") or ExposureGroup.INDIVIDUAL.value,
                risk_group_weights=weights,
                risk_group_priority=priorities,
                policy_reserve=Decimal(str(rb.get("policy_reserve") or 0)),
                fund_value=Decimal(str(rb.get("fund_value") or 0)),
            ))
        return lines
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Aggregation rules
# ---------------------------------------------------------------------------

def load_aggregation_rules(
    conn, tenant_id: str, product_code: str
) -> list[AggregationRule]:
    """Explicit UW_AGGREGATION_RULE rows for the product/risk-groups. The
    engine falls back to SUM when no rule matches; the risk-group default
    aggregation_method is folded in as a product_code=NULL, exposure_group=NULL
    rule so a risk group configured as MAXIMUM is honoured without a rule row."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT rg.group_code AS risk_group, ar.exposure_group,
                   ar.product_code, ar.aggregation_method
            FROM uw_aggregation_rule ar
            JOIN uw_risk_group rg ON rg.id = ar.risk_group_id
            WHERE ar.tenant_id = %s::uuid
              AND (ar.product_code = %s OR ar.product_code IS NULL)
              AND ar.is_active = true
              AND ar.effective_date <= CURRENT_DATE
              AND (ar.expiry_date IS NULL OR ar.expiry_date >= CURRENT_DATE)
            """,
            (tenant_id, product_code),
        )
        rules = [AggregationRule(
            risk_group=dict(r)["risk_group"],
            exposure_group=dict(r).get("exposure_group"),
            product_code=dict(r).get("product_code"),
            aggregation_method=dict(r)["aggregation_method"],
        ) for r in cur.fetchall()]

        # Fold in the risk-group default method (product_code=NULL) for any
        # group not covered by an explicit rule row.
        covered = {r.risk_group for r in rules}
        cur.execute(
            """
            SELECT group_code, aggregation_method FROM uw_risk_group
            WHERE tenant_id = %s::uuid AND is_active = true
            """,
            (tenant_id,),
        )
        for g in cur.fetchall():
            gd = dict(g)
            if gd["group_code"] not in covered:
                rules.append(AggregationRule(
                    risk_group=gd["group_code"],
                    exposure_group=None,
                    product_code=None,
                    aggregation_method=gd["aggregation_method"],
                ))
        return rules
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Formula + reference tables (FCL)
# ---------------------------------------------------------------------------

def _load_reference_table(conn, reference_table_id: str) -> Optional[ReferenceTable]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT rt.table_code
            FROM uw_reference_table rt
            WHERE rt.id = %s::uuid
            """,
            (reference_table_id,),
        )
        header = _row_dict(cur.fetchone())
        if not header:
            return None
        cur.execute(
            """
            SELECT match_type, band_min, band_max, match_value, output_value
            FROM uw_reference_table_row
            WHERE reference_table_id = %s::uuid AND is_active = true
            ORDER BY sort_order, band_min NULLS LAST
            """,
            (reference_table_id,),
        )
        rows = [
            ReferenceTableRow(
                match_type=dict(r)["match_type"],
                band_min=(Decimal(str(dict(r)["band_min"])) if dict(r).get("band_min") is not None else None),
                band_max=(Decimal(str(dict(r)["band_max"])) if dict(r).get("band_max") is not None else None),
                match_value=dict(r).get("match_value"),
                output_value=Decimal(str(dict(r)["output_value"])),
            )
            for r in cur.fetchall()
        ]
        return ReferenceTable(table_code=header["table_code"], rows=rows)
    finally:
        cur.close()


def _load_formula(conn, formula_id: str) -> Optional[Formula]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT formula_name, formula_type
            FROM uw_formula WHERE id = %s::uuid
            """,
            (formula_id,),
        )
        header = _row_dict(cur.fetchone())
        if not header:
            return None
        cur.execute(
            """
            SELECT seq_no, operator, factor, parameter_type, user_value, user_label,
                   reference_table_id, condition
            FROM uw_formula_step
            WHERE formula_id = %s::uuid
            ORDER BY seq_no
            """,
            (formula_id,),
        )
        steps: list[FormulaStep] = []
        for s in cur.fetchall():
            sd = dict(s)
            ptype = sd.get("parameter_type")
            op = _OPERATOR_MAP.get(sd.get("operator"))
            if op is None:
                logger.warning("Formula %s step %s has unsupported operator %s",
                               header["formula_name"], sd.get("seq_no"), sd.get("operator"))
                continue

            constant_value = None
            input_field = None
            reference_table = None

            if ptype == "USER_VALUE":
                constant_value = Decimal(str(sd.get("user_value") or 0))
                parameter_source = "CONSTANT"
            elif ptype in _INPUT_FIELD_PARAMS:
                input_field = _INPUT_FIELD_PARAMS[ptype]
                parameter_source = "INPUT_FIELD"
            elif ptype == "REFERENCE_TABLE":
                parameter_source = "REFERENCE_TABLE"
                input_field = sd.get("user_label") or "age"
                if sd.get("reference_table_id"):
                    reference_table = _load_reference_table(conn, str(sd["reference_table_id"]))
            else:
                logger.warning("Formula %s step %s has unsupported parameter_type %s",
                               header["formula_name"], sd.get("seq_no"), ptype)
                continue

            steps.append(FormulaStep(
                seq=int(sd["seq_no"]),
                operator=op,
                factor=Decimal(str(sd.get("factor") or 0)),
                parameter_source=parameter_source,
                constant_value=constant_value,
                input_field=input_field,
                reference_table=reference_table,
                condition=_parse_condition(sd.get("condition")),
            ))
        return Formula(formula_name=header["formula_name"],
                       formula_type=header["formula_type"], steps=steps)
    finally:
        cur.close()


def load_fcl_rules(
    conn, tenant_id: str, product_code: str, scheme_id: Optional[str] = None
) -> list[FclRule]:
    """UW_FCL_CONFIG rows for the product (+ scheme). Exposure-group-scoped
    rules and the product/scheme-level rule (exposure_group NULL) are both
    returned; the engine applies per-exposure-group rules first, falling
    back to the product/scheme-level rule."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, exposure_group, fcl_basis, flat_fcl_amount, formula_id,
                   apply_fcl_per_benefit, premium_payer_filter
            FROM uw_fcl_config
            WHERE tenant_id = %s::uuid
              AND product_code = %s
              AND (scheme_id = %s OR scheme_id IS NULL)
              AND is_active = true
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY (scheme_id IS NOT NULL) DESC, (exposure_group IS NOT NULL) DESC
            """,
            (tenant_id, product_code, scheme_id),
        )
        rules: list[FclRule] = []
        for r in cur.fetchall():
            rd = dict(r)
            formula = None
            if rd.get("formula_id") and rd["fcl_basis"] == "FORMULA":
                formula = _load_formula(conn, str(rd["formula_id"]))
            rules.append(FclRule(
                exposure_group=rd.get("exposure_group"),
                fcl_basis=rd["fcl_basis"],
                flat_fcl_amount=(
                    Decimal(str(rd["flat_fcl_amount"])) if rd.get("flat_fcl_amount") is not None else None
                ),
                apply_fcl_per_benefit=bool(rd["apply_fcl_per_benefit"]),
                premium_payer_filter=rd["premium_payer_filter"] or "ANY",
                formula=formula,
            ))
        return rules
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Product config assembly
# ---------------------------------------------------------------------------

def build_product_config(
    conn,
    tenant_id: str,
    product_code: str,
    scheme_id: Optional[str] = None,
    scheme_member_count: Optional[int] = None,
    employer_code: Optional[str] = None,
) -> ProductConfig:
    return ProductConfig(
        product_code=product_code,
        scheme_id=scheme_id,
        aggregation_rules=load_aggregation_rules(conn, tenant_id, product_code),
        fcl_rules=load_fcl_rules(conn, tenant_id, product_code, scheme_id),
        nml_config=load_nml_config(conn, tenant_id, product_code),
        cumulative_config=load_cumulative_config(conn, tenant_id, product_code),
        ri_config=load_ri_config(conn, tenant_id, product_code),
        premium_payer_filter="ANY",
        scheme_member_count=scheme_member_count,
        employer_code=employer_code,
    )


# ---------------------------------------------------------------------------
# RI Config (Phase 4) — retention limits per risk group
# ---------------------------------------------------------------------------

def load_ri_config(
    conn, tenant_id: str, product_code: str
) -> list[RIConfig]:
    """Load RI retention config from ri_reinsurer. Returns list of
    RIConfig for active reinsurers with retention limits."""
    cur = conn.cursor()
    try:
        # ri_reinsurer is a global table (no tenant_id column) — scope by the
        # product_codes[] the reinsurer is configured for instead.
        cur.execute(
            """
            SELECT id, reinsurer_code, reinsurer_name, retention_limit,
                   product_codes, is_active
            FROM ri_reinsurer
            WHERE is_active = true
              AND (product_codes IS NULL OR %s = ANY(product_codes))
              AND (treaty_expiry_date IS NULL OR treaty_expiry_date > CURRENT_DATE)
            ORDER BY retention_limit ASC
            """,
            (product_code,),
        )
        rows = cur.fetchall()
        configs: list[RIConfig] = []
        for r in rows:
            rd = dict(r)
            configs.append(RIConfig(
                risk_group="LIFE",  # Default — in practice would be per risk group
                retention_limit=_dec(rd.get("retention_limit")) or Decimal("0"),
                reinsurer_id=str(rd.get("id")) if rd.get("id") else None,
                is_active=bool(rd.get("is_active", True)),
            ))
        return configs
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Cumulative SAR (Phase 3) — thresholds per risk group
# ---------------------------------------------------------------------------

def load_cumulative_config(
    conn, tenant_id: str, product_code: str
) -> list[CumulativeConfig]:
    """Load cumulative threshold config from uw_risk_group. Each risk group
    defines its threshold_basis and thresholds."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT group_code, uw_threshold_basis, include_existing_policies,
                   include_pending_proposals,
                   auto_refer_threshold, senior_uw_threshold,
                   ri_approval_threshold, decline_threshold
            FROM uw_risk_group
            WHERE tenant_id = %s::uuid
              AND is_active = true
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
        configs: list[CumulativeConfig] = []
        for r in rows:
            rd = dict(r)
            configs.append(CumulativeConfig(
                risk_group=rd["group_code"],
                threshold_basis=rd.get("uw_threshold_basis", "INDIVIDUAL"),
                auto_refer_threshold=_dec(rd.get("auto_refer_threshold")),
                senior_uw_threshold=_dec(rd.get("senior_uw_threshold")),
                ri_approval_threshold=_dec(rd.get("ri_approval_threshold")),
                decline_threshold=_dec(rd.get("decline_threshold")),
                include_existing_policies=bool(rd.get("include_existing_policies", True)),
                include_pending_proposals=bool(rd.get("include_pending_proposals", True)),
            ))
        return configs
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# NML (Phase 2) — medical requirements from excess SAR
# ---------------------------------------------------------------------------

def load_nml_config(
    conn, tenant_id: str, product_code: str
) -> list[NMLConfig]:
    """Load all active NML config rows for a product. The engine will match
    against age + excess SAR per risk group."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT age_min, age_max, sar_min, sar_max, nml_category,
                   medical_tests_required, reinsurer_approval_required
            FROM uw_nml_config
            WHERE tenant_id = %s::uuid
              AND product_code = %s
              AND is_active = true
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY age_min NULLS FIRST, sar_min
            """,
            (tenant_id, product_code),
        )
        rows = cur.fetchall()
        configs: list[NMLConfig] = []
        for r in rows:
            rd = dict(r)
            configs.append(NMLConfig(
                age_min=rd.get("age_min"),
                age_max=rd.get("age_max"),
                sar_min=Decimal(str(rd["sar_min"])) if rd.get("sar_min") is not None else Decimal("0"),
                sar_max=Decimal(str(rd["sar_max"])) if rd.get("sar_max") is not None else None,
                nml_category=rd.get("nml_category", "NON_MEDICAL"),
                medical_tests_required=list(rd.get("medical_tests_required") or []),
                reinsurer_approval_required=bool(rd.get("reinsurer_approval_required")),
            ))
        return configs
    finally:
        cur.close()


def load_nml_medical_requirements(
    conn,
    tenant_id: str,
    product_code: str,
    age: int,
    excess_sar: dict[str, Decimal],
    nml_band_sar: Decimal,
) -> list[str]:
    """Look up UW_NML_CONFIG by (product, age, excess-SAR band). Returns the
    medical tests / requirements applicable to the given excess SAR.

    nml_band_sar is the SAR value to grade (per risk group, the engine caller
    passes the largest relevant exposure-group excess SAR — see sar_service).
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT nml_category, medical_tests_required, reinsurer_approval_required
            FROM uw_nml_config
            WHERE tenant_id = %s::uuid
              AND product_code = %s
              AND (age_min IS NULL OR %s >= age_min)
              AND (age_max IS NULL OR %s <= age_max)
              AND %s >= sar_min
              AND (sar_max IS NULL OR %s <= sar_max)
              AND is_active = true
              AND effective_date <= CURRENT_DATE
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            ORDER BY sar_max NULLS LAST
            LIMIT 1
            """,
            (tenant_id, product_code, age, age, nml_band_sar, nml_band_sar),
        )
        row = _row_dict(cur.fetchone())
        if not row:
            return []
        reqs = list(row.get("medical_tests_required") or [])
        if row.get("reinsurer_approval_required"):
            reqs.append("REINSURER_APPROVAL")
        if row["nml_category"] != "NON_MEDICAL":
            reqs.append(f"NML_{row['nml_category']}")
        return reqs
    finally:
        cur.close()
