"""
RiskUW — Configurable SAR Engine (v2.3)

Ported from the reference implementation in the SAR Framework v2.3 design
package (sar_engine.py) into the RiskUW backend.

Standalone service, per the architectural recommendation in
RiskUW_SAR_Framework_v2.docx §17: not embedded in the underwriting
router, so it can be unit-tested independently and reused across the
individual-evaluate, batch evaluate-proposal, and agent-portal flows.

Implements the 10-step processing sequence from §11, revised to run
the risk_group -> exposure_group split agreed in the design review:

    1. Individual SAR         — per benefit, via sar_formula
    2. Premium Payer Filter   — exclude benefits not matching filter
    3. Risk Group Aggregation — sum/max per risk group (was "clubbing")
    4. Exposure Group Split   — gross SAR broken out by exposure group
    5. FCL Check              — per exposure group (or product/scheme
                                 fallback) -> gross_sar, fcl_applied, excess_sar
    6. NML / Medical Trigger  — excess SAR -> medical requirements
    7. Cumulative SAR         — existing policies + pending proposals
    8. Cumulative Decision    — thresholds -> escalation (REFER/SENIOR/RI/DECLINE)
    9. UW Rules Engine hook   — [existing engine — handled by caller]
   10. RI Retention Check     — [Phase 4 — stubbed]

Phase 1/2/3 scope: steps 1-8 are implemented for real. Steps 9-10
are no-op extension points (steps 9-10 would otherwise raise
NotImplementedError; they are left as no-ops so the caller can wire
Phase 4 behaviour additively without rewriting steps 1-8).

The engine is stateless: all config is passed in as DTOs per call, so
one instance is safe to reuse across tenants and requests. No eval() is
ever used — every step is a typed, structured row.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

# ---------------------------------------------------------------------------
# Enums (kept inlined — the reference models.py is SQLAlchemy-specific and the
# backend uses raw psycopg2; these mirror the design's str-Enum constants)
# ---------------------------------------------------------------------------

from enum import Enum


class SarFormula(str, Enum):
    FACE_AMOUNT = "FACE_AMOUNT"
    SUM_OF_SELECTED = "SUM_OF_SELECTED"
    MAXIMUM_BENEFIT = "MAXIMUM_BENEFIT"
    MORTALITY_PORTION = "MORTALITY_PORTION"
    NET_AMOUNT_AT_RISK = "NET_AMOUNT_AT_RISK"
    PERCENTAGE = "PERCENTAGE"
    EXPRESSION = "EXPRESSION"


class PremiumPayer(str, Enum):
    EMPLOYER = "EMPLOYER"
    EMPLOYEE = "EMPLOYEE"
    JOINT = "JOINT"
    ANY = "ANY"


class ExposureGroup(str, Enum):
    FREE_COVER = "FREE_COVER"
    EXCESS_COVER = "EXCESS_COVER"
    EMPLOYER_BASE = "EMPLOYER_BASE"
    VOLUNTARY_TOPUP = "VOLUNTARY_TOPUP"
    INDIVIDUAL = "INDIVIDUAL"
    OPTIONAL_RIDER = "OPTIONAL_RIDER"


class AggregationMethod(str, Enum):
    SUM = "SUM"
    MAXIMUM = "MAXIMUM"
    WEIGHTED_SUM = "WEIGHTED_SUM"
    CUSTOM_EXPRESSION = "CUSTOM_EXPRESSION"


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

@dataclass
class BenefitLine:
    """One proposal-level benefit, joined with its UW_BENEFIT_MASTER config."""

    benefit_id: str
    benefit_code: str
    sum_assured: Decimal
    premium_payer: str  # PremiumPayer value
    include_in_sar: bool
    sar_formula: str  # SarFormula value
    sar_percentage: Optional[Decimal]
    sar_expression: Optional[str]
    uw_exposure_group: Optional[str]  # ExposureGroup value

    # Risk group membership — resolved from UW_BENEFIT_GROUP_MAP, so a
    # single benefit can contribute to more than one risk group with a
    # weight (e.g. Dread Disease -> 60% LIFE, 40% HEALTH).
    risk_group_weights: dict[str, Decimal] = field(default_factory=dict)

    # v2.2: priority per risk-group membership, mirrors weight above.
    # Lower number = higher priority. Only consulted as a MAXIMUM /
    # CUSTOM_EXPRESSION tie-break; SUM/WEIGHTED_SUM ignore it.
    risk_group_priority: dict[str, int] = field(default_factory=dict)

    # Inputs needed by specific formulas
    policy_reserve: Decimal = Decimal("0")       # MORTALITY_PORTION
    fund_value: Decimal = Decimal("0")            # NET_AMOUNT_AT_RISK


@dataclass
class ApplicantPayload:
    applicant_ref: str
    age: int
    annual_salary: Optional[Decimal] = None


@dataclass
class NMLConfig:
    """Non-Medical Limit configuration row."""
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    sar_min: Decimal = Decimal("0")
    sar_max: Optional[Decimal] = None
    nml_category: str = "NON_MEDICAL"  # NON_MEDICAL, BASIC_MEDICAL, FULL_MEDICAL, JUMBO
    medical_tests_required: list[str] = field(default_factory=list)
    reinsurer_approval_required: bool = False


@dataclass
class CumulativeConfig:
    """Cumulative SAR threshold configuration per risk group."""
    risk_group: str
    threshold_basis: str  # INDIVIDUAL, GROUP, EXPOSURE_GROUP, PROPOSAL, CUSTOMER, GROUP_SCHEME
    auto_refer_threshold: Optional[Decimal] = None
    senior_uw_threshold: Optional[Decimal] = None
    ri_approval_threshold: Optional[Decimal] = None
    decline_threshold: Optional[Decimal] = None
    include_existing_policies: bool = True
    include_pending_proposals: bool = True


@dataclass
class RIConfig:
    """Reinsurance retention configuration per risk group."""
    risk_group: str
    retention_limit: Decimal  # Amount above which cession is required
    reinsurer_id: Optional[str] = None  # UUID of the reinsurer
    is_active: bool = True


@dataclass
class ReferenceTableRow:
    match_type: str  # BAND / EXACT
    band_min: Optional[Decimal] = None
    band_max: Optional[Decimal] = None  # None = no upper bound
    match_value: Optional[str] = None
    output_value: Decimal = Decimal("0")


@dataclass
class ReferenceTable:
    table_code: str
    rows: list[ReferenceTableRow] = field(default_factory=list)

    def lookup(self, key) -> Decimal:
        for row in self.rows:
            if row.match_type == "EXACT" and str(key) == row.match_value:
                return row.output_value
            if row.match_type == "BAND":
                try:
                    numeric_key = Decimal(key)
                except Exception:
                    continue
                if numeric_key >= row.band_min and (row.band_max is None or numeric_key <= row.band_max):
                    return row.output_value
        return Decimal("0")


@dataclass
class FormulaStep:
    seq: int
    operator: str  # ADD / SUBTRACT / MULTIPLY / DIVIDE / PERCENT / IF / ELSE / ENDIF
    factor: Decimal
    parameter_source: str  # CONSTANT / INPUT_FIELD / REFERENCE_TABLE
    constant_value: Optional[Decimal] = None
    input_field: Optional[str] = None
    reference_table: Optional[ReferenceTable] = None
    condition: Optional[dict] = None  # Phase B — typed condition tree on IF steps


@dataclass
class Formula:
    formula_name: str
    formula_type: str
    steps: list[FormulaStep] = field(default_factory=list)


@dataclass
class FclRule:
    """Resolved UW_FCL_CONFIG row applicable to this proposal."""

    exposure_group: Optional[str]  # None = applies at product/scheme level
    fcl_basis: str
    flat_fcl_amount: Optional[Decimal]
    apply_fcl_per_benefit: bool
    premium_payer_filter: str
    formula: Optional[Formula] = None  # v2.3 — used when fcl_basis == FORMULA


@dataclass
class AggregationRule:
    """Resolved UW_AGGREGATION_RULE row. v2.2 — replaces the flat
    risk_group -> method mapping used in v2.1, so aggregation can differ
    by exposure group within the same risk group (e.g. SUM employer-base,
    MAXIMUM voluntary top-up, both within LIFE)."""

    risk_group: str
    exposure_group: Optional[str]  # None = applies to all exposure groups
    product_code: Optional[str]    # None = applies to all products
    aggregation_method: str


@dataclass
class ProductConfig:
    product_code: str
    scheme_id: Optional[str]
    aggregation_rules: list[AggregationRule] = field(default_factory=list)
    fcl_rules: list[FclRule] = field(default_factory=list)
    nml_config: list[NMLConfig] = field(default_factory=list)  # Phase 2
    cumulative_config: list[CumulativeConfig] = field(default_factory=list)  # Phase 3
    ri_config: list[RIConfig] = field(default_factory=list)  # Phase 4
    premium_payer_filter: str = PremiumPayer.ANY.value
    scheme_member_count: Optional[int] = None  # NEW v2.3 — for MEMBER_COUNT scale formulas
    employer_code: Optional[str] = None  # NEW v2.3 — for Employer FCL Table formulas


# ---------------------------------------------------------------------------
# Output DTO
# ---------------------------------------------------------------------------

@dataclass
class SARResult:
    individual_sar: dict[str, Decimal] = field(default_factory=dict)      # benefit_id -> SAR
    risk_group_sar: dict[str, Decimal] = field(default_factory=dict)      # risk_group -> gross SAR
    gross_sar: dict[str, Decimal] = field(default_factory=dict)           # exposure_group -> gross SAR
    fcl_applied: dict[str, Decimal] = field(default_factory=dict)         # exposure_group -> FCL amount used
    excess_sar: dict[str, Decimal] = field(default_factory=dict)          # exposure_group -> post-FCL SAR
    cumulative_sar: dict[str, Decimal] = field(default_factory=dict)      # Phase 3
    medical_requirements: list[str] = field(default_factory=list)         # Phase 2
    ri_approval_required: bool = False                                    # Phase 4
    escalation: Optional[str] = None                                      # Phase 3


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FormulaEngine:
    """Business Formula Engine — Phase A + Phase B.

    Phase A (linear step chain, matches the existing Premium Formula Builder
    UI/semantics: SEQ, OPERATOR, FACTOR, PARAMETER, VALUE/SCALE per step):
        result = 0
        for each step in seq order:
            value = resolve(step.parameter_source, ...)
            result = combine(step.operator, result, step.factor * value)

    Phase B (conditional formulas): an IF step carries a typed condition tree
    (data, not code) and starts a branch block:
        IF  <condition>            -> evaluate; true: run THEN steps
        ELSE                       -> false: run ELSE steps
        ENDIF                      -> block ends, accumulator continues
    Both branches inherit the accumulator value at block entry, so either
    "compute branch result" or "add-on when true" formulas work. Nested
    IF/ELSE/ENDIF blocks are supported.

    Safe by construction: this evaluator never executes carrier-supplied text
    as code (no eval()); every step is a typed, structured row (operator enum
    + typed parameter source) and every condition is a typed JSONB tree.
    """

    def evaluate(self, formula: Formula, context: dict) -> Decimal:
        steps = sorted(formula.steps, key=lambda s: s.seq)
        result = Decimal("0")
        i = 0
        n = len(steps)
        while i < n:
            step = steps[i]
            op = step.operator

            if op == "IF":
                if self._eval_condition(step.condition, context):
                    i += 1  # descend into THEN branch
                else:
                    # Jump past the THEN branch to ELSE (enter it) or ENDIF.
                    found = self._find_block_end(steps, i)
                    if found is None:
                        break  # malformed block (no terminator) — stop
                    j, is_else = found
                    i = j + 1 if is_else else j
                continue

            if op == "ELSE":
                # Reached only after the THEN branch ran — jump to ENDIF.
                found = self._find_block_end(steps, i)
                if found is None:
                    break
                i = found[0]  # terminator at this depth is ENDIF (not ELSE)
                continue

            if op == "ENDIF":
                i += 1
                continue

            value = self._resolve_value(step, context)
            if value is None:
                i += 1
                continue  # missing input for this step — skip, don't zero out the whole formula
            contribution = step.factor * value
            result = self._combine(op, result, contribution)
            i += 1
        return result

    def _find_block_end(self, steps: list, start: int) -> Optional[tuple]:
        """Forward scan from `start` for the first ELSE/ENDIF terminator at
        the same nesting depth as the IF/ELSE at `start`. Returns
        (index, is_else) or None if the block is malformed (unclosed).

        Depth bookkeeping: an inner IF opens a nested block (depth+1) and its
        ENDIF closes it (depth-1); an ELSE is a sibling marker and never
        changes the scan depth."""
        depth = 0
        for j in range(start + 1, len(steps)):
            op = steps[j].operator
            if op == "IF":
                depth += 1
            elif op == "ELSE":
                if depth == 0:
                    return j, True
            elif op == "ENDIF":
                if depth == 0:
                    return j, False
                depth -= 1
        return None

    def _eval_condition(self, condition, context: dict) -> bool:
        """Evaluate a typed condition tree to a boolean. Missing / malformed
        conditions default to False (the step is not taken)."""
        if not isinstance(condition, dict) or not condition.get("clauses"):
            return False
        clauses = condition["clauses"]
        logic = str(condition.get("logic") or "AND").upper()
        results = [self._eval_clause(c, context) for c in clauses]
        verdict = any(results) if logic == "OR" else all(results)
        return (not verdict) if condition.get("negate") else verdict

    def _eval_clause(self, clause, context: dict) -> bool:
        """A clause is either a nested condition tree or a comparison."""
        if isinstance(clause, dict) and "clauses" in clause:
            return self._eval_condition(clause, context)

        field = clause.get("field")
        op = str(clause.get("op") or "EQ").upper()
        lhs = context.get(field)
        if lhs is None:
            return False  # missing input field — condition false (mirrors step skip)

        if op == "BETWEEN":
            lo = self._coerce(clause.get("min"))
            hi = self._coerce(clause.get("max"))
            val = self._coerce(lhs)
            if val is None or lo is None or hi is None:
                return False
            return lo <= val <= hi

        if op in ("IN", "NOT_IN"):
            # list membership — value is a list of comparable operands
            vals = clause.get("value")
            if not isinstance(vals, list):
                return False
            val = self._coerce(lhs)
            if val is None:
                return False
            matched = any(self._coerce(x) == val for x in vals if x is not None)
            return matched if op == "IN" else not matched

        if op in ("CONTAINS_ANY", "NOT_CONTAINS_ANY"):
            # array-field overlap — lhs is a list, value is a list; true when
            # any value appears in lhs. Used for multi-select fields
            # (e.g. hazard_types).
            vals = clause.get("value")
            if not isinstance(lhs, (list, tuple, set)) or not isinstance(vals, list):
                return False
            lhs_set = {self._coerce(x) for x in lhs if x is not None}
            rhs_set = {self._coerce(x) for x in vals if x is not None}
            overlap = bool(lhs_set & rhs_set)
            return overlap if op == "CONTAINS_ANY" else not overlap

        rhs = self._coerce(clause.get("value"))
        if rhs is None:
            return False
        val = self._coerce(lhs)
        if val is None:
            return False

        if op == "EQ":
            return val == rhs
        if op == "NEQ":
            return val != rhs
        if op == "GT":
            return val > rhs
        if op == "GTE":
            return val >= rhs
        if op == "LT":
            return val < rhs
        if op == "LTE":
            return val <= rhs
        return False  # unknown comparison op

    @staticmethod
    def _coerce(v):
        """Normalize a comparison operand for mixed numeric/string compares.
        Numeric strings become Decimal; strings stay strings; other numbers
        become Decimal."""
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, Decimal):
            return v
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, float):
            return Decimal(str(v))
        if isinstance(v, str):
            try:
                return Decimal(v)
            except Exception:
                return v  # non-numeric string — compare as text
        return v

    def _resolve_value(self, step: FormulaStep, context: dict) -> Optional[Decimal]:
        if step.parameter_source == "CONSTANT":
            return step.constant_value

        if step.parameter_source == "INPUT_FIELD":
            return context.get(step.input_field)

        if step.parameter_source == "REFERENCE_TABLE":
            if step.reference_table is None or step.input_field is None:
                return None
            key = context.get(step.input_field)
            if key is None:
                return None
            return step.reference_table.lookup(key)

        raise ValueError(f"Unknown parameter_source '{step.parameter_source}'")

    def _combine(self, operator: str, result: Decimal, contribution: Decimal) -> Decimal:
        if operator == "ADD":
            return result + contribution
        if operator == "SUBTRACT":
            return result - contribution
        if operator == "MULTIPLY":
            return result * contribution
        if operator == "DIVIDE":
            if contribution == 0:
                return result
            return result / contribution
        if operator == "PERCENT":
            return result * (contribution / Decimal(100))
        raise ValueError(f"Unknown operator '{operator}'")


class SAREngine:
    """Configurable Sum-at-Risk calculator. Stateless — all config is
    passed in per call, so one instance is safe to reuse across tenants
    and requests."""

    def calculate(
        self,
        applicant: ApplicantPayload,
        benefits: list[BenefitLine],
        product_config: ProductConfig,
        include_existing: bool = True,
    ) -> SARResult:
        result = SARResult()

        # Step 1: Individual SAR per benefit
        result.individual_sar = self._calculate_individual_sar(benefits)

        # Step 2: Premium Payer Filter (product-level default filter;
        # per-benefit exposure_group filtering happens implicitly via
        # step 4's grouping)
        filtered_benefits = self._apply_premium_payer_filter(
            benefits, product_config.premium_payer_filter
        )

        # Step 3: Risk Group Aggregation (was "clubbing" in v2.0). v2.2:
        # resolved per (risk_group, exposure_group, product) via
        # AggregationRule rather than a flat per-risk-group method.
        result.risk_group_sar = self._aggregate_by_risk_group(
            filtered_benefits, result.individual_sar, product_config
        )

        # Step 4: Exposure Group Split — gross SAR by exposure group.
        # This is the new step vs. v2.0: instead of FCL being applied
        # directly to risk_group_sar, we first re-bucket by
        # uw_exposure_group so FCL rules scoped to e.g. VOLUNTARY_TOPUP
        # only touch that bucket.
        result.gross_sar = self._split_by_exposure_group(
            filtered_benefits, result.individual_sar
        )

        # Step 5: FCL Check — per exposure group where a rule exists,
        # else fall back to product/scheme-level rule (None exposure_group).
        result.fcl_applied, result.excess_sar = self._apply_fcl(
            result.gross_sar, product_config.fcl_rules, applicant, product_config
        )

        # Step 6: NML / Medical Trigger — Phase 2
        self._apply_nml_medical_trigger(result, applicant, product_config)

        # Step 7: Cumulative SAR — Phase 3
        self._apply_cumulative_sar(applicant, result, include_existing, product_config)

        # Step 8: Cumulative Decision — Phase 3
        self._apply_cumulative_thresholds(result, product_config)

        # Step 10: RI Retention Check — Phase 4
        self._apply_ri_retention_check(result, product_config)

        return result

    # ------------------------------------------------------------------
    # Step 1
    # ------------------------------------------------------------------

    def _calculate_individual_sar(self, benefits: list[BenefitLine]) -> dict[str, Decimal]:
        sar_by_benefit: dict[str, Decimal] = {}
        for benefit in benefits:
            if not benefit.include_in_sar:
                sar_by_benefit[benefit.benefit_id] = Decimal("0")
                continue
            sar_by_benefit[benefit.benefit_id] = self._apply_sar_formula(benefit)
        return sar_by_benefit

    def _apply_sar_formula(self, benefit: BenefitLine) -> Decimal:
        formula = benefit.sar_formula
        if formula == SarFormula.FACE_AMOUNT.value:
            return benefit.sum_assured
        if formula == SarFormula.MORTALITY_PORTION.value:
            return max(benefit.sum_assured - benefit.policy_reserve, Decimal("0"))
        if formula == SarFormula.NET_AMOUNT_AT_RISK.value:
            return max(max(benefit.sum_assured, benefit.fund_value) - benefit.fund_value, Decimal("0"))
        if formula == SarFormula.PERCENTAGE.value:
            pct = benefit.sar_percentage or Decimal("0")
            return benefit.sum_assured * pct / Decimal("100")
        if formula == SarFormula.SUM_OF_SELECTED.value:
            # Resolved at aggregation time (step 3) — individual value is
            # the raw face amount here.
            return benefit.sum_assured
        if formula == SarFormula.MAXIMUM_BENEFIT.value:
            # Same — resolved at aggregation time.
            return benefit.sum_assured
        if formula == SarFormula.EXPRESSION.value:
            raise NotImplementedError(
                f"EXPRESSION formula for benefit {benefit.benefit_code} is a "
                "Phase 6 (Advanced) feature — see roadmap §15/§16."
            )
        raise ValueError(f"Unknown sar_formula '{formula}' on benefit {benefit.benefit_code}")

    # ------------------------------------------------------------------
    # Step 2
    # ------------------------------------------------------------------

    def _apply_premium_payer_filter(
        self, benefits: list[BenefitLine], payer_filter: str
    ) -> list[BenefitLine]:
        if payer_filter == PremiumPayer.ANY.value:
            return benefits
        if payer_filter == "EXCLUDE_EMPLOYER":
            return [b for b in benefits if b.premium_payer != PremiumPayer.EMPLOYER.value]
        return [b for b in benefits if b.premium_payer == payer_filter]

    # ------------------------------------------------------------------
    # Step 3
    # ------------------------------------------------------------------

    def _aggregate_by_risk_group(
        self,
        benefits: list[BenefitLine],
        individual_sar: dict[str, Decimal],
        product_config: ProductConfig,
    ) -> dict[str, Decimal]:
        """v2.2: benefits are first bucketed by (risk_group, exposure_group)
        so aggregation method can differ per exposure group within the same
        risk group (e.g. SUM employer-base, MAXIMUM voluntary top-up, both
        feeding into the same LIFE risk_group_sar total)."""
        subgroups: dict[tuple[str, str], list[tuple[Decimal, int]]] = defaultdict(list)

        for benefit in benefits:
            exposure_group = benefit.uw_exposure_group or ExposureGroup.INDIVIDUAL.value
            benefit_sar = individual_sar.get(benefit.benefit_id, Decimal("0"))
            for risk_group, weight_pct in benefit.risk_group_weights.items():
                weighted = benefit_sar * weight_pct / Decimal("100")
                priority = benefit.risk_group_priority.get(risk_group, 100)
                subgroups[(risk_group, exposure_group)].append((weighted, priority))

        risk_group_sar: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for (risk_group, exposure_group), values in subgroups.items():
            method = self._resolve_aggregation_method(product_config, risk_group, exposure_group)
            risk_group_sar[risk_group] += self._apply_aggregation(method, values, risk_group)

        return dict(risk_group_sar)

    def _resolve_aggregation_method(
        self, product_config: ProductConfig, risk_group: str, exposure_group: str
    ) -> str:
        """Most-specific-match resolution: (product + exposure_group) beats
        (exposure_group only) beats the risk-group-wide default. Mirrors
        the precedence pattern already used for FCL rules in step 5."""
        best_score = -1
        best_method = AggregationMethod.SUM.value
        for rule in product_config.aggregation_rules:
            if rule.risk_group != risk_group:
                continue
            if rule.product_code not in (None, product_config.product_code):
                continue
            if rule.exposure_group not in (None, exposure_group):
                continue
            score = (2 if rule.product_code else 0) + (1 if rule.exposure_group else 0)
            if score > best_score:
                best_score = score
                best_method = rule.aggregation_method
        return best_method

    def _apply_aggregation(
        self, method: str, values: list[tuple[Decimal, int]], risk_group: str
    ) -> Decimal:
        amounts = [v[0] for v in values]
        if method in (AggregationMethod.SUM.value, AggregationMethod.WEIGHTED_SUM.value):
            # Weighting already applied per-benefit before this point;
            # WEIGHTED_SUM and SUM are equivalent once weights are baked in.
            return sum(amounts, Decimal("0"))
        if method == AggregationMethod.MAXIMUM.value:
            if not values:
                return Decimal("0")
            max_amount = max(amounts)
            tied = [v for v in values if v[0] == max_amount]
            if len(tied) > 1:
                tied.sort(key=lambda v: v[1])  # lower priority number wins the tie
            return tied[0][0]
        raise NotImplementedError(
            f"aggregation_method '{method}' for risk group '{risk_group}' "
            "is a Phase 6 (Advanced) feature."
        )

    # ------------------------------------------------------------------
    # Step 4 — NEW vs v2.0
    # ------------------------------------------------------------------

    def _split_by_exposure_group(
        self, benefits: list[BenefitLine], individual_sar: dict[str, Decimal]
    ) -> dict[str, Decimal]:
        """Re-bucket individual SAR by uw_exposure_group. A benefit with
        no uw_exposure_group set falls into INDIVIDUAL by default, which
        preserves v2.0 behaviour (no exposure-group-scoped FCL, product/
        scheme-level FCL rule applies instead)."""
        gross_by_exposure: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for benefit in benefits:
            group = benefit.uw_exposure_group or ExposureGroup.INDIVIDUAL.value
            gross_by_exposure[group] += individual_sar.get(benefit.benefit_id, Decimal("0"))
        return dict(gross_by_exposure)

    # ------------------------------------------------------------------
    # Step 5
    # ------------------------------------------------------------------

    def _apply_fcl(
        self,
        gross_sar: dict[str, Decimal],
        fcl_rules: list[FclRule],
        applicant: ApplicantPayload,
        product_config: ProductConfig,
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        rules_by_exposure = {r.exposure_group: r for r in fcl_rules}
        product_level_rule = rules_by_exposure.get(None)

        fcl_applied: dict[str, Decimal] = {}
        excess_sar: dict[str, Decimal] = {}

        for exposure_group, gross in gross_sar.items():
            rule = rules_by_exposure.get(exposure_group, product_level_rule)
            fcl_amount = (
                self._resolve_fcl_amount(rule, applicant, product_config) if rule else Decimal("0")
            )
            fcl_applied[exposure_group] = fcl_amount
            excess_sar[exposure_group] = max(gross - fcl_amount, Decimal("0"))

        return fcl_applied, excess_sar

    def _resolve_fcl_amount(
        self, rule: FclRule, applicant: ApplicantPayload, product_config: ProductConfig
    ) -> Decimal:
        if rule.fcl_basis == "FLAT":
            return rule.flat_fcl_amount or Decimal("0")

        if rule.fcl_basis == "FORMULA":
            # v2.3 — replaces the bespoke SALARY_MULTIPLE / AGE_BAND /
            # MEMBER_COUNT_SCALE / SALARY_BAND_SCALE bases. Salary
            # multiples, age scales, member-count scales, and employer
            # tables are all just formulas now; see §6C.
            if rule.formula is None:
                return Decimal("0")
            context = self._build_formula_context(applicant, product_config)
            return FormulaEngine().evaluate(rule.formula, context)

        raise NotImplementedError(
            f"fcl_basis '{rule.fcl_basis}' is not recognized. Only FLAT and "
            "FORMULA are supported as of v2.3 — see roadmap §16."
        )

    def _build_formula_context(
        self, applicant: ApplicantPayload, product_config: ProductConfig
    ) -> dict:
        return {
            "age": Decimal(applicant.age),
            "annual_salary": applicant.annual_salary,
            "scheme_member_count": (
                Decimal(product_config.scheme_member_count)
                if product_config.scheme_member_count is not None
                else None
            ),
            "employer_code": product_config.employer_code,
        }

    # ------------------------------------------------------------------
    # Steps 6-10 — extension points for later phases
    # ------------------------------------------------------------------

    def _apply_nml_medical_trigger(
        self, result: SARResult, applicant: ApplicantPayload, product_config: ProductConfig
    ) -> None:
        """Phase 2: Look up UW_NML_CONFIG by (age, excess_sar per risk group)
        and populate result.medical_requirements."""
        if not product_config.nml_config:
            return
        applicant_age = applicant.age
        for nml in product_config.nml_config:
            # Age band match
            if nml.age_min is not None and applicant_age < nml.age_min:
                continue
            if nml.age_max is not None and applicant_age > nml.age_max:
                continue
            # SAR band match: we check each exposure group's excess SAR
            # If ANY exposure group's excess SAR falls in the band, the requirement applies
            for eg, excess in result.excess_sar.items():
                if excess < nml.sar_min:
                    continue
                if nml.sar_max is not None and excess > nml.sar_max:
                    continue
                # Matched: add medical requirements
                if nml.nml_category != "NON_MEDICAL":
                    result.medical_requirements.append(f"NML_{nml.nml_category}")
                for test in nml.medical_tests_required:
                    if test not in result.medical_requirements:
                        result.medical_requirements.append(test)
                if nml.reinsurer_approval_required and "REINSURER_APPROVAL" not in result.medical_requirements:
                    result.medical_requirements.append("REINSURER_APPROVAL")

    def _apply_cumulative_sar(
        self, applicant: ApplicantPayload, result: SARResult, include_existing: bool,
        product_config: ProductConfig
    ) -> None:
        """Phase 3: Query existing policies and pending proposals to populate
        result.cumulative_sar per risk group."""
        if not product_config.cumulative_config:
            return
        # The engine is stateless and doesn't have DB access.
        # The caller (sar_service) should pre-load cumulative SAR and pass it in.
        # For now, this is a no-op; the service layer will call a separate
        # cumulative SAR resolution function that has DB access.
        # See services.sar_service.resolve_cumulative_sar()
        pass

    def _apply_cumulative_thresholds(self, result: SARResult, product_config: ProductConfig) -> None:
        """Phase 3: Apply UW_CUMULATIVE_THRESHOLD and set
        result.escalation (REFER / SENIOR_UW / RI_APPROVAL / DECLINE)."""
        if not product_config.cumulative_config:
            return
        for cc in product_config.cumulative_config:
            cumulative = result.cumulative_sar.get(cc.risk_group, Decimal("0"))
            current = result.risk_group_sar.get(cc.risk_group, Decimal("0"))
            total = cumulative + current

            # Check thresholds in order of severity
            if cc.decline_threshold is not None and total >= cc.decline_threshold:
                result.escalation = "DECLINE"
                break
            if cc.ri_approval_threshold is not None and total >= cc.ri_approval_threshold:
                result.escalation = "RI_APPROVAL"
                break
            if cc.senior_uw_threshold is not None and total >= cc.senior_uw_threshold:
                result.escalation = "SENIOR_UW"
                break
            if cc.auto_refer_threshold is not None and total >= cc.auto_refer_threshold:
                result.escalation = "REFER"
                break

    def _apply_ri_retention_check(self, result: SARResult, product_config: ProductConfig) -> None:
        """Phase 4: Compare total excess SAR against RI retention limits and
        set result.ri_approval_required when the net amount at risk (after
        Free Cover Limit) exceeds the reinsurer's retention.

        excess_sar is keyed by exposure group, so the check runs against the
        sum across all exposure groups."""
        if not product_config.ri_config:
            return

        total_excess = sum(result.excess_sar.values()) if result.excess_sar else Decimal("0")
        for ri in product_config.ri_config:
            if not ri.is_active:
                continue
            if total_excess > ri.retention_limit:
                result.ri_approval_required = True
                break
