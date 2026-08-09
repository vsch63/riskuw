"""
proposal_uw.py — Benefit Package / Proposal Underwriting
POST /underwriting/evaluate-proposal
"""
from __future__ import annotations
import json, logging, time, uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deps import CurrentUser

logger = logging.getLogger("uw_platform")
router = APIRouter()

class MedicalInfo(BaseModel):
    height_inches:       Optional[float] = None
    weight_lbs:          Optional[float] = None
    systolic_bp:         Optional[int]   = None
    diastolic_bp:        Optional[int]   = None
    tobacco_status:      str  = "NEVER"
    diabetes_type:       str  = "NONE"
    a1c:                 Optional[float] = None
    heart_condition:     str  = "NONE"
    cancer_status:       str  = "NONE"
    kidney_disease:      bool = False
    copd:                bool = False
    stroke_history:      bool = False
    depression_history:  bool = False
    hiv_positive:        bool = False
    cirrhosis:           bool = False
    hazardous_activity:  bool = False
    alcohol_drinks_week: int  = 0
    occupation_class:    int  = 1
    occupation_title:    str  = ""
    icd10_codes:         list[str] = Field(default_factory=list)
    extra_debit_points:  int  = 0

class BenefitLine(BaseModel):
    product_code:      str
    benefit_type:      str  = "BASE"
    face_amount:       float
    coverage_term_yrs: int  = 20
    is_base_plan:      bool = False
    benefit_label:     Optional[str] = None

class ProposalEvaluateRequest(BaseModel):
    proposal_ref:        str
    applicant_ref:       str
    age:                 int
    gender:              str
    state:               str   = "MH"
    annual_income:       float = 0
    existing_coverage:   float = 0
    medical:             MedicalInfo = Field(default_factory=MedicalInfo)
    benefits:            list[BenefitLine]
    apply_linking_rules: bool  = True
    premium_mode:        str   = "ANNUAL"
    source:              str   = "ONLINE"

class BenefitDecisionOut(BaseModel):
    product_code:      str
    benefit_type:      str
    benefit_label:     str
    is_base_plan:      bool
    face_amount:       float
    coverage_term_yrs: int
    outcome:           str
    risk_class:        Optional[str]
    net_debit_points:  int
    annual_premium:    Optional[float]
    exclusions:        list = Field(default_factory=list)
    rules_fired:       list = Field(default_factory=list)
    linked_decline:    bool = False
    decline_reason:    Optional[str] = None
    processing_ms:     int  = 0

class ProposalEvaluateResponse(BaseModel):
    proposal_id:          str
    proposal_ref:         str
    applicant_ref:        str
    overall_status:       str
    benefit_decisions:    list[BenefitDecisionOut]
    total_annual_premium: float
    evaluated_at:         str
    linking_rules_applied:bool
    summary:              dict

def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn

def _build_payload(body: ProposalEvaluateRequest, benefit: BenefitLine) -> dict:
    m = body.medical
    return {
        "applicant_ref": body.applicant_ref, "age": body.age,
        "gender": body.gender, "state": body.state,
        "annual_income": body.annual_income, "existing_coverage": body.existing_coverage,
        "product_code": benefit.product_code, "face_amount": benefit.face_amount,
        "coverage_term_yrs": benefit.coverage_term_yrs,
        "height_inches": m.height_inches, "weight_lbs": m.weight_lbs,
        "systolic_bp": m.systolic_bp, "diastolic_bp": m.diastolic_bp,
        "tobacco_status": m.tobacco_status, "diabetes_type": m.diabetes_type,
        "a1c": m.a1c, "heart_condition": m.heart_condition,
        "cancer_status": m.cancer_status, "kidney_disease": m.kidney_disease,
        "copd": m.copd, "stroke_history": m.stroke_history,
        "depression_history": m.depression_history, "hiv_positive": m.hiv_positive,
        "cirrhosis": m.cirrhosis, "hazardous_activity": m.hazardous_activity,
        "alcohol_drinks_week": m.alcohol_drinks_week,
        "occupation_class": m.occupation_class, "occupation_title": m.occupation_title,
        "icd10_codes": m.icd10_codes, "extra_debit_points": m.extra_debit_points,
    }

