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
