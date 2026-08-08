"""
routers/rules.py
─────────────────
GET  /rules/library          — built-in rule library (read-only reference)
GET  /rules/custom-fields    — custom field definitions
POST /rules/custom-fields    — create custom field

GET  /custom-rules           — list custom rules
POST /custom-rules           — create custom rule
POST /custom-rules/{id}/workflow — update custom rule status
DELETE /custom-rules/{id}    — delete custom rule

GET  /products/{code}/rules  — already in products router (kept there)
POST /products/{code}/rules/assign — assign rule to product
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import CurrentUser

router = APIRouter(tags=["rules"])

ADMIN_ROLES = {"admin", "super_admin"}


def _get_db():
    from database import get_conn, release_conn
    import psycopg2.extras
    conn = get_conn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn, release_conn


# ── Built-in rule library ─────────────────────────────────────────────────────
RULE_LIBRARY = [
    # AGE
    {"rule_id":"R001","rule_name":"Age Loading 46–55",            "category":"AGE",       "debits":15,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Standard age loading for applicants aged 46 to 55 years."},
    {"rule_id":"R002","rule_name":"Age Loading 56+",              "category":"AGE",       "debits":30,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Standard age loading for applicants aged 56 years and above."},
    # LIFESTYLE
    {"rule_id":"R005","rule_name":"Tobacco / Smoker Loading",     "category":"LIFESTYLE", "debits":50,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading applied for current tobacco users including cigarettes, beedis, gutka, and chewing tobacco."},
    {"rule_id":"R040","rule_name":"Heavy Alcohol Use",            "category":"LIFESTYLE", "debits":50,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for consumption of 22 or more alcoholic drinks per week."},
    {"rule_id":"R045","rule_name":"Hazardous Activity",           "category":"LIFESTYLE", "debits":30,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Flat extra loading for participation in hazardous hobbies or activities."},
    # BUILD
    {"rule_id":"R010","rule_name":"Elevated BMI (30–35)",         "category":"BUILD",     "debits":25,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for Obese Class I — BMI between 30 and 34.9."},
    {"rule_id":"R011","rule_name":"Elevated BMI (>35)",           "category":"BUILD",     "debits":75,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for Obese Class II and above — BMI 35 or higher."},
    # MEDICAL
    {"rule_id":"R015","rule_name":"Diabetes Type 2",              "category":"MEDICAL",   "debits":50,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for Type 2 diabetes mellitus. APS from treating physician required."},
    {"rule_id":"R016","rule_name":"Diabetes Type 1",              "category":"MEDICAL",   "debits":100, "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for Type 1 (insulin-dependent) diabetes mellitus."},
    {"rule_id":"R020","rule_name":"Cardiac Event < 2 years",      "category":"MEDICAL",   "debits":125, "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for MI, CABG, or stent placement within last 2 years."},
    {"rule_id":"R021","rule_name":"Cardiac Event 2–5 years",      "category":"MEDICAL",   "debits":75,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for cardiac event occurring 2 to 5 years ago."},
    {"rule_id":"R022","rule_name":"Cardiac Event > 5 years",      "category":"MEDICAL",   "debits":40,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Reduced loading for cardiac event more than 5 years ago with good recovery."},
    {"rule_id":"R025","rule_name":"Stage 2 Hypertension",         "category":"MEDICAL",   "debits":25,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for systolic BP 140–159 mmHg or diastolic 90–99 mmHg."},
    {"rule_id":"R026","rule_name":"Uncontrolled Hypertension",    "category":"MEDICAL",   "debits":50,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for systolic BP ≥160 mmHg or diastolic ≥100 mmHg."},
    {"rule_id":"R030","rule_name":"Stroke History",               "category":"MEDICAL",   "debits":75,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for history of cerebrovascular accident or TIA."},
    {"rule_id":"R031","rule_name":"Kidney Disease",               "category":"MEDICAL",   "debits":75,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for chronic kidney disease stages 3 and above."},
    {"rule_id":"R032","rule_name":"Depression — Hospitalized",    "category":"MEDICAL",   "debits":75,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for depression requiring inpatient hospitalization."},
    {"rule_id":"R033","rule_name":"Depression — Outpatient",      "category":"MEDICAL",   "debits":25,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for depression managed on outpatient basis."},
    {"rule_id":"R034","rule_name":"Epilepsy / Seizure Disorder",  "category":"MEDICAL",   "debits":50,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for epilepsy or recurrent seizure disorder."},
    {"rule_id":"R035","rule_name":"COPD / Emphysema",             "category":"MEDICAL",   "debits":75,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":True, "description":"Loading for chronic obstructive pulmonary disease."},
    # FAMILY
    {"rule_id":"R050","rule_name":"Family History — CVD < 60",    "category":"FAMILY",    "debits":15,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for parent or sibling with cardiovascular disease before age 60."},
    {"rule_id":"R051","rule_name":"Family History — Stroke < 65", "category":"FAMILY",    "debits":15,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for parent or sibling with stroke before age 65."},
    {"rule_id":"R052","rule_name":"Family History — Cancer",      "category":"FAMILY",    "debits":10,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for first-degree family history of malignant cancer."},
    {"rule_id":"R053","rule_name":"Family History — Diabetes",    "category":"FAMILY",    "debits":10,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for first-degree family history of diabetes mellitus."},
    # HARD STOPS
    {"rule_id":"R100","rule_name":"HIV Positive — Hard Stop",     "category":"HARD_STOP", "debits":999, "credits":0,"flat_extra":0,"is_hard_stop":True, "aps_required":False,"description":"Absolute decline for HIV positive applicants on individual life products."},
    {"rule_id":"R101","rule_name":"Liver Cirrhosis — Hard Stop",  "category":"HARD_STOP", "debits":999, "credits":0,"flat_extra":0,"is_hard_stop":True, "aps_required":False,"description":"Absolute decline for liver cirrhosis regardless of severity."},
    {"rule_id":"R102","rule_name":"2+ DUI/DWI in 5 Years",       "category":"HARD_STOP", "debits":999, "credits":0,"flat_extra":0,"is_hard_stop":True, "aps_required":False,"description":"Absolute decline for two or more DUI/DWI convictions in the last 5 years."},
    {"rule_id":"R103","rule_name":"Declined Occupation Class",    "category":"HARD_STOP", "debits":999, "credits":0,"flat_extra":0,"is_hard_stop":True, "aps_required":False,"description":"Absolute decline for applicants in occupation class D (highest hazard)."},
    {"rule_id":"R104","rule_name":"Age Outside Product Range",    "category":"HARD_STOP", "debits":999, "credits":0,"flat_extra":0,"is_hard_stop":True, "aps_required":False,"description":"Decline when applicant age is outside the product's eligible age range."},
    # DRIVING
    {"rule_id":"R060","rule_name":"Major Traffic Violation",      "category":"DRIVING",   "debits":25,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for major traffic violations in the last 3 years."},
    {"rule_id":"R061","rule_name":"At-Fault Accident",            "category":"DRIVING",   "debits":15,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for at-fault accidents in the last 3 years."},
    {"rule_id":"R062","rule_name":"License Suspended",            "category":"DRIVING",   "debits":50,  "credits":0,"flat_extra":0,"is_hard_stop":False,"aps_required":False,"description":"Loading for current or recent driving license suspension."},
]


@router.get("/rules/library")
def get_rule_library(
    category: Optional[str] = None,
    search: Optional[str] = None,
    user: CurrentUser = CurrentUser,
):
    rules = RULE_LIBRARY
    if category and category != "All":
        rules = [r for r in rules if r["category"] == category]
    if search:
        s = search.lower()
        rules = [r for r in rules if s in r["rule_id"].lower() or s in r["rule_name"].lower() or s in (r.get("description") or "").lower()]
    return rules


# ── Custom fields ─────────────────────────────────────────────────────────────

class CustomFieldIn(BaseModel):
    field_name: str
    label: str
    data_type: str = "string"
    description: Optional[str] = None


@router.get("/rules/custom-fields")
def list_custom_fields(user: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM rule_custom_fields ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        release(conn)


@router.post("/rules/custom-fields")
def create_custom_field(body: CustomFieldIn, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rule_custom_fields (field_name, label, data_type, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (field_name) DO UPDATE
            SET label=EXCLUDED.label, data_type=EXCLUDED.data_type,
                description=EXCLUDED.description
            RETURNING *
            """,
            (body.field_name, body.label, body.data_type, body.description),
        )
        row = dict(cur.fetchone())
        conn.commit()
        cur.close()
        return row
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


