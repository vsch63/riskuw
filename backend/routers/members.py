"""
routers/members.py
Member Data Registry — personal/contact info linked to UW cases via applicant_ref
"""
from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from deps import CurrentUser
from database import get_conn, release_conn
import psycopg2.extras

router = APIRouter(prefix="/members", tags=["Members"])

def _db():
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn

def _fmt(row: dict) -> dict:
    for f in ("dob", "nominee_dob"):
        if row.get(f):
            row[f] = str(row[f])
    for f in ("annual_income",):
        if row.get(f) is not None:
            row[f] = float(row[f])
    return row

class MemberIn(BaseModel):
    applicant_ref:    str
    salutation:       Optional[str]   = None
    full_name:        str
    middle_name:      Optional[str]   = None
    email:            Optional[str]   = None
    phone:            Optional[str]   = None
    mobile:           Optional[str]   = None
    alternate_phone:  Optional[str]   = None
    dob:              Optional[date]  = None
    gender:           Optional[str]   = None
    address_line1:    Optional[str]   = None
    address_line2:    Optional[str]   = None
    city:             Optional[str]   = None
    state:            Optional[str]   = None
    pincode:          Optional[str]   = None
    country:          str             = "India"
    nationality:      str             = "Indian"
    pan_number:       Optional[str]   = None
    aadhar_masked:    Optional[str]   = None
    occupation:       Optional[str]   = None
    annual_income:    Optional[float] = None
    nominee_name:     Optional[str]   = None
    nominee_relation: Optional[str]   = None
    nominee_dob:      Optional[date]  = None
    group_name:       Optional[str]   = None
    employee_id:      Optional[str]   = None
    department:       Optional[str]   = None
    is_active:        bool            = True

# ── List / Search ─────────────────────────────────────────────────────────────
@router.get("")
def list_members(
    current: CurrentUser,
    search:      Optional[str] = None,
    active_only: bool = False,
    page:        int  = 1,
    page_size:   int  = 50,
):
    conn, release = _db()
    try:
        cur = conn.cursor()
        where, params = [], []
        if active_only:
            where.append("m.is_active = true")
        if search:
            where.append("""(
                m.full_name     ILIKE %s OR m.applicant_ref ILIKE %s OR
                m.email         ILIKE %s OR m.phone         ILIKE %s OR
                m.mobile        ILIKE %s OR m.pan_number    ILIKE %s OR
                m.employee_id   ILIKE %s OR m.group_name    ILIKE %s
            )""")
            s = f"%{search}%"
            params.extend([s]*8)

        base = """
            SELECT m.*,
                   q.outcome, q.approved_premium, q.product_code,
                   q.decision_date, q.risk_class
            FROM applicant_master m
            LEFT JOIN LATERAL (
                SELECT outcome, approved_premium, product_code,
                       decision_date, risk_class
                FROM policy_admin_queue
                WHERE applicant_ref = m.applicant_ref
                ORDER BY created_at DESC LIMIT 1
            ) q ON true
        """
        if where:
            base += " WHERE " + " AND ".join(where)

        # Count
        cur.execute(f"SELECT COUNT(*) FROM ({base}) t", params)
        total = cur.fetchone()["count"]

        base += f" ORDER BY m.created_at DESC LIMIT {page_size} OFFSET {(page-1)*page_size}"
        cur.execute(base, params)
        rows = [_fmt(dict(r)) for r in cur.fetchall()]
        cur.close()
        return {"total": total, "page": page, "page_size": page_size, "items": rows}
    finally:
        release(conn)

