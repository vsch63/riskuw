"""
services/sar_service.py
────────────────────────
SAR orchestrator — assembles UW_* config via services.sar_config, runs the
stateless SAREngine, resolves Phase-2 NML medical requirements, and persists
the result to uw_sar_result. Intended to be called from the multi-benefit
proposal evaluation flow (POST /underwriting/evaluate-proposal) before the
per-benefit UW rules engine runs.

Pipeline (SAR design §11, Phase 1/2 scope):
    1. individual SAR per benefit        (engine)
    2. premium payer filter              (engine)
    3. risk-group aggregation            (engine)
    4. exposure-group split              (engine)
    5. FCL check -> excess SAR           (engine)
    6. NML / medical trigger             (here — Phase 2)
    9. excess SAR feeds the UW rules     (caller: underwriting router)
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from services.sar_engine import (
    ApplicantPayload,
    ExposureGroup,
    SAREngine,
)
from services.sar_config import (
    build_product_config,
    load_benefit_lines,
    load_nml_medical_requirements,
)

logger = logging.getLogger(__name__)


def _d(v: Decimal) -> str:
    """Decimal -> JSON-safe string (keeps exactness; frontend parses/rounds)."""
    return str(v)


def _scalar(row) -> Optional[Decimal]:
    """Extract a single SUM()/COUNT() value from a result row, regardless of
    whether the connection's cursor factory returns tuples or dict-like rows
    (RealDictCursor). Returns None for an empty row."""
    if row is None:
        return None
    if hasattr(row, "keys"):  # dict-like (RealDictRow / DictRow)
        if not row:
            return None
        return next(iter(row.values()))
    return row[0]


def resolve_cumulative_sar(
    conn,
    tenant_id: str,
    applicant_ref: str,
    product_code: str,
    cumulative_config,
) -> dict[str, Decimal]:
    """Resolve cumulative SAR for the applicant across existing policies and
    pending proposals. Returns dict of risk_group -> cumulative SAR.

    Reads from:
    - policy table (existing in-force policies)
    - proposal table (pending proposals not yet converted to policy)
    - uw_sar_result (SAR breakdown for each proposal)

    Filters by risk group's uw_threshold_basis:
    - INDIVIDUAL: only same applicant_ref
    - GROUP / GROUP_SCHEME: same group/scheme (would need group membership lookup)
    - CUSTOMER: same customer (if applicant can have multiple refs)
    - EXPOSURE_GROUP: same exposure group
    - PROPOSAL: same proposal only (no cumulative)

    For Phase 3 MVP, implements INDIVIDUAL and GROUP_SCHEME only.
    """
    cumulative: dict[str, Decimal] = defaultdict(Decimal)

    cur = conn.cursor()
    try:
        # Collect applicable SAR sources based on threshold basis
        for cc in cumulative_config:
            basis = cc.threshold_basis
            rg = cc.risk_group

            sar = Decimal("0")

            # 1. Existing policies
            if cc.include_existing_policies:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(sum_assured), 0)
                    FROM policy
                    WHERE tenant_id = %s::uuid
                      AND applicant_ref = %s
                      AND product_code = %s
                      AND status IN ('IN_FORCE', 'ACTIVE', 'PENDING_ACCEPTANCE')
                    """,
                    (tenant_id, applicant_ref, product_code),
                )
                row = _scalar(cur.fetchone())
                if row:
                    sar += Decimal(str(row))

            # 2. Pending proposals (not yet converted to policy)
            if cc.include_pending_proposals:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(pb.face_amount), 0)
                    FROM proposal p
                    JOIN proposal_benefit pb ON p.id = pb.proposal_id
                    WHERE p.tenant_id = %s::uuid
                      AND p.applicant_ref = %s
                      AND pb.product_code = %s
                      AND p.overall_status IN ('SUBMITTED', 'UNDER_REVIEW', 'REFERRED')
                    """,
                    (tenant_id, applicant_ref, product_code),
                )
                row = _scalar(cur.fetchone())
                if row:
                    sar += Decimal(str(row))

            # 3. Prior SAR results (more granular — per risk_group/exposure_group)
            if cc.include_pending_proposals:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(excess_sar), 0)
                    FROM uw_sar_result
                    WHERE tenant_id = %s::uuid
                      AND proposal_id IN (
                          SELECT p.id FROM proposal p
                          JOIN proposal_benefit pb ON p.id = pb.proposal_id
                          WHERE p.tenant_id = %s::uuid
                            AND p.applicant_ref = %s
                            AND pb.product_code = %s
                            AND p.overall_status IN ('SUBMITTED', 'UNDER_REVIEW', 'REFERRED')
                      )
                      AND risk_group = %s
                    """,
                    (tenant_id, tenant_id, applicant_ref, product_code, rg),
                )
                row = _scalar(cur.fetchone())
                if row:
                    sar += Decimal(str(row))

            if sar > 0:
                cumulative[rg] = sar

        return dict(cumulative)
    finally:
        cur.close()


