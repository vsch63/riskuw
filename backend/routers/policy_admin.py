"""
routers/policy_admin.py
─────────────────────────────────────────────────────────────────────────────
GET  /policy/list                       — list policies with filters
GET  /policy/{policy_id}                — policy detail with history
POST /policy/issue/{case_id}            — issue a policy from an approved case
POST /policy/{policy_id}/premium        — record a premium payment
POST /policy/{policy_id}/lapse          — manually lapse a policy
POST /policy/{policy_id}/revive         — revive a lapsed policy
POST /policy/{policy_id}/surrender      — surrender a policy
GET  /policy/{policy_id}/letter         — generate policy schedule letter
POST /policy/run-lapse-check            — batch job: lapse overdue policies
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from deps import CurrentUser

router = APIRouter(prefix="/policy", tags=["policy-admin"])

ALLOWED_ROLES = ("underwriter", "senior_underwriter", "admin", "super_admin")


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


def _get_config(cur, tenant_id: str, key: str, default: str) -> str:
    cur.execute(
        "SELECT config_value FROM system_config WHERE tenant_id=%s AND config_key=%s",
        (tenant_id, key),
    )
    row = cur.fetchone()
    return row["config_value"] if row else default


def _generate_policy_number(cur, tenant_id: str) -> str:
    """
    Atomic, collision-free policy number generation.
    Configurable format: {PREFIX}-{YY}-{SEQ padded to N digits}{SUFFIX}
    All parts configurable via system_config:
      - policy_number_prefix  (default "RUW")
      - policy_number_digits  (default 6)
      - policy_number_suffix  (default "", e.g. "-IN" or a product code)
    """
    cur.execute("SELECT nextval('policy_number_seq') AS seq")
    seq = cur.fetchone()["seq"]
    prefix = _get_config(cur, tenant_id, "policy_number_prefix", "RUW")
    digits = int(_get_config(cur, tenant_id, "policy_number_digits", "6"))
    suffix = _get_config(cur, tenant_id, "policy_number_suffix", "")
    year = datetime.now().strftime("%y")
    seq_padded = str(seq).zfill(digits)
    number = f"{prefix}-{year}-{seq_padded}"
    if suffix:
        number = f"{number}{suffix}"
    return number


def _log_status_change(cur, policy_id: str, from_status: Optional[str], to_status: str,
                        reason: str, changed_by: str):
    cur.execute("""
        INSERT INTO policy_status_history (policy_id, from_status, to_status, reason, changed_by)
        VALUES (%s, %s, %s, %s, %s)
    """, (policy_id, from_status, to_status, reason, changed_by))


# ── List policies ────────────────────────────────────────────────────────────────
@router.get("/list")
def list_policies(
    status:   str = Query(default=""),
    product:  str = Query(default=""),
    search:   str = Query(default=""),
    page:     int = Query(default=1, ge=1),
    per_page: int = Query(default=50, le=200),
    current:  CurrentUser = None,
):
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where = ["tenant_id = %s"]
        params = [current.tenant_id]
        if status:
            where.append("status = %s")
            params.append(status)
        if product:
            where.append("product_code = %s")
            params.append(product)
        if search:
            where.append("(policy_number ILIKE %s OR applicant_ref ILIKE %s OR applicant_name ILIKE %s)")
            params.extend([f"%{search}%"] * 3)
        where_sql = " AND ".join(where)
        offset = (page - 1) * per_page

        cur.execute(f"""
            SELECT policy_number, applicant_ref, applicant_name, product_code,
                   sum_assured, annual_premium, status, issue_date,
                   next_premium_due, total_premiums_paid, id
            FROM policy
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for k in ("sum_assured", "annual_premium", "total_premiums_paid"):
                if r.get(k) is not None:
                    r[k] = float(r[k])
            for k in ("issue_date", "next_premium_due"):
                if r.get(k):
                    r[k] = str(r[k])
            r["id"] = str(r["id"])

        cur.execute(f"SELECT COUNT(*) AS c FROM policy WHERE {where_sql}", params)
        total = cur.fetchone()["c"]

        cur.execute("""
            SELECT status, COUNT(*) AS c FROM policy WHERE tenant_id=%s GROUP BY status
        """, (current.tenant_id,))
        status_counts = {r["status"]: r["c"] for r in cur.fetchall()}

        cur.close()
        return {"policies": rows, "total": int(total), "page": page,
                "per_page": per_page, "status_counts": status_counts}
    finally:
        release(conn)