def _run_eval(conn, payload: dict, tenant_id: str) -> dict:
    from routers.underwriting import EvaluateRequest, _fallback_evaluate
    class _FakeUser:
        username = "system"; role = "admin"; tenant_id = tenant_id
    req = EvaluateRequest(**{k: v for k, v in payload.items()
                             if k in EvaluateRequest.model_fields})
    try:
        from services.uw_engine import run_evaluation
        result = run_evaluation(req.model_dump(), "system", tenant_id)
    except ImportError:
        result = _fallback_evaluate(req, _FakeUser())
    extra = payload.get("extra_debit_points", 0) or 0
    if extra > 0:
        cur = conn.cursor()
        cur.execute("SELECT stp_threshold,refer_threshold,decline_threshold FROM products "
                    "WHERE product_code=%s AND tenant_id=%s::uuid",
                    (payload["product_code"], tenant_id))
        row = cur.fetchone(); cur.close()
        t = dict(row) if row else {}
        ndp = (result.get("net_debit_points") or 0) + extra
        result["net_debit_points"] = ndp
        if ndp >= t.get("decline_threshold", 350): result["outcome"] = "DECLINED"
        elif ndp >= t.get("refer_threshold", 175):  result["outcome"] = "REFERRED"
        elif ndp > t.get("stp_threshold", 75):      result["outcome"] = "APPROVED_RATED"
    return result

def _rider_premium(conn, product_code: str, face_amount: float,
                   age: int, benefit_type: str) -> Optional[float]:
    """Calculate rider premium — flat rate per thousand if no rate table."""
    try:
        cur = conn.cursor()
        # Try rate table first
        cur.execute("""
            SELECT rate_per_thou FROM premium_rates
            WHERE product_code=%s AND %s BETWEEN age_min AND age_max
            AND gender='MALE' LIMIT 1
        """, (product_code, age))
        row = cur.fetchone()
        cur.close()
        if row:
            rate = float(dict(row)["rate_per_thou"])
            return round(rate * face_amount / 1000, 2)
        # Flat rate fallback per benefit type
        flat_rates = {
            "RIDER_CI":   2.50,  # ₹2.50 per ₹1000 SA
            "RIDER_ADB":  0.50,  # ₹0.50 per ₹1000 SA
            "RIDER_WOP":  0.30,  # ₹0.30 per ₹1000 SA
            "RIDER_ATPD": 0.80,  # ₹0.80 per ₹1000 SA
        }
        rate = flat_rates.get(benefit_type, 1.0)
        # Age loading: add 2% per year over 35
        age_loading = max(0, (age - 35) * 0.02)
        effective_rate = rate * (1 + age_loading)
        return round(effective_rate * face_amount / 1000, 2)
    except Exception as e:
        logger.warning(f"Rider premium calc failed for {product_code}: {e}")
        return None

def _compute_status(decisions: list[BenefitDecisionOut]) -> str:
    approved = {"APPROVED_STP","APPROVED_RATED","APPROVED_EXCLUDED"}
    outcomes = {d.outcome for d in decisions}
    if all(o in approved for o in outcomes):     return "ALL_APPROVED"
    if all(o == "DECLINED" for o in outcomes):  return "ALL_DECLINED"
    if all(o == "REFERRED" for o in outcomes):  return "ALL_REFERRED"
    return "PARTIAL_APPROVAL"