def _persist(
    conn,
    tenant_id: str,
    proposal_id: str,
    product_code: str,
    individual_sar: dict,
    benefits,
    fcl_applied: dict,
    excess_sar: dict,
) -> None:
    """Persist one uw_sar_result row per (risk_group, exposure_group).

    FCL is computed at exposure-group granularity by the engine, so it is
    allocated to each risk group within an exposure group proportionally to
    that risk group's gross SAR in the bucket.
    """
    # bucket gross per (risk_group, exposure_group)
    bucket_gross: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    bucket_benefits: dict[tuple[str, str], list[str]] = defaultdict(list)
    eg_gross: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in benefits:
        eg = b.uw_exposure_group or ExposureGroup.INDIVIDUAL.value
        sar = individual_sar.get(b.benefit_id, Decimal("0"))
        for rg, w in b.risk_group_weights.items():
            weighted = sar * w / Decimal("100")
            key = (rg, eg)
            bucket_gross[key] += weighted
            bucket_benefits[key].append(b.benefit_code)
        eg_gross[eg] += sar

    cur = conn.cursor()
    try:
        for (rg, eg), gross in bucket_gross.items():
            total_eg = eg_gross[eg]
            fcl = fcl_applied.get(eg, Decimal("0"))
            allocated_fcl = (fcl * gross / total_eg) if total_eg > 0 else Decimal("0")
            excess = max(gross - allocated_fcl, Decimal("0"))
            cur.execute(
                """
                INSERT INTO uw_sar_result
                    (tenant_id, proposal_id, risk_group, exposure_group,
                     gross_sar, fcl_applied, excess_sar, source_benefit_ids)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    tenant_id, proposal_id, rg, eg,
                    _d(gross), _d(allocated_fcl), _d(excess),
                    json.dumps(sorted(set(bucket_benefits[(rg, eg)]))),
                ),
            )
    finally:
        cur.close()


def run_sar(
    conn,
    tenant_id: str,
    product_code: str,
    applicant: dict,
    benefits: list[dict],
    scheme_id: Optional[str] = None,
    scheme_member_count: Optional[int] = None,
    employer_code: Optional[str] = None,
    proposal_id: Optional[str] = None,
    proposal_ref: Optional[str] = None,
) -> dict:
    """Run the SAR pipeline for one proposal. Returns a serializable dict.

    Args:
        conn:      psycopg2 connection (caller commits/rolls back).
        tenant_id: tenant UUID string.
        product_code: base product code (for product-level FCL / NML config).
        applicant: dict with at least applicant_ref, age; optional annual_salary.
        benefits:  list of benefit dicts — product_code, face_amount, optional
                   benefit_type, is_base_plan, policy_reserve, fund_value.
        scheme_id / scheme_member_count / employer_code: group-scheme context
                   used by FCL formulas (member-count scale, employer table).
        proposal_id / proposal_ref: for uw_sar_result persistence. Persistence
                   is skipped when proposal_id is None (caller may not persist).
    """
    engine = SAREngine()

    applicant_payload = ApplicantPayload(
        applicant_ref=applicant.get("applicant_ref", "APP"),
        age=int(applicant.get("age") or 0),
        annual_salary=(
            Decimal(str(applicant["annual_salary"])) if applicant.get("annual_salary") is not None else None
        ),
    )

    benefit_lines = load_benefit_lines(conn, tenant_id, benefits)
    if not benefit_lines:
        return {
            "configured": False,
            "error": "No SAR-configured benefits for this proposal",
            "individual_sar": {}, "risk_group_sar": {}, "gross_sar": {},
            "fcl_applied": {}, "excess_sar": {},
            "medical_requirements": [], "auto_approve": {},
        }

    product_config = build_product_config(
        conn, tenant_id, product_code, scheme_id,
        scheme_member_count=scheme_member_count, employer_code=employer_code,
    )

    # Phase 3 — resolve cumulative SAR before engine runs (engine needs it for thresholds)
    cumulative_sar = resolve_cumulative_sar(
        conn, tenant_id, applicant_payload.applicant_ref, product_code,
        product_config.cumulative_config,
    )
    # Inject cumulative SAR into engine result after calculation
    # (engine's _apply_cumulative_thresholds reads result.cumulative_sar)

    result = engine.calculate(applicant_payload, benefit_lines, product_config)
    result.cumulative_sar = cumulative_sar

    # Phase 2 — NML medical requirements (graded on the largest excess SAR).
    medical_requirements: list[str] = []
    if result.excess_sar:
        peak_excess = max(result.excess_sar.values())
        medical_requirements = load_nml_medical_requirements(
            conn, tenant_id, product_code, applicant_payload.age,
            result.excess_sar, peak_excess,
        )

    # Auto-approve per exposure group: gross <= FCL (excess 0) with cover present.
    auto_approve = {
        eg: (result.gross_sar.get(eg, Decimal("0")) > Decimal("0")
             and result.excess_sar.get(eg, Decimal("0")) == Decimal("0"))
        for eg in result.gross_sar
    }
    # Benefit ids whose exposure bucket is fully covered by FCL (the caller
    # may skip full UW evaluation for these). Keyed by the request benefit
    # index injected via "_idx".
    auto_approve_benefit_ids = [
        b.benefit_id for b in benefit_lines
        if auto_approve.get(b.uw_exposure_group or ExposureGroup.INDIVIDUAL.value, False)
        and b.include_in_sar
    ]

    # Persist (only when the caller supplies a proposal id).
    if proposal_id:
        try:
            _persist(
                conn, tenant_id, str(proposal_id), product_code,
                result.individual_sar, benefit_lines,
                result.fcl_applied, result.excess_sar,
            )
        except Exception:
            logger.exception("uw_sar_result persistence failed (non-fatal)")
            conn.rollback()

    return {
        "configured": True,
        "individual_sar": {k: _d(v) for k, v in result.individual_sar.items()},
        "risk_group_sar": {k: _d(v) for k, v in result.risk_group_sar.items()},
        "gross_sar": {k: _d(v) for k, v in result.gross_sar.items()},
        "fcl_applied": {k: _d(v) for k, v in result.fcl_applied.items()},
        "excess_sar": {k: _d(v) for k, v in result.excess_sar.items()},
        "cumulative_sar": {k: _d(v) for k, v in result.cumulative_sar.items()},
        "medical_requirements": medical_requirements,
        "auto_approve": auto_approve,
        "auto_approve_benefit_ids": auto_approve_benefit_ids,
        "ri_approval_required": result.ri_approval_required,
        "escalation": result.escalation,
    }


def persist_sar(
    conn, tenant_id: str, proposal_id: str, sar: dict, request_benefits: list[dict]
) -> bool:
    """Persist a previously computed run_sar result to uw_sar_result once the
    proposal row exists (proposal_id). Re-loads benefit config for the
    (risk_group, exposure_group) bucketing. Returns True on success.

    Best-effort: the caller should not fail the proposal if persistence of
    the SAR breakdown fails (it is a diagnostic/audit detail)."""
    if not sar or not sar.get("configured"):
        return False
    try:
        benefit_lines = load_benefit_lines(conn, tenant_id, request_benefits)
        if not benefit_lines:
            return False
        individual_sar = {k: Decimal(v) for k, v in sar.get("individual_sar", {}).items()}
        fcl_applied = {k: Decimal(v) for k, v in sar.get("fcl_applied", {}).items()}
        excess_sar = {k: Decimal(v) for k, v in sar.get("excess_sar", {}).items()}
        _persist(
            conn, tenant_id, str(proposal_id), "",
            individual_sar, benefit_lines, fcl_applied, excess_sar,
        )
        return True
    except Exception:
        logger.exception("uw_sar_result persistence failed (non-fatal)")
        return False