# ── Policy detail ─────────────────────────────────────────────────────────────────
@router.get("/{policy_id}")
def get_policy(policy_id: str, current: CurrentUser = None):
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM policy WHERE id=%s AND tenant_id=%s",
                    (policy_id, current.tenant_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Policy not found")
        policy = dict(row)

        for k in list(policy.keys()):
            if isinstance(policy[k], (date, datetime)):
                policy[k] = str(policy[k])
            from decimal import Decimal
            if isinstance(policy[k], Decimal):
                policy[k] = float(policy[k])
        policy["id"] = str(policy["id"])

        cur.execute("""
            SELECT due_date, amount_due, amount_paid, paid_date, status,
                   payment_mode, receipt_number
            FROM policy_premium_history WHERE policy_id=%s ORDER BY due_date
        """, (policy_id,))
        premiums = []
        for r in cur.fetchall():
            p = dict(r)
            for k in ("due_date", "paid_date"):
                if p.get(k): p[k] = str(p[k])
            for k in ("amount_due", "amount_paid"):
                if p.get(k) is not None: p[k] = float(p[k])
            premiums.append(p)

        cur.execute("""
            SELECT from_status, to_status, reason, changed_by, changed_at
            FROM policy_status_history WHERE policy_id=%s ORDER BY changed_at DESC
        """, (policy_id,))
        history = []
        for r in cur.fetchall():
            h = dict(r)
            if h.get("changed_at"): h["changed_at"] = str(h["changed_at"])[:19]
            history.append(h)

        cur.close()
        return {"policy": policy, "premium_history": premiums, "status_history": history}
    finally:
        release(conn)


# ── Issue policy ─────────────────────────────────────────────────────────────────
class IssuePolicyRequest(BaseModel):
    nominee_name:     Optional[str] = None
    nominee_relation: Optional[str] = None
    premium_mode:     str = "ANNUAL"


@router.post("/issue/{case_id}")
def issue_policy(case_id: str, body: IssuePolicyRequest, current: CurrentUser = None):
    """Issue a policy from an approved underwriting case."""
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT c.id AS case_id, c.application_id, c.product_code, c.face_amount,
                   c.status, a.applicant_ref, a.coverage_term_yrs,
                   d.id AS decision_id, d.approved_premium, d.risk_class
            FROM uw_case c
            JOIN application a ON a.id = c.application_id
            LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = true
            WHERE c.id = %s
        """, (case_id,))
        case = cur.fetchone()
        if not case:
            raise HTTPException(404, "Case not found")
        if case["status"] not in ("APPROVED",):
            raise HTTPException(400, f"Case status is '{case['status']}' — only APPROVED cases can be issued")

        cur.execute("SELECT id FROM policy WHERE application_id=%s", (case["application_id"],))
        if cur.fetchone():
            raise HTTPException(409, "A policy already exists for this application")

        policy_number = _generate_policy_number(cur, current.tenant_id)
        annual_premium = float(case["approved_premium"] or 0)
        mode_divisor = {"ANNUAL": 1, "HALF_YEARLY": 2, "QUARTERLY": 4, "MONTHLY": 12}.get(body.premium_mode, 1)
        modal_premium = round(annual_premium / mode_divisor, 2) if annual_premium else 0

        cur.execute("""
            INSERT INTO policy (
                policy_number, application_id, case_id, decision_id,
                product_code, applicant_ref, sum_assured, annual_premium,
                premium_mode, modal_premium, risk_class, coverage_term_yrs,
                status, nominee_name, nominee_relation,
                tenant_id, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'PENDING_ACCEPTANCE', %s, %s, %s, %s
            ) RETURNING id
        """, (
            policy_number, case["application_id"], case["case_id"], case["decision_id"],
            case["product_code"], case["applicant_ref"], case["face_amount"], annual_premium,
            body.premium_mode, modal_premium, case["risk_class"], case["coverage_term_yrs"],
            body.nominee_name, body.nominee_relation,
            current.tenant_id, current.username,
        ))
        policy_id = cur.fetchone()["id"]

        _log_status_change(cur, policy_id, None, "PENDING_ACCEPTANCE",
                            "Policy issued from approved UW case", current.username)

        conn.commit()
        cur.close()
        return {"status": "issued", "policy_id": str(policy_id), "policy_number": policy_number}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        release(conn)


# ── Record premium payment ──────────────────────────────────────────────────────
class PremiumPayment(BaseModel):
    amount_paid:    float
    paid_date:      str
    payment_mode:   str = "ONLINE"
    receipt_number: Optional[str] = None


@router.post("/{policy_id}/premium")
def record_premium(policy_id: str, body: PremiumPayment, current: CurrentUser = None):
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM policy WHERE id=%s AND tenant_id=%s",
                    (policy_id, current.tenant_id))
        policy = cur.fetchone()
        if not policy:
            raise HTTPException(404, "Policy not found")

        is_first_payment = policy["status"] == "PENDING_FIRST_PREMIUM" or policy["status"] == "PENDING_ACCEPTANCE"

        # Record the payment
        cur.execute("""
            INSERT INTO policy_premium_history
                (policy_id, due_date, amount_due, amount_paid, paid_date, status, payment_mode, receipt_number)
            VALUES (%s, %s, %s, %s, %s, 'PAID', %s, %s)
        """, (policy_id, body.paid_date, body.amount_paid, body.amount_paid,
              body.paid_date, body.payment_mode, body.receipt_number))

        # Calculate next due date based on premium mode
        mode_months = {"ANNUAL": 12, "HALF_YEARLY": 6, "QUARTERLY": 3, "MONTHLY": 1}.get(policy["premium_mode"], 12)
        paid_dt = datetime.strptime(body.paid_date, "%Y-%m-%d").date()
        next_due = date(paid_dt.year + (paid_dt.month + mode_months - 1) // 12,
                         (paid_dt.month + mode_months - 1) % 12 + 1, min(paid_dt.day, 28))

        grace_days = int(_get_config(cur, current.tenant_id, "policy_grace_period_days", "30"))
        grace_end = next_due + timedelta(days=grace_days)

        new_status = "IN_FORCE"
        commencement = policy["commencement_date"] or paid_dt
        maturity = None
        if policy["coverage_term_yrs"]:
            maturity = date(commencement.year + policy["coverage_term_yrs"], commencement.month, commencement.day)

        cur.execute("""
            UPDATE policy SET
                status = %s,
                last_premium_paid_date = %s,
                total_premiums_paid = COALESCE(total_premiums_paid, 0) + %s,
                next_premium_due = %s,
                grace_period_end = %s,
                issue_date = COALESCE(issue_date, %s),
                commencement_date = COALESCE(commencement_date, %s),
                maturity_date = COALESCE(maturity_date, %s),
                updated_at = now()
            WHERE id = %s
        """, (new_status, body.paid_date, body.amount_paid, next_due, grace_end,
              paid_dt, paid_dt, maturity, policy_id))

        if is_first_payment:
            _log_status_change(cur, policy_id, policy["status"], "IN_FORCE",
                                f"First premium received: {body.amount_paid}", current.username)
        elif policy["status"] in ("LAPSED",):
            _log_status_change(cur, policy_id, policy["status"], "IN_FORCE",
                                f"Premium received, policy reactivated", current.username)

        conn.commit()
        cur.close()
        return {"status": "recorded", "next_premium_due": str(next_due), "policy_status": "IN_FORCE"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        release(conn)


# ── Lapse / Revive / Surrender ──────────────────────────────────────────────────
class StatusChangeRequest(BaseModel):
    reason: str


@router.post("/{policy_id}/lapse")
def lapse_policy(policy_id: str, body: StatusChangeRequest, current: CurrentUser = None):
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM policy WHERE id=%s AND tenant_id=%s",
                    (policy_id, current.tenant_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Policy not found")
        cur.execute("""
            UPDATE policy SET status='LAPSED', lapsed_at=now(), updated_at=now() WHERE id=%s
        """, (policy_id,))
        _log_status_change(cur, policy_id, row["status"], "LAPSED", body.reason, current.username)
        conn.commit()
        cur.close()
        return {"status": "lapsed"}
    finally:
        release(conn)


@router.post("/{policy_id}/revive")
def revive_policy(policy_id: str, body: StatusChangeRequest, current: CurrentUser = None):
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM policy WHERE id=%s AND tenant_id=%s",
                    (policy_id, current.tenant_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Policy not found")
        if row["status"] != "LAPSED":
            raise HTTPException(400, "Only LAPSED policies can be revived")
        cur.execute("""
            UPDATE policy SET status='IN_FORCE', revived_at=now(), updated_at=now() WHERE id=%s
        """, (policy_id,))
        _log_status_change(cur, policy_id, "LAPSED", "IN_FORCE", body.reason, current.username)
        conn.commit()
        cur.close()
        return {"status": "revived"}
    finally:
        release(conn)


@router.post("/{policy_id}/surrender")
def surrender_policy(policy_id: str, body: StatusChangeRequest, current: CurrentUser = None):
    if current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, total_premiums_paid FROM policy WHERE id=%s AND tenant_id=%s",
                    (policy_id, current.tenant_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Policy not found")
        surrender_value = float(row["total_premiums_paid"] or 0) * 0.3  # simple placeholder formula
        cur.execute("""
            UPDATE policy SET status='SURRENDERED', surrendered_at=now(),
                surrender_value=%s, updated_at=now() WHERE id=%s
        """, (surrender_value, policy_id))
        _log_status_change(cur, policy_id, row["status"], "SURRENDERED", body.reason, current.username)
        conn.commit()
        cur.close()
        return {"status": "surrendered", "surrender_value": surrender_value}
    finally:
        release(conn)


# ── Batch lapse check (run periodically) ────────────────────────────────────────
@router.post("/run-lapse-check")
def run_lapse_check(current: CurrentUser = None):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admins only")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, policy_number, status FROM policy
            WHERE status = 'IN_FORCE' AND grace_period_end < CURRENT_DATE
        """)
        to_lapse = cur.fetchall()
        for p in to_lapse:
            cur.execute("""
                UPDATE policy SET status='LAPSED', lapsed_at=now(), updated_at=now() WHERE id=%s
            """, (p["id"],))
            _log_status_change(cur, p["id"], "IN_FORCE", "LAPSED",
                                "Auto-lapsed: premium overdue past grace period", "system")
        conn.commit()
        cur.close()
        return {"lapsed_count": len(to_lapse), "policies": [p["policy_number"] for p in to_lapse]}
    finally:
        release(conn)