def _persist(conn, body, decisions, overall_status, total_premium, tenant_id: str) -> str:
    cur = conn.cursor()
    pid = str(uuid.uuid4())
    try:
        cur.execute("""
            INSERT INTO proposal
              (id,proposal_ref,tenant_id,applicant_ref,overall_status,
               total_annual_premium,premium_mode,source,submitted_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id,proposal_ref) DO UPDATE
              SET overall_status=EXCLUDED.overall_status,
                  total_annual_premium=EXCLUDED.total_annual_premium,
                  updated_at=now()
            RETURNING id
        """, (pid, body.proposal_ref, tenant_id, body.applicant_ref,
              overall_status, total_premium, body.premium_mode,
              body.source, "system"))
        row = cur.fetchone()
        if row:
            pid = str(dict(row)["id"])
        for d in decisions:
            cur.execute("""
                INSERT INTO proposal_benefit
                  (proposal_id,benefit_type,product_code,face_amount,
                   coverage_term_yrs,outcome,risk_class,net_debit_points,
                   annual_premium,exclusions,rules_fired,linked_decline,processing_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pid, d.benefit_type, d.product_code, d.face_amount,
                  d.coverage_term_yrs, d.outcome, d.risk_class,
                  d.net_debit_points, d.annual_premium,
                  json.dumps(d.exclusions) if d.exclusions else None,
                  json.dumps([r if isinstance(r,dict) else {"rule":str(r)}
                              for r in (d.rules_fired or [])]),
                  d.linked_decline, d.processing_ms))
        conn.commit()
        cur.close()
        logger.info(f"Proposal {body.proposal_ref} persisted: {pid}")
        return pid
    except Exception as e:
        conn.rollback()
        cur.close()
        logger.error(f"Proposal persist error: {e}")
        raise

@router.post("/underwriting/evaluate-proposal",
             response_model=ProposalEvaluateResponse)
def evaluate_proposal(body: ProposalEvaluateRequest, current: CurrentUser):
    if not body.benefits:
        raise HTTPException(400, "At least one benefit required")
    if len(body.benefits) > 10:
        raise HTTPException(400, "Maximum 10 benefits per proposal")
    if not any(b.is_base_plan for b in body.benefits):
        body.benefits[0].is_base_plan = True

    conn, release = _get_db()
    decisions: list[BenefitDecisionOut] = []
    base_outcome: str | None = None
    base_code = next(b.product_code for b in body.benefits if b.is_base_plan)

    try:
        cur = conn.cursor()
        for benefit in body.benefits:
            label = benefit.benefit_label or benefit.product_code
            t0 = time.time()

            # Validate product
            cur.execute(
                "SELECT product_code FROM products WHERE product_code=%s AND tenant_id=%s",
                (benefit.product_code, current.tenant_id))
            if not cur.fetchone():
                decisions.append(BenefitDecisionOut(
                    product_code=benefit.product_code, benefit_type=benefit.benefit_type,
                    benefit_label=label, is_base_plan=benefit.is_base_plan,
                    face_amount=benefit.face_amount, coverage_term_yrs=benefit.coverage_term_yrs,
                    outcome="ERROR", risk_class=None, net_debit_points=0,
                    annual_premium=None, decline_reason=f"Product {benefit.product_code} not found",
                    processing_ms=0))
                continue

            # Rider compatibility check
            if not benefit.is_base_plan:
                cur.execute(
                    "SELECT id FROM product_benefit_config WHERE tenant_id=%s"
                    " AND base_product_code=%s AND rider_product_code=%s AND is_active=true",
                    (current.tenant_id, base_code, benefit.product_code))
                if not cur.fetchone():
                    decisions.append(BenefitDecisionOut(
                        product_code=benefit.product_code, benefit_type=benefit.benefit_type,
                        benefit_label=label, is_base_plan=False,
                        face_amount=benefit.face_amount, coverage_term_yrs=benefit.coverage_term_yrs,
                        outcome="DECLINED", risk_class=None, net_debit_points=0,
                        annual_premium=None,
                        decline_reason=f"{benefit.product_code} not compatible with {base_code}",
                        processing_ms=0))
                    continue

            # Linking rule
            if (body.apply_linking_rules and not benefit.is_base_plan
                    and base_outcome == "DECLINED"):
                decisions.append(BenefitDecisionOut(
                    product_code=benefit.product_code, benefit_type=benefit.benefit_type,
                    benefit_label=label, is_base_plan=False,
                    face_amount=benefit.face_amount, coverage_term_yrs=benefit.coverage_term_yrs,
                    outcome="DECLINED", risk_class=None, net_debit_points=0,
                    annual_premium=None, linked_decline=True,
                    decline_reason="Base plan declined — rider auto-declined",
                    processing_ms=int((time.time()-t0)*1000)))
                continue

            # Run evaluation
            try:
                payload = _build_payload(body, benefit)
                result  = _run_eval(conn, payload, current.tenant_id)
                outcome   = result.get("outcome", "REFERRED")
                risk_class= result.get("risk_class")
                ndp       = result.get("net_debit_points", 0) or 0
                premium   = result.get("approved_premium") or result.get("annual_premium")
                rules     = result.get("rules_fired", [])

                # Calculate rider premium if not returned by engine
                if premium is None and outcome in ("APPROVED_STP","APPROVED_RATED"):
                    if benefit.is_base_plan:
                        premium = None  # base plan has no rate table fallback here
                    else:
                        premium = _rider_premium(
                            conn, benefit.product_code, benefit.face_amount,
                            body.age, benefit.benefit_type)

                d = BenefitDecisionOut(
                    product_code=benefit.product_code, benefit_type=benefit.benefit_type,
                    benefit_label=label, is_base_plan=benefit.is_base_plan,
                    face_amount=benefit.face_amount, coverage_term_yrs=benefit.coverage_term_yrs,
                    outcome=outcome, risk_class=risk_class, net_debit_points=ndp,
                    annual_premium=float(premium) if premium else None,
                    rules_fired=[r if isinstance(r,dict) else {"rule":str(r)}
                                 for r in (rules or [])],
                    linked_decline=False,
                    processing_ms=int((time.time()-t0)*1000))
                decisions.append(d)
                if benefit.is_base_plan:
                    base_outcome = outcome
                logger.info(f"Proposal {body.proposal_ref}: {benefit.product_code} → {outcome} premium={premium}")

            except Exception as e:
                logger.error(f"Proposal {body.proposal_ref} benefit {benefit.product_code}: {e}")
                decisions.append(BenefitDecisionOut(
                    product_code=benefit.product_code, benefit_type=benefit.benefit_type,
                    benefit_label=label, is_base_plan=benefit.is_base_plan,
                    face_amount=benefit.face_amount, coverage_term_yrs=benefit.coverage_term_yrs,
                    outcome="ERROR", risk_class=None, net_debit_points=0,
                    annual_premium=None, decline_reason=str(e),
                    processing_ms=int((time.time()-t0)*1000)))

        cur.close()

        overall_status = _compute_status(decisions)
        total_premium  = sum(d.annual_premium for d in decisions
                             if d.annual_premium and d.outcome in
                             ("APPROVED_STP","APPROVED_RATED","APPROVED_EXCLUDED"))

        # Persist
        try:
            proposal_id = _persist(conn, body, decisions, overall_status, total_premium, current.tenant_id)
        except Exception as pe:
            logger.error(f"Persist failed: {pe}")
            proposal_id = str(uuid.uuid4())

        # Send ONE consolidated email
        try:
            from services.notification import send_proposal_decision_email
            from database import get_conn as _gc, release_conn as _rc
            _c2 = _gc()
            _cur2 = _c2.cursor()
            _cur2.execute(
                "SELECT email, full_name FROM applicant_master WHERE applicant_ref=%s AND tenant_id=%s LIMIT 1",
                (body.applicant_ref, current.tenant_id))
            _row = _cur2.fetchone()
            _cur2.close()
            if _row:
                _m = dict(_row) if hasattr(_row,"keys") else {"email":_row[0],"full_name":_row[1]}
                if _m.get("email"):
                    send_proposal_decision_email(
                        conn=_c2,
                        to_email=_m["email"],
                        applicant_name=_m.get("full_name") or body.applicant_ref,
                        applicant_ref=body.applicant_ref,
                        proposal_ref=body.proposal_ref,
                        overall_status=overall_status,
                        benefit_decisions=[{
                            "product_code":  d.product_code,
                            "benefit_label": d.benefit_label,
                            "outcome":       d.outcome,
                            "risk_class":    d.risk_class,
                            "annual_premium":d.annual_premium,
                            "face_amount":   d.face_amount,
                            "coverage_term_yrs": d.coverage_term_yrs,
                            "linked_decline":d.linked_decline,
                        } for d in decisions])
            _rc(_c2)
        except Exception as _e:
            logger.warning(f"Proposal email skipped: {_e}")

    finally:
        release(conn)

    approved = sum(1 for d in decisions if d.outcome in ("APPROVED_STP","APPROVED_RATED","APPROVED_EXCLUDED"))
    declined = sum(1 for d in decisions if d.outcome == "DECLINED")
    referred = sum(1 for d in decisions if d.outcome == "REFERRED")

    return ProposalEvaluateResponse(
        proposal_id=proposal_id,
        proposal_ref=body.proposal_ref,
        applicant_ref=body.applicant_ref,
        overall_status=overall_status,
        benefit_decisions=decisions,
        total_annual_premium=total_premium,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        linking_rules_applied=body.apply_linking_rules,
        summary={"total_benefits":len(decisions),"approved":approved,
                 "declined":declined,"referred":referred,
                 "linked_declines":sum(1 for d in decisions if d.linked_decline),
                 "total_premium":total_premium})

@router.get("/underwriting/proposals")
def list_proposals(page: int=1, per_page: int=20, status: Optional[str]=None, current: CurrentUser = None):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where  = "WHERE p.tenant_id=%s"
        params = [current.tenant_id if current else "00000000-0000-0000-0000-000000000001"]
        if status:
            where += " AND p.overall_status=%s"
            params.append(status)
        cur.execute(f"""
            SELECT p.id,p.proposal_ref,p.applicant_ref,p.overall_status,
                   p.total_annual_premium,p.source,p.created_at,
                   COUNT(pb.id) AS benefit_count
            FROM proposal p LEFT JOIN proposal_benefit pb ON pb.proposal_id=p.id
            {where} GROUP BY p.id ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
        """, params+[per_page,(page-1)*per_page])
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*) AS total FROM proposal p {where}", params)
        total = dict(cur.fetchone())["total"]
        cur.close()
        return {"proposals":rows,"total":total,"page":page,"per_page":per_page}
    finally:
        release(conn)

@router.get("/underwriting/proposals/{proposal_id}")
def get_proposal(proposal_id: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM proposal WHERE id=%s AND tenant_id=%s",
                    (proposal_id, current.tenant_id))
        proposal = cur.fetchone()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        cur.execute("SELECT * FROM proposal_benefit WHERE proposal_id=%s ORDER BY created_at",
                    (proposal_id,))
        benefits = [dict(r) for r in cur.fetchall()]
        cur.close()
        return {"proposal":dict(proposal),"benefits":benefits}
    finally:
        release(conn)