# ── Get single member ─────────────────────────────────────────────────────────
@router.get("/{applicant_ref}")
def get_member(applicant_ref: str, current: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM applicant_master WHERE applicant_ref = %s",
            (applicant_ref,)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Member not found")
        return _fmt(dict(row))
    finally:
        release(conn)

# ── Create ────────────────────────────────────────────────────────────────────
@router.post("", status_code=201)
def create_member(body: MemberIn, current: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        # Check duplicate applicant_ref
        cur.execute(
            "SELECT id FROM applicant_master WHERE applicant_ref = %s",
            (body.applicant_ref,)
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"Member with ref '{body.applicant_ref}' already exists"
            )
        cur.execute("""
            INSERT INTO applicant_master (
                applicant_ref, salutation, full_name, middle_name,
                email, phone, mobile, alternate_phone,
                dob, gender, address_line1, address_line2,
                city, state, pincode, country, nationality,
                pan_number, aadhar_masked, occupation, annual_income,
                nominee_name, nominee_relation, nominee_dob,
                group_name, employee_id, department,
                is_active, source, uploaded_by
            ) VALUES (
                %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,
                %s,%s,%s,%s,%s, %s,%s,%s,%s,
                %s,%s,%s, %s,%s,%s, %s,%s,%s
            ) RETURNING id
        """, (
            body.applicant_ref, body.salutation, body.full_name, body.middle_name,
            body.email, body.phone, body.mobile, body.alternate_phone,
            body.dob, body.gender, body.address_line1, body.address_line2,
            body.city, body.state, body.pincode, body.country, body.nationality,
            body.pan_number, body.aadhar_masked, body.occupation, body.annual_income,
            body.nominee_name, body.nominee_relation, body.nominee_dob,
            body.group_name, body.employee_id, body.department,
            body.is_active, "MANUAL", current.username,
        ))
        conn.commit()
        mid = cur.fetchone()["id"]
        cur.close()
        return {"id": mid, "message": "Member created"}
    finally:
        release(conn)

# ── Update ────────────────────────────────────────────────────────────────────
@router.put("/{applicant_ref}")
def update_member(applicant_ref: str, body: MemberIn, current: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE applicant_master SET
                salutation=%s, full_name=%s, middle_name=%s,
                email=%s, phone=%s, mobile=%s, alternate_phone=%s,
                dob=%s, gender=%s, address_line1=%s, address_line2=%s,
                city=%s, state=%s, pincode=%s, country=%s, nationality=%s,
                pan_number=%s, aadhar_masked=%s, occupation=%s, annual_income=%s,
                nominee_name=%s, nominee_relation=%s, nominee_dob=%s,
                group_name=%s, employee_id=%s, department=%s,
                is_active=%s, updated_at=now()
            WHERE applicant_ref=%s
        """, (
            body.salutation, body.full_name, body.middle_name,
            body.email, body.phone, body.mobile, body.alternate_phone,
            body.dob, body.gender, body.address_line1, body.address_line2,
            body.city, body.state, body.pincode, body.country, body.nationality,
            body.pan_number, body.aadhar_masked, body.occupation, body.annual_income,
            body.nominee_name, body.nominee_relation, body.nominee_dob,
            body.group_name, body.employee_id, body.department,
            body.is_active, applicant_ref,
        ))
        conn.commit()
        cur.close()
        return {"message": "Member updated"}
    finally:
        release(conn)

# ── Delete ────────────────────────────────────────────────────────────────────
@router.delete("/{applicant_ref}")
def delete_member(applicant_ref: str, current: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM applicant_master WHERE applicant_ref=%s",
            (applicant_ref,)
        )
        conn.commit()
        cur.close()
        return {"message": "Member deleted"}
    finally:
        release(conn)

# ── Get UW history for a member ───────────────────────────────────────────────
@router.get("/{applicant_ref}/uw-history")
def get_uw_history(applicant_ref: str, current: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT outcome, risk_class, net_debit_points,
                   approved_premium, product_code, face_amount,
                   decision_date, status, created_at
            FROM policy_admin_queue
            WHERE applicant_ref = %s
            ORDER BY created_at DESC
        """, (applicant_ref,))
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            row = dict(r)
            for f in ("decision_date", "created_at"):
                if row.get(f):
                    row[f] = str(row[f])
            if row.get("approved_premium"):
                row["approved_premium"] = float(row["approved_premium"])
            result.append(row)
        return result
    finally:
        release(conn)

# ── CSV/Excel Upload ──────────────────────────────────────────────────────────
import io, csv, uuid
from fastapi import UploadFile, File, Form

@router.post("/upload")
async def upload_members(
    current:    CurrentUser,
    file:       UploadFile = File(...),
    on_conflict: str       = Form("update"),  # "update" | "skip"
    notes:      str        = Form(""),
):
    """Upload CSV or Excel file of member data."""
    conn, release = _db()
    try:
        content = await file.read()
        filename = file.filename or "upload.csv"

        # Parse file
        rows = []
        if filename.endswith((".xlsx", ".xls")):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
                ws = wb.active
                headers = None
                for row in ws.iter_rows(values_only=True):
                    if headers is None:
                        headers = [str(c).strip().lower() if c else "" for c in row]
                    else:
                        rows.append(dict(zip(headers, row)))
            except ImportError:
                raise HTTPException(status_code=400,
                    detail="openpyxl not installed — upload CSV instead")
        else:
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = [{k.strip().lower(): v for k, v in r.items()} for r in reader]

        if not rows:
            raise HTTPException(status_code=400, detail="File is empty or unreadable")

        # Required column
        if "applicant_ref" not in (rows[0].keys() if rows else []):
            raise HTTPException(status_code=400,
                detail="Missing required column: applicant_ref")

        inserted = updated = skipped = errors = 0
        upload_ref = str(uuid.uuid4())[:8].upper()
        cur = conn.cursor()

        for row in rows:
            ref = str(row.get("applicant_ref", "")).strip()
            if not ref:
                errors += 1
                continue
            try:
                # Check if exists
                cur.execute(
                    "SELECT id FROM applicant_master WHERE applicant_ref=%s", (ref,)
                )
                exists = cur.fetchone()

                def g(k, default=None):
                    v = row.get(k)
                    return str(v).strip() if v not in (None, "", "None") else default

                if exists:
                    if on_conflict == "skip":
                        skipped += 1
                        continue
                    cur.execute("""
                        UPDATE applicant_master SET
                            full_name=%s, email=%s, phone=%s, mobile=%s,
                            dob=%s, gender=%s, address_line1=%s, address_line2=%s,
                            city=%s, state=%s, pincode=%s, country=%s,
                            occupation=%s, group_name=%s, employee_id=%s,
                            department=%s, nominee_name=%s, nominee_relation=%s,
                            updated_at=now()
                        WHERE applicant_ref=%s
                    """, (
                        g("full_name"), g("email"), g("phone"), g("mobile"),
                        g("dob"), g("gender"), g("address_line1"), g("address_line2"),
                        g("city"), g("state"), g("pincode"), g("country","India"),
                        g("occupation"), g("group_name"), g("employee_id"),
                        g("department"), g("nominee_name"), g("nominee_relation"),
                        ref,
                    ))
                    updated += 1
                else:
                    cur.execute("""
                        INSERT INTO applicant_master (
                            applicant_ref, full_name, email, phone, mobile,
                            dob, gender, address_line1, address_line2,
                            city, state, pincode, country, occupation,
                            group_name, employee_id, department,
                            nominee_name, nominee_relation,
                            is_active, source, uploaded_by
                        ) VALUES (
                            %s,%s,%s,%s,%s, %s,%s,%s,%s,
                            %s,%s,%s,%s,%s, %s,%s,%s,
                            %s,%s, true,'UPLOAD',%s
                        )
                    """, (
                        ref, g("full_name",""), g("email"), g("phone"), g("mobile"),
                        g("dob"), g("gender"), g("address_line1"), g("address_line2"),
                        g("city"), g("state"), g("pincode"), g("country","India"),
                        g("occupation"), g("group_name"), g("employee_id"),
                        g("department"), g("nominee_name"), g("nominee_relation"),
                        current.username,
                    ))
                    inserted += 1
            except Exception as e:
                errors += 1
                conn.rollback()
                continue

        conn.commit()

        # Log upload
        cur.execute("""
            INSERT INTO member_upload_log
                (upload_ref, filename, total_rows, inserted, updated,
                 skipped, errors, uploaded_by, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            upload_ref, filename, len(rows),
            inserted, updated, skipped, errors,
            current.username, notes,
        ))
        conn.commit()
        cur.close()

        return {
            "upload_ref": upload_ref,
            "filename":   filename,
            "total_rows": len(rows),
            "inserted":   inserted,
            "updated":    updated,
            "skipped":    skipped,
            "errors":     errors,
        }
    finally:
        release(conn)


@router.get("/upload-history")
def upload_history(current: CurrentUser):
    conn, release = _db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT upload_ref, filename, total_rows, inserted, updated,
                   skipped, errors, uploaded_by, uploaded_at, notes
            FROM member_upload_log
            ORDER BY uploaded_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        result = []
        for r in rows:
            row = dict(zip(cols, r))
            if row.get("uploaded_at"):
                row["uploaded_at"] = str(row["uploaded_at"])
            result.append(row)
        cur.close()
        return result
    finally:
        release(conn)
