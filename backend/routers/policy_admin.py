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