# ── Custom rules ──────────────────────────────────────────────────────────────

# Mirrors the real custom_uw_rule table (V001) — logic/conditions/action are
# NOT NULL, and the frontend payload sends exactly these keys. debit_points /
# hard_stop / requires_aps have no columns of their own; when `action` is not
# supplied they are folded into the action jsonb.
class CustomRuleIn(BaseModel):
    rule_id: str
    rule_name: str
    category: str = "CUSTOM"
    description: Optional[str] = None
    product_code: Optional[str] = None
    condition_logic: str = "AND"
    priority: int = 1
    debit_points: int = 0
    hard_stop: bool = False
    requires_aps: bool = False
    effective_date: Optional[str] = None
    expire_date: Optional[str] = None
    conditions: dict | list | None = None
    action: Optional[dict] = None
    version: str = "1.0"
    status: str = "DRAFT"
    rule_code: Optional[str] = None  # legacy alias; superseded by rule_id


class WorkflowIn(BaseModel):
    new_status: str
    reason: Optional[str] = None


@router.get("/custom-rules")
def list_custom_rules(user: CurrentUser = CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM custom_uw_rule WHERE tenant_id=%s ORDER BY created_at DESC",
            (user.tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            row = dict(r)
            # Map real table columns to the frontend contract
            # (rule_name / rule_code / expire_date / condition_logic /
            #  debit_points / hard_stop / requires_aps).
            row["rule_name"] = row.pop("name", None) or row["rule_id"]
            row["rule_code"] = row["rule_id"]
            row["condition_logic"] = row.get("logic")
            if row.get("effective_date"):
                row["effective_date"] = str(row["effective_date"])[:10]
            row["expire_date"] = str(row["expiry_date"])[:10] if row.get("expiry_date") else None
            action = row.get("action") or {}
            if isinstance(action, str):
                try:
                    action = json.loads(action)
                except Exception:
                    action = {}
            row["debit_points"] = action.get("debit_points", 0)
            row["hard_stop"] = action.get("hard_stop", False)
            row["requires_aps"] = action.get("requires_aps", False)
            row["version"] = row.get("rule_version")
            result.append(row)
        return result
    except Exception:
        return []
    finally:
        release(conn)


@router.post("/custom-rules", status_code=201)
def create_custom_rule(body: CustomRuleIn, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        action = body.action if body.action is not None else {
            "debit_points": body.debit_points,
            "hard_stop": body.hard_stop,
            "requires_aps": body.requires_aps,
        }
        cur.execute(
            """
            INSERT INTO custom_uw_rule
                (tenant_id, product_code, rule_id, name, description, category,
                 logic, is_enabled, priority, conditions, action,
                 effective_date, expiry_date, status, rule_version,
                 created_by, updated_by, version)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, true, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s,
                    %s, %s, 1)
            RETURNING id
            """,
            (
                user.tenant_id or "00000000-0000-0000-0000-000000000001",
                body.product_code, body.rule_id, body.rule_name,
                body.description, body.category,
                body.condition_logic or "AND", body.priority,
                json.dumps(body.conditions) if body.conditions is not None else "{}",
                json.dumps(action),
                body.effective_date or None, body.expire_date or None,
                body.status, body.version,
                user.username, user.username,
            ),
        )
        rule_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        return {"id": rule_id, "message": "Custom rule created"}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


@router.post("/custom-rules/{rule_id}/workflow")
def update_rule_workflow(
    rule_id: str,
    body: WorkflowIn,
    user: CurrentUser = CurrentUser,
):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            "UPDATE custom_uw_rule SET status=%s, updated_at=now() WHERE id=%s AND tenant_id=%s",
            (body.new_status, rule_id, user.tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
        conn.commit()
        cur.close()
        return {"message": "Status updated", "new_status": body.new_status}
    except HTTPException:
        conn.rollback(); raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


@router.delete("/custom-rules/{rule_id}")
def delete_custom_rule(rule_id: str, user: CurrentUser = CurrentUser):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")
    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM custom_uw_rule WHERE id=%s AND tenant_id=%s",
            (rule_id, user.tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
        conn.commit()
        cur.close()
        return {"message": "Rule deleted"}
    except HTTPException:
        conn.rollback(); raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)


# ── Assign rule to product ────────────────────────────────────────────────────

class AssignRuleIn(BaseModel):
    rule_id: str
    is_enabled: bool = True
    debit_points_override: Optional[int] = None
    debit_override_active: bool = False


@router.post("/products/{code}/rules/assign")
def assign_rule_to_product(
    code: str,
    body: AssignRuleIn,
    user: CurrentUser = CurrentUser,
):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only")

    # Get rule name from library
    lib_rule = next((r for r in RULE_LIBRARY if r["rule_id"] == body.rule_id), None)
    rule_name    = lib_rule["rule_name"] if lib_rule else body.rule_id
    category     = lib_rule["category"]  if lib_rule else "CUSTOM"
    default_debit= lib_rule["debits"]    if lib_rule else 0

    conn, release = _get_db()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO product_rules
                (product_code, rule_id, rule_name, category, default_debit,
                 is_enabled, debit_points_override, debit_override_active,
                 flat_extra_override, flat_extra_override_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, false)
            ON CONFLICT (product_code, rule_id) DO UPDATE SET
                is_enabled             = EXCLUDED.is_enabled,
                debit_points_override  = EXCLUDED.debit_points_override,
                debit_override_active  = EXCLUDED.debit_override_active
            """,
            (
                code.upper(), body.rule_id, rule_name, category, default_debit,
                body.is_enabled,
                body.debit_points_override, body.debit_override_active,
            ),
        )
        conn.commit()
        cur.close()
        return {"message": f"Rule {body.rule_id} assigned to {code}"}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        release(conn)
