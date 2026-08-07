"""
backend/tests/test_sar_engine_regression.py
───────────────────────────────────────────
Regression tests for the ported SAR engine and the Business Formula Engine
(Phase A). test_sar_engine.py mirrors the reference package's test suite
1:1; this file locks in RiskUW-specific behaviour beyond the reference
cases — edge conditions that the port could silently break on later edits.

Pure unit tests: no DB, no HTTP. Everything is exercised through the
stateless DTO API (services.sar_engine).
"""
from decimal import Decimal

from services.sar_engine import (
    AggregationRule,
    ApplicantPayload,
    BenefitLine,
    FclRule,
    Formula,
    FormulaEngine,
    FormulaStep,
    ProductConfig,
    ReferenceTable,
    ReferenceTableRow,
    SAREngine,
)


def _benefit(benefit_id, benefit_code, sum_assured, **kw):
    """Minimal BenefitLine factory — defaults a benefit to LIFE/100%,
    FACE_AMOUNT, EMPLOYEE-paid, included in SAR, VOLUNTARY_TOPUP exposure."""
    defaults = dict(
        premium_payer="EMPLOYEE",
        include_in_sar=True,
        sar_formula="FACE_AMOUNT",
        sar_percentage=None,
        sar_expression=None,
        uw_exposure_group="VOLUNTARY_TOPUP",
        risk_group_weights={"LIFE": Decimal("100")},
    )
    defaults.update(kw)
    return BenefitLine(
        benefit_id=benefit_id, benefit_code=benefit_code,
        sum_assured=sum_assured, **defaults,
    )


def _liferules(*rules):
    return [AggregationRule(
        risk_group="LIFE", exposure_group=None, product_code=None,
        aggregation_method="SUM",
    )] + list(rules)


# ---------------------------------------------------------------------------
# FormulaEngine (Phase A) — no reference tests covered this new component
# ---------------------------------------------------------------------------

def test_formula_multi_step_operator_chain():
    """ADD/SUBTRACT/MULTIPLY/DIVIDE compose on the running total in seq
    order: ((0 + 100) - 30) * 2 / 5 = 28."""
    formula = Formula(
        formula_name="chain", formula_type="FCL",
        steps=[
            FormulaStep(seq=10, operator="ADD", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("100")),
            FormulaStep(seq=20, operator="SUBTRACT", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("30")),
            FormulaStep(seq=30, operator="MULTIPLY", factor=Decimal("2"), parameter_source="CONSTANT", constant_value=Decimal("1")),
            FormulaStep(seq=40, operator="DIVIDE", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("5")),
        ],
    )
    assert FormulaEngine().evaluate(formula, {}) == Decimal("28")


def test_formula_steps_applied_in_seq_order_even_if_input_order_reversed():
    """Steps are evaluated by seq, not by list order. seq 20 first in the
    list must still run after seq 10."""
    formula = Formula(
        formula_name="reordered", formula_type="FCL",
        steps=[
            FormulaStep(seq=20, operator="SUBTRACT", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("30")),
            FormulaStep(seq=10, operator="ADD", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("100")),
        ],
    )
    assert FormulaEngine().evaluate(formula, {}) == Decimal("70")


def test_formula_missing_input_field_skips_step_not_zeroes():
    """A step whose input field is absent from the context is skipped;
    the rest of the formula still evaluates (missing input must not zero
    out the whole result)."""
    formula = Formula(
        formula_name="skip-missing", formula_type="FCL",
        steps=[
            FormulaStep(seq=10, operator="ADD", factor=Decimal("5"), parameter_source="INPUT_FIELD", input_field="annual_salary"),
            FormulaStep(seq=20, operator="ADD", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("100")),
        ],
    )
    assert FormulaEngine().evaluate(formula, {"age": 40}) == Decimal("100")


def test_formula_divide_by_zero_keeps_result():
    """DIVIDE with a zero contribution must not raise ZeroDivisionError —
    the engine treats it as a no-op that leaves the running total intact."""
    formula = Formula(
        formula_name="zero-divide", formula_type="FCL",
        steps=[
            FormulaStep(seq=10, operator="ADD", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("100")),
            FormulaStep(seq=20, operator="DIVIDE", factor=Decimal("1"), parameter_source="INPUT_FIELD", input_field="annual_salary"),
        ],
    )
    assert FormulaEngine().evaluate(formula, {"annual_salary": Decimal("0")}) == Decimal("100")


