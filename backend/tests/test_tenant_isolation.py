"""
backend/tests/test_tenant_isolation.py
──────────────────────────────────────
Multi-tenant data isolation tests (TC-TEN-001 … TC-TEN-007).

Guards the V040 tenant-scoping sweep:
  * applicant_master rows are readable / editable / deletable only within
    their owning tenant — a cross-tenant lookup must never leak a row
  * the same applicant_ref may exist in two different tenants, because the
    uniqueness constraint is now (tenant_id, applicant_ref)
  * batch jobs and their records are scoped to the owning tenant — a foreign
    job id 404s and its records never appear
  * proposals persist under the calling tenant (proposal.tenant_id) and the
    same proposal_ref across two tenants yields two distinct rows

Design notes:
  * Tenant admin accounts are created directly in the DB (the /auth/register
    endpoint is admin-only), then tests authenticate through the real
    /auth/login flow. Suite is self-contained and order-independent.
  * Tenant codes are fixed so re-runs are idempotent; applicant_refs are
    unique per test to avoid collisions with other modules.
"""
from __future__ import annotations

import os
import uuid

import bcrypt
import psycopg2
import psycopg2.extras
import pytest

TENANT_A_CODE = "TISO-A"
TENANT_B_CODE = "TISO-B"
ADMIN_A = "tiso_admin_a"
ADMIN_B = "tiso_admin_b"
PASSWORD = "TisoPass123!"


def _db():
    """Direct psycopg2 connection to the same DB the app is pointed at."""
    conn = psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = False
    return conn


def _seed_tenant_admin(tenant_code: str, username: str) -> str:
    """Create a tenant + admin user (idempotent). Returns tenant_id as str."""
    conn = _db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT id::text AS id FROM tenant WHERE tenant_code=%s", (tenant_code,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
        else:
            cur.execute("""
                INSERT INTO tenant
                    (tenant_code, tenant_name, status, plan_tier, contact_email,
                     company_type, max_users, max_decisions_per_month,
                     api_enabled, timezone, date_format, created_by)
                VALUES (%s, %s, 'ACTIVE', 'STANDARD', %s, 'INSURER',
                        25, 10000, true, 'Asia/Kolkata', 'DD-MM-YYYY', 'system')
                RETURNING id::text AS id
            """, (tenant_code, f"Tenant {tenant_code}", f"{tenant_code}@test.local"))
            tenant_id = cur.fetchone()["id"]

        cur.execute(
            "SELECT 1 FROM uw_user WHERE username=%s AND is_deleted=false",
            (username,),
        )
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO uw_user
                    (id, username, email, hashed_password, full_name, role,
                     is_active, is_deleted, tenant_id, created_by, updated_by, version)
                VALUES (%s, %s, %s, %s, %s, 'admin', true, false, %s::uuid,
                        'system', 'system', 1)
            """, (
                str(uuid.uuid4()), username, f"{username}@test.local",
                bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode(),
                f"Admin {tenant_code}", tenant_id,
            ))

        conn.commit()
        cur.close()
        return tenant_id
    finally:
        conn.close()


@pytest.fixture(scope="module")
def iso_tenants():
    """Tenant A + B admin credentials, seeded once for the whole module."""
    a = _seed_tenant_admin(TENANT_A_CODE, ADMIN_A)
    b = _seed_tenant_admin(TENANT_B_CODE, ADMIN_B)
    return {"a": a, "b": b}


def _login(client, username: str) -> dict:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:4].upper()}"


# ── Member (applicant_master) isolation ─────────────────────────────────────

def test_member_cross_tenant_invisible(iso_tenants, client):
    """TC-TEN-001: tenant B cannot list or fetch tenant A's member."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ref = _ref("ISO")

    r = client.post("/members", headers=ha,
                    json={"applicant_ref": ref, "full_name": "Tenant A Member"})
    assert r.status_code == 201, r.text

    # B's search never surfaces A's row
    r = client.get("/members", headers=hb, params={"search": ref})
    assert r.status_code == 200
    body = r.json()
    items = body.get("items") if isinstance(body, dict) else body
    assert ref not in [it.get("applicant_ref") for it in items], \
        "Tenant B leaked Tenant A's member in list"

    # B's direct fetch is a 404, not a 200
    r = client.get(f"/members/{ref}", headers=hb)
    assert r.status_code == 404, "Cross-tenant member fetch must 404"

    # A can still see it
    r = client.get(f"/members/{ref}", headers=ha)
    assert r.status_code == 200


