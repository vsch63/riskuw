"""
backend/tests/test_config_versioning.py
────────────────────────────────────────
Append-versioning (Phase 3c): every config save inserts a new row with the
next version and supersedes the previous one.

  * Saving the same benefit twice → two rows, v2 current, v1 expired.
  * Future-dated save → previous version stays active until it takes effect.
  * History endpoint returns every version.
  * Lists return only active versions.
"""
from __future__ import annotations

import datetime as dt

from database import get_conn, release_conn

CODE = "VER-TST-01"


def _cleanup():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM uw_benefit_group_map WHERE benefit_id IN "
                    "(SELECT id FROM uw_benefit_master WHERE benefit_code = %s)", (CODE,))
        cur.execute("DELETE FROM uw_benefit_master WHERE benefit_code = %s", (CODE,))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)


def _as_dict(row):
    return dict(row)


def _save(client, headers, **kw):
    body = {
        "benefit_code": CODE,
        "benefit_type": "BASE",
        "risk_type": "MORTALITY",
        "uw_exposure_group": "INDIVIDUAL",
        "risk_group": "LIFE",
        "premium_payer": "EMPLOYEE",
        "underwriting_required": True,
        "include_in_sar": True,
        "sar_formula": "FACE_AMOUNT",
        "processing_sequence": 1,
    }
    body.update(kw)
    return client.post("/sar-config/benefits", json=body, headers=headers)


def test_save_appends_version_and_supersedes(client, auth_headers):
    try:
        # v1
        r1 = _save(client, auth_headers, processing_sequence=1)
        assert r1.status_code in (200, 201), r1.text
        # v2 — same code, changed
        r2 = _save(client, auth_headers, processing_sequence=5)
        assert r2.status_code in (200, 201), r2.text

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT version, processing_sequence, expiry_date FROM uw_benefit_master "
                    "WHERE benefit_code=%s ORDER BY version", (CODE,))
        rows = [_as_dict(r) for r in cur.fetchall()]
        cur.close()
        release_conn(conn)

        assert len(rows) == 2, f"expected 2 versions, got {rows}"
        v1, v2 = rows
        assert int(v1["version"]) == 1 and int(v1["processing_sequence"]) == 1
        assert int(v2["version"]) == 2 and int(v2["processing_sequence"]) == 5
        # v1 is expired (superseded); v2 still open
        assert v1["expiry_date"] is not None, "v1 should be expired by supersede"
        assert v2["expiry_date"] is None, "v2 should remain active"

        # List shows only the active version
        lst = client.get("/sar-config/benefits", headers=auth_headers).json()
        matches = [b for b in lst if b["benefit_code"] == CODE]
        assert len(matches) == 1 and matches[0]["version"] == 2
    finally:
        _cleanup()


def test_future_dated_save_keeps_current_active(client, auth_headers):
    try:
        _save(client, auth_headers, processing_sequence=1)  # v1 effective today
        future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
        _save(client, auth_headers, processing_sequence=9, effective_date=future)  # v2 scheduled

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT version, processing_sequence, effective_date, expiry_date "
                    "FROM uw_benefit_master WHERE benefit_code=%s ORDER BY version", (CODE,))
        rows = [_as_dict(r) for r in cur.fetchall()]
        cur.close()
        release_conn(conn)

        assert len(rows) == 2, rows
        v1, v2 = rows
        # v1 is superseded UP TO the day before v2 takes effect, so its window
        # still covers today — it stays active now (scheduling).
        assert v1["expiry_date"] is not None and v1["expiry_date"] >= dt.date.today(), \
            f"v1 must stay active while v2 is future-dated, got {rows}"
        assert str(v2["effective_date"]) == future and v2["expiry_date"] is None

        # Active list must NOT include the future-scheduled v2
        lst = client.get("/sar-config/benefits", headers=auth_headers).json()
        matches = [b for b in lst if b["benefit_code"] == CODE]
        assert len(matches) == 1 and matches[0]["version"] == 1, \
            f"expected only v1 in active list, got {matches}"
    finally:
        _cleanup()