def test_formula_percent_operator_takes_percentage_of_running_result():
    """PERCENT scales the running total by contribution/100 — same semantics
    as the premium engine's '%'. 200 * (50/100) = 100."""
    formula = Formula(
        formula_name="pct", formula_type="FCL",
        steps=[
            FormulaStep(seq=10, operator="ADD", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("200")),
            FormulaStep(seq=20, operator="PERCENT", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("50")),
        ],
    )
    assert FormulaEngine().evaluate(formula, {}) == Decimal("100")


def test_formula_percent_with_factor_scales_contribution_first():
    """factor is applied before the percentage: 200 * (3 * 10/100) = 60."""
    formula = Formula(
        formula_name="pct-factor", formula_type="FCL",
        steps=[
            FormulaStep(seq=10, operator="ADD", factor=Decimal("1"), parameter_source="CONSTANT", constant_value=Decimal("200")),
            FormulaStep(seq=20, operator="PERCENT", factor=Decimal("3"), parameter_source="CONSTANT", constant_value=Decimal("10")),
        ],
    )
    assert FormulaEngine().evaluate(formula, {}) == Decimal("60")


def test_reference_table_band_is_inclusive_and_open_ended():
    """BAND rows match on both edges; band_max=None is an open upper bound.
    49 hits the 1-49 band, 50 and 99 hit the 50-99 band, 100 falls in the
    gap between 99 and 500, and 500+ hits the open band."""
    table = ReferenceTable(table_code="SCALE", rows=[
        ReferenceTableRow(match_type="BAND", band_min=Decimal("1"), band_max=Decimal("49"), output_value=Decimal("500000")),
        ReferenceTableRow(match_type="BAND", band_min=Decimal("50"), band_max=Decimal("99"), output_value=Decimal("1000000")),
        ReferenceTableRow(match_type="BAND", band_min=Decimal("500"), band_max=None, output_value=Decimal("5000000")),
    ])
    assert table.lookup(49) == Decimal("500000")
    assert table.lookup(50) == Decimal("1000000")
    assert table.lookup(99) == Decimal("1000000")
    assert table.lookup(100) == Decimal("0")
    assert table.lookup(500) == Decimal("5000000")
    assert table.lookup(99999) == Decimal("5000000")


def test_reference_table_exact_miss_returns_zero():
    """EXACT rows only match the literal value; anything else is a miss
    that yields 0 (no exception)."""
    table = ReferenceTable(table_code="EMPLOYER", rows=[
        ReferenceTableRow(match_type="EXACT", match_value="ABC", output_value=Decimal("10000000")),
    ])
    assert table.lookup("ABC") == Decimal("10000000")
    assert table.lookup("XYZ") == Decimal("0")


def test_reference_table_band_with_non_numeric_key_is_skipped():
    """A non-numeric key evaluated against a BAND table must not raise;
    it falls through to 0."""
    table = ReferenceTable(table_code="SCALE", rows=[
        ReferenceTableRow(match_type="BAND", band_min=Decimal("1"), band_max=Decimal("49"), output_value=Decimal("500000")),
    ])
    assert table.lookup("NOT-A-NUMBER") == Decimal("0")


# ---------------------------------------------------------------------------
# SAREngine — step 2 (premium payer filter)
# ---------------------------------------------------------------------------

def test_premium_payer_filter_restricts_aggregation_not_individual_sar():
    """Step 1 always computes individual SAR for every benefit; step 2 then
    drops non-matching payers from risk-group and exposure-group buckets.
    A filtered-out benefit must still appear in individual_sar."""
    applicant = ApplicantPayload(applicant_ref="APP-PF", age=40)
    benefits = [
        _benefit("E1", "GRP_TERM", Decimal("4000000"), premium_payer="EMPLOYER",
                 uw_exposure_group="EMPLOYER_BASE"),
        _benefit("E2", "GRP_TERM", Decimal("1000000"), premium_payer="EMPLOYEE",
                 uw_exposure_group="VOLUNTARY_TOPUP"),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[],
        premium_payer_filter="EMPLOYER",
    )
    result = SAREngine().calculate(applicant, benefits, config)

    # Step 1 — unfiltered
    assert result.individual_sar["E2"] == Decimal("1000000")
    # Step 3/4 — only the EMPLOYER benefit survives the filter
    assert result.risk_group_sar["LIFE"] == Decimal("4000000")
    assert set(result.gross_sar) == {"EMPLOYER_BASE"}