def test_same_applicant_ref_allowed_across_tenants(iso_tenants, client):
    """TC-TEN-002: unique constraint is (tenant_id, applicant_ref), so the
    same ref may exist in both tenants without a 409."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ref = _ref("ISO")

    assert client.post("/members", headers=ha,
                       json={"applicant_ref": ref, "full_name": "Name A"}).status_code == 201
    assert client.post("/members", headers=hb,
                       json={"applicant_ref": ref, "full_name": "Name B"}).status_code == 201

    a = client.get(f"/members/{ref}", headers=ha).json()
    b = client.get(f"/members/{ref}", headers=hb).json()
    assert a["full_name"] == "Name A"
    assert b["full_name"] == "Name B"


def test_member_update_scoped(iso_tenants, client):
    """TC-TEN-003: B's update cannot modify A's row (B can't even see it)."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ref = _ref("ISO")

    assert client.post("/members", headers=ha,
                       json={"applicant_ref": ref, "full_name": "Original"}).status_code == 201

    # B attempts an update — should either 404 or leave A untouched
    r = client.put(f"/members/{ref}", headers=hb,
                   json={"applicant_ref": ref, "full_name": "Hacked"})
    assert r.status_code in (404, 200)

    row = client.get(f"/members/{ref}", headers=ha).json()
    assert row["full_name"] == "Original", "Tenant B modified Tenant A's member"


def test_member_delete_scoped(iso_tenants, client):
    """TC-TEN-004: B's delete removes only B's row; A's survives."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ref = _ref("ISO")

    assert client.post("/members", headers=ha,
                       json={"applicant_ref": ref, "full_name": "A"}).status_code == 201
    assert client.post("/members", headers=hb,
                       json={"applicant_ref": ref, "full_name": "B"}).status_code == 201

    assert client.delete(f"/members/{ref}", headers=hb).status_code == 200
    assert client.get(f"/members/{ref}", headers=hb).status_code == 404
    assert client.get(f"/members/{ref}", headers=ha).status_code == 200, \
        "Tenant B's delete removed Tenant A's row"


# ── Batch jobs isolation (batch_jobs + batch_job_records) ───────────────────

def test_batch_job_isolation(iso_tenants, client):
    """TC-TEN-005: a job belongs to one tenant — foreign fetch 404s and its
    records never render for the other tenant."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ta, tb = iso_tenants["a"], iso_tenants["b"]

    conn = _db()
    job_a = job_b = None
    try:
        cur = conn.cursor()
        suffix = uuid.uuid4().hex[:4].upper()
        cur.execute("""
            INSERT INTO batch_jobs (job_number, tenant_id, submitted_by)
            VALUES (%s, %s, 'tiso') RETURNING id
        """, (f"TISO-A-JOB-{suffix}", ta,))
        job_a = cur.fetchone()["id"]
        cur.execute("""
            INSERT INTO batch_jobs (job_number, tenant_id, submitted_by)
            VALUES (%s, %s, 'tiso') RETURNING id
        """, (f"TISO-B-JOB-{suffix}", tb,))
        job_b = cur.fetchone()["id"]

        # One record per job, each with its own tenant_id (V040).
        cur.execute("""
            INSERT INTO batch_job_records
                (job_id, tenant_id, applicant_ref, status, outcome)
            VALUES (%s, %s, 'TISO-REC-A', 'PROCESSED', 'APPROVED_STP')
        """, (job_a, ta))
        cur.execute("""
            INSERT INTO batch_job_records
                (job_id, tenant_id, applicant_ref, status, outcome)
            VALUES (%s, %s, 'TISO-REC-B', 'PROCESSED', 'APPROVED_STP')
        """, (job_b, tb))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    assert job_a and job_b

    # A sees its own job; B's job is invisible to A
    assert client.get(f"/batch/jobs/{job_a}", headers=ha).status_code == 200
    assert client.get(f"/batch/jobs/{job_b}", headers=ha).status_code == 404
    assert client.get(f"/batch/jobs/{job_a}", headers=hb).status_code == 404

    # Records for B's job never appear under A's view
    r = client.get(f"/batch/jobs/{job_b}/records", headers=ha)
    assert r.status_code == 200
    body = r.json()
    records = body.get("records") if isinstance(body, dict) else body
    assert records == [], f"Tenant A leaked Tenant B's records: {records}"

    # A's own records still visible
    r = client.get(f"/batch/jobs/{job_a}/records", headers=ha)
    assert r.status_code == 200
    body = r.json()
    records = body.get("records") if isinstance(body, dict) else body
    assert len(records) == 1 and records[0]["applicant_ref"] == "TISO-REC-A"


# ── Proposal isolation (proposal.tenant_id) ────────────────────────────────

def test_proposal_persisted_per_tenant(iso_tenants, client):
    """TC-TEN-006: evaluating the same proposal_ref in two tenants creates
    two distinct proposal rows, one per tenant (ON CONFLICT (tenant_id,
    proposal_ref))."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ref = _ref("TISO-PROP")

    body = {
        "proposal_ref": ref,
        "applicant_ref": _ref("TISO-APP"),
        "age": 35,
        "gender": "MALE",
        "state": "MH",
        "annual_salary": 500000,
        "tobacco_status": "NEVER",
        "heart_condition": "NONE",
        "diabetes_type": "NONE",
        "benefits": [{
            "benefit_type": "BASE",
            "product_code": "TISO-PROD",
            "face_amount": 500000,
            "coverage_term_yrs": 20,
        }],
    }

    ra = client.post("/underwriting/evaluate-proposal", headers=ha, json=body)
    rb = client.post("/underwriting/evaluate-proposal", headers=hb, json=body)
    assert ra.status_code == 200, ra.text
    assert rb.status_code == 200, rb.text

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id::text AS t FROM proposal WHERE proposal_ref=%s",
            (ref,),
        )
        rows = cur.fetchall()
        cur.close()
        tenant_ids = {r["t"] for r in rows}
        assert len(rows) == 2, f"expected 2 proposal rows, got {len(rows)}: {rows}"
        assert iso_tenants["a"] in tenant_ids and iso_tenants["b"] in tenant_ids, \
            "proposal rows not scoped to their tenants"
    finally:
        conn.close()


# ── Analytics isolation (batch_job_records.tenant_id) ──────────────────────

def test_analytics_summary_tenant_scoped(iso_tenants, client):
    """TC-TEN-007: /analytics/summary counts only the caller's own
    batch_job_records (V040 added batch_job_records.tenant_id)."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ta, tb = iso_tenants["a"], iso_tenants["b"]

    conn = _db()
    try:
        cur = conn.cursor()
        # Two records for A, one for B — A's summary must equal A's own count.
        suffix = uuid.uuid4().hex[:4].upper()
        cur.execute("""
            INSERT INTO batch_jobs (job_number, tenant_id, submitted_by)
            VALUES (%s, %s, 'tiso') RETURNING id
        """, (f"TISO-AN-JOB-{suffix}", ta,))
        job_a = cur.fetchone()["id"]
        for i in range(2):
            cur.execute("""
                INSERT INTO batch_job_records
                    (job_id, tenant_id, applicant_ref, status, outcome)
                VALUES (%s, %s, %s, 'PROCESSED', 'APPROVED_STP')
            """, (job_a, ta, f"TISO-AN-A-{suffix}-{i}"))
        cur.execute("""
            INSERT INTO batch_jobs (job_number, tenant_id, submitted_by)
            VALUES (%s, %s, 'tiso') RETURNING id
        """, (f"TISO-AN-JOB-B-{suffix}", tb,))
        job_b = cur.fetchone()["id"]
        cur.execute("""
            INSERT INTO batch_job_records
                (job_id, tenant_id, applicant_ref, status, outcome)
            VALUES (%s, %s, 'TISO-AN-B', 'PROCESSED', 'APPROVED_STP')
        """, (job_b, tb))
        conn.commit()

        # Ground-truth counts straight from the DB.
        cur.execute(
            "SELECT COUNT(*) AS n FROM batch_job_records WHERE tenant_id=%s AND status <> 'ERROR'",
            (ta,),
        )
        expected_a = cur.fetchone()["n"]
        cur.execute(
            "SELECT COUNT(*) AS n FROM batch_job_records WHERE tenant_id=%s AND status <> 'ERROR'",
            (tb,),
        )
        expected_b = cur.fetchone()["n"]
        cur.close()
    finally:
        conn.close()

    ra = client.get("/analytics/summary", headers=ha)
    assert ra.status_code == 200, ra.text
    assert ra.json()["total_cases"] == expected_a, \
        f"A sees {ra.json()['total_cases']}, expected own-only {expected_a}"

    rb = client.get("/analytics/summary", headers=hb)
    assert rb.status_code == 200, rb.text
    assert rb.json()["total_cases"] == expected_b, \
        f"B sees {rb.json()['total_cases']}, expected own-only {expected_b}"

    # Sanity: the two tenants have distinct counts (3 vs 1), so a shared
    # unscoped count could never satisfy both assertions above.
    assert expected_a != expected_b


# ── Decision-queue isolation (policy_admin_queue.tenant_id, V041) ───────────

def test_queue_case_cross_tenant_invisible(iso_tenants, client):
    """TC-TEN-008: a case in the decision queue belongs to one tenant — the
    other tenant's /queue list never surfaces it and a direct id fetch 404s
    (V041 scoped policy_admin_queue.tenant_id)."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ta = iso_tenants["a"]

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO policy_admin_queue
                (applicant_ref, applicant_name, product_code, face_amount, age, gender,
                 outcome, risk_class, net_debit_points, decision_date, tenant_id)
            VALUES (%s, 'Queue Isolation Applicant', 'TST', 1000000, 35, 'M',
                    'REFERRED', 'STANDARD', 25, now(), %s::uuid)
            RETURNING id
        """, (_ref("TISO-Q"), ta))
        cid = cur.fetchone()["id"]
        conn.commit()
        cur.close()
    finally:
        conn.close()

    # A sees its own case via the legacy queue endpoint (returns a list)
    r = client.get("/queue", headers=ha)
    assert r.status_code == 200, r.text
    ids = [str(it["id"]) for it in r.json() if isinstance(it, dict)]
    assert str(cid) in ids, "Tenant A cannot see its own queue case"

    # B's list never surfaces A's case
    r = client.get("/queue", headers=hb)
    assert r.status_code == 200, r.text
    ids = [str(it["id"]) for it in r.json() if isinstance(it, dict)]
    assert str(cid) not in ids, "Tenant B leaked Tenant A's queue case in list"

    # B's direct fetch by id is a 404, not a 200
    r = client.get(f"/queue/{cid}", headers=hb)
    assert r.status_code == 404, "Cross-tenant queue case fetch must 404"

    # A can still fetch it
    assert client.get(f"/queue/{cid}", headers=ha).status_code == 200


