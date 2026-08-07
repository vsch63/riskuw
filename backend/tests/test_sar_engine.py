"""
backend/tests/test_sar_engine.py
────────────────────────────────
Unit tests for the ported SAR engine — reproduce the worked example and the
v2.2 / v2.3 test cases from RiskUW_SAR_Framework_v2.3 (reference
test_sar_engine.py). Pure unit tests: no DB, no HTTP.
"""
from decimal import Decimal

from services.sar_engine import (
    AggregationRule,
    ApplicantPayload,
    BenefitLine,
    FclRule,
    Formula,
    FormulaStep,
    ProductConfig,
    ReferenceTable,
    ReferenceTableRow,
    SAREngine,
)


def test_worked_example():
    """§14 worked example (Group Term + Endowment + ADB Rider), adapted for
    the exposure-group split."""
    applicant = ApplicantPayload(applicant_ref="APP-001", age=40)

    benefits = [
        BenefitLine(
            benefit_id="B1", benefit_code="ENDOW", sum_assured=Decimal("1000000"),
            premium_payer="EMPLOYEE", include_in_sar=True, sar_formula="MORTALITY_PORTION",
            sar_percentage=None, sar_expression=None,
            uw_exposure_group="VOLUNTARY_TOPUP",
            risk_group_weights={"LIFE": Decimal("100")},
            policy_reserve=Decimal("100000"),
        ),
        BenefitLine(
            benefit_id="B2", benefit_code="GRP_TERM", sum_assured=Decimal("4000000"),
            premium_payer="EMPLOYER", include_in_sar=True, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None,
            uw_exposure_group="EMPLOYER_BASE",
            risk_group_weights={"LIFE": Decimal("100")},
        ),
        BenefitLine(
            benefit_id="B3", benefit_code="ADB", sum_assured=Decimal("2000000"),
            premium_payer="EMPLOYEE", include_in_sar=True, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None,
            uw_exposure_group="VOLUNTARY_TOPUP",
            risk_group_weights={"ACCIDENT": Decimal("100")},
        ),
        BenefitLine(
            benefit_id="B4", benefit_code="CI", sum_assured=Decimal("1000000"),
            premium_payer="EMPLOYEE", include_in_sar=False, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None,
            uw_exposure_group="VOLUNTARY_TOPUP",
            risk_group_weights={"HEALTH": Decimal("100")},
        ),
    ]

    product_config = ProductConfig(
        product_code="GRP-TERM-1",
        scheme_id="SCHEME-001",
        aggregation_rules=[
            AggregationRule(risk_group="LIFE", exposure_group=None, product_code=None, aggregation_method="SUM"),
            AggregationRule(risk_group="ACCIDENT", exposure_group=None, product_code=None, aggregation_method="SUM"),
            AggregationRule(risk_group="HEALTH", exposure_group=None, product_code=None, aggregation_method="SUM"),
        ],
        fcl_rules=[
            FclRule(
                exposure_group="EMPLOYER_BASE", fcl_basis="FLAT",
                flat_fcl_amount=Decimal("2000000"),
                apply_fcl_per_benefit=False, premium_payer_filter="ANY",
            ),
        ],
        premium_payer_filter="ANY",
    )

    engine = SAREngine()
    result = engine.calculate(applicant, benefits, product_config)

    # Step 1: individual SAR
    assert result.individual_sar["B1"] == Decimal("900000")   # 10L - 1L reserve
    assert result.individual_sar["B2"] == Decimal("4000000")
    assert result.individual_sar["B3"] == Decimal("2000000")
    assert result.individual_sar["B4"] == Decimal("0")        # excluded

    # Step 3: risk group aggregation -> LIFE = 9L + 40L = 49L
    assert result.risk_group_sar["LIFE"] == Decimal("4900000")
    assert result.risk_group_sar["ACCIDENT"] == Decimal("2000000")

    # Step 4: exposure group split
    assert result.gross_sar["EMPLOYER_BASE"] == Decimal("4000000")
    assert result.gross_sar["VOLUNTARY_TOPUP"] == Decimal("900000") + Decimal("2000000")

    # Step 5: FCL — only EMPLOYER_BASE has a rule (2000000)
    assert result.fcl_applied["EMPLOYER_BASE"] == Decimal("2000000")
    assert result.excess_sar["EMPLOYER_BASE"] == Decimal("2000000")  # 40L - 20L
    assert result.fcl_applied["VOLUNTARY_TOPUP"] == Decimal("0")     # no rule -> no FCL
    assert result.excess_sar["VOLUNTARY_TOPUP"] == Decimal("2900000")