def test_premium_payer_filter_exclude_employer():
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[],
        premium_payer_filter="EXCLUDE_EMPLOYER",
    )
    benefits = [
        _benefit("E1", "GRP_TERM", Decimal("4000000"), premium_payer="EMPLOYER",
                 uw_exposure_group="EMPLOYER_BASE"),
        _benefit("E2", "GRP_TERM", Decimal("1000000"), premium_payer="EMPLOYEE",
                 uw_exposure_group="VOLUNTARY_TOPUP"),
    ]
    result = SAREngine().calculate(
        ApplicantPayload(applicant_ref="APP-PF2", age=40), benefits, config)
    assert result.risk_group_sar["LIFE"] == Decimal("1000000")


# ---------------------------------------------------------------------------
# SAREngine — step 4 (exposure group split) / step 5 (FCL)
# ---------------------------------------------------------------------------

def test_missing_exposure_group_defaults_to_individual():
    """A benefit with no uw_exposure_group lands in the INDIVIDUAL bucket
    (v2.0 compatibility), and a product-level FCL rule applies to it."""
    applicant = ApplicantPayload(applicant_ref="APP-EG", age=40)
    benefits = [
        _benefit("E1", "GRP_TERM", Decimal("3000000"), uw_exposure_group=None),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[
            FclRule(exposure_group=None, fcl_basis="FLAT",
                    flat_fcl_amount=Decimal("2000000"),
                    apply_fcl_per_benefit=False, premium_payer_filter="ANY"),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)

    assert result.gross_sar == {"INDIVIDUAL": Decimal("3000000")}
    assert result.risk_group_sar["LIFE"] == Decimal("3000000")
    assert result.fcl_applied["INDIVIDUAL"] == Decimal("2000000")
    assert result.excess_sar["INDIVIDUAL"] == Decimal("1000000")


def test_product_level_fcl_falls_back_to_every_exposure_group():
    """A rule with exposure_group=None is the product/scheme-level rule and
    applies to every exposure group that lacks its own rule."""
    applicant = ApplicantPayload(applicant_ref="APP-FCL", age=40)
    benefits = [
        _benefit("E1", "GRP_TERM", Decimal("3000000"), uw_exposure_group="EMPLOYER_BASE"),
        _benefit("E2", "GRP_TERM", Decimal("1000000"), uw_exposure_group="VOLUNTARY_TOPUP"),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[
            FclRule(exposure_group=None, fcl_basis="FLAT",
                    flat_fcl_amount=Decimal("2000000"),
                    apply_fcl_per_benefit=False, premium_payer_filter="ANY"),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)

    assert result.fcl_applied["EMPLOYER_BASE"] == Decimal("2000000")
    assert result.fcl_applied["VOLUNTARY_TOPUP"] == Decimal("2000000")
    assert result.excess_sar["EMPLOYER_BASE"] == Decimal("1000000")
    assert result.excess_sar["VOLUNTARY_TOPUP"] == Decimal("0")  # fully covered


def test_exposure_group_fcl_beats_product_level_fallback():
    """A rule scoped to one exposure group wins for that group; other groups
    fall back to the product-level rule."""
    applicant = ApplicantPayload(applicant_ref="APP-FCL2", age=40)
    benefits = [
        _benefit("E1", "GRP_TERM", Decimal("3000000"), uw_exposure_group="EMPLOYER_BASE"),
        _benefit("E2", "GRP_TERM", Decimal("1000000"), uw_exposure_group="VOLUNTARY_TOPUP"),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[
            FclRule(exposure_group=None, fcl_basis="FLAT",
                    flat_fcl_amount=Decimal("5000000"),
                    apply_fcl_per_benefit=False, premium_payer_filter="ANY"),
            FclRule(exposure_group="VOLUNTARY_TOPUP", fcl_basis="FLAT",
                    flat_fcl_amount=Decimal("500000"),
                    apply_fcl_per_benefit=False, premium_payer_filter="ANY"),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)

    assert result.fcl_applied["VOLUNTARY_TOPUP"] == Decimal("500000")   # own rule
    assert result.excess_sar["VOLUNTARY_TOPUP"] == Decimal("500000")
    assert result.fcl_applied["EMPLOYER_BASE"] == Decimal("5000000")    # fallback
    assert result.excess_sar["EMPLOYER_BASE"] == Decimal("0")


def test_auto_approve_when_gross_under_fcl():
    """gross <= FCL means excess 0 for the bucket (the auto-approve case the
    caller keys off)."""
    applicant = ApplicantPayload(applicant_ref="APP-AA", age=40)
    benefits = [_benefit("E1", "GRP_TERM", Decimal("2000000"))]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[
            FclRule(exposure_group=None, fcl_basis="FLAT",
                    flat_fcl_amount=Decimal("5000000"),
                    apply_fcl_per_benefit=False, premium_payer_filter="ANY"),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.excess_sar["VOLUNTARY_TOPUP"] == Decimal("0")


# ---------------------------------------------------------------------------
# SAREngine — step 3 (risk group aggregation)
# ---------------------------------------------------------------------------

def test_weighted_risk_group_membership_splits_sar():
    """A benefit mapped 60% LIFE / 40% HEALTH contributes proportionally to
    both risk groups, while its exposure-group gross SAR stays the full
    amount (unweighted)."""
    applicant = ApplicantPayload(applicant_ref="APP-W", age=40)
    benefits = [
        _benefit("B1", "CI", Decimal("1000000"),
                 risk_group_weights={"LIFE": Decimal("60"), "HEALTH": Decimal("40")}),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=[
            AggregationRule(risk_group="LIFE", exposure_group=None, product_code=None, aggregation_method="SUM"),
            AggregationRule(risk_group="HEALTH", exposure_group=None, product_code=None, aggregation_method="SUM"),
        ],
        fcl_rules=[],
    )
    result = SAREngine().calculate(applicant, benefits, config)

    assert result.risk_group_sar["LIFE"] == Decimal("600000")
    assert result.risk_group_sar["HEALTH"] == Decimal("400000")
    assert result.gross_sar["VOLUNTARY_TOPUP"] == Decimal("1000000")


def test_maximum_aggregation_takes_largest_amount():
    """MAXIMUM picks the largest SAR; priority is only a tie-breaker, so with
    unequal amounts the higher-priority rider is irrelevant."""
    applicant = ApplicantPayload(applicant_ref="APP-MAX", age=40)
    benefits = [
        _benefit("R1", "ADB", Decimal("2000000"),
                 risk_group_weights={"ACCIDENT": Decimal("100")},
                 risk_group_priority={"ACCIDENT": 1}),
        _benefit("R2", "ATPD", Decimal("3000000"),
                 risk_group_weights={"ACCIDENT": Decimal("100")},
                 risk_group_priority={"ACCIDENT": 9}),
    ]
    config = ProductConfig(
        product_code="GRP-PA-1", scheme_id=None,
        aggregation_rules=[
            AggregationRule(risk_group="ACCIDENT", exposure_group=None, product_code=None, aggregation_method="MAXIMUM"),
        ],
        fcl_rules=[],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.risk_group_sar["ACCIDENT"] == Decimal("3000000")


def test_aggregation_specificity_precedence_product_exposure_beats_exposure_only():
    """Most-specific rule wins: (product + exposure group) beats
    (exposure group only) beats the risk-group default. A product-scoped SUM
    therefore overrides an exposure-group-scoped MAXIMUM for that product."""
    applicant = ApplicantPayload(applicant_ref="APP-PREC", age=40)
    benefits = [
        _benefit("B1", "ADB", Decimal("2000000"),
                 risk_group_weights={"ACCIDENT": Decimal("100")}),
        _benefit("B2", "ATPD", Decimal("3000000"),
                 risk_group_weights={"ACCIDENT": Decimal("100")}),
    ]
    config = ProductConfig(
        product_code="GRP-PA-1", scheme_id=None,
        aggregation_rules=[
            AggregationRule(risk_group="ACCIDENT", exposure_group=None, product_code=None, aggregation_method="SUM"),
            AggregationRule(risk_group="ACCIDENT", exposure_group="VOLUNTARY_TOPUP", product_code=None, aggregation_method="MAXIMUM"),
            AggregationRule(risk_group="ACCIDENT", exposure_group="VOLUNTARY_TOPUP", product_code="GRP-PA-1", aggregation_method="SUM"),
        ],
        fcl_rules=[],
    )
    # (product + exposure) SUM wins -> 2L + 3L = 5L
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.risk_group_sar["ACCIDENT"] == Decimal("5000000")

    # Drop the product-scoped rule -> (exposure only) MAXIMUM -> 3L
    config.aggregation_rules.pop()
    result2 = SAREngine().calculate(applicant, benefits, config)
    assert result2.risk_group_sar["ACCIDENT"] == Decimal("3000000")

    # Drop the exposure-scoped rule too -> risk-group default SUM -> 5L
    config.aggregation_rules.pop()
    result3 = SAREngine().calculate(applicant, benefits, config)
    assert result3.risk_group_sar["ACCIDENT"] == Decimal("5000000")


# ---------------------------------------------------------------------------
# SAREngine — step 1 (individual SAR formula variants)
# ---------------------------------------------------------------------------

def test_mortality_portion_floors_at_zero():
    """MORTALITY_PORTION = max(sum_assured - policy_reserve, 0); a reserve
    above the sum assured yields 0, not a negative SAR."""
    applicant = ApplicantPayload(applicant_ref="APP-MP", age=40)
    benefits = [
        _benefit("B1", "ENDOW", Decimal("500000"),
                 sar_formula="MORTALITY_PORTION", policy_reserve=Decimal("800000")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.individual_sar["B1"] == Decimal("0")
    assert result.risk_group_sar["LIFE"] == Decimal("0")


def test_percentage_formula():
    applicant = ApplicantPayload(applicant_ref="APP-PCT", age=40)
    benefits = [
        _benefit("B1", "CI", Decimal("800000"),
                 sar_formula="PERCENTAGE", sar_percentage=Decimal("25")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.individual_sar["B1"] == Decimal("200000")


def test_net_amount_at_risk_formula():
    """NET_AMOUNT_AT_RISK = max(max(SA, fund_value) - fund_value, 0)."""
    applicant = ApplicantPayload(applicant_ref="APP-NAR", age=40)
    benefits = [
        _benefit("B1", "ULIP", Decimal("1000000"),
                 sar_formula="NET_AMOUNT_AT_RISK", fund_value=Decimal("400000")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.individual_sar["B1"] == Decimal("600000")


# ---------------------------------------------------------------------------
# SAREngine — robustness
# ---------------------------------------------------------------------------

def test_empty_benefit_list_is_graceful():
    """An empty benefit list must not raise; every bucket stays empty."""
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
    )
    result = SAREngine().calculate(
        ApplicantPayload(applicant_ref="APP-EMPTY", age=40), [], config)
    assert result.individual_sar == {}
    assert result.risk_group_sar == {}
    assert result.gross_sar == {}
    assert result.fcl_applied == {}
    assert result.excess_sar == {}


def test_include_in_sar_false_excluded_from_all_buckets():
    """include_in_sar=False yields individual SAR 0 and never enters the
    risk-group or exposure-group totals, but the key is still present so
    callers can map it back to the request row."""
    applicant = ApplicantPayload(applicant_ref="APP-INC", age=40)
    benefits = [
        _benefit("B1", "GRP_TERM", Decimal("2000000"), include_in_sar=False),
        _benefit("B2", "GRP_TERM", Decimal("1000000")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.individual_sar["B1"] == Decimal("0")
    assert result.risk_group_sar["LIFE"] == Decimal("1000000")
    assert result.gross_sar["VOLUNTARY_TOPUP"] == Decimal("1000000")


# ---------------------------------------------------------------------------
# Cumulative SAR escalation thresholds (V029) — regression
# ---------------------------------------------------------------------------

def test_cumulative_thresholds_escalate_in_severity_order():
    """With thresholds set, current + cumulative gross SAR crossing a
    threshold must set escalation. DECLINE wins over lower-severity
    thresholds."""
    from services.sar_engine import CumulativeConfig
    applicant = ApplicantPayload(applicant_ref="APP-CUM", age=40)
    benefits = [
        _benefit("B1", "LIFE", Decimal("3000000")),  # risk group LIFE
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
        cumulative_config=[
            CumulativeConfig(
                risk_group="LIFE", threshold_basis="INDIVIDUAL",
                auto_refer_threshold=Decimal("1000000"),
                senior_uw_threshold=Decimal("2000000"),
                ri_approval_threshold=Decimal("2500000"),
                decline_threshold=Decimal("3000000"),
            ),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    result.cumulative_sar = {"LIFE": Decimal("1000000")}  # total = 4M -> decline
    result.escalation = None
    SAREngine()._apply_cumulative_thresholds(result, config)
    assert result.escalation == "DECLINE"


# ---------------------------------------------------------------------------
# Condition tree IN / NOT_IN operators (Phase 2 standards reuse the same
# typed condition evaluator) — regression
# ---------------------------------------------------------------------------

def _cond_ok(condition, context):
    return FormulaEngine()._eval_condition(condition, context)


def test_condition_in_matches_any_value():
    """IN matches when the field value is one of the listed values — needed
    for categorical standards (e.g. tobacco_status IN CIGAR/PIPE)."""
    cond = {"clauses": [{"field": "tobacco_status", "op": "IN",
                         "value": ["CIGAR", "PIPE"]}], "logic": "AND"}
    assert _cond_ok(cond, {"tobacco_status": "PIPE"}) is True
    assert _cond_ok(cond, {"tobacco_status": "SMOKER"}) is False


def test_condition_not_in():
    """NOT_IN inverts membership; a missing field is still False (missing
    inputs never evaluate true)."""
    cond = {"clauses": [{"field": "occupation_class", "op": "NOT_IN",
                         "value": ["1", "2"]}], "logic": "AND"}
    assert _cond_ok(cond, {"occupation_class": "4"}) is True
    assert _cond_ok(cond, {"occupation_class": "1"}) is False
    assert _cond_ok(cond, {}) is False


def test_condition_all_and_mixed_ops():
    """Compound conditions compose EQ + numeric GT under AND; an IN clause
    can sit alongside a range clause."""
    cond = {
        "clauses": [
            {"field": "diabetes_type", "op": "EQ", "value": "TYPE2"},
            {"field": "a1c", "op": "GT", "value": 7.5},
        ],
        "logic": "AND",
    }
    assert _cond_ok(cond, {"diabetes_type": "TYPE2", "a1c": 8.1}) is True
    assert _cond_ok(cond, {"diabetes_type": "TYPE2", "a1c": 7.0}) is False
    assert _cond_ok(cond, {"diabetes_type": "TYPE1", "a1c": 8.1}) is False


def test_cumulative_thresholds_refer_when_below_higher_thresholds():
    """Total below senior/ri/decline but above auto_refer -> REFER."""
    from services.sar_engine import CumulativeConfig
    applicant = ApplicantPayload(applicant_ref="APP-CUM2", age=40)
    benefits = [
        _benefit("B1", "LIFE", Decimal("800000")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
        cumulative_config=[
            CumulativeConfig(
                risk_group="LIFE", threshold_basis="INDIVIDUAL",
                auto_refer_threshold=Decimal("1000000"),
                senior_uw_threshold=Decimal("2000000"),
                ri_approval_threshold=Decimal("2500000"),
                decline_threshold=Decimal("3000000"),
            ),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    result.cumulative_sar = {"LIFE": Decimal("500000")}  # total = 1.3M -> refer
    result.escalation = None
    SAREngine()._apply_cumulative_thresholds(result, config)
    assert result.escalation == "REFER"


def test_cumulative_thresholds_none_when_within_all():
    """Total under every threshold -> no escalation."""
    from services.sar_engine import CumulativeConfig
    applicant = ApplicantPayload(applicant_ref="APP-CUM3", age=40)
    benefits = [
        _benefit("B1", "LIFE", Decimal("500000")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
        cumulative_config=[
            CumulativeConfig(
                risk_group="LIFE", threshold_basis="INDIVIDUAL",
                auto_refer_threshold=Decimal("1000000"),
                senior_uw_threshold=Decimal("2000000"),
                ri_approval_threshold=Decimal("2500000"),
                decline_threshold=Decimal("3000000"),
            ),
        ],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    result.cumulative_sar = {"LIFE": Decimal("200000")}  # total = 700k
    result.escalation = None
    SAREngine()._apply_cumulative_thresholds(result, config)
    assert result.escalation is None


# ---------------------------------------------------------------------------
# RI retention check (Phase 4) — regression
# ---------------------------------------------------------------------------

def test_ri_retention_triggers_when_total_excess_exceeds_limit():
    """Total excess SAR above the retention limit must set
    ri_approval_required (excess_sar is keyed by exposure group)."""
    from services.sar_engine import RIConfig
    applicant = ApplicantPayload(applicant_ref="APP-RI1", age=40)
    benefits = [
        _benefit("B1", "LIFE", Decimal("6000000")),  # gross 60L
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(),
        fcl_rules=[FclRule(exposure_group="VOLUNTARY_TOPUP", fcl_basis="FLAT",
                           flat_fcl_amount=Decimal("2000000"),
                           apply_fcl_per_benefit=False, premium_payer_filter="ANY")],  # excess 40L
        ri_config=[RIConfig(risk_group="LIFE", retention_limit=Decimal("3000000"))],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.ri_approval_required is True


def test_ri_retention_not_triggered_within_limit():
    """Total excess SAR within the retention limit -> no RI approval needed."""
    from services.sar_engine import RIConfig
    applicant = ApplicantPayload(applicant_ref="APP-RI2", age=40)
    benefits = [
        _benefit("B1", "LIFE", Decimal("1000000")),
    ]
    config = ProductConfig(
        product_code="GRP-1", scheme_id=None,
        aggregation_rules=_liferules(), fcl_rules=[],
        ri_config=[RIConfig(risk_group="LIFE", retention_limit=Decimal("3000000"))],
    )
    result = SAREngine().calculate(applicant, benefits, config)
    assert result.ri_approval_required is False


# ---------------------------------------------------------------------------
# FormulaEngine (Phase B) — IF/ELSE/ENDIF conditional branching
# ---------------------------------------------------------------------------

def _step(seq, operator, value=None, field=None, condition=None, factor=Decimal("1")):
    """Compact FormulaStep factory — CONSTANT when value given, else INPUT_FIELD."""
    return FormulaStep(
        seq=seq, operator=operator, factor=factor,
        parameter_source="CONSTANT" if value is not None else "INPUT_FIELD",
        constant_value=Decimal(str(value)) if value is not None else None,
        input_field=field, condition=condition,
    )


def test_if_else_then_branch_taken():
    """IF age>=40 THEN salary*30 ELSE salary*20 — senior applicant takes THEN."""
    formula = Formula(formula_name="fcl", formula_type="FCL", steps=[
        _step(10, "IF", condition={"clauses": [{"field": "age", "op": "GTE", "value": 40}]}),
        _step(20, "ADD", field="annual_salary"),
        _step(30, "MULTIPLY", 30),
        _step(40, "ELSE"),
        _step(50, "ADD", field="annual_salary"),
        _step(60, "MULTIPLY", 20),
        _step(70, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 45, "annual_salary": Decimal("100000")}) == Decimal("3000000")
    assert FormulaEngine().evaluate(formula, {"age": 35, "annual_salary": Decimal("100000")}) == Decimal("2000000")


def test_if_without_else_skips_when_false():
    """No ELSE block: false condition skips the THEN steps and continues after ENDIF."""
    formula = Formula(formula_name="fcl", formula_type="FCL", steps=[
        _step(10, "IF", condition={"clauses": [{"field": "age", "op": "GT", "value": 40}]}),
        _step(20, "ADD", 100),
        _step(30, "ENDIF"),
        _step(40, "ADD", 50),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 50}) == Decimal("150")
    assert FormulaEngine().evaluate(formula, {"age": 30}) == Decimal("50")


def test_condition_and_requires_all():
    """AND joins clauses: both must hold."""
    cond = {"logic": "AND", "clauses": [
        {"field": "age", "op": "GTE", "value": 40},
        {"field": "annual_salary", "op": "GTE", "value": 50000},
    ]}
    formula = Formula(formula_name="and", formula_type="FCL", steps=[
        _step(10, "IF", condition=cond),
        _step(20, "ADD", 100),
        _step(30, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 45, "annual_salary": Decimal("60000")}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"age": 45, "annual_salary": Decimal("40000")}) == Decimal("0")
    assert FormulaEngine().evaluate(formula, {"age": 35, "annual_salary": Decimal("60000")}) == Decimal("0")


def test_condition_or_any_suffices():
    """OR joins clauses: any one suffices."""
    cond = {"logic": "OR", "clauses": [
        {"field": "age", "op": "GTE", "value": 60},
        {"field": "scheme_member_count", "op": "GTE", "value": 100},
    ]}
    formula = Formula(formula_name="or", formula_type="FCL", steps=[
        _step(10, "IF", condition=cond),
        _step(20, "ADD", 100),
        _step(30, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 65, "scheme_member_count": Decimal("10")}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"age": 40, "scheme_member_count": Decimal("200")}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"age": 40, "scheme_member_count": Decimal("10")}) == Decimal("0")


def test_condition_not_inverts():
    """negate flips the whole group (NOT)."""
    cond = {"negate": True, "clauses": [{"field": "age", "op": "BETWEEN", "min": 18, "max": 30}]}
    formula = Formula(formula_name="not", formula_type="FCL", steps=[
        _step(10, "IF", condition=cond),
        _step(20, "ADD", 500),
        _step(30, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 45}) == Decimal("500")   # NOT in [18,30] → true
    assert FormulaEngine().evaluate(formula, {"age": 25}) == Decimal("0")     # in [18,30] → false


def test_condition_between_is_inclusive():
    """BETWEEN matches both edges."""
    cond = {"clauses": [{"field": "age", "op": "BETWEEN", "min": 40, "max": 50}]}
    formula = Formula(formula_name="between", formula_type="FCL", steps=[
        _step(10, "IF", condition=cond),
        _step(20, "ADD", 100),
        _step(30, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 40}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"age": 50}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"age": 39}) == Decimal("0")
    assert FormulaEngine().evaluate(formula, {"age": 51}) == Decimal("0")


def test_condition_eq_on_string_field():
    """EQ compares text fields (employer_code) as strings."""
    cond = {"clauses": [{"field": "employer_code", "op": "EQ", "value": "TECHM"}]}
    formula = Formula(formula_name="eq", formula_type="FCL", steps=[
        _step(10, "IF", condition=cond),
        _step(20, "ADD", 100),
        _step(30, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"employer_code": "TECHM"}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"employer_code": "INFY"}) == Decimal("0")


def test_condition_missing_field_is_false():
    """A field absent from context makes the clause false (never an error)."""
    cond = {"clauses": [{"field": "annual_salary", "op": "GTE", "value": 1}]}
    formula = Formula(formula_name="missing", formula_type="FCL", steps=[
        _step(10, "IF", condition=cond),
        _step(20, "ADD", 100),
        _step(30, "ELSE"),
        _step(40, "ADD", 7),
        _step(50, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 40}) == Decimal("7")


def test_condition_malformed_defaults_false():
    """A None / empty / non-object condition is never taken."""
    formula = Formula(formula_name="malformed", formula_type="FCL", steps=[
        _step(10, "IF", condition=None),
        _step(20, "ADD", 100),
        _step(30, "ENDIF"),
        _step(40, "ADD", 5),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 50}) == Decimal("5")


def test_nested_if_else_blocks():
    """Outer THEN contains an inner IF/ELSE — inner picks the addend."""
    formula = Formula(formula_name="nested", formula_type="DECISION", steps=[
        _step(10, "IF", condition={"clauses": [{"field": "age", "op": "GTE", "value": 40}]}),
        _step(20, "IF", condition={"clauses": [{"field": "annual_salary", "op": "GTE", "value": 50000}]}),
        _step(30, "ADD", 100),
        _step(40, "ELSE"),
        _step(50, "ADD", 50),
        _step(60, "ENDIF"),
        _step(70, "ELSE"),
        _step(80, "ADD", 5),
        _step(90, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 45, "annual_salary": Decimal("60000")}) == Decimal("100")
    assert FormulaEngine().evaluate(formula, {"age": 45, "annual_salary": Decimal("30000")}) == Decimal("50")
    assert FormulaEngine().evaluate(formula, {"age": 35, "annual_salary": Decimal("60000")}) == Decimal("5")


def test_if_else_blocks_preserve_accumulator_from_entry():
    """Both branches inherit the running total at block entry (ADD-on before)."""
    formula = Formula(formula_name="entry", formula_type="FCL", steps=[
        _step(10, "ADD", 1000),
        _step(20, "IF", condition={"clauses": [{"field": "age", "op": "GTE", "value": 40}]}),
        _step(30, "ADD", 500),
        _step(40, "ELSE"),
        _step(50, "ADD", 100),
        _step(60, "ENDIF"),
    ])
    assert FormulaEngine().evaluate(formula, {"age": 45}) == Decimal("1500")
    assert FormulaEngine().evaluate(formula, {"age": 30}) == Decimal("1100")