# ── Policy Schedule Letter (PDF) ─────────────────────────────────────────────
@router.get("/{policy_id}/letter")
def generate_policy_letter(policy_id: str, current: CurrentUser = None):
    """Generate a professional PDF policy schedule letter."""
    if current and current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Load policy details
        cur.execute("""
            SELECT p.*, am.full_name, am.email, am.mobile, am.phone,
                   am.address_line1, am.address_line2, am.city, am.state,
                   am.pincode, am.country, am.nominee_name, am.nominee_relation,
                   am.nominee_dob, am.pan_number
            FROM policy p
            LEFT JOIN applicant_master am ON am.applicant_ref = p.applicant_ref
            WHERE p.id = %s AND p.tenant_id = %s::uuid
        """, (policy_id, current.tenant_id if current else "00000000-0000-0000-0000-000000000001"))
        pol = cur.fetchone()
        if not pol:
            raise HTTPException(404, "Policy not found")

        # Load multi-benefit data if available
        cur.execute("""
            SELECT pb.benefit_type, pb.product_code, pb.face_amount,
                   pb.outcome, pb.risk_class, pb.annual_premium, pb.exclusions,
                   pr.product_name
            FROM proposal_benefit pb
            JOIN proposal prop ON prop.id = pb.proposal_id
            LEFT JOIN products pr ON pr.product_code = pb.product_code
            WHERE prop.applicant_ref = %s
            ORDER BY pb.benefit_type
        """, (pol["applicant_ref"],))
        benefits = cur.fetchall()

        # Load premium history
        cur.execute("""
            SELECT due_date, paid_date, amount_due, amount_paid, payment_mode, receipt_number, status
            FROM policy_premium_history
            WHERE policy_id = %s
            ORDER BY due_date DESC LIMIT 5
        """, (policy_id,))
        premiums = cur.fetchall()

        # Load letter template
        cur.execute("""
            SELECT header_company_name, header_tagline, contact_email,
                   contact_phone, footer_text
            FROM letter_templates
            WHERE outcome = 'APPROVED' AND is_active = true
            LIMIT 1
        """)
        tpl = cur.fetchone() or {}
        cur.close()

        # Build PDF
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
        from fastapi.responses import StreamingResponse

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=15*mm, bottomMargin=20*mm)

        # Colours
        TEAL    = colors.HexColor("#006B5E")
        DARK    = colors.HexColor("#1A1A2E")
        LGRAY   = colors.HexColor("#F0F4F4")
        MGRAY   = colors.HexColor("#888888")
        WHITE   = colors.white
        RED     = colors.HexColor("#DC2626")
        AMBER   = colors.HexColor("#D97706")

        styles = getSampleStyleSheet()
        def S(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        H1    = S("H1", fontSize=18, textColor=TEAL, fontName="Helvetica-Bold", spaceAfter=2)
        H2    = S("H2", fontSize=11, textColor=DARK, fontName="Helvetica-Bold", spaceAfter=4)
        BODY  = S("BODY", fontSize=9, textColor=DARK, leading=14, spaceAfter=4)
        SMALL = S("SMALL", fontSize=8, textColor=MGRAY, leading=12)
        CENTER= S("CENTER", fontSize=9, textColor=DARK, alignment=TA_CENTER)
        MONO  = S("MONO", fontSize=9, textColor=TEAL, fontName="Courier-Bold")

        # Read company name from system_config first (tenant level)
        cur.execute("""
            SELECT config_key, config_value FROM system_config
            WHERE config_key IN ('platform_name','tenant_name','company_name')
        """)
        sys_cfg = {r["config_key"]: r["config_value"] for r in cur.fetchall()}
        company = (sys_cfg.get("tenant_name") or sys_cfg.get("platform_name") or
                   sys_cfg.get("company_name") or
                   tpl.get("header_company_name") or "RiskUW Insurance")
        tagline = tpl.get("header_tagline") or "AI-Enabled Life Insurance Underwriting"
        contact_email = tpl.get("contact_email") or "uw@riskuw.online"
        contact_phone = tpl.get("contact_phone") or "+91 1800 123 4567"
        footer_text   = tpl.get("footer_text") or (
            "This document is computer-generated and does not require a signature. "
            "Any misrepresentation may result in cancellation of this policy.")

        story = []

        # ── HEADER ────────────────────────────────────────────────────────────
        header_data = [[
            Paragraph(f"<b>{company}</b>", S("CH", fontSize=16, textColor=TEAL, fontName="Helvetica-Bold")),
            Paragraph(f"<b>POLICY SCHEDULE</b>", S("CR", fontSize=13, textColor=DARK, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        header_tbl = Table(header_data, colWidths=[100*mm, 70*mm])
        header_tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("BACKGROUND", (0,0), (-1,-1), DARK),
            ("LEFTPADDING", (0,0), (0,0), 6*mm),
            ("RIGHTPADDING", (-1,0), (-1,0), 6*mm),
            ("TOPPADDING", (0,0), (-1,-1), 4*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm),
        ]))
        story.append(header_tbl)

        # Tagline bar
        tl_data = [[Paragraph(tagline, S("TL", fontSize=8, textColor=colors.HexColor("#00D4AA"), alignment=TA_CENTER))]]
        tl_tbl = Table(tl_data, colWidths=[170*mm])
        tl_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#0A1628")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
        ]))
        story.append(tl_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICY NUMBER BANNER ──────────────────────────────────────────────
        status_color = TEAL if pol["status"] == "IN_FORCE" else AMBER if pol["status"] == "PENDING_ACCEPTANCE" else RED
        pn_data = [[
            Paragraph(f"Policy Number: <b>{pol['policy_number']}</b>",
                S("PN", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold")),
            Paragraph(f"Status: <b>{pol['status'].replace('_',' ')}</b>",
                S("PS", fontSize=10, textColor=status_color, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        pn_tbl = Table(pn_data, colWidths=[100*mm, 70*mm])
        pn_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1E3A5F")),
            ("LEFTPADDING", (0,0), (0,0), 4*mm),
            ("RIGHTPADDING", (-1,0), (-1,0), 4*mm),
            ("TOPPADDING", (0,0), (-1,-1), 3*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3*mm),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(pn_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICYHOLDER DETAILS ──────────────────────────────────────────────
        story.append(Paragraph("POLICYHOLDER DETAILS", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        name = pol.get("full_name") or pol.get("applicant_name") or pol.get("applicant_ref","—")
        addr_parts = [pol.get("address_line1"), pol.get("city"),
                      pol.get("state"), pol.get("pincode"), pol.get("country")]
        address = ", ".join(p for p in addr_parts if p) or "—"

        ph_data = [
            ["Full Name", name, "PAN Number", pol.get("pan_number") or "—"],
            ["Email", pol.get("email") or "—", "Mobile", pol.get("mobile") or pol.get("phone") or "—"],
            ["Address", address, "", ""],
            ["Nominee", pol.get("nominee_name") or "—", "Relationship", pol.get("nominee_relation") or "—"],
        ]
        ph_tbl = Table(ph_data, colWidths=[35*mm, 55*mm, 35*mm, 45*mm])
        ph_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0,0), (0,-1), DARK),
            ("TEXTCOLOR", (2,0), (2,-1), DARK),
            ("BACKGROUND", (0,0), (-1,-1), LGRAY),
            ("BACKGROUND", (1,0), (1,-1), WHITE),
            ("BACKGROUND", (3,0), (3,-1), WHITE),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
            ("SPAN", (1,2), (3,2)),
        ]))
        story.append(ph_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICY DETAILS ────────────────────────────────────────────────────
        story.append(Paragraph("POLICY DETAILS", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        def fmt_date(d):
            if not d: return "—"
            return str(d)[:10]
        def fmt_amt(v):
            if not v: return "—"
            try: return f"\u20b9{float(v):,.2f}"
            except: return str(v)

        pol_data = [
            ["Product Code", pol.get("product_code") or "—",
             "Risk Class", pol.get("risk_class") or "—"],
            ["Sum Assured", fmt_amt(pol.get("sum_assured") or pol.get("face_amount")),
             "Coverage Term", f"{pol.get('coverage_term_yrs') or '—'} years"],
            ["Issue Date", fmt_date(pol.get("issue_date")),
             "Commencement Date", fmt_date(pol.get("commencement_date"))],
            ["Maturity Date", fmt_date(pol.get("maturity_date")),
             "Next Premium Due", fmt_date(pol.get("next_premium_due"))],
            ["Premium Mode", (pol.get("premium_mode") or "ANNUAL").replace("_"," ").title(),
             "Modal Premium", fmt_amt(pol.get("modal_premium") or pol.get("annual_premium"))],
            ["Grace Period End", fmt_date(pol.get("grace_period_end")),
             "Total Premiums Paid", fmt_amt(pol.get("total_premiums_paid"))],
        ]
        pol_tbl = Table(pol_data, colWidths=[40*mm, 50*mm, 40*mm, 40*mm])
        pol_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,-1), LGRAY),
            ("BACKGROUND", (1,0), (1,-1), WHITE),
            ("BACKGROUND", (3,0), (3,-1), WHITE),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
        ]))
        story.append(pol_tbl)
        story.append(Spacer(1, 5*mm))

        # ── BENEFIT SCHEDULE ──────────────────────────────────────────────────
        story.append(Paragraph("BENEFIT SCHEDULE", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        if benefits:
            ben_header = [
                Paragraph("<b>Benefit</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Product</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Sum Assured</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph("<b>Status</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Annual Premium</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph("<b>Exclusions</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
            ]
            ben_rows = [ben_header]
            total_prem = 0
            for b in benefits:
                b_outcome = b.get("outcome","—")
                b_color = TEAL if "APPROVED" in (b_outcome or "") else RED
                excl = ""
                if b.get("exclusions"):
                    import json as _json
                    try:
                        excl_list = b["exclusions"] if isinstance(b["exclusions"], list) else _json.loads(b["exclusions"])
                        excl = "; ".join(e.get("condition","") for e in excl_list if isinstance(e, dict))
                    except: excl = str(b["exclusions"])[:40]
                prem = b.get("annual_premium")
                if prem: total_prem += float(prem)
                ben_rows.append([
                    Paragraph(b.get("benefit_type","").replace("RIDER_","") + (" (Base)" if b.get("benefit_type") == "BASE" else " Rider"),
                        S("BC", fontSize=8, textColor=DARK)),
                    Paragraph(b.get("product_code","—"), S("BC", fontSize=8, textColor=DARK, fontName="Courier")),
                    Paragraph(fmt_amt(b.get("face_amount")), S("BC", fontSize=8, textColor=DARK, alignment=TA_RIGHT)),
                    Paragraph(b_outcome.replace("_"," "), S("BC", fontSize=8, textColor=b_color)),
                    Paragraph(fmt_amt(prem) if prem else "—", S("BC", fontSize=8, textColor=DARK, alignment=TA_RIGHT)),
                    Paragraph(excl or "None", S("BC", fontSize=7, textColor=AMBER if excl else MGRAY)),
                ])
            # Total row
            ben_rows.append([
                Paragraph("<b>TOTAL</b>", S("BT", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                "", "", "",
                Paragraph(f"<b>{fmt_amt(total_prem)}</b>",
                    S("BT", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                "",
            ])
            ben_tbl = Table(ben_rows, colWidths=[30*mm, 32*mm, 28*mm, 28*mm, 28*mm, 24*mm])
            nrows = len(ben_rows)
            ben_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("BACKGROUND", (0,nrows-1), (-1,nrows-1), colors.HexColor("#1E3A5F")),
                ("BACKGROUND", (0,1), (-1,nrows-2), WHITE),
                ("ROWBACKGROUNDS", (0,1), (-1,nrows-2), [WHITE, LGRAY]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("SPAN", (0,nrows-1), (3,nrows-1)),
                ("SPAN", (5,nrows-1), (5,nrows-1)),
            ]))
            story.append(ben_tbl)
        else:
            # Single benefit — show base product only
            sb_data = [
                [Paragraph("<b>Cover</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                 Paragraph("<b>Sum Assured</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                 Paragraph("<b>Annual Premium</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
                [Paragraph(pol.get("product_code") or "Life Insurance", BODY),
                 Paragraph(fmt_amt(pol.get("sum_assured") or pol.get("face_amount")), S("SA", fontSize=9, alignment=TA_RIGHT)),
                 Paragraph(fmt_amt(pol.get("annual_premium")), S("AP", fontSize=9, alignment=TA_RIGHT))],
            ]
            sb_tbl = Table(sb_data, colWidths=[80*mm, 45*mm, 45*mm])
            sb_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("BACKGROUND", (0,1), (-1,1), LGRAY),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
            ]))
            story.append(sb_tbl)

        story.append(Spacer(1, 5*mm))

        # ── PREMIUM HISTORY ───────────────────────────────────────────────────
        if premiums:
            story.append(Paragraph("PREMIUM PAYMENT HISTORY", H2))
            story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))
            pr_header = ["Due Date", "Paid Date", "Amount", "Mode", "Receipt No.", "Status"]
            pr_rows = [pr_header]
            for pr in premiums:
                pr_rows.append([
                    fmt_date(pr.get("due_date")),
                    fmt_date(pr.get("paid_date")),
                    fmt_amt(pr.get("amount_paid") or pr.get("amount_due")),
                    (pr.get("payment_mode") or "—").replace("_"," ").title(),
                    pr.get("receipt_number") or "—",
                    pr.get("status") or "—",
                ])
            pr_tbl = Table(pr_rows, colWidths=[28*mm, 28*mm, 30*mm, 28*mm, 32*mm, 24*mm])
            pr_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("TEXTCOLOR", (0,0), (-1,0), WHITE),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LGRAY]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
            ]))
            story.append(pr_tbl)
            story.append(Spacer(1, 5*mm))

        # ── IMPORTANT NOTES ───────────────────────────────────────────────────
        story.append(Paragraph("IMPORTANT INFORMATION", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))
        notes = [
            "This policy schedule is subject to the terms and conditions of the policy contract.",
            "The free-look period is 15 days from the date of receipt of this policy document.",
            "Please preserve this document safely as it is required for claims processing.",
            f"For queries: {contact_email}  |  {contact_phone}",
        ]
        for note in notes:
            story.append(Paragraph(f"• {note}", SMALL))
        story.append(Spacer(1, 5*mm))

        # ── FOOTER ────────────────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL))
        story.append(Spacer(1, 2*mm))
        gen_date = datetime.now().strftime("%d %B %Y at %H:%M")
        story.append(Paragraph(
            f"{footer_text}<br/>"
            f"<font color='#888888' size='7'>Generated: {gen_date}  |  "
            f"Policy: {pol['policy_number']}  |  Powered by RiskUW</font>",
            S("FT", fontSize=7, textColor=MGRAY, leading=10, alignment=TA_CENTER)
        ))

        doc.build(story)
        buf.seek(0)

        from fastapi.responses import StreamingResponse
        filename = f"PolicySchedule_{pol['policy_number']}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(500, f"PDF generation failed: {e}\n{traceback.format_exc()[:300]}")
    finally:
        release(conn)

# ── Policy Schedule Letter (PDF) ─────────────────────────────────────────────
@router.get("/{policy_id}/letter")
def generate_policy_letter(policy_id: str, current: CurrentUser = None):
    """Generate a professional PDF policy schedule letter."""
    if current and current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Load policy details
        cur.execute("""
            SELECT p.*, am.full_name, am.email, am.mobile, am.phone,
                   am.address_line1, am.address_line2, am.city, am.state,
                   am.pincode, am.country, am.nominee_name, am.nominee_relation,
                   am.nominee_dob, am.pan_number
            FROM policy p
            LEFT JOIN applicant_master am ON am.applicant_ref = p.applicant_ref
            WHERE p.id = %s AND p.tenant_id = %s::uuid
        """, (policy_id, current.tenant_id if current else "00000000-0000-0000-0000-000000000001"))
        pol = cur.fetchone()
        if not pol:
            raise HTTPException(404, "Policy not found")

        # Load multi-benefit data if available
        cur.execute("""
            SELECT pb.benefit_type, pb.product_code, pb.face_amount,
                   pb.outcome, pb.risk_class, pb.annual_premium, pb.exclusions,
                   pr.product_name
            FROM proposal_benefit pb
            JOIN proposal prop ON prop.id = pb.proposal_id
            LEFT JOIN products pr ON pr.product_code = pb.product_code
            WHERE prop.applicant_ref = %s
            ORDER BY pb.benefit_type
        """, (pol["applicant_ref"],))
        benefits = cur.fetchall()

        # Load premium history
        cur.execute("""
            SELECT due_date, paid_date, amount, mode, receipt_number, status
            FROM policy_premium_history
            WHERE policy_id = %s
            ORDER BY due_date DESC LIMIT 5
        """, (policy_id,))
        premiums = cur.fetchall()

        # Load letter template
        cur.execute("""
            SELECT header_company_name, header_tagline, contact_email,
                   contact_phone, footer_text
            FROM letter_templates
            WHERE outcome = 'APPROVED' AND is_active = true
            LIMIT 1
        """)
        tpl = cur.fetchone() or {}
        cur.close()

        # Build PDF
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
        from fastapi.responses import StreamingResponse

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=15*mm, bottomMargin=20*mm)

        # Colours
        TEAL    = colors.HexColor("#006B5E")
        DARK    = colors.HexColor("#1A1A2E")
        LGRAY   = colors.HexColor("#F0F4F4")
        MGRAY   = colors.HexColor("#888888")
        WHITE   = colors.white
        RED     = colors.HexColor("#DC2626")
        AMBER   = colors.HexColor("#D97706")

        styles = getSampleStyleSheet()
        def S(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        H1    = S("H1", fontSize=18, textColor=TEAL, fontName="Helvetica-Bold", spaceAfter=2)
        H2    = S("H2", fontSize=11, textColor=DARK, fontName="Helvetica-Bold", spaceAfter=4)
        BODY  = S("BODY", fontSize=9, textColor=DARK, leading=14, spaceAfter=4)
        SMALL = S("SMALL", fontSize=8, textColor=MGRAY, leading=12)
        CENTER= S("CENTER", fontSize=9, textColor=DARK, alignment=TA_CENTER)
        MONO  = S("MONO", fontSize=9, textColor=TEAL, fontName="Courier-Bold")

        company = tpl.get("header_company_name") or "RiskUW Insurance"
        tagline = tpl.get("header_tagline") or "AI-Enabled Life Insurance Underwriting"
        contact_email = tpl.get("contact_email") or "uw@riskuw.online"
        contact_phone = tpl.get("contact_phone") or "+91 1800 123 4567"
        footer_text   = tpl.get("footer_text") or (
            "This document is computer-generated and does not require a signature. "
            "Any misrepresentation may result in cancellation of this policy.")

        story = []

        # ── HEADER ────────────────────────────────────────────────────────────
        header_data = [[
            Paragraph(f"<b>{company}</b>", S("CH", fontSize=16, textColor=TEAL, fontName="Helvetica-Bold")),
            Paragraph(f"<b>POLICY SCHEDULE</b>", S("CR", fontSize=13, textColor=DARK, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        header_tbl = Table(header_data, colWidths=[100*mm, 70*mm])
        header_tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("BACKGROUND", (0,0), (-1,-1), DARK),
            ("LEFTPADDING", (0,0), (0,0), 6*mm),
            ("RIGHTPADDING", (-1,0), (-1,0), 6*mm),
            ("TOPPADDING", (0,0), (-1,-1), 4*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm),
        ]))
        story.append(header_tbl)

        # Tagline bar
        tl_data = [[Paragraph(tagline, S("TL", fontSize=8, textColor=colors.HexColor("#00D4AA"), alignment=TA_CENTER))]]
        tl_tbl = Table(tl_data, colWidths=[170*mm])
        tl_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#0A1628")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
        ]))
        story.append(tl_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICY NUMBER BANNER ──────────────────────────────────────────────
        status_color = TEAL if pol["status"] == "IN_FORCE" else AMBER if pol["status"] == "PENDING_ACCEPTANCE" else RED
        pn_data = [[
            Paragraph(f"Policy Number: <b>{pol['policy_number']}</b>",
                S("PN", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold")),
            Paragraph(f"Status: <b>{pol['status'].replace('_',' ')}</b>",
                S("PS", fontSize=10, textColor=status_color, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        pn_tbl = Table(pn_data, colWidths=[100*mm, 70*mm])
        pn_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1E3A5F")),
            ("LEFTPADDING", (0,0), (0,0), 4*mm),
            ("RIGHTPADDING", (-1,0), (-1,0), 4*mm),
            ("TOPPADDING", (0,0), (-1,-1), 3*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3*mm),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(pn_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICYHOLDER DETAILS ──────────────────────────────────────────────
        story.append(Paragraph("POLICYHOLDER DETAILS", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        name = pol.get("full_name") or pol.get("applicant_name") or pol.get("applicant_ref","—")
        addr_parts = [pol.get("address_line1"), pol.get("city"),
                      pol.get("state"), pol.get("pincode"), pol.get("country")]
        address = ", ".join(p for p in addr_parts if p) or "—"

        ph_data = [
            ["Full Name", name, "PAN Number", pol.get("pan_number") or "—"],
            ["Email", pol.get("email") or "—", "Mobile", pol.get("mobile") or pol.get("phone") or "—"],
            ["Address", address, "", ""],
            ["Nominee", pol.get("nominee_name") or "—", "Relationship", pol.get("nominee_relation") or "—"],
        ]
        ph_tbl = Table(ph_data, colWidths=[35*mm, 55*mm, 35*mm, 45*mm])
        ph_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0,0), (0,-1), DARK),
            ("TEXTCOLOR", (2,0), (2,-1), DARK),
            ("BACKGROUND", (0,0), (-1,-1), LGRAY),
            ("BACKGROUND", (1,0), (1,-1), WHITE),
            ("BACKGROUND", (3,0), (3,-1), WHITE),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
            ("SPAN", (1,2), (3,2)),
        ]))
        story.append(ph_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICY DETAILS ────────────────────────────────────────────────────
        story.append(Paragraph("POLICY DETAILS", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        def fmt_date(d):
            if not d: return "—"
            return str(d)[:10]
        def fmt_amt(v):
            if not v: return "—"
            try: return f"\u20b9{float(v):,.2f}"
            except: return str(v)

        pol_data = [
            ["Product Code", pol.get("product_code") or "—",
             "Risk Class", pol.get("risk_class") or "—"],
            ["Sum Assured", fmt_amt(pol.get("sum_assured") or pol.get("face_amount")),
             "Coverage Term", f"{pol.get('coverage_term_yrs') or '—'} years"],
            ["Issue Date", fmt_date(pol.get("issue_date")),
             "Commencement Date", fmt_date(pol.get("commencement_date"))],
            ["Maturity Date", fmt_date(pol.get("maturity_date")),
             "Next Premium Due", fmt_date(pol.get("next_premium_due"))],
            ["Premium Mode", (pol.get("premium_mode") or "ANNUAL").replace("_"," ").title(),
             "Modal Premium", fmt_amt(pol.get("modal_premium") or pol.get("annual_premium"))],
            ["Grace Period End", fmt_date(pol.get("grace_period_end")),
             "Total Premiums Paid", fmt_amt(pol.get("total_premiums_paid"))],
        ]
        pol_tbl = Table(pol_data, colWidths=[40*mm, 50*mm, 40*mm, 40*mm])
        pol_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,-1), LGRAY),
            ("BACKGROUND", (1,0), (1,-1), WHITE),
            ("BACKGROUND", (3,0), (3,-1), WHITE),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
        ]))
        story.append(pol_tbl)
        story.append(Spacer(1, 5*mm))

        # ── BENEFIT SCHEDULE ──────────────────────────────────────────────────
        story.append(Paragraph("BENEFIT SCHEDULE", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        if benefits:
            ben_header = [
                Paragraph("<b>Benefit</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Product</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Sum Assured</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph("<b>Status</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Annual Premium</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph("<b>Exclusions</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
            ]
            ben_rows = [ben_header]
            total_prem = 0
            for b in benefits:
                b_outcome = b.get("outcome","—")
                b_color = TEAL if "APPROVED" in (b_outcome or "") else RED
                excl = ""
                if b.get("exclusions"):
                    import json as _json
                    try:
                        excl_list = b["exclusions"] if isinstance(b["exclusions"], list) else _json.loads(b["exclusions"])
                        excl = "; ".join(e.get("condition","") for e in excl_list if isinstance(e, dict))
                    except: excl = str(b["exclusions"])[:40]
                prem = b.get("annual_premium")
                if prem: total_prem += float(prem)
                ben_rows.append([
                    Paragraph(b.get("benefit_type","").replace("RIDER_","") + (" (Base)" if b.get("benefit_type") == "BASE" else " Rider"),
                        S("BC", fontSize=8, textColor=DARK)),
                    Paragraph(b.get("product_code","—"), S("BC", fontSize=8, textColor=DARK, fontName="Courier")),
                    Paragraph(fmt_amt(b.get("face_amount")), S("BC", fontSize=8, textColor=DARK, alignment=TA_RIGHT)),
                    Paragraph(b_outcome.replace("_"," "), S("BC", fontSize=8, textColor=b_color)),
                    Paragraph(fmt_amt(prem) if prem else "—", S("BC", fontSize=8, textColor=DARK, alignment=TA_RIGHT)),
                    Paragraph(excl or "None", S("BC", fontSize=7, textColor=AMBER if excl else MGRAY)),
                ])
            # Total row
            ben_rows.append([
                Paragraph("<b>TOTAL</b>", S("BT", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                "", "", "",
                Paragraph(f"<b>{fmt_amt(total_prem)}</b>",
                    S("BT", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                "",
            ])
            ben_tbl = Table(ben_rows, colWidths=[30*mm, 32*mm, 28*mm, 28*mm, 28*mm, 24*mm])
            nrows = len(ben_rows)
            ben_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("BACKGROUND", (0,nrows-1), (-1,nrows-1), colors.HexColor("#1E3A5F")),
                ("BACKGROUND", (0,1), (-1,nrows-2), WHITE),
                ("ROWBACKGROUNDS", (0,1), (-1,nrows-2), [WHITE, LGRAY]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("SPAN", (0,nrows-1), (3,nrows-1)),
                ("SPAN", (5,nrows-1), (5,nrows-1)),
            ]))
            story.append(ben_tbl)
        else:
            # Single benefit — show base product only
            sb_data = [
                [Paragraph("<b>Cover</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                 Paragraph("<b>Sum Assured</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                 Paragraph("<b>Annual Premium</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
                [Paragraph(pol.get("product_code") or "Life Insurance", BODY),
                 Paragraph(fmt_amt(pol.get("sum_assured") or pol.get("face_amount")), S("SA", fontSize=9, alignment=TA_RIGHT)),
                 Paragraph(fmt_amt(pol.get("annual_premium")), S("AP", fontSize=9, alignment=TA_RIGHT))],
            ]
            sb_tbl = Table(sb_data, colWidths=[80*mm, 45*mm, 45*mm])
            sb_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("BACKGROUND", (0,1), (-1,1), LGRAY),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
            ]))
            story.append(sb_tbl)

        story.append(Spacer(1, 5*mm))

        # ── PREMIUM HISTORY ───────────────────────────────────────────────────
        if premiums:
            story.append(Paragraph("PREMIUM PAYMENT HISTORY", H2))
            story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))
            pr_header = ["Due Date", "Paid Date", "Amount", "Mode", "Receipt No.", "Status"]
            pr_rows = [pr_header]
            for pr in premiums:
                pr_rows.append([
                    fmt_date(pr.get("due_date")),
                    fmt_date(pr.get("paid_date")),
                    fmt_amt(pr.get("amount")),
                    (pr.get("mode") or "—").replace("_"," ").title(),
                    pr.get("receipt_number") or "—",
                    pr.get("status") or "—",
                ])
            pr_tbl = Table(pr_rows, colWidths=[28*mm, 28*mm, 30*mm, 28*mm, 32*mm, 24*mm])
            pr_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("TEXTCOLOR", (0,0), (-1,0), WHITE),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LGRAY]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
            ]))
            story.append(pr_tbl)
            story.append(Spacer(1, 5*mm))

        # ── IMPORTANT NOTES ───────────────────────────────────────────────────
        story.append(Paragraph("IMPORTANT INFORMATION", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))
        notes = [
            "This policy schedule is subject to the terms and conditions of the policy contract.",
            "The free-look period is 15 days from the date of receipt of this policy document.",
            "Please preserve this document safely as it is required for claims processing.",
            f"For queries: {contact_email}  |  {contact_phone}",
        ]
        for note in notes:
            story.append(Paragraph(f"• {note}", SMALL))
        story.append(Spacer(1, 5*mm))

        # ── FOOTER ────────────────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL))
        story.append(Spacer(1, 2*mm))
        gen_date = datetime.now().strftime("%d %B %Y at %H:%M")
        story.append(Paragraph(
            f"{footer_text}<br/>"
            f"<font color='#888888' size='7'>Generated: {gen_date}  |  "
            f"Policy: {pol['policy_number']}  |  Powered by RiskUW</font>",
            S("FT", fontSize=7, textColor=MGRAY, leading=10, alignment=TA_CENTER)
        ))

        doc.build(story)
        buf.seek(0)

        from fastapi.responses import StreamingResponse
        filename = f"PolicySchedule_{pol['policy_number']}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(500, f"PDF generation failed: {e}\n{traceback.format_exc()[:300]}")
    finally:
        release(conn)