def test_v2_2_exposure_scoped_aggregation_with_priority_tiebreak():
    """v2.2: two ACCIDENT riders both VOLUNTARY_TOPUP, aggregation=MAXIMUM,
    tied at the same SAR — lower priority number should win the tie."""
    applicant = ApplicantPayload(applicant_ref="APP-002", age=35)

    benefits = [
        BenefitLine(
            benefit_id="R1", benefit_code="ADB", sum_assured=Decimal("2000000"),
            premium_payer="EMPLOYEE", include_in_sar=True, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None, uw_exposure_group="VOLUNTARY_TOPUP",
            risk_group_weights={"ACCIDENT": Decimal("100")},
            risk_group_priority={"ACCIDENT": 1},  # higher priority (lower number)
        ),
        BenefitLine(
            benefit_id="R2", benefit_code="ATPD", sum_assured=Decimal("2000000"),
            premium_payer="EMPLOYEE", include_in_sar=True, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None, uw_exposure_group="VOLUNTARY_TOPUP",
            risk_group_weights={"ACCIDENT": Decimal("100")},
            risk_group_priority={"ACCIDENT": 5},
        ),
    ]

    product_config = ProductConfig(
        product_code="GRP-PA-1",
        scheme_id=None,
        aggregation_rules=[
            AggregationRule(
                risk_group="ACCIDENT", exposure_group="VOLUNTARY_TOPUP",
                product_code="GRP-PA-1", aggregation_method="MAXIMUM",
            ),
        ],
        fcl_rules=[],
    )

    engine = SAREngine()
    result = engine.calculate(applicant, benefits, product_config)

    # Both riders tie at 20L; MAXIMUM should return 20L either way, and the
    # engine should not raise on the tie (priority resolves it deterministically).
    assert result.risk_group_sar["ACCIDENT"] == Decimal("2000000")


def test_v2_3_member_count_scale_via_formula_engine():
    """v2.3: FCL graded by scheme size, now expressed as a Formula (Business
    Formula Engine, Phase A) instead of the retired MEMBER_COUNT_SCALE
    fcl_basis. A 250-life scheme should land in the 100-499 band."""
    applicant = ApplicantPayload(applicant_ref="APP-003", age=45, annual_salary=Decimal("1200000"))

    benefits = [
        BenefitLine(
            benefit_id="B1", benefit_code="GRP_TERM", sum_assured=Decimal("3000000"),
            premium_payer="EMPLOYER", include_in_sar=True, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None, uw_exposure_group="EMPLOYER_BASE",
            risk_group_weights={"LIFE": Decimal("100")},
        ),
    ]

    member_count_scale = ReferenceTable(
        table_code="FCL_MEMBER_COUNT_SCALE",
        rows=[
            ReferenceTableRow(match_type="BAND", band_min=Decimal("1"), band_max=Decimal("49"), output_value=Decimal("500000")),
            ReferenceTableRow(match_type="BAND", band_min=Decimal("50"), band_max=Decimal("99"), output_value=Decimal("1000000")),
            ReferenceTableRow(match_type="BAND", band_min=Decimal("100"), band_max=Decimal("499"), output_value=Decimal("2000000")),
            ReferenceTableRow(match_type="BAND", band_min=Decimal("500"), band_max=None, output_value=Decimal("5000000")),
        ],
    )

    fcl_formula = Formula(
        formula_name="FCL by Scheme Size",
        formula_type="FCL",
        steps=[
            FormulaStep(
                seq=10, operator="ADD", factor=Decimal("1"),
                parameter_source="REFERENCE_TABLE",
                input_field="scheme_member_count",
                reference_table=member_count_scale,
            ),
        ],
    )

    product_config = ProductConfig(
        product_code="GRP-TERM-2",
        scheme_id="SCHEME-250",
        scheme_member_count=250,
        aggregation_rules=[
            AggregationRule(risk_group="LIFE", exposure_group=None, product_code=None, aggregation_method="SUM"),
        ],
        fcl_rules=[
            FclRule(
                exposure_group="EMPLOYER_BASE", fcl_basis="FORMULA",
                flat_fcl_amount=None, apply_fcl_per_benefit=False, premium_payer_filter="ANY",
                formula=fcl_formula,
            ),
        ],
    )

    engine = SAREngine()
    result = engine.calculate(applicant, benefits, product_config)

    # 250 members -> 100-499 band -> FCL = 20L
    assert result.fcl_applied["EMPLOYER_BASE"] == Decimal("2000000")
    assert result.excess_sar["EMPLOYER_BASE"] == Decimal("1000000")  # 30L - 20L