def test_benefit_versions_history_endpoint(client, auth_headers):
    try:
        _save(client, auth_headers, processing_sequence=1)
        _save(client, auth_headers, processing_sequence=2)
        r = client.get(f"/sar-config/benefits/versions?benefit_code={CODE}", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["benefit_code"] == CODE
        assert len(data["versions"]) == 2
        # newest first, current flag set
        assert data["versions"][0]["version"] == 2 and data["versions"][0]["is_current"]
        assert data["versions"][1]["version"] == 1 and not data["versions"][1]["is_current"]
    finally:
        _cleanup()


def test_benefit_options_drives_dropdown(client, auth_headers):
    """GET /sar-config/benefit-options is the Benefit tab dropdown source.

    Base plans come from products (no canonical tenant_id — unscoped read),
    compatible riders from product_benefit_config scoped to the tenant. Only
    active rows are returned so the strict dropdown can't pick a phantom
    benefit with no backing product.
    """
    PROD = "BOPT-PROD"
    RIDER = "BOPT-RIDER-CI"
    DEAD = "BOPT-RIDER-DEAD"
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT tenant_id FROM uw_user WHERE username = 'admin'")
        tenant_id = dict(cur.fetchone())["tenant_id"]
        cur.execute("""
            INSERT INTO products (product_code, product_name, product_type, is_active)
            VALUES (%s, 'Benefit Options Test Product', 'INDIVIDUAL_TERM', true)
        """, (PROD,))
        for code, active in ((RIDER, True), (DEAD, False)):
            cur.execute("""
                INSERT INTO product_benefit_config
                    (tenant_id, base_product_code, rider_product_code, benefit_type, is_active)
                VALUES (%s::uuid, %s, %s, 'RIDER_CI', %s)
            """, (tenant_id, PROD, code, active))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)

    try:
        r = client.get("/sar-config/benefit-options", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()
        codes = {i["benefit_code"]: i for i in items}
        assert codes[PROD]["benefit_type"] == "BASE", codes
        assert codes[RIDER]["benefit_type"] == "RIDER_CI", codes
        assert DEAD not in codes, "inactive rider must be excluded"
        for i in items:
            assert "benefit_code" in i and "benefit_type" in i and "product_name" in i
    finally:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM product_benefit_config WHERE base_product_code = %s", (PROD,))
            cur.execute("DELETE FROM products WHERE product_code = %s", (PROD,))
            conn.commit()
        finally:
            cur.close()
            release_conn(conn)


def test_benefit_group_memberships_roundtrip(client, auth_headers):
    """Benefit ↔ risk-group memberships persist and round-trip.

    Saving with group_maps attaches the memberships and the benefit list
    returns them; saving without group_maps supersedes the version and clears
    them (so the UI no longer silently wipes an existing membership set).
    """
    RG = "RG-MAP-TST"
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM uw_benefit_group_map WHERE benefit_id IN "
                    "(SELECT id FROM uw_benefit_master WHERE benefit_code = %s)", (CODE,))
        cur.execute("DELETE FROM uw_benefit_master WHERE benefit_code = %s", (CODE,))
        cur.execute("DELETE FROM uw_risk_group WHERE group_code = %s", (RG,))
        conn.commit()
    finally:
        cur.close()
        release_conn(conn)

    try:
        r = client.post("/sar-config/risk-groups", json={
            "group_code": RG, "group_name": "Membership Map Test", "aggregation_method": "SUM",
        }, headers=auth_headers)
        assert r.status_code in (200, 201), r.text

        # v1 with memberships
        _save(client, auth_headers, group_maps=[
            {"risk_group_code": RG, "weight_pct": 100, "priority": 5}])
        lst = client.get("/sar-config/benefits", headers=auth_headers).json()
        row = [b for b in lst if b["benefit_code"] == CODE][0]
        assert row["group_maps"] == [
            {"risk_group_code": RG, "weight_pct": 100, "priority": 5}], row["group_maps"]

        # v2 without group_maps → supersedes and clears membership
        _save(client, auth_headers, processing_sequence=9)
        lst = client.get("/sar-config/benefits", headers=auth_headers).json()
        row = [b for b in lst if b["benefit_code"] == CODE][0]
        assert row["group_maps"] == [], row["group_maps"]
    finally:
        _cleanup()
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM uw_risk_group WHERE group_code = %s", (RG,))
            conn.commit()
        finally:
            cur.close()
            release_conn(conn)
