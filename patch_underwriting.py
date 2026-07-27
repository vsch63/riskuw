import sys

with open('/opt/riskuw/backend/routers/underwriting.py') as f:
    content = f.read()

# ── New endpoints to append before the end of file ───────────────────────────
new_endpoints = '''

# ══════════════════════════════════════════════════════════════════════════════
# BENEFIT GROUPING — Rider config + Multi-benefit proposal evaluation
# ══════════════════════════════════════════════════════════════════════════════

class BenefitLine(BaseModel):
    benefit_type:      str            # BASE | RIDER_CI | RIDER_ADB | RIDER_WOP | RIDER_ATPD
    product_code:      str
    face_amount:       float
    coverage_term_yrs: int = 20
    premium_mode:      str = "ANNUAL"


class ProposalRequest(BaseModel):
    model_config = {"extra": "allow"}
    proposal_ref:  str = "PROP-001"
    applicant_ref: str = "APP-001"
    age:           int
    gender:        str
    state:         str = "MH"
    annual_income: float = 100000
    # Medical fields — shared across all benefits
    tobacco_status:       str = "NEVER"
    heart_condition:      str = "NONE"
    diabetes_type:        str = "NONE"
    a1c:                  float | None = None
    hiv_positive:         bool = False
    cirrhosis:            bool = False
    stroke_history:       bool = False
    kidney_disease:       bool = False
    occupation_class:     str = "1"
    # Benefits list — first must be BASE
    benefits:             list[BenefitLine] = []


@router.get("/rider-config")
def get_rider_config(base_product_code: str, current: CurrentUser):
    """Return compatible riders for a given base product."""
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pbc.benefit_type, pbc.rider_product_code, pbc.inherits_medical,
                   pbc.max_rider_sa_pct, p.product_name AS rider_name
            FROM product_benefit_config pbc
            JOIN products p ON p.product_code = pbc.rider_product_code
            WHERE pbc.tenant_id = %s::uuid
              AND pbc.base_product_code = %s
              AND pbc.is_active = true
            ORDER BY pbc.benefit_type
        """, (current.tenant_id, base_product_code))
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = dict(r) if hasattr(r, "keys") else {
                "benefit_type": r[0], "rider_product_code": r[1],
                "inherits_medical": r[2], "max_rider_sa_pct": r[3], "rider_name": r[4]
            }
            if d.get("max_rider_sa_pct"):
                d["max_rider_sa_pct"] = float(d["max_rider_sa_pct"])
            result.append(d)
        return result
    except Exception as e:
        raise HTTPException(500, f"Rider config lookup failed: {e}")
    finally:
        release(conn)


@router.post("/evaluate-proposal")
def evaluate_proposal(body: ProposalRequest, current: FlexibleAuth):
    """
    Multi-benefit proposal evaluation.
    Evaluates base product + all rider lines using shared medical context.
    Applies cross-benefit rules (if BASE declined, all riders declined).
    Returns per-benefit decisions + composite overall_status + total premium.
    """
    if current.role not in ("underwriter","senior_underwriter","admin","super_admin","api_client"):
        raise HTTPException(403, "Underwriters only")

    if not body.benefits:
        raise HTTPException(400, "At least one benefit (BASE) is required")

    base = next((b for b in body.benefits if b.benefit_type == "BASE"), None)
    if not base:
        raise HTTPException(400, "First benefit must have benefit_type='BASE'")

    import time
    conn, release = _get_db()
    try:
        # Build shared medical payload from proposal request
        shared = body.model_dump(exclude={"benefits"})
        shared["applicant_ref"] = body.applicant_ref

        benefit_results = []
        base_outcome    = None
        base_debits     = 0
        total_premium   = 0.0

        for i, benefit in enumerate(body.benefits):
            t0 = time.time()
            is_base = benefit.benefit_type == "BASE"

            # Build per-benefit payload
            payload = {
                **shared,
                "product_code":      benefit.product_code,
                "face_amount":       benefit.face_amount,
                "coverage_term_yrs": benefit.coverage_term_yrs,
                "premium_mode":      benefit.premium_mode,
            }

            # Cross-benefit rule: if BASE was DECLINED, all riders are declined (linked)
            linked_decline = False
            if not is_base and base_outcome and "DECLIN" in base_outcome:
                result_row = {
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "DECLINED",
                    "risk_class":       "DECLINE",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [],
                    "exclusions":       None,
                    "linked_decline":   True,
                    "processing_ms":    0,
                }
                benefit_results.append(result_row)
                continue

            # Cross-benefit rule: if BASE debits > 300, CI rider auto-declined
            if benefit.benefit_type == "RIDER_CI" and base_debits > 300:
                result_row = {
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "DECLINED",
                    "risk_class":       "DECLINE",
                    "net_debit_points": 0,
                    "annual_premium":   None,
                    "rules_fired":      [{"rule": "CROSS_BENEFIT_CI_BLOCK", "reason": f"Base debit score {base_debits} exceeds CI rider threshold (300)"}],
                    "exclusions":       None,
                    "linked_decline":   True,
                    "processing_ms":    0,
                }
                benefit_results.append(result_row)
                continue

            # Cross-benefit rule: if BASE debits 150-300, CI rider auto-referred
            if benefit.benefit_type == "RIDER_CI" and base_debits >= 150:
                result_row = {
                    "benefit_type":     benefit.benefit_type,
                    "product_code":     benefit.product_code,
                    "face_amount":      benefit.face_amount,
                    "outcome":          "REFERRED",
                    "risk_class":       "SUBSTANDARD",
                    "net_debit_points": base_debits,
                    "annual_premium":   None,
                    "rules_fired":      [{"rule": "CROSS_BENEFIT_CI_REFER", "reason": f"Base debit score {base_debits} triggers CI rider referral (150-300 range)"}],
                    "exclusions":       None,
                    "linked_decline":   False,
                    "processing_ms":    0,
                }
                benefit_results.append(result_row)
                continue

            # Run the actual UW engine for this benefit
            try:
                from services.uw_engine import run_evaluation
                uw_result = run_evaluation(payload, current.username, current.tenant_id)
            except ImportError:
                uw_result = _fallback_evaluate(
                    type("B", (), payload)(), current  # type: ignore
                )

            outcome          = uw_result.get("outcome", "ERROR")
            net_debits       = uw_result.get("net_debit_points", 0)
            annual_premium   = uw_result.get("approved_premium") or uw_result.get("premium_detail", {}).get("annual_premium")
            processing_ms    = int((time.time() - t0) * 1000)

            # Track base outcome/debits for cross-benefit rules
            if is_base:
                base_outcome = outcome
                base_debits  = net_debits or 0

            # Accumulate premium only for approved benefits
            if annual_premium and "APPROVED" in outcome:
                total_premium += float(annual_premium)

            # Build exclusions for CI rider if approved with medical conditions
            exclusions = None
            if benefit.benefit_type == "RIDER_CI" and "APPROVED" in outcome:
                exc_list = []
                if body.diabetes_type not in ("NONE", None):
                    exc_list.append({"condition": "DIABETES", "text": "No CI benefit payable for diabetes or diabetes-related complications", "permanent": True})
                if body.heart_condition not in ("NONE", None):
                    exc_list.append({"condition": "CARDIAC", "text": "No CI benefit payable for cardiac conditions", "permanent": True})
                if exc_list:
                    exclusions = exc_list
                    outcome = "APPROVED_EXCLUDED"

            result_row = {
                "benefit_type":     benefit.benefit_type,
                "product_code":     benefit.product_code,
                "face_amount":      benefit.face_amount,
                "outcome":          outcome,
                "risk_class":       uw_result.get("risk_class"),
                "net_debit_points": net_debits,
                "annual_premium":   round(float(annual_premium), 2) if annual_premium else None,
                "rules_fired":      uw_result.get("rules_fired", [])[:5],  # trim for response size
                "exclusions":       exclusions,
                "linked_decline":   False,
                "processing_ms":    processing_ms,
            }
            benefit_results.append(result_row)

        # Compute overall_status
        outcomes  = [b["outcome"] for b in benefit_results]
        all_appr  = all("APPROVED" in o for o in outcomes)
        any_appr  = any("APPROVED" in o for o in outcomes)
        all_decl  = all("DECLIN" in o for o in outcomes)

        if all_appr:
            overall = "ALL_APPROVED"
        elif all_decl:
            overall = "ALL_DECLINED"
        elif any_appr:
            overall = "PARTIALLY_APPROVED"
        else:
            overall = "REFERRED"

        # Persist to proposal + proposal_benefit tables
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO proposal
                    (proposal_ref, tenant_id, applicant_ref, overall_status,
                     total_annual_premium, premium_mode, source, submitted_by)
                VALUES (%s, %s::uuid, %s, %s, %s, %s, 'ONLINE', %s)
                ON CONFLICT (tenant_id, proposal_ref) DO UPDATE
                SET overall_status = EXCLUDED.overall_status,
                    total_annual_premium = EXCLUDED.total_annual_premium,
                    updated_at = now()
                RETURNING id
            """, (
                body.proposal_ref, current.tenant_id, body.applicant_ref,
                overall, round(total_premium, 2),
                base.premium_mode if base else "ANNUAL",
                current.username,
            ))
            proposal_id = cur.fetchone()[0]

            for br in benefit_results:
                cur.execute("""
                    INSERT INTO proposal_benefit
                        (proposal_id, benefit_type, product_code, face_amount,
                         outcome, risk_class, net_debit_points, annual_premium,
                         exclusions, rules_fired, linked_decline)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """, (
                    proposal_id, br["benefit_type"], br["product_code"], br["face_amount"],
                    br["outcome"], br["risk_class"], br["net_debit_points"], br["annual_premium"],
                    __import__("json").dumps(br["exclusions"]) if br["exclusions"] else None,
                    __import__("json").dumps(br["rules_fired"]) if br["rules_fired"] else None,
                    br["linked_decline"],
                ))
            conn.commit()
            cur.close()
        except Exception as pe:
            logger.warning(f"Proposal persistence failed: {pe}")
            conn.rollback()

        return {
            "proposal_ref":        body.proposal_ref,
            "applicant_ref":       body.applicant_ref,
            "overall_status":      overall,
            "total_annual_premium": round(total_premium, 2),
            "benefits":            benefit_results,
            "benefit_count":       len(benefit_results),
            "evaluated_at":        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"evaluate_proposal failed: {e}", exc_info=True)
        raise HTTPException(500, f"Proposal evaluation failed: {e}")
    finally:
        release(conn)
'''

if "@router.get(\"/ai-audit\")" in content:
    content = content + new_endpoints
    with open('/opt/riskuw/backend/routers/underwriting.py', 'w') as f:
        f.write(content)
    print("Endpoints added successfully")
else:
    print("Anchor not found")
