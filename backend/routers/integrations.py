"""
backend/routers/integrations.py
────────────────────────────────
External data integration endpoints.

POST /integrations/verify           — run a verification check
GET  /integrations/results          — get results for a case/applicant
GET  /integrations/providers        — list available providers
GET  /integrations/config           — get/update provider config (admin)
PATCH /integrations/config/{id}     — enable/disable a provider
GET  /integrations/summary/{applicant_ref} — full verification summary for a case
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_conn, release_conn
from routers.auth import CurrentUser

logger = logging.getLogger("uw_platform")
router = APIRouter(prefix="/integrations", tags=["integrations"])


def _get_db():
    conn = get_conn()
    return conn, lambda c: release_conn(c)


def _row(r) -> dict:
    if r is None: return {}
    return dict(r) if hasattr(r, "keys") else dict(r)


# ── Request models ────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    integration_type: str           # IDENTITY | CREDIT | LAB | AML | PHARMACY | DRIVING
    provider_code: str | None = None  # if None, uses first enabled provider for type
    applicant_ref: str
    case_ref_id: int | None = None
    country_code: str | None = None  # if None, resolved from tenant's default_country
    # Applicant data for verification
    full_name: str | None = None
    age: int | None = None
    gender: str | None = None
    pan_number: str | None = None
    aadhaar_number: str | None = None
    dob: str | None = None
    annual_income: float | None = None
    product_code: str | None = None
    tobacco_status: str | None = None
    diabetes_type: str | None = None
    heart_condition: str | None = None
    # Extra fields passed through to provider
    extra: dict = {}


class ConfigUpdateRequest(BaseModel):
    is_enabled: bool | None = None
    api_endpoint: str | None = None
    api_key: str | None = None      # stored encrypted, never returned
    config_json: dict | None = None


# ── Helper: persist request + result ─────────────────────────────────────────

def _persist_result(conn, req_id: int, result, provider_code: str, integration_type: str,
                    applicant_ref: str, case_ref_id: int | None):
    import json as _json
    cur = conn.cursor()
    expires_at = datetime.now(timezone.utc) + timedelta(days=result.expires_in_days)

    cur.execute("""
        INSERT INTO integration_results (
            request_id, provider_code, integration_type, applicant_ref, case_ref_id,
            kyc_verified, kyc_name, kyc_dob, kyc_pan, kyc_aadhaar_masked, kyc_address,
            credit_score, credit_bureau, credit_report_ref, credit_flags,
            lab_order_ref, lab_tests, lab_report_url,
            aml_status, aml_flags,
            confidence_score, raw_response, expires_at, notes
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s
        ) RETURNING id
    """, (
        req_id, provider_code, integration_type, applicant_ref, case_ref_id,
        result.kyc_verified, result.kyc_name, result.kyc_dob, result.kyc_pan,
        result.kyc_aadhaar_masked, result.kyc_address,
        result.credit_score, result.credit_bureau, result.credit_report_ref,
        _json.dumps(result.credit_flags),
        result.lab_order_ref, _json.dumps(result.lab_tests), result.lab_report_url,
        result.aml_status, _json.dumps(result.aml_flags),
        result.confidence_score, _json.dumps(result.raw_response), expires_at, result.notes
    ))
    res_id = _row(cur.fetchone()).get("id")
    cur.close()
    return res_id


# ── List providers ────────────────────────────────────────────────────────────

@router.get("/tenant-context")
def get_tenant_context(current: CurrentUser):
    """
    Returns the current tenant's operating countries + default country + currency.
    Used by the Integrations frontend to decide whether to show a country
    selector at all, and what to default it to.
    """
    from services.country_currency import currency_for_country, list_countries
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT operating_countries, default_country FROM tenant WHERE id=%s::uuid",
            (current.tenant_id,),
        )
        row = cur.fetchone()
        cur.close()
        d = _row(row) if row else {}
        operating = d.get("operating_countries") or ["IN"]
        default   = d.get("default_country") or "IN"
        return {
            "operating_countries": operating,
            "default_country":     default,
            "currency":            currency_for_country(default),
            "is_multi_country":    len(operating) > 1,
            "available_countries": [c for c in list_countries() if c["code"] in operating],
        }
    except Exception:
        from services.country_currency import currency_for_country
        return {
            "operating_countries": ["IN"], "default_country": "IN",
            "currency": currency_for_country("IN"), "is_multi_country": False,
            "available_countries": [],
        }
    finally:
        release(conn)


@router.get("/providers")
def list_providers(current: CurrentUser, integration_type: str = "ALL", country_code: str = "ALL"):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where = "WHERE tenant_id = %s"
        params = [current.tenant_id]
        if integration_type != "ALL":
            where += " AND integration_type = %s"
            params.append(integration_type)
        if country_code != "ALL":
            where += " AND country_code = %s"
            params.append(country_code)
        cur.execute(f"""
            SELECT id, provider_code, provider_name, integration_type,
                   country_code, is_enabled, is_mock, api_endpoint,
                   config_json, created_at, updated_at
            FROM integration_config
            {where}
            ORDER BY country_code, integration_type, provider_name
        """, params)
        rows = [_row(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        raise HTTPException(500, f"Failed to list providers: {e}")
    finally:
        release(conn)


# ── Config update ─────────────────────────────────────────────────────────────

@router.patch("/config/{config_id}")
def update_config(config_id: int, body: ConfigUpdateRequest, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin required")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sets, params = [], []
        if body.is_enabled is not None:
            sets.append("is_enabled=%s"); params.append(body.is_enabled)
        if body.api_endpoint:
            sets.append("api_endpoint=%s"); params.append(body.api_endpoint)
        if body.api_key:
            # Simple base64 "encryption" for storage — use proper KMS in production
            import base64
            sets.append("api_key_enc=%s")
            params.append(base64.b64encode(body.api_key.encode()).decode())
        if body.config_json:
            sets.append("config_json=%s"); params.append(json.dumps(body.config_json))
        if not sets:
            raise HTTPException(400, "Nothing to update")
        sets.append("updated_at=now()")
        params += [config_id, current.tenant_id]
        cur.execute(f"""
            UPDATE integration_config SET {", ".join(sets)}
            WHERE id=%s AND tenant_id=%s RETURNING *
        """, params)
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Config not found")
        conn.commit()
        cur.close()
        return _row(row)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Config update failed: {e}")
    finally:
        release(conn)


# ── Run verification ──────────────────────────────────────────────────────────

@router.post("/verify")
def run_verification(body: VerifyRequest, current: CurrentUser):
    """
    Run an external data verification check.
    Auto-selects provider if provider_code not specified.
    country_code resolves from the tenant's default_country if not given.
    """
    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Resolve country_code from tenant config if not explicitly passed
        country_code = body.country_code
        if not country_code:
            cur.execute(
                "SELECT default_country FROM tenant WHERE id=%s::uuid",
                (current.tenant_id,),
            )
            trow = cur.fetchone()
            country_code = _row(trow).get("default_country", "IN") if trow else "IN"

        # Find provider
        where = "tenant_id=%s AND integration_type=%s AND is_enabled=true AND country_code=%s"
        params: list = [current.tenant_id, body.integration_type, country_code]
        if body.provider_code:
            where += " AND provider_code=%s"
            params.append(body.provider_code)
        cur.execute(f"""
            SELECT id, provider_code, is_mock, api_endpoint, config_json, api_key_enc
            FROM integration_config WHERE {where}
            ORDER BY is_mock ASC, id ASC LIMIT 1
        """, params)
        cfg_row = cur.fetchone()
        if not cfg_row:
            raise HTTPException(404,
                f"No enabled provider found for type={body.integration_type}. "
                f"Go to System Config → Integrations to enable a provider.")
        cfg = _row(cfg_row)

        # Load config (decode API key if present)
        provider_config = cfg.get("config_json") or {}
        if cfg.get("api_endpoint"):
            provider_config["api_endpoint"] = cfg["api_endpoint"]
        if cfg.get("api_key_enc"):
            import base64
            try:
                provider_config["api_key"] = base64.b64decode(cfg["api_key_enc"]).decode()
            except Exception:
                pass

        # Build payload for provider
        payload = {
            "applicant_ref":   body.applicant_ref,
            "full_name":       body.full_name,
            "age":             body.age,
            "gender":          body.gender,
            "pan_number":      body.pan_number,
            "aadhaar_number":  body.aadhaar_number,
            "dob":             body.dob,
            "annual_income":   body.annual_income,
            "product_code":    body.product_code,
            "tobacco_status":  body.tobacco_status,
            "diabetes_type":   body.diabetes_type,
            "heart_condition": body.heart_condition,
            **(body.extra or {}),
        }

        # Create request record
        cur.execute("""
            INSERT INTO integration_requests (
                tenant_id, case_ref_id, applicant_ref, integration_type,
                provider_code, country_code, status, request_payload, requested_by
            ) VALUES (%s,%s,%s,%s,%s,%s,'PENDING',%s,%s)
            RETURNING id, request_ref
        """, (
            current.tenant_id, body.case_ref_id, body.applicant_ref,
            body.integration_type, cfg["provider_code"], country_code,
            json.dumps(payload, default=str), current.username,
        ))
        req_row = _row(cur.fetchone())
        req_id  = req_row["id"]
        req_ref = req_row["request_ref"]
        conn.commit()
        cur.close()

        # Run the provider
        try:
            # Import and auto-register all mock providers
            import services.integrations.mock  # noqa: F401
            from services.integrations.base import get_provider
            provider = get_provider(cfg["provider_code"], config=provider_config)
            result   = provider.verify(payload)
            status   = "COMPLETED" if result.success else "FAILED"
        except Exception as pe:
            logger.error(f"Provider {cfg['provider_code']} failed: {pe}", exc_info=True)
            # Update request as failed
            cur2 = conn.cursor()
            cur2.execute("""
                UPDATE integration_requests SET status='FAILED', error_message=%s,
                completed_at=now() WHERE id=%s
            """, (str(pe), req_id))
            conn.commit()
            cur2.close()
            raise HTTPException(500, f"Provider error: {pe}")

        # Persist result
        cur3 = conn.cursor()
        res_id = _persist_result(conn, req_id, result, cfg["provider_code"],
                                  body.integration_type, body.applicant_ref, body.case_ref_id)
        cur3.execute("""
            UPDATE integration_requests SET status=%s, completed_at=now() WHERE id=%s
        """, (status, req_id))
        conn.commit()
        cur3.close()

        return {
            "request_ref":     req_ref,
            "provider_code":   cfg["provider_code"],
            "integration_type": body.integration_type,
            "country_code":    country_code,
            "is_mock":         cfg["is_mock"],
            "status":          status,
            "result":          result.to_dict(),
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"run_verification failed: {e}", exc_info=True)
        raise HTTPException(500, f"Verification failed: {e}")
    finally:
        release(conn)


# ── Get results for a case / applicant ───────────────────────────────────────

@router.get("/results")
def get_results(
    current: CurrentUser,
    applicant_ref: str | None = None,
    case_ref_id: int | None = None,
    integration_type: str = "ALL",
):
    if not applicant_ref and not case_ref_id:
        raise HTTPException(400, "Provide applicant_ref or case_ref_id")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        where, params = [], []
        if applicant_ref:
            where.append("ir.applicant_ref=%s"); params.append(applicant_ref)
        if case_ref_id:
            where.append("ir.case_ref_id=%s"); params.append(case_ref_id)
        if integration_type != "ALL":
            where.append("ir.integration_type=%s"); params.append(integration_type)

        cur.execute(f"""
            SELECT
                ir.id, ir.request_id, ir.provider_code, ir.integration_type,
                ir.applicant_ref, ir.case_ref_id,
                ir.kyc_verified, ir.kyc_name, ir.kyc_dob, ir.kyc_pan,
                ir.kyc_aadhaar_masked, ir.kyc_address,
                ir.credit_score, ir.credit_bureau, ir.credit_report_ref, ir.credit_flags,
                ir.lab_order_ref, ir.lab_tests, ir.lab_report_url,
                ir.aml_status, ir.aml_flags,
                ir.confidence_score, ir.notes, ir.verified_at, ir.expires_at,
                req.request_ref, req.requested_by, req.status AS request_status
            FROM integration_results ir
            JOIN integration_requests req ON req.id = ir.request_id
            WHERE {" AND ".join(where)}
            ORDER BY ir.verified_at DESC
        """, params)
        rows = [_row(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["verified_at"] = str(r["verified_at"]) if r.get("verified_at") else None
            r["expires_at"]  = str(r["expires_at"])  if r.get("expires_at")  else None
        return rows
    except Exception as e:
        raise HTTPException(500, f"Failed to get results: {e}")
    finally:
        release(conn)


# ── Full verification summary ─────────────────────────────────────────────────

@router.get("/summary/{applicant_ref}")
def get_summary(applicant_ref: str, current: CurrentUser):
    """
    Returns a structured summary of all available verification data for an applicant.
    Used by Workbench drawer and Evaluate page to show verification status at a glance.
    """
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (ir.integration_type)
                ir.integration_type, ir.provider_code,
                ir.kyc_verified, ir.credit_score, ir.aml_status,
                ir.confidence_score, ir.notes, ir.verified_at, ir.expires_at,
                ir.lab_tests, ir.aml_flags, ir.credit_flags
            FROM integration_results ir
            JOIN integration_requests req ON req.id = ir.request_id
            WHERE ir.applicant_ref=%s
            ORDER BY ir.integration_type, ir.verified_at DESC
        """, (applicant_ref,))
        rows = [_row(r) for r in cur.fetchall()]

        # Outstanding requirements (which types haven't been run yet)
        completed_types = {r["integration_type"] for r in rows}
        all_types       = {"IDENTITY","CREDIT","LAB","AML","PHARMACY","DRIVING"}
        pending_types   = all_types - completed_types

        cur.execute("""
            SELECT DISTINCT integration_type, provider_name
            FROM integration_config
            WHERE tenant_id=%s AND is_enabled=true AND integration_type=ANY(%s)
            ORDER BY integration_type
        """, (current.tenant_id, list(pending_types)))
        available_pending = [_row(r) for r in cur.fetchall()]
        cur.close()

        for r in rows:
            r["verified_at"] = str(r["verified_at"]) if r.get("verified_at") else None
            r["expires_at"]  = str(r["expires_at"])  if r.get("expires_at")  else None

        # Build risk flags from all results
        all_flags = []
        for r in rows:
            flags = r.get("aml_flags") or []
            if isinstance(flags, str):
                import json as _j
                flags = _j.loads(flags)
            if r.get("credit_score") and r["credit_score"] < 650:
                flags.append("LOW_CREDIT_SCORE")
            if r.get("kyc_verified") is False:
                flags.append("KYC_FAILED")
            all_flags.extend(flags)

        return {
            "applicant_ref":    applicant_ref,
            "completed":        rows,
            "pending_types":    list(pending_types),
            "available_pending": available_pending,
            "all_risk_flags":   list(set(all_flags)),
            "overall_status":   (
                "CLEAR"         if not all_flags and not pending_types else
                "FLAGGED"       if any(f in all_flags for f in ["DUI_HISTORY","HIT","KYC_FAILED","WRITTEN_OFF_ACCOUNT"]) else
                "PENDING"       if pending_types else
                "REVIEW_NEEDED"
            ),
        }
    except Exception as e:
        raise HTTPException(500, f"Summary failed: {e}")
    finally:
        release(conn)