def test_v2_3_employer_table_and_salary_multiple_via_formula_engine():
    """v2.3: two more Formula Engine examples from the design doc in one
    test — an exact-match Employer FCL Table, and a salary multiple
    expressed as a formula (ADD with factor=5, INPUT_FIELD=annual_salary),
    replacing the old dedicated SALARY_MULTIPLE fcl_basis."""
    applicant = ApplicantPayload(applicant_ref="APP-004", age=38, annual_salary=Decimal("800000"))

    benefits = [
        BenefitLine(
            benefit_id="B1", benefit_code="GRP_TERM", sum_assured=Decimal("6000000"),
            premium_payer="EMPLOYER", include_in_sar=True, sar_formula="FACE_AMOUNT",
            sar_percentage=None, sar_expression=None, uw_exposure_group="EMPLOYER_BASE",
            risk_group_weights={"LIFE": Decimal("100")},
        ),
    ]

    employer_table = ReferenceTable(
        table_code="FCL_EMPLOYER_TABLE",
        rows=[ReferenceTableRow(match_type="EXACT", match_value="ABC", output_value=Decimal("10000000"))],
    )
    employer_formula = Formula(
        formula_name="FCL by Employer",
        formula_type="FCL",
        steps=[
            FormulaStep(
                seq=10, operator="ADD", factor=Decimal("1"),
                parameter_source="REFERENCE_TABLE", input_field="employer_code",
                reference_table=employer_table,
            ),
        ],
    )
    salary_multiple_formula = Formula(
        formula_name="FCL by Salary x5",
        formula_type="FCL",
        steps=[
            FormulaStep(
                seq=10, operator="ADD", factor=Decimal("5"),
                parameter_source="INPUT_FIELD", input_field="annual_salary",
            ),
        ],
    )

    product_config = ProductConfig(
        product_code="GRP-TERM-3",
        scheme_id="SCHEME-ABC",
        employer_code="ABC",
        aggregation_rules=[
            AggregationRule(risk_group="LIFE", exposure_group=None, product_code=None, aggregation_method="SUM"),
        ],
        fcl_rules=[
            FclRule(
                exposure_group="EMPLOYER_BASE", fcl_basis="FORMULA",
                flat_fcl_amount=None, apply_fcl_per_benefit=False, premium_payer_filter="ANY",
                formula=employer_formula,
            ),
        ],
    )

    engine = SAREngine()
    result = engine.calculate(applicant, benefits, product_config)
    # Employer 'ABC' -> exact match -> FCL = 1Cr; SAR 60L < FCL -> auto-approve
    assert result.fcl_applied["EMPLOYER_BASE"] == Decimal("10000000")
    assert result.excess_sar["EMPLOYER_BASE"] == Decimal("0")

    # Now re-run the same benefit against the salary-multiple formula instead
    product_config.fcl_rules = [
        FclRule(
            exposure_group="EMPLOYER_BASE", fcl_basis="FORMULA",
            flat_fcl_amount=None, apply_fcl_per_benefit=False, premium_payer_filter="ANY",
            formula=salary_multiple_formula,
        ),
    ]
    result2 = engine.calculate(applicant, benefits, product_config)
    # Salary 8L x 5 = 40L FCL; SAR 60L - 40L = 20L excess
    assert result2.fcl_applied["EMPLOYER_BASE"] == Decimal("4000000")
    assert result2.excess_sar["EMPLOYER_BASE"] == Decimal("2000000")