# ── Member-upload-log isolation (member_upload_log.tenant_id, V041) ─────────

def test_member_upload_log_scoped(iso_tenants, client):
    """TC-TEN-009: /members/upload-history returns only the caller's own
    tenant's upload rows (V041 scoped member_upload_log.tenant_id)."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    ta, tb = iso_tenants["a"], iso_tenants["b"]

    conn = _db()
    try:
        cur = conn.cursor()
        suffix = uuid.uuid4().hex[:4].upper()
        cur.execute("""
            INSERT INTO member_upload_log
                (upload_ref, filename, total_rows, inserted, updated,
                 skipped, errors, uploaded_by, tenant_id)
            VALUES (%s, %s, 1, 1, 0, 0, 0, %s, %s::uuid)
        """, (f"TISO-UL-A-{suffix}", f"iso-a-{suffix}.csv", ADMIN_A, ta))
        cur.execute("""
            INSERT INTO member_upload_log
                (upload_ref, filename, total_rows, inserted, updated,
                 skipped, errors, uploaded_by, tenant_id)
            VALUES (%s, %s, 1, 1, 0, 0, 0, %s, %s::uuid)
        """, (f"TISO-UL-B-{suffix}", f"iso-b-{suffix}.csv", ADMIN_B, tb))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    ra = client.get("/members/upload-history", headers=ha)
    assert ra.status_code == 200, ra.text
    a_refs = [r["upload_ref"] for r in ra.json()]
    assert f"TISO-UL-A-{suffix}" in a_refs, "Tenant A missing its own upload log"
    assert f"TISO-UL-B-{suffix}" not in a_refs, "Tenant A leaked Tenant B's upload log"

    rb = client.get("/members/upload-history", headers=hb)
    assert rb.status_code == 200, rb.text
    b_refs = [r["upload_ref"] for r in rb.json()]
    assert f"TISO-UL-B-{suffix}" in b_refs, "Tenant B missing its own upload log"
    assert f"TISO-UL-A-{suffix}" not in b_refs, "Tenant B leaked Tenant A's upload log"


# ── Product catalog isolation (V042) ─────────────────────────────────────────

def test_product_catalog_tenant_isolated(iso_tenants, client):
    """TC-TEN-010: the products catalog is tenant-owned (V042) — B can
    neither list, fetch, update, nor write thresholds for A's product."""
    ha = _login(client, ADMIN_A)
    hb = _login(client, ADMIN_B)
    code = f"PISO-{uuid.uuid4().hex[:4].upper()}"
    body = {
        "product_code": code,
        "product_name": f"ISO Product {code}",
        "product_type": "individual",
        "min_age": 18,
        "max_age": 65,
        "min_face_amount": 100000,
        "max_face_amount": 10000000,
        "stp_threshold": 75,
        "refer_threshold": 150,
        "decline_threshold": 300,
    }
    try:
        r = client.post("/products", headers=ha, json=body)
        assert r.status_code in (200, 201), r.text

        # B's list never surfaces A's product
        codes = [p["product_code"] for p in client.get("/products", headers=hb).json()]
        assert code not in codes, "Tenant B leaked Tenant A's product in list"

        # B's fetch / update / thresholds writes are 404s, not 200s
        assert client.get(f"/products/{code}", headers=hb).status_code == 404
        assert client.patch(f"/products/{code}", headers=hb,
                            json={"max_age": 70}).status_code == 404
        assert client.put(f"/products/{code}/thresholds", headers=hb,
                          json={"stp_threshold": 10, "refer_threshold": 20,
                                "decline_threshold": 30}).status_code == 404

        # B can't read A's sub-resources either
        assert client.get(f"/products/{code}/rules", headers=hb).status_code == 404
        assert client.get(f"/products/{code}/build-table", headers=hb).status_code == 404

        # A still sees its own product and can fetch it
        codes = [p["product_code"] for p in client.get("/products", headers=ha).json()]
        assert code in codes, "Tenant A lost its own product"
        assert client.get(f"/products/{code}", headers=ha).status_code == 200
    finally:
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM products WHERE product_code = %s", (code,))
            conn.commit()
            cur.close()
        finally:
            conn.close()
