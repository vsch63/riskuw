"""
uw_platform.py — UW Platform  (Automated Underwriting Engine)
Run: streamlit run uw_platform.py

DEPENDENCY NOTE (xlrd fix):
  pip install "xlrd>=2.0.1" openpyxl
  Required for .xls Excel file support in batch upload.
  Without xlrd, field normalisation and pre-validation are skipped for .xls files.
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, date
import time
import io
import base64
from ai_engine.ai_scoring_panel import render_ai_scoring_panel
# render_ai_scoring_panel(uw_result, applicant_dict)

# ══════════════════════════════════════════════════════════════
#  STRUCTURED LOGGING
#  Outputs JSON-formatted lines so any log aggregator (CloudWatch,
#  Datadog, ELK, GCP Logging) can ingest without extra parsing.
#  Log level is controlled by the LOG_LEVEL env var (default INFO).
#  Usage anywhere in this file:
#      logger.info("message")
#      logger.warning("message", exc_info=_exc)
#      logger.error("message", exc_info=True)
# ══════════════════════════════════════════════════════════════
import logging
import json
import os as _logging_os
import traceback as _tb


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level":     record.levelname,
            "logger":    record.name,
            "function":  record.funcName,
            "line":      record.lineno,
            "message":   record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif hasattr(record, "exc_info") and record.exc_info is False and \
                hasattr(record, "__dict__") and "_exc" in record.__dict__:
            pass  # exc_info=_exc path handled below
        # Support exc_info=<exception instance> (our pattern: logger.warning("...", exc_info=_exc))
        if isinstance(getattr(record, "exc_info", None), BaseException):
            exc = record.exc_info
            payload["exception"] = "".join(
                _tb.format_exception(type(exc), exc, exc.__traceback__)
            ).strip()
            record.exc_info = None  # prevent double-formatting
        return json.dumps(payload, ensure_ascii=False)


def _build_logger() -> logging.Logger:
    _log = logging.getLogger("uw_platform")
    if _log.handlers:          # avoid adding handlers on Streamlit reruns
        return _log
    _level_name = _logging_os.environ.get("LOG_LEVEL", "INFO").upper()
    _level = getattr(logging, _level_name, logging.INFO)
    _log.setLevel(_level)
    _handler = logging.StreamHandler()
    _handler.setFormatter(_JsonFormatter())
    _log.addHandler(_handler)
    _log.propagate = False     # don't double-emit to root logger
    return _log


logger = _build_logger()

# ── Configuration ──────────────────────────────────────────────────────────────
from config import cfg
cfg.log_startup_summary()

# ══════════════════════════════════════════════════════════════
#  PDF DECISION REPORT GENERATOR
# ══════════════════════════════════════════════════════════════

def generate_decision_pdf(r: dict, prod: dict, tmpl: dict | None = None) -> bytes:
    """
    Generate a professional UW decision report as PDF.
    Uses letter_template fields (company name, body text, next steps, footer, contact)
    when a template dict is supplied; otherwise falls back to platform defaults.
    Returns HTML (bytes). Falls back gracefully — weasyprint converts to true PDF.
    """
    from datetime import datetime
    import json as _json

    # ── Template fields (with sensible defaults) ─────────────────
    tmpl                = tmpl or {}
    company_name        = tmpl.get("header_company_name") or "🛡️ UW Platform"
    company_tagline     = tmpl.get("header_tagline")      or "Automated Underwriting Decision Report"
    contact_email       = tmpl.get("contact_email")       or ""
    contact_phone       = tmpl.get("contact_phone")       or ""
    letter_body         = tmpl.get("body_text")           or ""
    footer_text         = tmpl.get("footer_text")         or (
        "This document is generated automatically by the UW Platform underwriting engine. "
        "All decisions are subject to underwriter review where required."
    )
    next_steps_raw      = tmpl.get("next_steps")
    if isinstance(next_steps_raw, str):
        try:
            next_steps_raw = _json.loads(next_steps_raw)
        except Exception as _exc:
            logger.debug("[generate_decision_pdf] Suppressed exception", exc_info=_exc)
            next_steps_raw = []
    next_steps: list    = next_steps_raw if isinstance(next_steps_raw, list) else []

    prod        = prod or {}
    outcome     = r.get("outcome") or "—"
    risk_class  = r.get("risk_class") or "—"
    net_debits  = r.get("net_debit_points") or 0
    app_id      = r.get("application_id") or "—"
    case_id     = r.get("case_id") or "—"
    decision_id = r.get("decision_id") or "—"
    rules_ver   = r.get("rules_version") or "—"
    eval_at     = str(r.get("evaluated_at") or "—")[:19].replace("T", " ")
    prod_name   = prod.get("name") or "Life Insurance"
    eff_date    = str(r.get("policy_effective_date") or "—")[:10]
    exp_date    = str(r.get("policy_expire_date") or "—")[:10]
    premium     = r.get("approved_premium")
    table_rating = r.get("table_rating")
    flat_extra  = r.get("flat_extra_per_thou")
    adverse     = r.get("adverse_action_text") or ""
    rules_fired = r.get("rules_fired") or []
    pathway     = (r.get("pathway") or "—").replace("_", " ")
    is_stp      = r.get("is_stp", False)

    # Outcome styling
    if "APPROVED" in outcome:
        outcome_color = "#065f46"
        outcome_border = "#10b981"
        outcome_text_color = "#6ee7b7"
        outcome_icon = "✓ APPROVED"
    elif "DECLINE" in outcome:
        outcome_color = "#7f1d1d"
        outcome_border = "#ef4444"
        outcome_text_color = "#fca5a5"
        outcome_icon = "✗ DECLINED"
    elif "POSTPONE" in outcome:
        outcome_color = "#1e1b4b"
        outcome_border = "#818cf8"
        outcome_text_color = "#c7d2fe"
        outcome_icon = "⏸ POSTPONED"
    else:
        outcome_color = "#1c1917"
        outcome_border = "#f59e0b"
        outcome_text_color = "#fcd34d"
        outcome_icon = "→ REFERRED"

    # Build rules fired rows
    rules_rows = ""
    for f in rules_fired[:20]:  # cap at 20 rules for PDF
        pts = ""
        if f.get("hard_stop"):
            pts = "HARD STOP"
            row_color = "#fef2f2"
            pts_color = "#dc2626"
        elif f.get("debit_points", 0) > 0:
            pts = f"+{f['debit_points']} db"
            row_color = "#fff7ed"
            pts_color = "#ea580c"
        elif f.get("credit_points", 0) > 0:
            pts = f"-{f['credit_points']} cr"
            row_color = "#f0fdf4"
            pts_color = "#16a34a"
        elif f.get("flat_extra", 0) > 0:
            pts = f"FE ${f['flat_extra']}/K"
            row_color = "#fff7ed"
            pts_color = "#ea580c"
        else:
            pts = "Refer"
            row_color = "#fffbeb"
            pts_color = "#d97706"

        expl = f.get("explanation", "")[:120]
        rules_rows += f"""
        <tr style="background:{row_color};">
            <td style="padding:6px 10px;font-size:11px;color:#374151;font-family:monospace;">
                {f.get("rule_id","—")}
            </td>
            <td style="padding:6px 10px;font-size:11px;color:#111827;font-weight:500;">
                {f.get("rule_name","—")}
            </td>
            <td style="padding:6px 10px;font-size:11px;color:#6b7280;">{expl}</td>
            <td style="padding:6px 10px;font-size:11px;font-weight:700;
                       color:{pts_color};text-align:right;white-space:nowrap;">{pts}</td>
        </tr>"""

    # Table rating / flat extra badges
    rating_badges = ""
    if table_rating:
        rating_badges += f'<span style="background:#fef3c7;color:#92400e;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;margin-right:8px;">Table {table_rating}</span>'
    if flat_extra:
        rating_badges += f'<span style="background:#fff7ed;color:#c2410c;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">Flat Extra ${flat_extra}/K</span>'

    # Adverse action section
    adverse_section = ""
    if adverse and adverse.strip():
        adverse_section = f"""
        <div style="margin-top:24px;padding:16px;background:#fef2f2;
                    border:1px solid #fecaca;border-radius:8px;">
            <div style="font-size:12px;font-weight:700;color:#dc2626;margin-bottom:8px;">
                ⚠ ADVERSE ACTION NOTICE
            </div>
            <div style="font-size:11px;color:#374151;font-family:monospace;
                        white-space:pre-wrap;line-height:1.6;">{adverse}</div>
        </div>"""

    pathway_display = "STRAIGHT THROUGH" if is_stp and "DECLINE" not in outcome else pathway

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>UW Decision Report — {app_id}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #111827;
          background: #fff; font-size: 13px; }}
  @media print {{
    body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body style="padding:40px;max-width:900px;margin:0 auto;">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              margin-bottom:28px;padding-bottom:16px;border-bottom:2px solid #1d4ed8;">
    <div>
      <div style="font-size:22px;font-weight:700;color:#1d4ed8;letter-spacing:-0.5px;">
        {company_name}
      </div>
      <div style="font-size:11px;color:#6b7280;margin-top:2px;">
        {company_tagline}
      </div>
      {"<div style='font-size:10px;color:#9ca3af;margin-top:2px;'>" + contact_phone + ("  |  " if contact_phone and contact_email else "") + contact_email + "</div>" if contact_phone or contact_email else ""}
    </div>
    <div style="text-align:right;">
      <div style="font-size:11px;color:#6b7280;">Generated</div>
      <div style="font-size:12px;font-weight:600;color:#374151;">
        {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}
      </div>
      <div style="font-size:10px;color:#9ca3af;margin-top:2px;">
        Decision ID: {decision_id}
      </div>
    </div>
  </div>

  <!-- Decision Banner -->
  <div style="background:{outcome_color};border:2px solid {outcome_border};
              border-radius:12px;padding:20px 24px;margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div style="font-size:10px;color:#9ca3af;text-transform:uppercase;
                    letter-spacing:0.1em;margin-bottom:4px;">{prod_name}</div>
        <div style="font-size:26px;font-weight:700;color:{outcome_text_color};
                    font-family:monospace;letter-spacing:0.05em;">{outcome_icon}</div>
        <div style="margin-top:8px;">
          <span style="background:rgba(0,0,0,0.3);color:#e5e7eb;padding:3px 12px;
                       border-radius:20px;font-size:11px;font-weight:600;">
            {pathway_display}
          </span>
          {rating_badges}
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:10px;color:#9ca3af;margin-bottom:2px;">RISK CLASS</div>
        <div style="font-size:20px;font-weight:700;color:#e5e7eb;font-family:monospace;">
          {risk_class}
        </div>
      </div>
    </div>
  </div>

  <!-- Key Metrics -->
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:14px;text-align:center;">
      <div style="font-size:20px;font-weight:700;color:#1d4ed8;">{net_debits:+.0f}</div>
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;
                  letter-spacing:0.08em;margin-top:2px;">Net Debits</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:14px;text-align:center;">
      <div style="font-size:20px;font-weight:700;color:#1d4ed8;">
        {f"${premium:,.2f}" if premium else "—"}
      </div>
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;
                  letter-spacing:0.08em;margin-top:2px;">Annual Premium</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:14px;text-align:center;">
      <div style="font-size:14px;font-weight:700;color:#374151;">{eff_date}</div>
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;
                  letter-spacing:0.08em;margin-top:2px;">Policy Effective</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:14px;text-align:center;">
      <div style="font-size:14px;font-weight:700;color:#374151;">{exp_date}</div>
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;
                  letter-spacing:0.08em;margin-top:2px;">Policy Expires</div>
    </div>
  </div>

  <!-- Audit IDs -->
  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
              padding:14px;margin-bottom:24px;font-family:monospace;font-size:11px;">
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;">
      <div><span style="color:#6b7280;">Application ID: </span>
           <span style="color:#111827;font-weight:600;">{app_id}</span></div>
      <div><span style="color:#6b7280;">Case ID: </span>
           <span style="color:#111827;font-weight:600;">{case_id}</span></div>
      <div><span style="color:#6b7280;">Decision ID: </span>
           <span style="color:#111827;font-weight:600;">{decision_id}</span></div>
      <div><span style="color:#6b7280;">Rules Version: </span>
           <span style="color:#111827;font-weight:600;">{rules_ver}</span></div>
      <div><span style="color:#6b7280;">Evaluated At: </span>
           <span style="color:#111827;font-weight:600;">{eval_at}</span></div>
      <div><span style="color:#6b7280;">Pathway: </span>
           <span style="color:#111827;font-weight:600;">{pathway_display}</span></div>
    </div>
  </div>

  <!-- Rules Fired -->
  {"<div style='margin-bottom:24px;'><div style='font-size:13px;font-weight:700;color:#111827;margin-bottom:10px;'>Rules Fired (" + str(len(rules_fired)) + ")</div><table style='width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;'><thead><tr style='background:#1d4ed8;color:white;'><th style='padding:8px 10px;text-align:left;font-size:11px;font-weight:600;'>Rule ID</th><th style='padding:8px 10px;text-align:left;font-size:11px;font-weight:600;'>Rule Name</th><th style='padding:8px 10px;text-align:left;font-size:11px;font-weight:600;'>Explanation</th><th style='padding:8px 10px;text-align:right;font-size:11px;font-weight:600;'>Points</th></tr></thead><tbody>" + rules_rows + "</tbody></table></div>" if rules_fired else ""}

  {adverse_section}

  <!-- Letter Body (from template) -->
  {('''<div style="margin-top:24px;padding:20px 24px;background:#f0f9ff;
                   border:1px solid #bae6fd;border-radius:8px;">
    <div style="font-size:12px;font-weight:700;color:#0369a1;margin-bottom:10px;">
      📄 DECISION LETTER
    </div>
    <div style="font-size:12px;color:#1e293b;white-space:pre-wrap;line-height:1.8;">''' +
    letter_body.format(
        applicant_name     = r.get("applicant_name", "Applicant"),
        outcome            = outcome,
        risk_class         = r.get("risk_class", "—"),
        net_debits         = r.get("net_debit_points", 0),
        policy_effective_date = str(r.get("policy_effective_date", "—"))[:10],
        policy_expire_date = str(r.get("policy_expire_date", "—"))[:10],
        approved_premium   = (f"${r.get('approved_premium'):,.2f}" if r.get("approved_premium") else "—"),
    ).replace("{", "{{").replace("}}", "}}")
    if letter_body else ""
    ) +
    ('''    </div>
  </div>''' if letter_body else "")}

  <!-- Next Steps (from template) -->
  {"<div style='margin-top:20px;padding:16px 20px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;'><div style='font-size:12px;font-weight:700;color:#15803d;margin-bottom:10px;'>✅ NEXT STEPS</div><ol style='margin:0;padding-left:20px;'>" + "".join(f"<li style='font-size:12px;color:#1e293b;margin-bottom:6px;'>{s}</li>" for s in next_steps) + "</ol></div>" if next_steps else ""}

  <!-- Footer -->
  <div style="margin-top:32px;padding-top:16px;border-top:1px solid #e5e7eb;
              display:flex;justify-content:space-between;align-items:center;">
    <div style="font-size:10px;color:#9ca3af;">
      {footer_text}
    </div>
    <div style="font-size:10px;color:#9ca3af;">
      CONFIDENTIAL — FOR INTERNAL USE ONLY
    </div>
  </div>

</body>
</html>"""

    return html.encode("utf-8")


def get_pdf_download_data(r: dict, prod: dict) -> tuple[bytes, str]:
    """
    Returns (file_bytes, filename) for the decision report.
    Fetches the active letter_template for the outcome from the API (if available).
    Tries weasyprint for true PDF, falls back to HTML download.
    """
    app_id   = r.get("application_id", "decision")[:12]
    outcome  = r.get("outcome", "decision").replace(" ", "_").replace("/", "_")
    filename_base = f"UW_Decision_{app_id}_{outcome}"

    # Try to load the active letter template for this outcome
    tmpl = fetch_active_letter_template(r.get("outcome", ""))
    # Also check if a preview template was staged in session state
    if st.session_state.get("lt_preview_template"):
        tmpl = st.session_state["lt_preview_template"]

    html_bytes = generate_decision_pdf(r, prod, tmpl=tmpl)

    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_bytes.decode("utf-8")).write_pdf()
        return pdf_bytes, f"{filename_base}.pdf"
    except ImportError:
        return html_bytes, f"{filename_base}.html"
    except Exception as _exc:
        logger.warning("[get_pdf_download_data] weasyprint PDF rendering failed — falling back to HTML", exc_info=_exc)
        return html_bytes, f"{filename_base}.html"


def _get_smtp_config() -> dict:
    """Load SMTP config from DB with session state fallback."""
    if st.session_state.get("_smtp_config"):
        return st.session_state["_smtp_config"]
    cfg = {}
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM smtp_config")
            cfg = {r[0]: r[1] for r in cur.fetchall()}
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_get_smtp_config] Failed to load SMTP config from DB — email notifications will not send", exc_info=_exc)
    st.session_state["_smtp_config"] = cfg
    return cfg


def _get_ri_auto_email() -> bool:
    """Return global RI auto-email setting from DB. Default True."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM system_config WHERE config_key='ri_auto_email_enabled'",
            )
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                return str(row[0]).lower() in ("true","1","yes")
    except Exception as _exc:
        logger.debug("[_get_ri_auto_email] Suppressed", exc_info=_exc)
    return True  # Default ON


def _set_ri_auto_email(enabled: bool):
    """Save global RI auto-email setting to DB."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_config (config_key, value, description)
                VALUES ('ri_auto_email_enabled', %s, 'Auto-email reinsurer on cession submission')
                ON CONFLICT (config_key) DO UPDATE SET value = EXCLUDED.value
            """, (str(enabled).lower(),))
            conn.commit(); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_set_ri_auto_email] Suppressed", exc_info=_exc)


def _send_ri_slip_email(case: dict, reinsurer: dict, slip_html: str) -> tuple[bool, str]:
    """
    Send RI cession slip to reinsurer contact email via SMTP.
    Returns (success, message).
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    ri_email = reinsurer.get("email","").strip()
    if not ri_email:
        return False, f"No email configured for reinsurer {reinsurer.get('name','')}. Add it in Reinsurer Registry."

    st.session_state.pop("_smtp_config", None)
    smtp = _get_smtp_config()
    host       = smtp.get("host","")
    port       = int(smtp.get("port", 587))
    s_user     = smtp.get("username","")
    s_pass     = smtp.get("password","")
    from_email = smtp.get("from_email","")
    use_tls    = smtp.get("use_tls","true").lower() == "true"

    if not host or not from_email or not s_user:
        return False, "SMTP not configured. Go to System Config → API Keys to set up SMTP."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"Reinsurance Cession Slip — {case.get('case_number','')} | "
            f"{reinsurer.get('treaty_code','FAC')} | "
            f"Face: ${case.get('face_amount',0):,.0f}"
        )
        msg["From"]    = f"UW Platform <{from_email}>"
        msg["To"]      = ri_email

        # Plain text fallback
        _n = reinsurer.get("name", "")
        _cn = case.get("case_number", "")
        _fa = case.get("face_amount", 0)
        _ca = case.get("ceded_amount", 0)
        _ou = case.get("outcome", "")
        text_body = (
            "Dear " + _n + " Team,\n\n"
            "Please find attached the RI cession slip for case " + _cn + ".\n\n"
            "Face Amount: " + f"${_fa:,.0f}" + "\n"
            "Ceded Amount: " + f"${_ca:,.0f}" + "\n"
            "UW Decision: " + _ou + "\n\n"
            "Please review and confirm receipt.\n\n"
            "Regards,\nUW Platform - Underwriting Department"
        )
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(slip_html, "html"))

        if use_tls:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        if s_user and s_pass:
            server.login(s_user, s_pass)
        server.sendmail(from_email, ri_email, msg.as_string())
        server.quit()
        return True, f"Email sent to {ri_email}"
    except Exception as _exc:
        logger.error("[_send_ri_slip_email] Failed", exc_info=_exc)
        return False, str(_exc)


def _save_smtp_config(cfg: dict):
    """Persist SMTP config to DB."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            for k, v in cfg.items():
                cur.execute("""INSERT INTO smtp_config (key,value) VALUES (%s,%s)
                    ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""",
                    (k, str(v)))
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_save_smtp_config] Failed to persist SMTP config to DB — changes will be lost on restart", exc_info=_exc)
    st.session_state["_smtp_config"] = cfg


# ── Notification engine ───────────────────────────────────────────────────────

_NOTIF_EVENTS = {
    "CASE_ASSIGNED":     "Case assigned to underwriter",
    "DECISION_RECORDED": "UW decision recorded (approve/decline/postpone)",
    "APS_REQUESTED":     "APS request raised",
    "APS_OVERDUE":       "APS not received by due date",
    "BATCH_COMPLETED":   "Batch job finished processing",
}

_NOTIF_DEFAULT_SUBJECTS = {
    "CASE_ASSIGNED":     "Case assigned to you: {case_number}",
    "DECISION_RECORDED": "Decision recorded: {case_number} - {outcome}",
    "APS_REQUESTED":     "APS requested: {case_number} | {rule_name}",
    "APS_OVERDUE":       "URGENT: APS overdue - {case_number} (due {due_date})",
    "BATCH_COMPLETED":   "Batch job complete: {job_number} | {total} records",
}

_NOTIF_DEFAULT_BODIES = {
    "CASE_ASSIGNED": (
        "Dear {uw_name},\n\n"
        "A case has been assigned to you.\n\n"
        "Case Number  : {case_number}\n"
        "Applicant Ref: {applicant_ref}\n"
        "Product      : {product_code}\n"
        "Face Amount  : {face_amount}\n"
        "SLA          : {sla_hours} hours\n"
        "Note         : {assign_note}\n\n"
        "Please log in to the UW Platform to action this case.\n\n"
        "Regards,\n{from_name}"
    ),
    "DECISION_RECORDED": (
        "A decision has been recorded on the following case.\n\n"
        "Case Number  : {case_number}\n"
        "Applicant Ref: {applicant_ref}\n"
        "Outcome      : {outcome}\n"
        "Risk Class   : {risk_class}\n"
        "Decided By   : {decided_by}\n"
        "Reason       : {reason}\n\n"
        "Regards,\n{from_name}"
    ),
    "APS_REQUESTED": (
        "An APS has been requested for the following case.\n\n"
        "Case Number    : {case_number}\n"
        "Applicant Ref  : {applicant_ref}\n"
        "Triggering Rule: {rule_name}\n"
        "Physician      : {physician_name}\n"
        "Due Date       : {due_date}\n\n"
        "Please follow up with the physician's office to ensure records arrive by the due date.\n\n"
        "Regards,\n{from_name}"
    ),
    "APS_OVERDUE": (
        "URGENT - APS OVERDUE\n\n"
        "Case Number  : {case_number}\n"
        "Physician    : {physician_name}\n"
        "Due Date     : {due_date}\n"
        "Days Overdue : {days_overdue}\n\n"
        "The APS for this case has not been received. "
        "Please chase the physician's office immediately.\n\n"
        "Regards,\n{from_name}"
    ),
    "BATCH_COMPLETED": (
        "Batch job processing is complete.\n\n"
        "Job Number : {job_number}\n"
        "Job Name   : {job_name}\n"
        "Total      : {total} records\n"
        "Approved   : {approved}\n"
        "Declined   : {declined}\n"
        "Referred   : {referred}\n"
        "Errors     : {errored}\n\n"
        "Go to Batch Jobs in the UW Platform to review results and download the report.\n\n"
        "Regards,\n{from_name}"
    ),
}


def _get_notification_config() -> dict:
    """Load all notification event configs from DB."""
    if st.session_state.get("_notif_cfg"):
        return st.session_state["_notif_cfg"]
    cfg = {}
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT event, enabled, recipients, subject_tpl, body_tpl "
                "FROM notification_config"
            )
            for row in cur.fetchall():
                cfg[row[0]] = {
                    "enabled":    row[1],
                    "recipients": row[2] or "",
                    "subject":    row[3] or "",
                    "body":       row[4] or "",
                }
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_get_notification_config] Suppressed exception", exc_info=_exc)
    st.session_state["_notif_cfg"] = cfg
    return cfg


def _save_notification_event(event: str, enabled: bool,
                              recipients: str, subject: str, body: str):
    """Upsert one notification event row."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO notification_config
                    (event, enabled, recipients, subject_tpl, body_tpl, updated_at)
                VALUES (%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (event) DO UPDATE SET
                    enabled=EXCLUDED.enabled,
                    recipients=EXCLUDED.recipients,
                    subject_tpl=EXCLUDED.subject_tpl,
                    body_tpl=EXCLUDED.body_tpl,
                    updated_at=NOW()
            """, (event, enabled, recipients.strip(), subject.strip(), body.strip()))
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_save_notification_event] Suppressed exception", exc_info=_exc)
    st.session_state.pop("_notif_cfg", None)


def _log_notification(event: str, recipient: str,
                       subject: str, status: str, error: str = ""):
    """Append a row to the notification audit log."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_log_notification] Failed to write notification log record to DB — notification event may be unrecorded", exc_info=_exc)


def _ensure_physician_table():
    """
    No-op shim kept for call-site compatibility.
    The physicians table is now created by migrations/001_initial_schema.sql.
    """
    pass


def _load_physicians(active_only: bool = True) -> list:
    """Load physician registry from DB. Returns list of dicts."""
    _ensure_physician_table()
    if st.session_state.get("_physicians_cache"):
        return st.session_state["_physicians_cache"]
    rows = []
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            q = """
                SELECT id, physician_name, registration_no, specialisation,
                       clinic_name, email, phone, address_line1, city, state,
                       effective_date, expire_date, is_active
                FROM physicians
            """
            if active_only:
                q += " WHERE is_active = TRUE"
            q += " ORDER BY physician_name"
            cur.execute(q)
            rows = [{
                "id":               r[0],
                "physician_name":   r[1],
                "registration_no":  r[2] or "",
                "specialisation":   r[3] or "",
                "clinic_name":      r[4] or "",
                "email":            r[5] or "",
                "phone":            r[6] or "",
                "address_line1":    r[7] or "",
                "city":             r[8] or "",
                "state":            r[9] or "",
                "effective_date":   r[10],
                "expire_date":      r[11],
                "is_active":        r[12],
            } for r in cur.fetchall()]
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.debug("[_load_physicians] Suppressed exception", exc_info=_exc)
    st.session_state["_physicians_cache"] = rows
    return rows


def send_aps_request_to_physician(
    physician_email: str,
    physician_name: str,
    applicant_name: str,
    applicant_ref: str,
    case_number: str,
    rule_name: str,
    due_date: str,
    from_name: str = "",
    from_email_override: str = "",
) -> tuple:
    """
    Send formal APS request letter to the physician by email.
    Returns (success, message).
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp = _get_smtp_config()
    host       = smtp.get("host","")
    port       = int(smtp.get("port", 587))
    username   = smtp.get("username","")
    password   = smtp.get("password","")
    from_email = from_email_override or smtp.get("from_email","")
    sender_name = from_name or smtp.get("from_name","UW Platform")
    use_tls    = smtp.get("use_tls","true").lower() == "true"

    if not host or not from_email:
        _log_notification(to_email or "", f"Decision: {case_number}", "NOT_SENT",
            error_msg="SMTP not configured", error_code="EMAIL-006",
            applicant_ref=applicant_ref or case_number, batch_job_name=batch_job_name)
        return False, "[EMAIL-006] SMTP not configured - go to System Config > Notifications"
    subject = f"Request for Attending Physician Statement — {applicant_ref}"

    body = f"""Dear Dr. {physician_name},

We are writing to request an Attending Physician Statement (APS) for one of your patients 
who has applied for life insurance with us.

PATIENT DETAILS
---------------
Patient Reference : {applicant_ref}
Patient Name      : {applicant_name or 'Provided separately'}
Case Reference    : {case_number}

RECORDS REQUIRED
---------------
Condition / Rule  : {rule_name or 'Full medical history'}

We require the following information:
- Complete medical history relevant to the above condition
- Current diagnosis, treatment plan and prognosis
- All relevant investigation results and lab reports
- Details of any hospitalisations in the past 5 years
- Current medications and dosages

APS DUE DATE: {due_date}

Please send the completed APS and supporting records to us by the above date.
If you require a signed patient authorisation form, please contact us at {from_email}.

This request has been authorised by the patient as part of their insurance application.

Thank you for your assistance.

Yours sincerely,
{sender_name}
Underwriting Department
{from_email}
"""

    try:
        msg = MIMEMultipart()
        msg["From"]    = f"{sender_name} <{from_email}>"
        msg["To"]      = physician_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if use_tls:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        if username and password:
            server.login(username, password)
        server.sendmail(from_email, physician_email, msg.as_string())
        server.quit()
        return True, f"APS request sent to Dr. {physician_name} at {physician_email}"
    except Exception as e:
        return False, f"Email failed: {e}"


def send_notification(event: str, context: dict,
                      extra_recipients: list = None) -> list:
    """
    Fire a platform notification for a named event.
    Silently does nothing if SMTP is not configured or the event is disabled.
    Returns list of (recipient, 'SENT'|'FAILED', error_msg) tuples.
    """
    import smtplib, re
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp = _get_smtp_config()
    host       = smtp.get("host","")
    port       = int(smtp.get("port", 587))
    username   = smtp.get("username","")
    password   = smtp.get("password","")
    from_email = smtp.get("from_email","")
    from_name  = smtp.get("from_name","UW Platform")
    use_tls    = smtp.get("use_tls","true").lower() == "true"

    if not host or not from_email:
        return []   # SMTP not configured — silent skip

    cfg = _get_notification_config()
    ev  = cfg.get(event, {})
    if ev and not ev.get("enabled", True):
        return []   # Event disabled by admin

    # Recipients: configured list + any extra (e.g. the assigned UW's email)
    configured  = [r.strip() for r in (ev.get("recipients","") or "").split(",")
                   if r.strip()]
    extras      = [r for r in (extra_recipients or []) if r and r.strip()]
    all_to      = list(dict.fromkeys(configured + extras))
    if not all_to:
        return []

    # Subject and body — use saved template or default
    raw_subj = (ev.get("subject") or "").strip() or \
               _NOTIF_DEFAULT_SUBJECTS.get(event, f"UW Platform: {event}")
    raw_body = (ev.get("body") or "").strip() or \
               _NOTIF_DEFAULT_BODIES.get(event, "Event: {event}")

    def _fill(tpl: str) -> str:
        ctx = {**context, "from_name": from_name, "event": event}
        return re.sub(r'\{(\w+)\}',
                      lambda m: str(ctx.get(m.group(1), "")), tpl)

    subject = _fill(raw_subj)
    body    = _fill(raw_body)

    results = []
    for recipient in all_to:
        try:
            msg = MIMEMultipart()
            msg["From"]    = f"{from_name} <{from_email}>"
            msg["To"]      = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            if use_tls:
                srv = smtplib.SMTP(host, port, timeout=10)
                srv.starttls()
            else:
                srv = smtplib.SMTP_SSL(host, port, timeout=10)
            if username and password:
                srv.login(username, password)
            srv.sendmail(from_email, recipient, msg.as_string())
            srv.quit()
            _log_notification(event, recipient, subject, "SENT")
            results.append((recipient, "SENT", ""))
        except Exception as e:
            _log_notification(event, recipient, subject, "FAILED", str(e))
            results.append((recipient, "FAILED", str(e)))
    return results


def _log_notification(recipient, subject, status, error_msg=None,
                      error_code=None, applicant_ref=None, batch_job_name=None, event="DECISION_EMAIL"):
    """Log email notification attempt to notification_log table."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO notification_log
                    (event, recipient, subject, status, error_msg, error_code, applicant_ref, batch_job_name)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (event, recipient, subject, status, error_msg, error_code, applicant_ref, batch_job_name)); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_log_notification] Failed to write notification log record to DB — notification event may be unrecorded", exc_info=_exc)

def send_decision_email(
    to_email: str, applicant_name: str, outcome: str,
    case_number: str, reason: str, letter_bytes: bytes,
    letter_filename: str, is_pdf: bool = True,
    applicant_ref: str = None, batch_job_name: str = None,
) -> tuple:
    """Send decision letter to applicant via SMTP. Returns (success, message)."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    smtp = _get_smtp_config()
    host       = smtp.get("host","")
    port       = int(smtp.get("port", 587))
    username   = smtp.get("username","")
    password   = smtp.get("password","")
    from_email = smtp.get("from_email","")
    from_name  = smtp.get("from_name","UW Platform")
    use_tls    = smtp.get("use_tls","true").lower() == "true"

    # ── Email Validation ──────────────────────────────────────────────
    try:
        from batch_email_validator import BatchEmailValidator as _BEV
        _vc = _BEV(check_mx=False).validate(to_email or "", check_duplicates=False)
        if not _vc.is_valid:
            _log_notification(to_email or "", f"Decision: {case_number}", "NOT_SENT",
                error_msg=_vc.error_detail, error_code=_vc.error_code,
                applicant_ref=applicant_ref or case_number, batch_job_name=batch_job_name)
            return False, f"[{_vc.error_code}] {_vc.error_detail}"
    except ImportError:
        pass

    if not host or not from_email:
        _log_notification(to_email or "", f"Decision: {case_number}", "NOT_SENT",
            error_msg="SMTP not configured", error_code="EMAIL-006",
            applicant_ref=applicant_ref or case_number, batch_job_name=batch_job_name)
        return False, "[EMAIL-006] SMTP not configured - go to System Config > Notifications"

    _subjects = {
        "APPROVED":      f"Your Life Insurance Application - Approved | {case_number}",
        "DECLINED":      f"Your Life Insurance Application - Adverse Action Notice | {case_number}",
        "POSTPONED":     f"Your Life Insurance Application - Postponed | {case_number}",
        "COUNTER_OFFER": f"Your Life Insurance Application - Counter Offer | {case_number}",
        "REFERRED":      f"Your Life Insurance Application - Under Review | {case_number}",
    }
    subject = _subjects.get(outcome, f"Your Life Insurance Application | {case_number}")
    _name = applicant_name or "Applicant"
    _outcome_text = {
        "APPROVED":      "We are pleased to inform you that your application has been approved.",
        "DECLINED":      "After careful review, we regret to inform you that your application has been declined.",
        "POSTPONED":     "Your application has been postponed pending additional review.",
        "COUNTER_OFFER": "We are pleased to offer a counter proposal for your consideration.",
        "REFERRED":      "Your application is currently under review by our underwriting team.",
    }.get(outcome, "A decision has been recorded for your application.")
    reason_line = f"Reason: {reason}\n" if reason and "DECLIN" in outcome else ""
    body_text = (
        f"Dear {_name},\n\n{_outcome_text}\n\n"
        f"Case Reference: {case_number}\nDecision: {outcome}\n{reason_line}\n"
        f"Please find the full decision report attached to this email.\n\n"
        f"If you have any questions, please contact our customer service team.\n\n"
        f"Regards,\n{from_name}"
    )
    try:
        msg = MIMEMultipart()
        msg["From"]    = f"{from_name} <{from_email}>"
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))
        part = MIMEBase("application", "octet-stream")
        part.set_payload(letter_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{letter_filename}"')
        msg.attach(part)
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        if username and password:
            server.login(username, password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        _log_notification(to_email, subject, "SENT",
            applicant_ref=applicant_ref or case_number,
            batch_job_name=batch_job_name)
        return True, f"Decision letter sent to {to_email}"
    except Exception as e:
        _log_notification(to_email, subject, "FAILED",
            error_msg=str(e)[:200],
            error_code="EMAIL-005",
            applicant_ref=applicant_ref or case_number,
            batch_job_name=batch_job_name)
        return False, f"[EMAIL-005] Email failed: {e}"


st.set_page_config(
    page_title="UW Platform — Underwriting Workbench",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');
  html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
  section[data-testid="stSidebar"] { background:#0f1117; border-right:1px solid #1e2530; }
  section[data-testid="stSidebar"] > div:first-child { overflow-y:auto !important; overflow-x:hidden; height:100vh; }
  section[data-testid="stSidebar"] .stButton > button { font-size:0.76rem !important; padding:0.28rem 0.5rem !important; margin-bottom:0 !important; min-height:0 !important; line-height:1.4 !important; }
  section[data-testid="stSidebar"] .stButton { margin-bottom:1px !important; }
  section[data-testid="stSidebar"] * { color:#e2e8f0 !important; }
  section[data-testid="stSidebar"] label { color:#94a3b8 !important; font-size:0.78rem !important; text-transform:uppercase; letter-spacing:0.05em; }
  section[data-testid="stSidebar"] hr { margin:0.3rem 0 !important; }
  section[data-testid="stSidebar"] p { margin:0 !important; font-size:0.72rem !important; }
  .main .block-container { padding-top:1.5rem; max-width:1400px; }
  .product-banner { background:linear-gradient(135deg,#0f172a,#1e293b); border:1px solid #334155; border-radius:10px; padding:1rem 1.2rem; margin-bottom:1rem; }
  .product-name { font-size:1rem; font-weight:600; color:#e2e8f0; }
  .product-meta { font-size:0.72rem; color:#64748b; margin-top:0.2rem; }
  .product-pill { background:#1e3a5f; color:#60a5fa; padding:3px 12px; border-radius:20px; font-size:0.72rem; font-weight:600; letter-spacing:0.05em; }
  .decision-approved { background:linear-gradient(135deg,#064e3b,#065f46); border:1px solid #10b981; border-radius:12px; padding:1.5rem; margin-bottom:1rem; }
  .decision-decline  { background:linear-gradient(135deg,#450a0a,#7f1d1d); border:1px solid #ef4444; border-radius:12px; padding:1.5rem; margin-bottom:1rem; }
  .decision-refer    { background:linear-gradient(135deg,#1c1917,#292524); border:1px solid #f59e0b; border-radius:12px; padding:1.5rem; margin-bottom:1rem; }
  .decision-postpone { background:linear-gradient(135deg,#1e1b4b,#312e81); border:1px solid #818cf8; border-radius:12px; padding:1.5rem; margin-bottom:1rem; }
  .outcome-badge { font-family:'IBM Plex Mono',monospace; font-size:1.4rem; font-weight:600; letter-spacing:0.05em; }
  .metric-card   { background:#1e2530; border:1px solid #2d3748; border-radius:8px; padding:1rem; text-align:center; }
  .metric-value  { font-family:'IBM Plex Mono',monospace; font-size:1.8rem; font-weight:600; color:#e2e8f0; }
  .metric-label  { font-size:0.72rem; color:#64748b; text-transform:uppercase; letter-spacing:0.08em; margin-top:0.2rem; }
  .rule-fired    { background:#1a1f2e; border-left:3px solid #ef4444; border-radius:0 6px 6px 0; padding:0.6rem 0.8rem; margin-bottom:0.4rem; font-size:0.85rem; }
  .rule-credit   { background:#0f2318; border-left:3px solid #10b981; border-radius:0 6px 6px 0; padding:0.6rem 0.8rem; margin-bottom:0.4rem; font-size:0.85rem; }
  .rule-hardstop { background:#2d0a0a; border-left:3px solid #dc2626; border-radius:0 6px 6px 0; padding:0.6rem 0.8rem; margin-bottom:0.4rem; font-size:0.85rem; }
  .rule-product  { background:#1a2535; border-left:3px solid #3b82f6; border-radius:0 6px 6px 0; padding:0.6rem 0.8rem; margin-bottom:0.4rem; font-size:0.85rem; }
  .exam-box { background:#1a1a2e; border:1px solid #4338ca; border-radius:8px; padding:0.7rem 1rem; font-size:0.82rem; color:#a5b4fc; margin-top:0.5rem; }
  .adverse-action { background:#1a1208; border:1px solid #92400e; border-radius:8px; padding:1rem; font-size:0.82rem; color:#fcd34d; font-family:'IBM Plex Mono',monospace; white-space:pre-wrap; line-height:1.6; }
  .stButton > button { width:100%; background:#1d4ed8; color:white; border:none; border-radius:8px; padding:0.7rem; font-weight:600; font-size:0.95rem; }
  .stButton > button:hover { background:#1e40af; }
  div[data-testid="stForm"] { background:transparent; }
</style>
""", unsafe_allow_html=True)

# ── Product catalog ────────────────────────────────────────────
PRODUCTS = {
    "IND-TERM-10": {
        "name": "Individual Term Life — 10 Year", "category": "Individual Life",
        "sub_type": "Term", "min_age": 18, "max_age": 70,
        "min_face": 100_000, "max_face": 10_000_000, "terms": [10],
        "uw_method": "Full UW", "exam_note": "$500K+ requires paramedical exam",
        "notes": "Pure protection. Highest STP rate. Best for income replacement.",
        "is_gi": False,
    },
    "IND-TERM-20": {
        "name": "Individual Term Life — 20 Year", "category": "Individual Life",
        "sub_type": "Term", "min_age": 18, "max_age": 65,
        "min_face": 100_000, "max_face": 10_000_000, "terms": [20],
        "uw_method": "Full UW", "exam_note": "$500K+ requires paramedical exam",
        "notes": "Most popular term. Max issue age 65 (policy runs to 85).",
        "is_gi": False,
    },
    "IND-TERM-30": {
        "name": "Individual Term Life — 30 Year", "category": "Individual Life",
        "sub_type": "Term", "min_age": 18, "max_age": 55,
        "min_face": 100_000, "max_face": 5_000_000, "terms": [30],
        "uw_method": "Full UW", "exam_note": "Exam always required. Strictest underwriting.",
        "notes": "Long-term protection. Max issue age 55. 2yr tobacco-free for non-tobacco rates.",
        "is_gi": False,
    },
    "IND-UL-FLEX": {
        "name": "Individual Universal Life — FlexLife", "category": "Individual Life",
        "sub_type": "Universal Life", "min_age": 18, "max_age": 70,
        "min_face": 250_000, "max_face": 10_000_000, "terms": [],
        "uw_method": "Full UW", "exam_note": "Exam required. Financial UW required >$1M.",
        "notes": "Flexible premium permanent life. Max Table 12. Permanent flat extras.",
        "is_gi": False,
    },
    "IND-WL-PREM": {
        "name": "Individual Whole Life — PremierLife", "category": "Individual Life",
        "sub_type": "Whole Life", "min_age": 18, "max_age": 65,
        "min_face": 100_000, "max_face": 5_000_000, "terms": [],
        "uw_method": "Full UW", "exam_note": "Full medical always required. Stricter build table.",
        "notes": "Traditional permanent life. Max Table 8. Max age 65. Most conservative criteria.",
        "is_gi": False,
    },
    "IND-FE-SIMPLE": {
        "name": "Final Expense — SimpleCare", "category": "Individual Life",
        "sub_type": "Final Expense", "min_age": 45, "max_age": 85,
        "min_face": 5_000, "max_face": 50_000, "terms": [],
        "uw_method": "Simplified Issue", "exam_note": "No exam required. Simplified issue.",
        "notes": "Senior market. Graded/modified benefit options for impaired risks.",
        "is_gi": False,
    },
    "GRP-BASIC-1x": {
        "name": "Group Basic Life — 1x Salary", "category": "Group Life",
        "sub_type": "Group Basic", "min_age": 18, "max_age": 70,
        "min_face": 10_000, "max_face": 500_000, "terms": [1],
        "uw_method": "Guaranteed Issue", "exam_note": "No exam. Guaranteed issue — no individual UW.",
        "notes": "Employer-paid basic life. No individual underwriting. Group experience rated.",
        "is_gi": True,
    },
    "GRP-SUPP-EOI": {
        "name": "Group Supplemental Life — Employee EOI", "category": "Group Life",
        "sub_type": "Group Supplemental", "min_age": 18, "max_age": 70,
        "min_face": 10_000, "max_face": 1_000_000, "terms": [1],
        "uw_method": "Simplified EOI", "exam_note": "No exam. EOI form required above $200K GI limit.",
        "notes": "Voluntary employee-paid. GI up to $200K. Approve or decline only — no table ratings.",
        "is_gi": False,
    },
    "IND-KEYMAN": {
        "name": "Key Person Life Insurance", "category": "Individual Life",
        "sub_type": "Key Person", "min_age": 18, "max_age": 65,
        "min_face": 250_000, "max_face": 20_000_000, "terms": [10, 15, 20],
        "uw_method": "Full UW", "exam_note": "Full medical + business financial statements required.",
        "notes": "Business key person coverage. Higher face amounts available. Financial justification required.",
        "is_gi": False,
    },
}

PRODUCT_CATEGORIES = {
    "Individual Life": ["IND-TERM-10","IND-TERM-20","IND-TERM-30","IND-UL-FLEX","IND-WL-PREM","IND-FE-SIMPLE","IND-KEYMAN"],
    "Group Life":      ["GRP-BASIC-1x","GRP-SUPP-EOI"],
}

API_BASE = cfg.api_base

# ── Session state ──────────────────────────────────────────────
if "token"        not in st.session_state: st.session_state.token = None
if "last_result"  not in st.session_state: st.session_state.last_result = None
if "last_product" not in st.session_state: st.session_state.last_product = None
if "case_history" not in st.session_state: st.session_state.case_history = []
if "page"         not in st.session_state: st.session_state.page = "Underwriting Workbench"
if "mfa_pending"  not in st.session_state: st.session_state.mfa_pending  = False
if "mfa_email"    not in st.session_state: st.session_state.mfa_email    = None
if "mfa_tok_temp" not in st.session_state: st.session_state.mfa_tok_temp = None

# ── Helpers ────────────────────────────────────────────────────
# ── Auth configuration ─────────────────────────────────────
# All authentication is handled exclusively by the FastAPI backend (/auth/login).
# User credentials are stored in the backend database (bcrypt-hashed).
# No credentials are stored in this file or the environment.
# Set API_BASE (above) to point at your FastAPI instance.
import hashlib as _hl

# ══════════════════════════════════════════════════════════════════════════════
#  MFA — TOTP (RFC 6238) implemented with stdlib only
# ══════════════════════════════════════════════════════════════════════════════
import hmac as _hmac, hashlib as _hashlib, struct as _struct
import base64 as _b64, secrets as _secrets
from urllib.parse import quote as _urlquote

def _mfa_ensure_table():
    """Create mfa_config table if it does not exist."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_mfa_ensure_table] Failed to create/verify mfa_config table — MFA will not function until resolved", exc_info=_exc)


def _mfa_generate_secret() -> str:
    """Generate a cryptographically random Base32 TOTP secret."""
    return _b64.b32encode(_secrets.token_bytes(20)).decode()


def _mfa_code(secret: str, t: int = None) -> str:
    """Compute the 6-digit TOTP code for a given 30-second window."""
    import time as _t
    if t is None:
        t = int(_t.time()) // 30
    key = _b64.b32decode(secret.upper().strip())
    msg = _struct.pack(">Q", t)
    h   = _hmac.new(key, msg, _hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = _struct.unpack(">I", h[offset:offset+4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def _mfa_verify(secret: str, code: str, window: int = 1) -> bool:
    """
    Verify a TOTP code. Accepts ±window steps (30s each) to allow clock drift.
    Uses constant-time comparison to prevent timing attacks.
    """
    import time as _t
    t = int(_t.time()) // 30
    code = code.strip().replace(" ", "")
    for delta in range(-window, window + 1):
        if _hmac.compare_digest(_mfa_code(secret, t + delta), code):
            return True
    return False


def _mfa_generate_backup_codes(n: int = 8) -> list:
    """Generate n single-use 8-character alphanumeric backup codes."""
    import random as _rnd, string as _str
    chars = _str.ascii_uppercase.replace("O","").replace("I","") + _str.digits.replace("0","")
    return [
        "".join(_rnd.SystemRandom().choices(chars, k=4)) + "-" +
        "".join(_rnd.SystemRandom().choices(chars, k=4))
        for _ in range(n)
    ]


def _mfa_otpauth_url(secret: str, email: str,
                     issuer: str = "UW Platform") -> str:
    """Build the otpauth:// URI for QR scanning."""
    return (f"otpauth://totp/{_urlquote(issuer)}:{_urlquote(email)}"
            f"?secret={secret}&issuer={_urlquote(issuer)}"
            f"&algorithm=SHA1&digits=6&period=30")


def _qr_svg(text: str, module_size: int = 6) -> str:
    """
    Generate a QR code as an SVG string — pure Python, zero dependencies.
    Returns an <svg>...</svg> string suitable for st.markdown(..., unsafe_allow_html=True).
    """
    # ── GF(256) arithmetic ────────────────────────────────────────────────────
    def _gf_setup():
        exp=[0]*512; log=[0]*256; x=1
        for i in range(255):
            exp[i]=x; log[x]=i; x<<=1
            if x&256: x^=285
        for i in range(255,512): exp[i]=exp[i-255]
        return exp,log
    _exp,_log=_gf_setup()
    def gm(a,b):
        return 0 if(a==0 or b==0) else _exp[(_log[a]+_log[b])%255]
    def rs_gen(n):
        p=[1]
        for i in range(n):
            r=[0]*(len(p)+1)
            for j,c in enumerate(p):
                r[j]^=gm(c,1); r[j+1]^=gm(c,_exp[i])
            p=r
        return p
    def rs_enc(data,nsym):
        g=rs_gen(nsym); msg=list(data)+[0]*nsym
        for i in range(len(data)):
            c=msg[i]
            if c:
                for j,gv in enumerate(g): msg[i+j]^=gm(gv,c)
        return msg[len(data):]

    # ── Version selection (byte mode, EC=M) ───────────────────────────────────
    import struct as _st
    raw=text.encode('utf-8'); n=len(raw)
    caps=[(1,14),(2,26),(3,36),(4,48),(5,60),(6,74),(7,84),(8,96),(9,108),(10,120)]
    version=next((v for v,cap in caps if n<=cap),10)
    sz=version*4+17
    ec_map={1:10,2:16,3:26,4:36,5:48,6:64,7:72,8:88,9:110,10:130}
    ec_sym=ec_map.get(version,26)

    # ── Alignment pattern positions ───────────────────────────────────────────
    ap_table={2:[(4,4)],3:[(4,4)],4:[(4,4),(4,16),(16,4),(16,16)],
              5:[(4,4),(4,16),(16,4),(16,16)],
              6:[(4,4),(4,16),(16,4),(16,16)],
              7:[(4,4),(4,20),(20,4),(20,20),(10,10),(10,20),(20,10)]}
    def align_pos(v): return ap_table.get(v,[])

    # ── Function module positions ─────────────────────────────────────────────
    def func_mods(size,version):
        m=set()
        for r in range(9):
            for c in range(9): m.add((r,c))
            for c in range(size-8,size): m.add((r,c))
        for r in range(size-8,size):
            for c in range(9): m.add((r,c))
        for i in range(8,size-8): m.add((6,i)); m.add((i,6))
        m.add((size-8,8))
        for r in range(9): m.add((8,r)); m.add((r,8))
        for c in range(size-8,size): m.add((8,c))
        for r in range(size-8,size): m.add((r,8))
        for (ar,ac) in align_pos(version):
            for dr in range(-2,3):
                for dc in range(-2,3): m.add((ar+dr,ac+dc))
        return m

    # ── Place function patterns ───────────────────────────────────────────────
    matrix=[[None]*sz for _ in range(sz)]
    def set_mod(r,c,v):
        if 0<=r<sz and 0<=c<sz: matrix[r][c]=v
    def finder(r0,c0):
        for dr in range(-1,8):
            for dc in range(-1,8):
                if 0<=dr<=6 and 0<=dc<=6:
                    v=(dr in(0,6) or dc in(0,6) or(2<=dr<=4 and 2<=dc<=4))
                else: v=False
                set_mod(r0+dr,c0+dc,v)
    finder(0,0); finder(0,sz-7); finder(sz-7,0)
    for i in range(8,sz-8):
        matrix[6][i]=(i%2==0); matrix[i][6]=(i%2==0)
    matrix[sz-8][8]=True
    for (ar,ac) in align_pos(version):
        for dr in range(-2,3):
            for dc in range(-2,3):
                r,c=ar+dr,ac+dc
                if matrix[r][c] is None:
                    matrix[r][c]=(dr in(-2,2) or dc in(-2,2) or(dr==0 and dc==0))

    # ── Data bits ─────────────────────────────────────────────────────────────
    bits=[0,1,0,0]
    for i in range(7,-1,-1): bits.append((n>>i)&1)
    for byte in raw:
        for i in range(7,-1,-1): bits.append((byte>>i)&1)
    bits+=[0,0,0,0]
    while len(bits)%8: bits.append(0)
    cws=[int(''.join(str(b) for b in bits[i:i+8]),2) for i in range(0,len(bits),8)]
    fm=func_mods(sz,version)
    data_capacity=(sz*sz-len(fm))//8
    pad=[0xEC,0x11]; pi=0
    while len(cws)<data_capacity-ec_sym: cws.append(pad[pi%2]); pi+=1
    ec=rs_enc(cws,ec_sym)
    final=cws+ec
    all_bits=[]
    for cw in final:
        for i in range(7,-1,-1): all_bits.append((cw>>i)&1)

    # ── Place data ────────────────────────────────────────────────────────────
    bi=0; col=sz-1
    while col>0:
        if col==6: col-=1
        for ri in range(sz):
            row=(sz-1-ri) if((sz-1-col)%2==0) else ri
            for dc in range(2):
                c=col-dc
                if matrix[row][c] is None:
                    matrix[row][c]=bool(all_bits[bi]) if bi<len(all_bits) else False
                    bi+=1
        col-=2

    # ── Best mask ─────────────────────────────────────────────────────────────
    mask_fns=[
        lambda r,c:(r+c)%2==0, lambda r,c:r%2==0,
        lambda r,c:c%3==0,     lambda r,c:(r+c)%3==0,
        lambda r,c:(r//2+c//3)%2==0,
        lambda r,c:(r*c)%2+(r*c)%3==0,
        lambda r,c:((r*c)%2+(r*c)%3)%2==0,
        lambda r,c:((r+c)%2+(r*c)%3)%2==0,
    ]
    def fmt_bits(mask_id):
        f=((0b01<<3)|mask_id)<<10
        for i in range(14,9,-1):
            if f&(1<<i): f^=0b10100110111<<(i-10)
        return (((0b01<<3)|mask_id)<<10|(f&0x3FF))^0b101010000010010
    def write_fmt(m,mask_id):
        fb=fmt_bits(mask_id)
        pos1=[(8,0),(8,1),(8,2),(8,3),(8,4),(8,5),(8,7),(8,8),
              (7,8),(5,8),(4,8),(3,8),(2,8),(1,8),(0,8)]
        for i,(_r,_c) in enumerate(pos1):
            if _r<sz and _c<sz: m[_r][_c]=bool((fb>>(14-i))&1)
        pos2=[(sz-1,8),(sz-2,8),(sz-3,8),(sz-4,8),(sz-5,8),(sz-6,8),(sz-7,8),
              (8,sz-8),(8,sz-7),(8,sz-6),(8,sz-5),(8,sz-4),(8,sz-3),(8,sz-2),(8,sz-1)]
        for i,(_r,_c) in enumerate(pos2):
            if _r<sz and _c<sz: m[_r][_c]=bool((fb>>(14-i))&1)
    def apply_mask(mask_id):
        fn=mask_fns[mask_id]; m=[row[:] for row in matrix]
        write_fmt(m,mask_id)
        for r in range(sz):
            for c in range(sz):
                if (r,c) not in fm and fn(r,c): m[r][c]=not m[r][c]
        return m
    def penalty(m):
        p=0
        for row in m:
            run=1
            for i in range(1,sz):
                if row[i]==row[i-1]: run+=1
                else:
                    if run>=5: p+=run-2
                    run=1
            if run>=5: p+=run-2
        for c in range(sz):
            run=1
            for r in range(1,sz):
                if m[r][c]==m[r-1][c]: run+=1
                else:
                    if run>=5: p+=run-2
                    run=1
            if run>=5: p+=run-2
        dark=sum(1 for r in range(sz) for c in range(sz) if m[r][c])
        p+=abs(dark*100//(sz*sz)-50)//5*10
        return p
    best=min(range(8),key=lambda i:penalty(apply_mask(i)))
    final_matrix=apply_mask(best)

    # ── Render SVG ────────────────────────────────────────────────────────────
    quiet=4; total=(sz+quiet*2)*module_size
    rects=[]
    for r,row in enumerate(final_matrix):
        for c,mod in enumerate(row):
            if mod:
                x=(c+quiet)*module_size; y=(r+quiet)*module_size
                rects.append(f'<rect x="{x}" y="{y}" width="{module_size}" height="{module_size}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
            f'style="width:200px;height:200px;display:block;background:white;border-radius:8px;">'
            f'<g fill="black">{"".join(rects)}</g></svg>')


def _mfa_get(username: str) -> dict | None:
    """Load MFA config for a user. Returns None if not set up."""
    _mfa_ensure_table()
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT totp_secret, is_enabled, is_verified,
                       backup_codes, enabled_at, last_used_at
                FROM mfa_config WHERE username = %s
            """, (username,))
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                return {
                    "secret":      row["totp_secret"] if isinstance(row, dict) else row[0],
                    "is_enabled":  row["is_enabled"]   if isinstance(row, dict) else row[1],
                    "is_verified": row["is_verified"]  if isinstance(row, dict) else row[2],
                    "backup_codes":list(row["backup_codes"] if isinstance(row, dict) else row[3]) if (row["backup_codes"] if isinstance(row, dict) else row[3]) else [],
                    "enabled_at":  str((row["enabled_at"]   if isinstance(row, dict) else row[4]) or "")[:10],
                    "last_used_at":str((row["last_used_at"] if isinstance(row, dict) else row[5]) or "")[:16],
                }
    except Exception as _exc:
        logger.warning("[_mfa_get] Failed to load MFA config for user — defaulting to no-MFA (user may bypass 2FA)", exc_info=_exc)
    return None


def _mfa_save(username: str, secret: str, is_enabled: bool,
               is_verified: bool, backup_codes: list = None):
    """Upsert MFA config for a user."""
    _mfa_ensure_table()
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO mfa_config
                    (username, totp_secret, is_enabled, is_verified,
                     backup_codes, enabled_at)
                VALUES (%s, %s, %s, %s, %s,
                        CASE WHEN %s THEN NOW() ELSE NULL END)
                ON CONFLICT (username) DO UPDATE SET
                    totp_secret  = EXCLUDED.totp_secret,
                    is_enabled   = EXCLUDED.is_enabled,
                    is_verified  = EXCLUDED.is_verified,
                    backup_codes = EXCLUDED.backup_codes,
                    enabled_at   = CASE WHEN EXCLUDED.is_enabled
                                        AND NOT mfa_config.is_enabled
                                        THEN NOW()
                                        ELSE mfa_config.enabled_at END
            """, (username, secret, is_enabled, is_verified,
                  backup_codes or [], is_enabled))
            cur.close(); _release_db_conn(conn)
            return True
    except Exception as _exc:
        logger.error("[_mfa_save] Failed to persist MFA secret — user MFA setup will be lost on next load", exc_info=_exc)
    return False


def _mfa_use_backup(username: str, code: str) -> bool:
    """
    Attempt to redeem a backup code. Removes it if valid (single-use).
    Returns True if the code was valid and consumed.
    """
    mfa = _mfa_get(username)
    if not mfa:
        return False
    codes = mfa.get("backup_codes", [])
    code_clean = code.strip().upper().replace(" ","")
    for i, bc in enumerate(codes):
        if _hmac.compare_digest(bc.replace("-",""), code_clean.replace("-","")):
            codes.pop(i)
            _mfa_ensure_table()
            try:
                conn = _get_db_conn()
                if conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE mfa_config SET backup_codes=%s WHERE username=%s",
                        (codes, username))
                    cur.close(); _release_db_conn(conn)
            except Exception as _exc:
                logger.error("[_mfa_use_backup] Failed to invalidate used backup code in DB — code may be reusable", exc_info=_exc)
            return True
    return False


def _mfa_mark_used(username: str):
    """Update last_used_at timestamp."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mfa_config SET last_used_at=NOW() WHERE username=%s",
                (username,))
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_mfa_mark_used] Failed to update last_used_at timestamp for MFA config", exc_info=_exc)


# ══════════════════════════════════════════════════════════════
#  FORGOT PASSWORD — Self-service reset with fallback chain:
#    1. Email OTP  (if user has email + SMTP configured)
#    2. TOTP authenticator  (if user has MFA enabled)
#    3. Contact admin  (if neither available)
# ══════════════════════════════════════════════════════════════

def _fp_ensure_table():
    """Create password_reset_otp table if it doesn't exist."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_otp (
                    id          SERIAL PRIMARY KEY,
                    username    VARCHAR(100) NOT NULL,
                    otp_hash    VARCHAR(200) NOT NULL,
                    expires_at  TIMESTAMPTZ NOT NULL,
                    used        BOOLEAN DEFAULT FALSE,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit(); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_fp_ensure_table] Suppressed exception", exc_info=_exc)


def _fp_lookup_user(username: str) -> dict | None:
    """
    Look up a user by username from local DB, uw_user table, then API.
    Returns dict with keys: username, email, has_mfa or None if not found.
    """
    _input = username.lower().strip()
    result = {"username": _input, "email": "", "has_mfa": False}

    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()

            # If input looks like an email, look up username from email first
            if "@" in _input:
                # Look up in uw_user by email
                try:
                    cur.execute(
                        "SELECT username, email FROM uw_user WHERE email=%s AND is_active=TRUE",
                        (_input,)
                    )
                    row = cur.fetchone()
                    if row:
                        result["username"] = row[0]
                        result["email"]    = row[1]
                        cur.close(); _release_db_conn(conn)
                        result["has_mfa"] = _mfa_required(result["username"])
                        return result
                except Exception as _exc:
                    logger.warning("[_fp_lookup_user] email lookup in uw_user failed", exc_info=_exc)
                # Also check platform_users_local by email
                cur.execute(
                    "SELECT username, email FROM platform_users_local WHERE email=%s AND is_active=TRUE",
                    (_input,)
                )
                row = cur.fetchone()
                if row:
                    result["username"] = row[0]
                    result["email"]    = row[1]
                    cur.close(); _release_db_conn(conn)
                    result["has_mfa"] = _mfa_required(result["username"])
                    return result
            else:
                # Username input — look up email
                # 1. Check platform_users_local
                cur.execute(
                    "SELECT email FROM platform_users_local WHERE username=%s AND is_active=TRUE",
                    (_input,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    result["email"] = row[0]
                    cur.close(); _release_db_conn(conn)
                    result["has_mfa"] = _mfa_required(_input)
                    return result

                # 2. Check uw_user table
                try:
                    cur.execute(
                        "SELECT email FROM uw_user WHERE username=%s AND is_active=TRUE",
                        (_input,)
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        result["email"] = row[0]
                        cur.close(); _release_db_conn(conn)
                        result["has_mfa"] = _mfa_required(_input)
                        return result
                except Exception as _exc:
                    logger.warning("[_fp_lookup_user] uw_user lookup failed", exc_info=_exc)

            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_fp_lookup_user] DB lookup failed", exc_info=_exc)

    # Set MFA status for whatever username we resolved
    result["has_mfa"] = _mfa_required(result["username"])

    # 3. Fallback — try backend API
    try:
        _tok = st.session_state.get("token", "")
        r = requests.get(
            f"{API_BASE}/auth/users/{_uname}",
            headers={"Authorization": f"Bearer {_tok}"},
            timeout=5
        )
        if r.status_code == 200:
            d = r.json()
            result["email"] = d.get("email", "")
            return result
    except Exception as _exc:
        logger.warning("[_fp_lookup_user] API lookup failed", exc_info=_exc)

    return result


def _fp_send_otp(username: str, email: str) -> tuple[bool, str]:
    """
    Generate a 6-digit OTP, store hashed in DB, and email it.
    Returns (success, message).
    """
    import hashlib as _hl, secrets as _sec, smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from datetime import datetime, timedelta, timezone

    _fp_ensure_table()

    # Generate OTP
    otp = str(_sec.randbelow(900000) + 100000)  # 100000–999999
    otp_hash = _hl.sha256(otp.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    # Store in DB (invalidate any prior unused OTPs for this user)
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE password_reset_otp SET used=TRUE WHERE username=%s AND used=FALSE",
                (username,)
            )
            cur.execute(
                "INSERT INTO password_reset_otp (username, otp_hash, expires_at) VALUES (%s,%s,%s)",
                (username, otp_hash, expires_at)
            )
            conn.commit(); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_fp_send_otp] DB error", exc_info=_exc)
        return False, "Could not generate reset token — database error."

    # Send email — always read fresh from DB (bypass session cache)
    st.session_state.pop("_smtp_config", None)
    smtp = _get_smtp_config()
    host      = smtp.get("host","")
    port      = int(smtp.get("port", 587))
    s_user    = smtp.get("username","")
    s_pass    = smtp.get("password","")
    from_email = smtp.get("from_email","")
    use_tls   = smtp.get("use_tls","true").lower() == "true"

    if not host or not from_email:
        return False, "SMTP_NOT_CONFIGURED"
    if not s_user:
        return False, "SMTP_NOT_CONFIGURED"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🔐 UW Platform — Password Reset OTP"
        msg["From"]    = f"UW Platform <{from_email}>"
        msg["To"]      = email

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;
                    border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc;">
          <div style="text-align:center;margin-bottom:24px;">
            <span style="font-size:2rem;">🛡️</span>
            <h2 style="color:#1e293b;margin:8px 0 4px;">UW Platform</h2>
            <p style="color:#64748b;margin:0;font-size:14px;">Password Reset Request</p>
          </div>
          <p style="color:#334155;font-size:15px;">
            You requested a password reset. Use the OTP below to proceed.
            This code expires in <strong>15 minutes</strong>.
          </p>
          <div style="text-align:center;margin:28px 0;">
            <div style="display:inline-block;background:#1e293b;color:#f1f5f9;
                        font-size:2.2rem;font-weight:700;letter-spacing:0.3rem;
                        padding:16px 36px;border-radius:10px;">
              {otp}
            </div>
          </div>
          <p style="color:#94a3b8;font-size:13px;text-align:center;">
            If you did not request this, ignore this email. Your password will not change.
          </p>
        </div>
        """
        msg.attach(MIMEText(html_body, "html"))

        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        if s_user and s_pass:
            server.login(s_user, s_pass)
        server.sendmail(from_email, email, msg.as_string())
        server.quit()
        return True, otp_hash  # return hash so we can verify later without re-querying

    except Exception as _exc:
        logger.error("[_fp_send_otp] Email send failed", exc_info=_exc)
        return False, f"Email send failed: {_exc}"


def _fp_verify_otp(username: str, otp_entered: str) -> bool:
    """Verify OTP — returns True if valid and not expired."""
    import hashlib as _hl
    from datetime import datetime, timezone
    otp_hash = _hl.sha256(otp_entered.strip().encode()).hexdigest()
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM password_reset_otp
                WHERE username=%s AND otp_hash=%s
                  AND used=FALSE AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
            """, (username, otp_hash))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE password_reset_otp SET used=TRUE WHERE id=%s", (row[0],))
                conn.commit()
            cur.close(); _release_db_conn(conn)
            return row is not None
    except Exception as _exc:
        logger.error("[_fp_verify_otp] DB error", exc_info=_exc)
    return False


def _fp_reset_password(username: str, new_password: str) -> tuple[bool, str]:
    """
    Reset the user's password in both local DB and backend API.
    Returns (success, message).
    """
    import hashlib as _hl
    pw_hash = _hl.sha256(new_password.encode()).hexdigest()
    _local_ok = False
    _api_ok   = False

    # Update local DB (platform_users_local + uw_user table)
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            # Update platform_users_local (case_manager, viewer)
            cur.execute(
                "UPDATE platform_users_local SET password_hash=%s WHERE username=%s",
                (pw_hash, username)
            )
            if cur.rowcount > 0:
                _local_ok = True
            # Also update uw_user table (admin, underwriter, super_admin)
            try:
                import bcrypt as _bcrypt
                _bc_hash = _bcrypt.hashpw(new_password.encode(), _bcrypt.gensalt()).decode()
                cur.execute(
                    "UPDATE uw_user SET hashed_password=%s, updated_at=NOW(), updated_by=%s WHERE username=%s",
                    (_bc_hash, "self_service_reset", username)
                )
                if cur.rowcount > 0:
                    _local_ok = True
            except Exception as _exc2:
                logger.warning("[_fp_reset_password] uw_user update failed", exc_info=_exc2)
            conn.commit(); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_fp_reset_password] Local DB error", exc_info=_exc)

    # Update backend API
    try:
        r = requests.post(
            f"{API_BASE}/auth/reset-password",
            json={"username": username, "new_password": new_password},
            timeout=8
        )
        _api_ok = r.status_code == 200
    except Exception as _exc:
        logger.warning("[_fp_reset_password] API update failed (may not support endpoint)", exc_info=_exc)

    if _local_ok or _api_ok:
        _log_audit("AUTH", "PASSWORD_RESET",
                   entity_type="USER", entity_id=username,
                   actor_username=username,
                   metadata={"method": "self_service_reset"})
        return True, "Password updated successfully."
    return False, "Could not update password — please contact your administrator."


def _render_forgot_password():
    """
    Forgot Password UI — renders inline on the login page.
    Fallback chain:
      1. Email OTP  → if user has email and SMTP is configured
      2. TOTP MFA   → if user has authenticator app enabled
      3. Admin reset → if neither available
    """
    st.markdown("#### 🔐 Reset Password")
    st.caption("Enter your username to begin the password reset process.")

    # ── Step state management ─────────────────────────────────
    fp_state = st.session_state.setdefault("_fp", {})
    step = fp_state.get("step", "username")  # username → method → otp/totp → newpw → done

    # ── STEP 1: Enter username ────────────────────────────────
    if step == "username":
        with st.form("fp_username_form"):
            fp_user = st.text_input("Username or Email",
                                    placeholder="e.g. vsch  or  vs.chakravarthi@yahoo.com",
                                    help="Enter your username or registered email address.")
            submitted = st.form_submit_button("Continue →", use_container_width=True, type="primary")
        if submitted:
            if not fp_user.strip():
                st.error("Please enter your username.")
            else:
                user_info = _fp_lookup_user(fp_user.strip())
                fp_state["username"]  = fp_user.strip().lower()
                fp_state["email"]     = user_info.get("email","") if user_info else ""
                fp_state["has_mfa"]   = user_info.get("has_mfa", False) if user_info else False

                smtp = _get_smtp_config()
                smtp_ready = bool(smtp.get("host") and smtp.get("from_email") and smtp.get("username"))
                fp_state["smtp_ready"] = smtp_ready

                has_email = bool(fp_state["email"])

                # Decide method
                if has_email and smtp_ready:
                    fp_state["method"] = "email"
                    ok, result = _fp_send_otp(fp_state["username"], fp_state["email"])
                    if ok:
                        # Only set step to otp_sent AFTER confirmed send
                        fp_state["step"] = "otp_sent"
                        st.session_state["_fp"] = fp_state
                        st.rerun()
                    else:
                        if result == "SMTP_NOT_CONFIGURED":
                            fp_state["method"] = "totp" if fp_state["has_mfa"] else "admin"
                            fp_state["step"]   = "totp" if fp_state["has_mfa"] else "admin"
                            st.session_state["_fp"] = fp_state
                            st.rerun()
                        else:
                            st.error(f"❌ Could not send OTP email: {result}")
                            st.info("💡 Tip: Check SMTP settings in System Config → Notifications.")
                elif fp_state["has_mfa"]:
                    fp_state["method"] = "totp"
                    fp_state["step"]   = "totp"
                else:
                    fp_state["method"] = "admin"
                    fp_state["step"]   = "admin"

                st.session_state["_fp"] = fp_state
                st.rerun()

    # ── STEP 2a: Email OTP verification ──────────────────────
    elif step == "otp_sent":
        masked_email = ""
        if fp_state.get("email"):
            parts = fp_state["email"].split("@")
            masked_email = parts[0][:2] + "***@" + parts[1] if len(parts) == 2 else "your email"
        st.success(f"✅ OTP sent to **{masked_email}**. Check your inbox (and spam folder).")
        st.info("Enter the 6-digit code below. It expires in 15 minutes.")

        with st.form("fp_otp_form"):
            otp_entered = st.text_input("Enter OTP", placeholder="e.g. 482916",
                                        max_chars=6, help="6-digit code from your email.")
            col1, col2 = st.columns(2)
            verify_btn = col1.form_submit_button("Verify OTP →", use_container_width=True, type="primary")
            resend_btn = col2.form_submit_button("Resend OTP", use_container_width=True)

        if verify_btn:
            if not otp_entered.strip().isdigit() or len(otp_entered.strip()) != 6:
                st.error("❌ Please enter a valid 6-digit OTP.")
            elif _fp_verify_otp(fp_state["username"], otp_entered.strip()):
                fp_state["step"] = "new_password"
                fp_state["verified"] = True
                st.session_state["_fp"] = fp_state
                st.rerun()
            else:
                st.error("❌ Invalid or expired OTP. Please try again or request a new code.")

        if resend_btn:
            ok, result = _fp_send_otp(fp_state["username"], fp_state["email"])
            if ok:
                st.success("✅ New OTP sent!")
            else:
                st.error(f"❌ Could not resend: {result}")

    # ── STEP 2b: TOTP authenticator verification ──────────────
    elif step == "totp":
        st.info("🔐 You don't have an email on file. Verify using your **authenticator app** instead.")
        with st.form("fp_totp_form"):
            totp_code = st.text_input("Authenticator Code", placeholder="6-digit code",
                                      max_chars=6, help="Open your authenticator app and enter the current code.")
            verify_btn = st.form_submit_button("Verify →", use_container_width=True, type="primary")
        if verify_btn:
            mfa_data = _mfa_get(fp_state["username"])
            if mfa_data and _mfa_verify(mfa_data["secret"], totp_code.strip()):
                fp_state["step"] = "new_password"
                fp_state["verified"] = True
                st.session_state["_fp"] = fp_state
                st.rerun()
            else:
                st.error("❌ Invalid code. Please check your authenticator app and try again.")

    # ── STEP 2c: Admin reset required ─────────────────────────
    elif step == "admin":
        st.warning(
            "⚠️ Your account has **no email address** and **no authenticator app** configured. "
            "Self-service reset is not available."
        )
        st.info(
            "👉 Please contact your **system administrator** to reset your password.\n\n"
            "Ask them to go to: **User Management → All Users → Reset Password**"
        )

    # ── STEP 3: Set new password ───────────────────────────────
    elif step == "new_password":
        st.success("✅ Identity verified. Please set your new password.")
        with st.form("fp_newpw_form"):
            new_pw  = st.text_input("New Password", type="password",
                                    placeholder="Min 8 characters",
                                    help="Minimum 8 characters.")
            new_pw2 = st.text_input("Confirm New Password", type="password",
                                    help="Must match the password above.")
            save_btn = st.form_submit_button("💾 Save New Password", use_container_width=True, type="primary")
        if save_btn:
            if len(new_pw) < 8:
                st.error("❌ Password must be at least 8 characters.")
            elif new_pw != new_pw2:
                st.error("❌ Passwords do not match.")
            else:
                ok, msg = _fp_reset_password(fp_state["username"], new_pw)
                if ok:
                    fp_state["step"] = "done"
                    st.session_state["_fp"] = fp_state
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

    # ── STEP 4: Done ───────────────────────────────────────────
    elif step == "done":
        st.success("🎉 Password reset successfully! You can now log in with your new password.")
        if st.button("← Back to Login", use_container_width=True, type="primary"):
            st.session_state.pop("_fp", None)
            st.session_state["_show_forgot"] = False
            st.rerun()
        return

    # ── Back to login link (all steps except done) ─────────────
    if st.button("← Back to Login", key="fp_back_btn"):
        st.session_state.pop("_fp", None)
        st.session_state["_show_forgot"] = False
        st.rerun()


def _mfa_required(username: str) -> bool:
    """Return True if MFA is fully enabled and verified for this user."""
    mfa = _mfa_get(username)
    return bool(mfa and mfa.get("is_enabled") and mfa.get("is_verified"))


def _ensure_login_attempts_table():
    """Track failed login attempts per username for brute-force protection."""
    pass  # table created by migrations/001_initial_schema.sql
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES    = 15

def _check_login_allowed(username: str) -> tuple:
    """
    Returns (allowed: bool, message: str).
    Blocks login if account is locked due to too many failed attempts.
    """
    _ensure_login_attempts_table()
    from datetime import datetime as _dtt, timezone as _tz
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT failed_count, locked_until
                FROM login_attempts WHERE username = %s
            """, (username,))
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                failed, locked_until = row
                if locked_until:
                    now = _dtt.now(_tz.utc)
                    if locked_until.tzinfo is None:
                        from datetime import timezone
                        locked_until = locked_until.replace(tzinfo=timezone.utc)
                    if now < locked_until:
                        remaining = int((locked_until - now).total_seconds() // 60) + 1
                        return False, (
                            f"Account temporarily locked after {MAX_LOGIN_ATTEMPTS} "
                            f"failed attempts. Try again in {remaining} minute(s)."
                        )
    except Exception as _exc:
        logger.debug("[_check_login_allowed] Suppressed exception", exc_info=_exc)
    return True, ""

def _record_login_failure(username: str):
    """Increment failed attempt counter; lock account after MAX_LOGIN_ATTEMPTS."""
    _ensure_login_attempts_table()
    from datetime import datetime as _dtt, timezone as _tz, timedelta as _tdd
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO login_attempts (username, failed_count, last_failed_at)
                VALUES (%s, 1, NOW())
                ON CONFLICT (username) DO UPDATE SET
                    failed_count   = login_attempts.failed_count + 1,
                    last_failed_at = NOW(),
                    locked_until   = CASE
                        WHEN login_attempts.failed_count + 1 >= %s
                        THEN NOW() + INTERVAL '%s minutes'
                        ELSE NULL END,
                    updated_at     = NOW()
            """, (username, MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES)); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_record_login_failure] Failed to record failed login attempt — brute-force protection may not increment correctly", exc_info=_exc)

def _record_login_success(username: str):
    """Clear failed attempt counter on successful login."""
    _ensure_login_attempts_table()
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO login_attempts (username, failed_count)
                VALUES (%s, 0)
                ON CONFLICT (username) DO UPDATE SET
                    failed_count  = 0,
                    locked_until  = NULL,
                    updated_at    = NOW()
            """, (username,)); cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_record_login_success] Failed to clear login failure counter after successful auth", exc_info=_exc)


def login(u, p):
    """
    Authenticate against the FastAPI backend exclusively.

    Strategy
    --------
    1. Submit (email, password) as supplied — the backend owns credential
       storage (bcrypt-hashed) and role assignment.
    2. If the backend returns a 401/403, authentication fails — no local
       fallback is attempted.  This is intentional: a local fallback would
       bypass backend-enforced password policies, MFA enforcement, and
       account-status checks.
    3. If the backend is unreachable (network error / timeout) a clear
       "service unavailable" message is surfaced instead of silently
       succeeding with a fake token.

    Returns
    -------
    str   — JWT access token on success.
    None  — authentication failure (wrong password, inactive account, etc.)
    tuple (None, str) — account locked due to brute-force protection.
    tuple (None, str) — backend unreachable (service unavailable message).
    """
    # Use full input as brute-force key (don't assume email prefix = username)
    _uname_bf = u.lower().strip()

    # Brute-force check — block before hitting the backend
    _allowed, _lock_msg = _check_login_allowed(_uname_bf)
    if not _allowed:
        return None, _lock_msg

    # Send exactly what the user typed — backend handles both username and email
    # Do NOT strip @domain — username can be different from email prefix (e.g. vsch vs vs.chakravarthi)
    username_for_api = u.strip()

    try:
        r = requests.post(
            f"{API_BASE}/auth/login",
            json={"username": username_for_api, "password": p},
            timeout=8,
        )

        if r.status_code == 200:
            data = r.json()
            # Role must come from the backend — never assumed client-side
            role = data.get("role") or data.get("user_role") or "underwriter"
            st.session_state.role = role
            _record_login_success(_uname_bf)
            _log_audit(
                "AUTH", "LOGIN_SUCCESS",
                entity_type="USER", entity_id=username_for_api,
                actor_username=username_for_api, actor_role=role,
                metadata={"method": "password", "email": u},
            )
            return data.get("access_token") or data.get("token") or data.get("access")

        if r.status_code in (401, 403):
            # Invalid credentials or disabled account — fail cleanly
            return None

        # Unexpected status (500, 503, …)
        return None, (
            f"Authentication service returned an unexpected status ({r.status_code}). "
            "Please contact your system administrator."
        )

    except requests.exceptions.ConnectionError:
        return None, (
            f"Cannot reach the authentication service at {API_BASE}. "
            "Ensure the UW Platform API is running and reachable, then try again."
        )
    except requests.exceptions.Timeout:
        return None, (
            "Authentication service timed out. "
            "The API may be overloaded — please try again in a moment."
        )
    except Exception as _exc:
        # Log unexpected errors but do not surface internal details to the UI
        import logging as _logging
        _logging.getLogger(__name__).exception("Unexpected error during login: %s", _exc)
        return None, "An unexpected error occurred during sign-in. Please try again."


def _load_all_products() -> tuple:
    """
    Returns (merged_products_dict, merged_categories_dict).
    Merges hardcoded PRODUCTS with any products stored in the DB/API.
    Result is cached in session state for the session.
    """
    cache_key = "all_products_merged"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    merged = dict(PRODUCTS)  # start with hardcoded
    merged_cats = {k: list(v) for k, v in PRODUCT_CATEGORIES.items()}

    # Try API first
    try:
        hdr = {"Authorization": f"Bearer {st.session_state.get('token','')}"}
        r = requests.get(f"{API_BASE}/products", headers=hdr, timeout=5)
        if r.status_code == 200:
            d = r.json()
            api_prods = d if isinstance(d, list) else d.get("products", d.get("items", []))
            for p in api_prods:
                code = p.get("product_code") or p.get("code")
                if not code or code in merged:
                    continue
                cat = p.get("category", "Other")
                merged[code] = {
                    "name":       p.get("product_name") or p.get("name") or code,
                    "category":   cat,
                    "sub_type":   p.get("product_type") or p.get("sub_type", ""),
                    "min_age":    p.get("min_age", 18),
                    "max_age":    p.get("max_age", 70),
                    "min_face":   p.get("min_face_amount") or p.get("min_face", 0),
                    "max_face":   p.get("max_face_amount") or p.get("max_face", 0),
                    "terms":      p.get("terms", []),
                    "uw_method":  p.get("uw_method", "Full UW"),
                    "exam_note":  p.get("exam_note", ""),
                    "notes":      p.get("description", ""),
                    "is_gi":      p.get("is_gi", False),
                }
                if cat not in merged_cats:
                    merged_cats[cat] = []
                if code not in merged_cats[cat]:
                    merged_cats[cat].append(code)
    except Exception as _exc:
        logger.debug("[_load_all_products] Suppressed exception", exc_info=_exc)

    # Also try direct DB if API missed anything
    try:
        _conn = _get_db_conn()
        if _conn:
            _cur = _conn.cursor()
            _cur.execute("""
                SELECT product_code, product_name, product_type,
                       COALESCE(category, 'Individual Life'),
                       min_age, max_age, min_face_amount, max_face_amount,
                       uw_method, exam_required, description,
                       is_guaranteed_issue
                FROM products ORDER BY product_code
            """)
            rows = _cur.fetchall()
            _cur.close()
            _release_db_conn(_conn)
            for row in rows:
                code = row[0]
                if code in merged:
                    continue  # already have it
                cat = row[3] or "Individual Life"
                merged[code] = {
                    "name":      row[1] or code,
                    "category":  cat,
                    "sub_type":  row[2] or "",
                    "min_age":   row[4] or 18,
                    "max_age":   row[5] or 70,
                    "min_face":  float(row[6] or 0),
                    "max_face":  float(row[7] or 0),
                    "terms":     [],
                    "uw_method": row[8] or "Full UW",
                    "exam_note": str(row[9] or ""),
                    "notes":     row[10] or "",
                    "is_gi":     bool(row[11] or False),
                }
                if cat not in merged_cats:
                    merged_cats[cat] = []
                if code not in merged_cats[cat]:
                    merged_cats[cat].append(code)
    except Exception as _exc:
        logger.debug("[_load_all_products] Suppressed exception", exc_info=_exc)

    st.session_state[cache_key] = (merged, merged_cats)
    return merged, merged_cats


def get_currency_symbol() -> str:
    """Return the configured currency symbol from session state, default $."""
    return st.session_state.get("currency_symbol", "$")


def _get_state_codes() -> list:
    """
    Load state/province codes from DB (state_codes table).
    Falls back to session_state cache, then US states as default.
    """
    _US_STATES = [
        "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
        "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
        "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
        "TX","UT","VT","VA","WA","WV","WI","WY"
    ]
    # Return from session cache first
    if "configured_state_codes" in st.session_state:
        return st.session_state["configured_state_codes"]
    # Try DB
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.close(); _release_db_conn(conn)
            if rows:
                codes = [r["state_code"] if isinstance(r, dict) else r[0] for r in rows]
                st.session_state["configured_state_codes"] = codes
                return codes
    except Exception as _exc:
        logger.warning("[_get_state_codes] Suppressed exception", exc_info=_exc)
    # Default to US states
    return _US_STATES


def get_currency_code() -> str:
    """Return the configured currency code from session state, default USD."""
    return st.session_state.get("currency_code", "USD")


def api_headers():
    return {"Authorization": f"Bearer {st.session_state.token}", "Content-Type": "application/json"}

def evaluate(payload):
    r = requests.post(f"{API_BASE}/underwriting/evaluate", json=payload, headers=api_headers(), timeout=10)
    return r.json(), r.status_code

def get_cases():
    """Fetch cases with full decision data from queue endpoint."""
    try:
        # Queue endpoint returns rich data: applicant_ref, outcome, risk_class, net_debit_points
        r = requests.get(f"{API_BASE}/queue/?page_size=100",
                         headers=api_headers(), timeout=8, allow_redirects=True)
        if r.status_code == 200:
            data = r.json()
            cases = data.get("cases", data.get("items", data if isinstance(data, list) else []))
            if cases:
                return cases
    except Exception as _exc:
        logger.debug("[get_cases] Suppressed exception", exc_info=_exc)
    # Fallback: basic cases endpoint
    try:
        r2 = requests.get(f"{API_BASE}/underwriting/cases?page_size=100",
                          headers=api_headers(), timeout=5)
        if r2.status_code == 200:
            return r2.json().get("cases", [])
    except Exception as _exc:
        logger.debug("[get_cases] Suppressed exception", exc_info=_exc)
    return []

def _get_db_conn():
    """
    Return a pooled database connection (backwards-compatible shim over db.pool).

    New code should use the context-manager form instead:
        from db.pool import get_cursor
        with get_cursor() as cur:
            cur.execute(...)

    Returns None if the pool cannot be reached (error is logged).
    Always call _release_db_conn(conn) in a finally block after use.
    """
    try:
        from db.pool import get_conn
        return get_conn(autocommit=True)
    except Exception as _exc:
        logger.error(
            "[_get_db_conn] Could not obtain DB connection from pool — "
            "check DATABASE_URL and that PostgreSQL is reachable",
            exc_info=_exc,
        )
        return None


def _release_db_conn(conn) -> None:
    """Return a pooled connection obtained via _get_db_conn()."""
    if conn is None:
        return
    try:
        from db.pool import release_conn
        release_conn(conn)
    except Exception as _exc:
        logger.warning("[_release_db_conn] Failed to release connection", exc_info=_exc)
        try:
            _release_db_conn(conn)
        except Exception as _exc:
            logger.debug("[_release_db_conn] _release_db_conn(conn) also failed — connection may be leaked", exc_info=_exc)


def _seed_product_error_codes():
    """
    Ensure product-related error codes exist in the DB.
    Called once on startup or first batch upload.
    """
    if st.session_state.get("_error_codes_seeded"):
        return
    try:
        conn = _get_db_conn()
        if not conn:
            return
        cur = conn.cursor()
        # Ensure error_codes table exists (may differ per installation)
        st.session_state["_error_codes_seeded"] = True
    except Exception as _exc:
        logger.warning("[_seed_product_error_codes] Suppressed exception", exc_info=_exc)


def validate_product_for_submission(product_code: str, age: int = None,
                                    face_amount: float = None) -> list:
    """
    Validate a product code before underwriting submission.
    Returns list of dicts: [{error_code, severity, message, resolution}]
    Empty list = all clear.
    """
    from datetime import date as _date_v
    errors = []

    if not product_code or not product_code.strip():
        errors.append({
            "error_code": "PROD_NOT_FOUND",
            "severity": "ERROR",
            "message": "No product_code provided. This field is mandatory.",
            "resolution": "Add product_code column with a valid product code (e.g. IND-TERM-20)."
        })
        return errors

    code = product_code.strip().upper()

    # Check if it looks like a product_type was supplied instead
    KNOWN_TYPES = {"INDIVIDUAL_TERM","INDIVIDUAL_UL","INDIVIDUAL_WL","INDIVIDUAL_FE",
                   "GROUP_TERM","GROUP_SUPP","KEY_PERSON","GUARANTEED_ISSUE"}
    if code in KNOWN_TYPES:
        errors.append({
            "error_code": "PROD_TYPE_INVALID",
            "severity": "ERROR",
            "message": f"'{code}' is a product type, not a product code. "
                       f"Use the specific product code (e.g. IND-TERM-20).",
            "resolution": "Replace product_type with product_code in your batch file. "
                          "Download the updated template."
        })
        return errors

    # Check hardcoded products first
    p = PRODUCTS.get(code)

    # Then check DB
    if not p:
        conn = _get_db_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT product_name, is_active, effective_date, expire_date,
                           min_age, max_age, min_face_amount, max_face_amount,
                           uw_method, is_guaranteed_issue
                    FROM products WHERE product_code = %s
                """, (code,))
                row = cur.fetchone()
                cur.close(); _release_db_conn(conn)
                if row:
                    today = _date_v.today()
                    p = {
                        "name":       row[0],
                        "is_active":  row[1],
                        "eff_date":   row[2],
                        "exp_date":   row[3],
                        "min_age":    row[4] or 0,
                        "max_age":    row[5] or 99,
                        "min_face":   float(row[6] or 0),
                        "max_face":   float(row[7] or 0),
                        "uw_method":  row[8] or "FULL_UW",
                        "is_gi":      bool(row[9]),
                    }
            except Exception as _exc:
                logger.debug("[validate_product_for_submission] Suppressed exception", exc_info=_exc)

    if not p:
        errors.append({
            "error_code": "PROD_NOT_FOUND",
            "severity": "ERROR",
            "message": f"Product code '{code}' does not exist in the system.",
            "resolution": "Check available products in Product Config or Batch Jobs → "
                          "Available Product Codes panel."
        })
        return errors

    today = _date_v.today()

    # Check is_active
    if not p.get("is_active", True):
        errors.append({
            "error_code": "PROD_INACTIVE",
            "severity": "ERROR",
            "message": f"Product '{code}' ({p.get('name','')}) is inactive and "
                       f"not available for new applications.",
            "resolution": "Contact your product manager to reactivate, or select an "
                          "alternative active product."
        })

    # Check effective date
    eff = p.get("eff_date") or p.get("effective_date")
    if eff:
        if hasattr(eff, 'date'):
            eff = eff.date()
        elif isinstance(eff, str):
            try:
                from datetime import datetime as _dt_v
                eff = _dt_v.fromisoformat(eff[:10]).date()
            except Exception as _exc:
                logger.debug("[validate_product_for_submission] Suppressed exception", exc_info=_exc)
                eff = None
        if eff and eff > today:
            errors.append({
                "error_code": "PROD_NOT_YET_EFFECTIVE",
                "severity": "WARNING",
                "message": f"Product '{code}' is not yet effective. "
                           f"Available from: {eff.strftime('%d %b %Y')}.",
                "resolution": "Wait until the effective date or select a currently active product."
            })

    # Check expiry date
    exp = p.get("exp_date") or p.get("expire_date")
    if exp:
        if hasattr(exp, 'date'):
            exp = exp.date()
        elif isinstance(exp, str):
            try:
                from datetime import datetime as _dt_v2
                exp = _dt_v2.fromisoformat(exp[:10]).date()
            except Exception as _exc:
                logger.debug("[validate_product_for_submission] Suppressed exception", exc_info=_exc)
                exp = None
        if exp and exp < today:
            errors.append({
                "error_code": "PROD_EXPIRED",
                "severity": "ERROR",
                "message": f"Product '{code}' ({p.get('name','')}) expired on "
                           f"{exp.strftime('%d %b %Y')} and is no longer available.",
                "resolution": "Select a currently active product. Check Product Config "
                              "for available products."
            })

    # Check age eligibility
    if age is not None:
        min_a = p.get("min_age", 0)
        max_a = p.get("max_age", 99)
        if not (min_a <= age <= max_a):
            errors.append({
                "error_code": "PROD_AGE_INELIGIBLE",
                "severity": "ERROR",
                "message": f"Age {age} is outside the eligible range for '{code}'. "
                           f"Product accepts ages {min_a}–{max_a}.",
                "resolution": f"Select a product that accepts age {age}, or verify the "
                              f"applicant's age."
            })

    # Check face amount eligibility
    if face_amount is not None:
        min_f = p.get("min_face", 0)
        max_f = p.get("max_face", float("inf"))
        sym = st.session_state.get("currency_symbol", "$")
        if face_amount < min_f or face_amount > max_f:
            errors.append({
                "error_code": "PROD_FACE_INELIGIBLE",
                "severity": "ERROR",
                "message": f"Face amount {sym}{face_amount:,.0f} is outside the range "
                           f"for '{code}' ({sym}{min_f:,.0f}–{sym}{max_f:,.0f}).",
                "resolution": f"Adjust the face amount or select a product that allows "
                              f"{sym}{face_amount:,.0f}."
            })

    # GI product with medical fields warning
    if p.get("is_gi") or p.get("uw_method","") in ("GUARANTEED_ISSUE","GI"):
        errors.append({
            "error_code": "PROD_UW_METHOD_MISMATCH",
            "severity": "WARNING",
            "message": f"'{code}' is a Guaranteed Issue product — no medical UW performed. "
                       f"Medical fields will be ignored.",
            "resolution": "If medical underwriting is required, select a Full UW product."
        })

    return errors


def check_eligibility(age, face_amount, product_code):
    # Try hardcoded dict first, then session-cached merged products, then DB
    p = PRODUCTS.get(product_code)
    if not p:
        cached = st.session_state.get("all_products_merged")
        if cached:
            p = cached[0].get(product_code)
    if not p:
        # Direct DB lookup as last resort
        try:
                _conn = _get_db_conn()
                if _conn:
                    _cur = _conn.cursor()
                _cur.execute("""
                    SELECT product_name, min_age, max_age, min_face_amount, max_face_amount
                    FROM products WHERE product_code = %s
                """, (product_code,))
                row = _cur.fetchone()
                _cur.close(); _release_db_conn(_conn)
                if row:
                    p = {"name": row[0], "min_age": row[1], "max_age": row[2],
                         "min_face": float(row[3] or 0), "max_face": float(row[4] or 0)}
        except Exception as _exc:
            logger.warning("[check_eligibility] Suppressed exception", exc_info=_exc)
    if not p:
        return []  # Unknown product — let engine decide
    errors = []
    if not (p["min_age"] <= age <= p["max_age"]):
        errors.append(f"Age {age} is outside eligibility for {p['name']}. Required: {p['min_age']}–{p['max_age']}.")
    if not (p["min_face"] <= face_amount <= p["max_face"]):
        sym = st.session_state.get("currency_symbol", "$")
        errors.append(f"Face amount {sym}{face_amount:,.0f} is outside range for {p['name']}. "
                      f"Allowed: {sym}{p['min_face']:,.0f}–{sym}{p['max_face']:,.0f}.")
    return errors


# ══════════════════════════════════════════════════════════════
#  FULL PAGE RENDER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _load_uw_rules(hdr: dict, product_code: str = "") -> list:
    """
    Load underwriting rules for the APS triggering rule dropdown.
    Tries multiple sources in order: rules_fired session cache,
    product-specific API, custom rules API, then DB direct query.
    Returns list of formatted strings: "RULE_ID — Rule Name"
    """
    rules = []

    # 1. Product-specific rules API (confirmed working in Product Config)
    if product_code and product_code not in ("—","UNKNOWN",""):
        try:
            r = requests.get(
                f"{API_BASE}/products/{product_code}/rules",
                headers=hdr, timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                items = (data if isinstance(data, list)
                         else data.get("rules", data.get("items", [])))
                for item in (items or []):
                    rid  = item.get("rule_id") or item.get("rule_code","")
                    name = item.get("rule_name") or rid
                    if rid:
                        rules.append(f"{rid} — {name}")
        except Exception as _exc:
            logger.debug("[_load_uw_rules] Suppressed exception", exc_info=_exc)

    # 2. Custom rules / rules builder API
    if not rules:
        for ep in ["/custom-rules", "/rules", "/rules/custom", "/custom_rules"]:
            try:
                r = requests.get(f"{API_BASE}{ep}", headers=hdr, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    items = (data if isinstance(data, list)
                             else data.get("rules", data.get("items", [])))
                    for item in (items or []):
                        rid  = (item.get("rule_code") or item.get("rule_id",""))
                        name = (item.get("rule_name") or item.get("name","") or rid)
                        if rid:
                            rules.append(f"{rid} — {name}")
                    if rules:
                        break
            except Exception as _exc:
                logger.debug("[_load_uw_rules] Suppressed exception", exc_info=_exc)
                continue

    # 3. DB fallback — product_rules table
    if not rules:
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                if product_code and product_code not in ("—","UNKNOWN",""):
                    cur.execute(
                        "SELECT rule_id FROM product_rules "
                        "WHERE product_code = %s ORDER BY rule_id",
                        (product_code,)
                    )
                else:
                    cur.execute(
                        "SELECT DISTINCT rule_id FROM product_rules ORDER BY rule_id"
                    )
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)
                rules = [row[0] for row in rows if row[0]]
        except Exception as _exc:
            logger.warning("[_load_uw_rules] Suppressed exception", exc_info=_exc)

    return rules


def render_uw_queue():
    """UW Case Queue — assignment, APS tracking, manual decisions, premium calc."""
    import pandas as pd
    st.markdown("## 📋 Underwriting Queue")
    st.caption("Manage referred cases, assign underwriters, track APS, calculate premiums.")

    # ── Manual auto-assign trigger (admin/senior_uw only) ─────────────────────
    if st.session_state.get("role","") in ("super_admin","admin","senior_underwriter"):
        with st.expander("🎯 Auto-assign unassigned cases", expanded=False):
            st.caption(
                "Assign all unassigned OPEN cases to eligible underwriters based on "
                "face amount authority limits. Uses load-balancing — UW with fewest "
                "active cases gets priority."
            )
            _aa_c1, _aa_c2, _aa_c3 = st.columns([2,1,2])
            _aa_sla  = _aa_c1.number_input(
                "SLA hours", min_value=1, max_value=240, value=48, step=8,
                key="aa_sla_hours",
                help="SLA deadline in hours from now for each assigned case."
            )
            _aa_all  = _aa_c2.checkbox(
                "All unassigned", value=True, key="aa_all",
                help="When checked, assigns all unassigned cases across all jobs. When unchecked, enter a job ID to limit scope."
            )
            _aa_job  = _aa_c3.text_input(
                "Job ID (optional)", placeholder="Leave blank for all",
                key="aa_job_id",
                help="Limit auto-assignment to cases from a specific batch job ID."
            ) if not _aa_all else ""
            _aa_route_med = st.checkbox(
                "🩺 Route medical cases to medical officers",
                value=True, key="aa_route_med",
                help="Medical cases (REQUEST_APS, exam required, APS pending) are routed to users flagged as Medical Officer first."
            )
            if st.button("🎯 Run Auto-Assignment Now", type="primary",
                         use_container_width=True, key="run_auto_assign"):
                with st.spinner("Assigning cases..."):
                    _aa_res = _auto_assign_referred_cases(
                        job_id=_aa_job.strip() or None,
                        sla_hours=int(_aa_sla),
                        route_medical=_aa_route_med,
                    )
                if _aa_res["assigned"] > 0:
                    _med_note = (f" ({_aa_res['medical_routed']} to medical officers)"
                                 if _aa_res.get("medical_routed", 0) > 0 else "")
                    st.success(f"✅ Assigned {_aa_res['assigned']} case(s){_med_note}.")
                if _aa_res["skipped"] > 0:
                    st.warning(f"⚠️ {_aa_res['skipped']} case(s) outside all authority limits — assign manually.")
                if _aa_res["errors"] > 0:
                    st.error(f"❌ {_aa_res['errors']} error(s) during assignment.")
                if _aa_res["details"]:
                    with st.expander("Details"):
                        for d in _aa_res["details"]:
                            st.caption(d)
                if not any([_aa_res["assigned"], _aa_res["skipped"], _aa_res["errors"]]):
                    st.info("No unassigned cases found.")

    tok = st.session_state.get("token", "")
    hdr = {"Authorization": f"Bearer {tok}"}

    # ── Role permissions for this page ───────────────────────────────────────
    _role        = st.session_state.get("role", "underwriter")
    _can_decide  = _role in ("super_admin","admin","senior_underwriter","underwriter")
    _can_assign  = _role in ("super_admin","admin","senior_underwriter")
    _can_override= _role in ("super_admin","admin","senior_underwriter")
    _view_only   = not _can_decide  # case_manager, viewer, auditor
    _my_uw_name  = st.session_state.get("username","")

    # ── Metrics row ───────────────────────────────────────────────────────────
    try:
        all_r  = requests.get(f"{API_BASE}/queue/", headers=hdr, timeout=5,
                              allow_redirects=True).json()
        open_r = requests.get(f"{API_BASE}/queue/?status=OPEN", headers=hdr,
                              timeout=5, allow_redirects=True).json()
        rev_r  = requests.get(f"{API_BASE}/queue/?status=IN_PROGRESS",
                              headers=hdr, timeout=5).json()
        all_cases  = all_r.get("cases", [])
        open_cases = open_r.get("cases", [])
        rev_cases  = rev_r.get("cases", [])
    except Exception as e:
        st.error(f"Queue API error: {e}")
        return

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Total Cases",  len(all_cases))
    c2.metric("Open",         len(open_cases), delta=len(open_cases),
              delta_color="inverse")
    c3.metric("In Progress",  len(rev_cases))
    c4.metric("APS Pending",  sum(c.get("aps_pending",0) for c in all_cases))
    c5.metric("SLA Breached", sum(1 for c in all_cases if c.get("sla_breached")),
              delta_color="inverse")

    st.divider()

    # ── Button-based tab nav (supports programmatic switching on rerun) ───────
    _UW_TABS = ["📋 Queue", "👤 Assign & Decide", "📋 APS Tracker",
                "💰 Premium Calculator", "🧠 AI APS Abstraction"]
    _uw_active = st.session_state.get("uw_active_tab", 0)
    _tb = st.columns(len(_UW_TABS))
    for _i, (_col, _name) in enumerate(zip(_tb, _UW_TABS)):
        if _col.button(_name, key=f"uwtab_{_i}", use_container_width=True,
                       type="primary" if _uw_active == _i else "secondary"):
            st.session_state["uw_active_tab"] = _i
            _uw_active = _i
            st.rerun()
    st.markdown("---")

    _show_queue   = (_uw_active == 0)
    _show_decide  = (_uw_active == 1)
    _show_aps     = (_uw_active == 2)
    _show_premium = (_uw_active == 3)
    _show_ai_aps  = (_uw_active == 4)

    # ══════════════════════════════════════════════════════════════
    #  TAB 1 — QUEUE
    # ══════════════════════════════════════════════════════════════
    if _show_queue:
        st.caption("All cases sorted by urgency. Click **Work this case** to open full details.")
        col1,col2,col3 = st.columns(3)
        f_status = col1.selectbox("Status filter",
                                  ["ALL","OPEN","IN_PROGRESS","APPROVED","DECLINED"],
                                  help="Filter queue to show only cases in the selected status. ALL shows every open and in-progress case.")
        f_rein   = col2.checkbox("Reinsurance required only",
                              help="Show only cases flagged for reinsurance, typically high face amount cases above the retention limit.")
        f_aps    = col3.checkbox("Has pending APS only",
                              help="Show only cases with at least one APS request still in PENDING or ORDERED status.")

        display = all_cases
        if f_status != "ALL":
            display = [c for c in display if c["status"] == f_status]
        if f_rein:
            display = [c for c in display if c.get("reinsurance_required")]
        if f_aps:
            display = [c for c in display if c.get("aps_pending", 0) > 0]

        if not display:
            st.info("No cases match the current filters.")
        else:
            for case in display:
                status_emoji = {
                    "OPEN":"🟡","IN_REVIEW":"🟠","APPROVED":"🟢",
                    "DECLINED":"🔴","POSTPONED":"⏸️"
                }.get(case["status"], "⚪")
                sla_txt = ""
                if case.get("sla_hours_remain") is not None:
                    h = case["sla_hours_remain"]
                    sla_txt = f" | ⏰ {h:.0f}h" if h > 0 else " | 🚨 SLA BREACHED"
                aps_txt  = (f" | 📋 {case['aps_pending']} APS"
                            if case.get("aps_pending") else "")
                rein_txt = " | 🏦 Reins." if case.get("reinsurance_required") else ""
                label = (
                    f"{status_emoji} {case['case_number']} | "
                    f"{case.get('age','?')}y {case.get('gender','?')} | "
                    f"{get_currency_symbol()}{case.get('face_amount',0):,.0f} | "
                    f"{case.get('product_code','?')}"
                    f"{sla_txt}{aps_txt}{rein_txt}"
                )
                with st.expander(label):
                    dc1,dc2,dc3,dc4 = st.columns(4)
                    dc1.metric("Status",     case["status"])
                    dc2.metric("Outcome",    case.get("outcome","Pending") or "Pending")
                    dc3.metric("Debits",     case.get("net_debit_points","—") or "—")
                    dc4.metric("Risk Class", case.get("risk_class","—") or "—")
                    if case.get("primary_reason"):
                        st.info(f"💬 {case['primary_reason']}")
                    if case.get("uw_notes"):
                        st.caption(f"🗒️ {case['uw_notes']}")
                    assigned = (case.get("assigned_uw_name")
                                or case.get("assigned_uw") or "Unassigned")
                    st.caption(
                        f"Assigned: {assigned} | "
                        f"Ref: {case.get('applicant_ref','—')} | "
                        f"State: {case.get('state','—')}"
                    )
                    if _can_decide:
                        if st.button("📂 Work this case →",
                                     key=f"work_{case['case_number']}",
                                     type="primary"):
                            st.session_state["working_case"]  = case
                            st.session_state["uw_active_tab"] = 1
                            # Clear any pending letter from a previous case
                            st.session_state.pop("_pending_letter", None)
                            st.rerun()
                    else:
                        st.caption("👁️ View only — your role cannot make decisions")

    # ══════════════════════════════════════════════════════════════
    #  TAB 2 — ASSIGN & DECIDE
    # ══════════════════════════════════════════════════════════════
    if _show_decide:

        # ── Show pending letter download if a decision was just recorded ──────
        _pending = st.session_state.get("_pending_letter")
        _current_working = st.session_state.get("working_case")
        # Auto-clear banner if a new case has been loaded (case_id changed)
        if _pending and _current_working:
            _pending_case_id = _pending.get("case_id","")
            _current_case_id = _current_working.get("id","")
            if _pending_case_id and _current_case_id and _pending_case_id != _current_case_id:
                st.session_state.pop("_pending_letter", None)
                _pending = None

        if _pending and not _current_working:
            # Show banner only when no new case is loaded yet
            _ldata = _pending
            _mime = "application/pdf" if _ldata["is_pdf"] else "text/html"
            _ext  = "PDF" if _ldata["is_pdf"] else "HTML"
            st.success(f"✅ Decision recorded: **{_ldata['outcome']}**")
            st.markdown("---")
            st.markdown("### 📄 Decision Letter Ready")
            st.info(
                "Your decision letter has been generated. "
                "Click below to download it. "
                "Select a new case from the Queue tab when you're done."
            )
            _dl_col, _cl_col = st.columns([3, 1])
            _dl_col.download_button(
                label=f"📥 Download Decision Letter ({_ext})",
                data=_ldata["bytes"],
                file_name=_ldata["filename"],
                mime=_mime,
                use_container_width=True,
                type="primary",
            )
            if _cl_col.button("✕ Dismiss", use_container_width=True):
                st.session_state.pop("_pending_letter", None)
                st.rerun()
            st.markdown("---")

        if _view_only:
            st.warning(
                f"👁️ **View only** — your role "
                f"(**{_role.replace('_',' ').title()}**) "
                f"can view cases but cannot make or assign decisions."
            )

        try:
            uw_r = requests.get(f"{API_BASE}/queue/underwriters",
                                headers=hdr, timeout=5).json()
            uw_list = uw_r.get("underwriters", [])
        except Exception as _exc:
            logger.debug("[render_uw_queue] Suppressed exception", exc_info=_exc)
            uw_list = []

        working = st.session_state.get("working_case")

        if not working:
            st.info("👈 Click **Work this case →** in the Queue tab, "
                    "or select one below.")
            _selectable = [c for c in all_cases
                           if c.get("status") not in ("APPROVED","DECLINED","CANCELLED")]
            if _selectable:
                _sel_opts = {
                    c["id"]: (
                        f"{c['case_number']} | "
                        f"{c.get('age','?')}y {c.get('gender','?')} | "
                        f"{get_currency_symbol()}{c.get('face_amount',0):,.0f} | "
                        f"{c.get('product_code','?')} | {c.get('status','?')}"
                    )
                    for c in _selectable
                }
                _picked = st.selectbox("Select case to view",
                                       list(_sel_opts.keys()),
                                       format_func=lambda k: _sel_opts[k],
                                       help="Pick a case from the queue to load its full details, decision, and APS status below.")
                if st.button("📂 Load Case", type="primary",
                             use_container_width=True):
                    st.session_state["working_case"] = next(
                        c for c in _selectable if c["id"] == _picked)
                    st.rerun()
        else:
            # ── Fetch enriched case detail ────────────────────────────────────
            _case_detail = dict(working)
            try:
                _cd_r = requests.get(f"{API_BASE}/queue/{working['id']}",
                                     headers=hdr, timeout=5)
                if _cd_r.status_code == 200:
                    _case_detail.update(_cd_r.json())
            except Exception as _exc:
                logger.debug("[render_uw_queue] Suppressed exception", exc_info=_exc)

            _rules_fired = _case_detail.get("rules_fired", [])
            if not _rules_fired:
                try:
                    _uw_r2 = requests.get(
                        f"{API_BASE}/underwriting/cases/{working['id']}",
                        headers=hdr, timeout=5)
                    if _uw_r2.status_code == 200:
                        _uw_data = _uw_r2.json()
                        _case_detail.update(_uw_data)
                        _rules_fired = _uw_data.get("rules_fired", [])
                except Exception as _exc:
                    logger.debug("[render_uw_queue] Suppressed exception", exc_info=_exc)

            if st.button("✕ Close / pick a different case",
                         key="close_working"):
                st.session_state.pop("working_case", None)
                st.rerun()

            # Outcome banner
            _oc = str(_case_detail.get("outcome","REFERRED")).upper()
            _outcome_colors = {
                "APPROVED":("#065f46","#d1fae5"),"DECLINED":("#7f1d1d","#fee2e2"),
                "REFERRED":("#78350f","#fef3c7"),"POSTPONED":("#1e1b4b","#e0e7ff"),
            }
            _bg, _fg = _outcome_colors.get(_oc, ("#374151","#f3f4f6"))
            _sla_txt = ""
            if _case_detail.get("sla_breached"):
                _sla_txt = " 🚨 SLA BREACHED"
            elif _case_detail.get("sla_hours_remain") is not None:
                _sla_txt = f" ⏰ {_case_detail['sla_hours_remain']:.0f}h remaining"
            st.markdown(
                f"<div style='padding:12px 16px;border-radius:8px;background:{_bg};"
                f"margin-bottom:12px;'>"
                f"<span style='font-size:17px;font-weight:700;color:{_fg};'>"
                f"📋 {_case_detail.get('case_number','—')}</span>"
                f"<span style='color:{_fg};font-size:12px;margin-left:14px;'>"
                f"{_oc}{_sla_txt}</span></div>",
                unsafe_allow_html=True
            )

            st.markdown("---")
            # SECTION 1 — Applicant Details
            st.markdown("### 👤 Applicant Details")
            _r1a,_r1b,_r1c = st.columns(3)
            _r1a.metric("Age",    _case_detail.get("age","—"))
            _r1b.metric("Gender", _case_detail.get("gender","—"))
            _r1c.metric("State",  _case_detail.get("state","—"))
            _r2a,_r2b,_r2c = st.columns(3)
            _fa = _case_detail.get("face_amount") or 0

            # ── Authority limit check ─────────────────────────────────────────
            if _can_decide and _my_uw_name and _role == "underwriter":
                _auth_ok, _auth_msg = _check_user_authority(
                    _my_uw_name, _fa,
                    _case_detail.get("product_code") or _case_detail.get("app_product_code","")
                )
                if not _auth_ok:
                    st.warning(
                        f"⚠️ **Authority limit:** {_auth_msg} "
                        f"This case should be reassigned to a senior underwriter."
                    )
            _r2a.metric("Face Amount",
                        f"{get_currency_symbol()}{_fa:,.0f}")
            _r2b.metric("Product", _case_detail.get("product_code","—") or "—")
            _r2c.metric("Tobacco", _case_detail.get("tobacco_status","—") or "—")

            _extra = [
                ("Occupation",    _case_detail.get("occupation_title")),
                ("Annual Income", f"{get_currency_symbol()}"
                                  f"{(_case_detail.get('annual_income') or 0):,.0f}"
                                  if _case_detail.get("annual_income") else None),
                ("Existing Cover",f"{get_currency_symbol()}"
                                  f"{(_case_detail.get('existing_coverage') or 0):,.0f}"
                                  if _case_detail.get("existing_coverage") else None),
                ("Term (yrs)",    _case_detail.get("coverage_term_yrs")),
                ("Height (in)",   _case_detail.get("height_inches")),
                ("Weight (lbs)",  _case_detail.get("weight_lbs")),
                ("SBP",           _case_detail.get("systolic_bp")),
                ("DBP",           _case_detail.get("diastolic_bp")),
                ("Diabetes",      _case_detail.get("diabetes_type")),
                ("Heart",         _case_detail.get("heart_condition")),
                ("Applicant Ref", _case_detail.get("applicant_ref")),
            ]
            _extra_clean = [(l,str(v)) for l,v in _extra
                            if v not in (None,"","NONE","none",0,"0")]
            if _extra_clean:
                with st.expander("📄 Full applicant data"):
                    for _i in range(0, len(_extra_clean), 3):
                        _ec = st.columns(3)
                        for _j,(_lbl,_val) in enumerate(_extra_clean[_i:_i+3]):
                            _ec[_j].metric(_lbl, _val)

            st.markdown("---")
            # SECTION 2 — Engine Decision
            st.markdown("### 🤖 Engine Decision")
            _e1,_e2,_e3,_e4 = st.columns(4)
            _e1.metric("Outcome",    _case_detail.get("outcome","—") or "—")
            _e2.metric("Risk Class", _case_detail.get("risk_class","—") or "—")
            _net_deb = _case_detail.get("net_debit_points") or 0
            _e3.metric("Net Debits", f"{_net_deb:+.0f}")
            _e4.metric("Pathway",
                       str(_case_detail.get("pathway","—") or "—").replace("_"," "))
            if _case_detail.get("primary_reason"):
                st.warning(
                    f"💬 **Refer reason:** {_case_detail['primary_reason']}")
            if _case_detail.get("adverse_action_text"):
                with st.expander("⚠️ Adverse action text"):
                    st.code(_case_detail["adverse_action_text"])

            st.markdown("---")
            # SECTION 3 — Rules Fired
            _rf_count = len(_rules_fired)
            st.markdown(
                f"### 📏 Rules Fired"
                f"{' (' + str(_rf_count) + ')' if _rf_count else ''}"
            )
            if _rules_fired:
                def _rule_card(f, bg, pts_color, pts_label):
                    st.markdown(
                        f"<div style='background:{bg};border-radius:6px;"
                        f"padding:10px 14px;margin-bottom:6px;'>"
                        f"<div style='display:flex;justify-content:space-between;"
                        f"align-items:flex-start;'>"
                        f"<div style='flex:1;'>"
                        f"<span style='font-family:monospace;font-size:11px;"
                        f"color:#6b7280;'>{f.get('rule_id','—')}</span>"
                        f"<span style='font-weight:600;font-size:13px;"
                        f"margin-left:8px;color:#111827;'>"
                        f"{f.get('rule_name','—')}</span>"
                        f"<div style='font-size:11px;color:#6b7280;margin-top:4px;"
                        f"line-height:1.4;'>"
                        f"{str(f.get('explanation',''))[:200]}</div>"
                        f"</div>"
                        f"<span style='font-weight:700;font-size:13px;"
                        f"color:{pts_color};white-space:nowrap;margin-left:12px;"
                        f"padding:2px 8px;border-radius:4px;"
                        f"background:rgba(0,0,0,0.06);'>"
                        f"{pts_label}</span>"
                        f"</div></div>",
                        unsafe_allow_html=True
                    )
                _hard   = [r for r in _rules_fired if r.get("hard_stop")]
                _debits = [r for r in _rules_fired
                           if (r.get("debit_points") or 0) > 0
                           and not r.get("hard_stop")]
                _fe     = [r for r in _rules_fired
                           if (r.get("flat_extra") or 0) > 0]
                _refers = [r for r in _rules_fired
                           if not r.get("hard_stop")
                           and (r.get("debit_points") or 0) == 0
                           and (r.get("credit_points") or 0) == 0
                           and (r.get("flat_extra") or 0) == 0]
                _creds  = [r for r in _rules_fired
                           if (r.get("credit_points") or 0) > 0]
                if _hard:
                    st.markdown("**🛑 Hard Stops**")
                    for f in _hard:
                        _rule_card(f,"#fef2f2","#dc2626","HARD STOP")
                if _debits:
                    st.markdown("**🔴 Debit Points**")
                    for f in _debits:
                        _rule_card(f,"#fff7ed","#ea580c",
                                   f"+{f.get('debit_points',0)} db")
                if _fe:
                    st.markdown("**🟠 Flat Extra**")
                    for f in _fe:
                        _rule_card(f,"#fff7ed","#ea580c",
                                   f"FE ${f.get('flat_extra',0)}/K")
                if _refers:
                    st.markdown("**🟡 Refer Triggers**")
                    for f in _refers:
                        _rule_card(f,"#fffbeb","#d97706","Refer")
                if _creds:
                    st.markdown("**🟢 Credits**")
                    for f in _creds:
                        _rule_card(f,"#f0fdf4","#16a34a",
                                   f"-{f.get('credit_points',0)} cr")
            else:
                st.caption("Rules breakdown not available from the engine for this case.")

            if _case_detail.get("uw_notes"):
                st.markdown("---")
                st.markdown("### 🗒️ Existing UW Notes")
                st.info(_case_detail["uw_notes"])

            # ── SECTION 4: Assign (senior_uw / admin / super_admin only) ──────
            st.markdown("---")
            if _can_assign:
                st.markdown("### 👤 Assign Case")
                with st.form("assign_form"):
                    uw_options = [f"{u['username']} ({u['active_cases']} active)"
                                  for u in uw_list]
                    _curr_uw = (_case_detail.get("assigned_uw_name")
                                or _case_detail.get("assigned_uw") or "")
                    _default_uw_idx = 0
                    if _curr_uw and uw_list:
                        _match = [i for i,u in enumerate(uw_list)
                                  if u["username"] == _curr_uw]
                        if _match:
                            _default_uw_idx = _match[0]
                    uw_sel = st.selectbox(
                        "Assign to underwriter",
                        uw_options if uw_options else ["No underwriters found"],
                        index=_default_uw_idx,
                        help=(
                            "The underwriter who will own and decide this case. "
                            "The number in brackets shows their current active "
                            "case load — use this to balance work fairly."
                        )
                    )
                    _a1,_a2 = st.columns(2)
                    sla_hrs = _a1.selectbox(
                        "SLA deadline",
                        [24,48,72,120], index=1,
                        format_func=lambda h: f"{h}h ({h//24}d)",
                        help=(
                            "Hours from now by which the underwriter must "
                            "complete their decision. Overdue cases are flagged "
                            "in red. 48h is standard; APS-pending cases may "
                            "need 72–120h."
                        )
                    )
                    assign_note = st.text_area(
                        "Note to underwriter", height=60,
                        help=(
                            "Internal note visible only to the assigned "
                            "underwriter — e.g. 'Prioritise — key account' or "
                            "'APS expected by 20 March'. Not shared with the "
                            "applicant."
                        )
                    )
                    if st.form_submit_button("👤 Assign", use_container_width=True):
                        uw_user_sel = next(
                            (u for u in uw_list
                             if uw_sel.startswith(u["username"])), None)
                        if uw_user_sel:
                            resp = requests.post(f"{API_BASE}/queue/assign",
                                headers=hdr, json={
                                    "case_id":     working["id"],
                                    "uw_username": uw_user_sel["username"],
                                    "sla_hours":   sla_hrs,
                                    "notes":       assign_note,
                                })
                            if resp.status_code == 200:
                                _log_audit("ASSIGNMENT","CASE_ASSIGNED",
                                    entity_type="CASE",
                                    entity_id=working["id"],
                                    entity_ref=working.get("case_number",""),
                                    before_state={"assigned_to": _case_detail.get("assigned_uw","")},
                                    after_state={"assigned_to": uw_user_sel["username"]},
                                    metadata={"note": assign_note})
                                st.success(
                                    f"✅ Assigned to {uw_user_sel['username']}")
                                # Notify the assigned underwriter
                                send_notification("CASE_ASSIGNED", {
                                    "case_number":   working.get("case_number", working.get("id","")),
                                    "applicant_ref": _case_detail.get("applicant_ref",""),
                                    "product_code":  _case_detail.get("product_code",""),
                                    "face_amount":   _case_detail.get("face_amount",""),
                                    "sla_hours":     sla_hrs,
                                    "assign_note":   assign_note or "",
                                    "uw_name":       (uw_user_sel.get("full_name") or
                                                     uw_user_sel.get("username","")),
                                }, extra_recipients=[
                                    uw_user_sel.get("email","")
                                ] if uw_user_sel.get("email") else [])
                                try:
                                    _ref = requests.get(
                                        f"{API_BASE}/queue/{working['id']}",
                                        headers=hdr, timeout=5)
                                    if _ref.status_code == 200:
                                        st.session_state["working_case"] = \
                                            _ref.json()
                                except Exception as _exc:
                                    logger.debug("[render_uw_queue] Suppressed exception", exc_info=_exc)
                                st.rerun()
                            else:
                                st.error(f"Error: {resp.text}")
                        else:
                            st.error("Please select a valid underwriter")
            else:
                st.info(
                    f"ℹ️ Case assignment requires **Senior Underwriter** role or above. "
                    f"Your role: **{_role.replace('_',' ').title()}**"
                )

            # ── SECTION 5: Record Decision ────────────────────────────────────
            st.markdown("---")
            if _can_decide:
                # For plain underwriter: can only decide their own assigned cases
                _assigned_to_me = False
                if _role == "underwriter":
                    _my_username = st.session_state.get("username","")
                    _assigned_uw = (_case_detail.get("assigned_uw_name")
                                    or _case_detail.get("assigned_uw",""))
                    _assigned_to_me = (_assigned_uw == _my_username)
                    if not _assigned_to_me and _my_username:
                        st.warning(
                            f"⚠️ This case is assigned to **{_assigned_uw or 'someone else'}**. "
                            f"Underwriters can only decide their own assigned cases. "
                            f"Contact a Senior Underwriter to reassign."
                        )

                _decision_allowed = (_role in ("super_admin","admin","senior_underwriter")
                                     or (_role == "underwriter" and _assigned_to_me)
                                     or (_role == "underwriter" and not _assigned_to_me
                                         and not st.session_state.get("username","")))

                if _decision_allowed:
                    st.markdown("### ✅ Record Decision")
                    st.caption(
                        f"Case **{_case_detail.get('case_number','—')}** | "
                        f"Engine: **{_case_detail.get('outcome','—') or '—'}** | "
                        f"Assigned: **{_case_detail.get('assigned_uw_name') or 'Unassigned'}**"
                    )
                    with st.form("decide_form"):
                        new_outcome = st.selectbox(
                            "Your Decision *",
                            ["APPROVED","DECLINED","POSTPONED",
                             "COUNTER_OFFER","REQUEST_APS"],
                            help=(
                                "APPROVED — Issue policy at stated terms\n"
                                "DECLINED — Reject application\n"
                                "POSTPONED — Defer 6–12 months\n"
                                "COUNTER_OFFER — Approve at modified terms\n"
                                "REQUEST_APS — Need physician records first"
                            )
                        )
                        # Risk class override only for senior+
                        if _can_override:
                            decision_risk_class = st.selectbox(
                                "Risk Class Override",
                                ["(keep engine result)","PREFERRED_PLUS","PREFERRED",
                                 "STANDARD_PLUS","STANDARD","SUBSTANDARD"],
                                help=(
                                    "Override the risk class assigned by the rules "
                                    "engine. Use this when the engine's assessment "
                                    "doesn't match the full clinical picture after "
                                    "reviewing the APS or additional evidence.\n\n"
                                    "**PREFERRED_PLUS** — Best rates, clean history\n"
                                    "**PREFERRED** — Minor impairments, good health\n"
                                    "**STANDARD_PLUS** — Slight elevation in risk\n"
                                    "**STANDARD** — Average risk profile\n"
                                    "**SUBSTANDARD** — Rated case, extra premium applies"
                                )
                            )
                        else:
                            decision_risk_class = "(keep engine result)"
                            st.caption(
                                "ℹ️ Risk class override requires Senior Underwriter role.")

                        decision_reason = st.text_area(
                            "Reason / Justification *", height=90,
                            placeholder=(
                                "e.g. BP within acceptable range, no organ damage. "
                                "Approving at Standard class."
                            ),
                            help=(
                                "Mandatory justification for your decision. "
                                "This is stored permanently in the audit trail and "
                                "used verbatim in the adverse action notice sent to "
                                "the applicant if declined. Be specific about which "
                                "evidence supports the decision."
                            )
                        )
                        uw_notes_d = st.text_area(
                            "Internal UW Notes", height=60,
                            placeholder="File documentation only — not shared with applicant",
                            help=(
                                "Internal underwriter file notes — visible to other "
                                "underwriters and managers reviewing the case, but "
                                "never included in applicant communications. Use for "
                                "clinical observations, APS summary, or escalation notes."
                            )
                        )
                        from datetime import date as _date
                        _dq1,_dq2 = st.columns(2)
                        dec_eff = _dq1.date_input(
                            "Effective Date",
                            value=_date.today(),
                            help=(
                                "Date this decision takes effect — defaults to today. "
                                "The policy effective date may differ from this if "
                                "there's an underwriting delay."
                            )
                        )
                        dec_exp = _dq2.date_input(
                            "Expire Date",
                            value=None,
                            help=(
                                "For POSTPONED or conditional decisions — the date "
                                "the decision lapses and the applicant must reapply. "
                                "Typically 6–12 months for postponements. Leave blank "
                                "for standard approvals and declines."
                            )
                        )
                        _btn_labels = {
                            "APPROVED":      "✅ Approve Case",
                            "DECLINED":      "❌ Decline Case",
                            "POSTPONED":     "⏸ Postpone Case",
                            "COUNTER_OFFER": "🔄 Record Counter Offer",
                            "REQUEST_APS":   "📋 Request APS & Pend Case",
                        }

                        # ── Letter dispatch ───────────────────────────────────
                        st.markdown("**📧 Letter Dispatch**")
                        _el1, _el2 = st.columns(2)
                        applicant_email = _el1.text_input(
                            "Applicant Email",
                            value=_case_detail.get("applicant_email","") or "",
                            placeholder="applicant@email.com",
                            help="Email to send the decision letter to. Requires SMTP in System Config > API Keys."
                        )
                        applicant_name = _el2.text_input(
                            "Applicant Name",
                            value=(_case_detail.get("applicant_name","") or
                                   _case_detail.get("applicant_ref","") or ""),
                            placeholder="e.g. Ravi Kumar",
                            help="Used in the letter salutation."
                        )
                        send_email_flag = st.checkbox(
                            "📤 Send decision letter by email",
                            value=bool(_case_detail.get("applicant_email","")),
                            help="Auto-email the letter PDF on submit. Requires valid email + SMTP configured."
                        )

                        if st.form_submit_button(
                            _btn_labels.get(new_outcome, "✅ Record Decision"),
                            use_container_width=True, type="primary"
                        ):
                            if not decision_reason.strip():
                                st.error("Reason / Justification is required")
                            else:
                                _payload = {
                                    "case_id":        working["id"],
                                    "new_outcome":    new_outcome,
                                    "reason":         decision_reason,
                                    "notes":          uw_notes_d,
                                    "effective_date": str(dec_eff) if dec_eff else None,
                                    "expire_date":    str(dec_exp) if dec_exp else None,
                                }
                                if decision_risk_class != "(keep engine result)":
                                    _payload["risk_class"] = decision_risk_class
                                resp = requests.post(
                                    f"{API_BASE}/queue/decide",
                                    headers=hdr, json=_payload)
                                if resp.status_code == 200:
                                    st.success(f"✅ Decision recorded: **{new_outcome}**")

                                    # Queue for policy admin export
                                    _queue_for_policy_admin({
                                        "applicant_ref":   _case_detail.get("applicant_ref",""),
                                        "applicant_name":  applicant_name.strip(),
                                        "applicant_email": applicant_email.strip(),
                                        "case_id":         working.get("id",""),
                                        "product_code":    _case_detail.get("product_code",""),
                                        "face_amount":     _case_detail.get("face_amount"),
                                        "age":             _case_detail.get("age"),
                                        "gender":          _case_detail.get("gender",""),
                                        "state":           _case_detail.get("state",""),
                                        "outcome":         new_outcome,
                                        "risk_class":      (
                                            decision_risk_class
                                            if decision_risk_class != "(keep engine result)"
                                            else _case_detail.get("risk_class","")
                                        ),
                                        "net_debit_points": _case_detail.get("net_debit_points"),
                                        "effective_date":   str(dec_eff) if dec_eff else None,
                                        "expire_date":      str(dec_exp) if dec_exp else None,
                                        "reason":           decision_reason,
                                    }, source="ONLINE")

                                    # Notify supervisors / configured recipients
                                    send_notification("DECISION_RECORDED", {
                                        "case_number":   working.get("case_number", working.get("id","")),
                                        "applicant_ref": _case_detail.get("applicant_ref",""),
                                        "outcome":       new_outcome,
                                        "risk_class":    (
                                            decision_risk_class
                                            if decision_risk_class != "(keep engine result)"
                                            else _case_detail.get("risk_class","")
                                        ),
                                        "decided_by":    st.session_state.get("username",""),
                                        "reason":        decision_reason,
                                    })

                                    # ── Generate letter ───────────────────────
                                    _lbytes = None
                                    _lfname = None
                                    _is_pdf = False
                                    try:
                                        from datetime import date as _dl
                                        _dec_resp = resp.json()
                                        _r_pdf = {
                                            "outcome": new_outcome,
                                            "risk_class": (
                                                decision_risk_class
                                                if decision_risk_class != "(keep engine result)"
                                                else _case_detail.get("risk_class","")
                                            ),
                                            "net_debit_points": _case_detail.get("net_debit_points",0) or 0,
                                            "application_id": str(_case_detail.get("applicant_ref", working.get("id","")))[:12],
                                            "case_id": working.get("id",""),
                                            "decision_id": (_dec_resp.get("decision_id", working.get("id","")) if isinstance(_dec_resp, dict) else working.get("id","")),
                                            "rules_version": _case_detail.get("rules_version","-"),
                                            "evaluated_at": str(_dl.today()),
                                            "pathway": _case_detail.get("pathway","MANUAL"),
                                            "is_stp": False,
                                            "adverse_action_text": decision_reason if "DECLIN" in new_outcome else "",
                                            "rules_fired": _case_detail.get("rules_fired",[]),
                                            "primary_reason": decision_reason,
                                            "policy_effective_date": str(dec_eff) if dec_eff else "",
                                            "policy_expire_date": str(dec_exp) if dec_exp else "",
                                        }
                                        _prod_pdf = st.session_state.get("last_product") or {}
                                        if not _prod_pdf:
                                            _pc = _case_detail.get("product_code","")
                                            _prod_pdf = {"name": _pc or "Life Insurance", "product_code": _pc}
                                            try:
                                                _all_prods, _ = _load_all_products()
                                                if _pc and _pc in _all_prods:
                                                    _prod_pdf = _all_prods[_pc]
                                            except Exception as _exc:
                                                logger.debug("[render_uw_queue] Suppressed exception", exc_info=_exc)
                                        _lbytes, _lfname = get_pdf_download_data(_r_pdf, _prod_pdf)
                                        _is_pdf = _lfname.endswith(".pdf")
                                    except Exception as _pe:
                                        st.warning(f"Letter generation failed: {_pe}")

                                    # ── Email OR Download — mutually exclusive ──
                                    _email_sent_ok = False
                                    if send_email_flag:
                                        if not applicant_email.strip():
                                            st.warning("No email address provided.")
                                        elif _lbytes is None:
                                            st.warning("Letter generation failed — email not sent.")
                                        else:
                                            _ok, _msg = send_decision_email(
                                                to_email=applicant_email.strip(),
                                                applicant_name=applicant_name.strip(),
                                                outcome=new_outcome,
                                                case_number=_case_detail.get("case_number", working.get("id","")),
                                                reason=decision_reason,
                                                letter_bytes=_lbytes,
                                                letter_filename=_lfname,
                                                is_pdf=_is_pdf,
                                            )
                                            if _ok:
                                                st.success(f"📧 Letter emailed to **{applicant_email.strip()}**")
                                                _email_sent_ok = True
                                            else:
                                                st.error(f"Email failed: {_msg}")

                                    # Store letter in session state for download banner
                                    # (download_button cannot render inside st.form —
                                    #  the banner at the TOP of this tab renders it after rerun)
                                    if _lbytes is not None and not _email_sent_ok:
                                        st.session_state["_pending_letter"] = {
                                            "bytes": _lbytes,
                                            "filename": _lfname,
                                            "is_pdf": _is_pdf,
                                            "outcome": new_outcome,
                                            "case_id": working.get("id",""),
                                        }
                                    else:
                                        st.session_state.pop("_pending_letter", None)

                                    st.session_state.pop("working_case", None)
                                    st.rerun()
                                else:
                                    st.error(f"Error: {resp.text}")
            else:
                st.info(
                    f"👁️ **View only** — your role "
                    f"(**{_role.replace('_',' ').title()}**) "
                    f"cannot record decisions."
                )

            # ── SECTION 6: Quick APS (any role that can decide) ──────────────
            if _can_decide:
                st.markdown("---")
                with st.expander("📋 Quick APS Request"):
                    # Build rule dropdown
                    _product_code = _case_detail.get("product_code","")
                    _aps_rule_opts = ["— select triggering rule —"]
                    _fired_opts = [
                        f"{r.get('rule_id','?')} — {r.get('rule_name', r.get('rule_id','?'))}"
                        for r in _rules_fired
                        if r.get("rule_id") or r.get("rule_name")
                    ]
                    if _fired_opts:
                        _aps_rule_opts += _fired_opts
                    else:
                        _loaded = _load_uw_rules(hdr, _product_code)
                        if _loaded:
                            _aps_rule_opts += _loaded
                    _aps_rule_opts.append("✏️ Enter manually…")

                    # Load physician registry for dropdown
                    _phy_list = _load_physicians()
                    _phy_opts = ["— type to search or select —"] + [
                        f"{p['physician_name']}"
                        + (f" ({p['specialisation']})" if p.get('specialisation') else "")
                        + (f" — {p['city']}" if p.get('city') else "")
                        for p in _phy_list
                    ]
                    _phy_opts.append("✏️ Enter manually…")

                    # ── Physician selector OUTSIDE the form so selection triggers rerun ──
                    st.markdown("**Physician**")
                    _phy_sel_idx = st.selectbox(
                        "Select from registry",
                        range(len(_phy_opts)),
                        format_func=lambda i: _phy_opts[i],
                        key="quick_aps_phy_sel",
                        help="Select a registered physician — name, phone, email fill automatically."
                    )
                    _phy_sel_label = _phy_opts[_phy_sel_idx]
                    _phy_rec = None
                    if _phy_sel_idx > 0 and _phy_sel_label != "✏️ Enter manually…":
                        _phy_rec = _phy_list[_phy_sel_idx - 1]

                    with st.form("quick_aps_form"):
                        aps_rule_sel = st.selectbox(
                            "Triggering Rule *", _aps_rule_opts,
                            help="The rule that caused the referral — tells the physician what records are needed."
                        )
                        aps_rule_manual = ""
                        if aps_rule_sel == "✏️ Enter manually…":
                            aps_rule_manual = st.text_input(
                                "Rule name / code (manual)",
                                placeholder="e.g. R021B — MI Timed Rating",
                                help="Enter the rule ID or name that triggered this APS requirement. Printed on the APS request letter sent to the physician."
                            )
                        aps_rule = (aps_rule_manual
                                    if aps_rule_sel == "✏️ Enter manually…"
                                    else ("" if aps_rule_sel.startswith("—")
                                          else aps_rule_sel))

                        # Physician fields — pre-filled from registry selection above
                        _qa1, _qa2 = st.columns(2)
                        aps_phys = _qa1.text_input(
                            "Physician Name *",
                            value=_phy_rec["physician_name"] if _phy_rec else "",
                            placeholder="Dr. Full Name",
                            disabled=bool(_phy_rec),
                            help="Pre-filled when a physician is selected above."
                        )
                        aps_phone = _qa2.text_input(
                            "Physician Phone",
                            value=_phy_rec["phone"] if _phy_rec else "",
                            disabled=bool(_phy_rec),
                            help="Phone number for the physician's clinic. Pre-filled when selected from the Physician Registry.",
                            placeholder="+91 98765 43210"
                        )
                        aps_email = st.text_input(
                            "Physician Email *",
                            value=_phy_rec["email"] if _phy_rec else "",
                            disabled=bool(_phy_rec),
                            placeholder="doctor@clinic.com",
                            help="APS request letter will be emailed here."
                        )
                        send_to_physician = st.checkbox(
                            "📧 Send APS request letter to physician by email",
                            value=bool(_phy_rec and _phy_rec.get("email")),
                            help="Emails a formal APS request letter to the physician."
                        )

                        from datetime import date as _date2, timedelta as _td2
                        aps_due = st.date_input(
                            "APS Due Date",
                            value=_date2.today() + _td2(days=30),
                            help="Standard is 30 days. Complex cases may need 60."
                        )
                        if st.form_submit_button("📤 Request APS", use_container_width=True):
                            _phys_email_q  = _phy_rec["email"] if _phy_rec else aps_email.strip()
                            _phys_phone_q  = _phy_rec["phone"] if _phy_rec else aps_phone.strip()
                            _phys_name_q   = _phy_rec["physician_name"] if _phy_rec else aps_phys.strip()
                            if not _phys_name_q:
                                st.error("Physician Name is required")
                            elif send_to_physician and not _phys_email_q:
                                st.error("Physician Email is required when 'Send to physician' is ticked")
                            else:
                                # Only send fields the backend API accepts
                                # physician_email/address stored locally, not sent to API
                                _api_payload_q = {
                                    "case_id":         working["id"],
                                    "application_id":  _case_detail.get("application_id",""),
                                    "rule_name":       aps_rule,
                                    "physician_name":  _phys_name_q,
                                    "due_date":        str(aps_due),
                                }
                                # Add phone only if backend may accept it
                                if _phys_phone_q:
                                    _api_payload_q["physician_phone"] = _phys_phone_q

                                _aps_case_ref = working.get("case_number", working.get("id",""))
                                resp = requests.post(
                                    f"{API_BASE}/queue/aps/request",
                                    headers=hdr, json={
                                        "case_id":         str(working["id"]),
                                        "application_id":  str(_case_detail.get("application_id","") or ""),
                                        "rule_name":       str(aps_rule or ""),
                                        "physician_name":  str(_phys_name_q or ""),
                                        "physician_phone": str(_phys_phone_q or ""),
                                        "due_date":        str(aps_due),
                                    })
                                if resp.status_code == 200:
                                    st.success("✅ APS requested")
                                    # Send email to physician using locally held email
                                    if send_to_physician and _phys_email_q:
                                        _ok_p, _msg_p = send_aps_request_to_physician(
                                            physician_email=_phys_email_q,
                                            physician_name=_phys_name_q,
                                            applicant_name=_case_detail.get("applicant_ref",""),
                                            applicant_ref=_case_detail.get("applicant_ref",""),
                                            case_number=working.get("case_number", working.get("id","")),
                                            rule_name=aps_rule,
                                            due_date=str(aps_due),
                                        )
                                        if _ok_p:
                                            st.success(f"📧 {_msg_p}")
                                        else:
                                            st.warning(f"APS recorded but email failed: {_msg_p}")
                                    # Notify internal team
                                    send_notification("APS_REQUESTED", {
                                        "case_number":    working.get("case_number", working.get("id","")),
                                        "applicant_ref":  _case_detail.get("applicant_ref",""),
                                        "rule_name":      aps_rule or "",
                                        "physician_name": _phys_name_q,
                                        "due_date":       str(aps_due),
                                    })
                                else:
                                    st.error(f"Error: {resp.text}")

    # ══════════════════════════════════════════════════════════════
    #  TAB 3 — APS TRACKER
    # ══════════════════════════════════════════════════════════════
    if _show_aps:
        st.caption("Track Attending Physician Statement requests per case.")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Request APS**")

            # Load rules
            _working_for_aps = st.session_state.get("working_case", {})
            _aps_prod = _working_for_aps.get("product_code","")
            _aps_tracker_rule_opts = ["— select triggering rule —"]
            _tracker_rules = _load_uw_rules(hdr, _aps_prod)
            if _tracker_rules:
                _aps_tracker_rule_opts += _tracker_rules
            _aps_tracker_rule_opts.append("✏️ Enter manually…")

            # Load physician registry
            _phy_list_t = _load_physicians()
            _phy_opts_t = ["— select from registry —"] + [
                f"{p['physician_name']}"
                + (f" ({p['specialisation']})" if p.get('specialisation') else "")
                + (f" — {p['city']}" if p.get('city') else "")
                for p in _phy_list_t
            ]
            _phy_opts_t.append("✏️ Enter manually…")

            # ── Physician selector OUTSIDE the form so changing it triggers rerun ──
            st.markdown("**Physician**")
            _phy_t_sel_idx = st.selectbox(
                "Select from registry",
                range(len(_phy_opts_t)),
                format_func=lambda i: _phy_opts_t[i],
                key="aps_tracker_phy_sel",
                help="Select a registered physician — name, phone, email and address fill automatically below."
            )
            _phy_t_label = _phy_opts_t[_phy_t_sel_idx]
            _phy_t_rec = None
            if _phy_t_sel_idx > 0 and _phy_t_label != "✏️ Enter manually…":
                _phy_t_rec = _phy_list_t[_phy_t_sel_idx - 1]

            with st.form("aps_req_form"):
                working = st.session_state.get("working_case")
                aps_case_id = st.text_input(
                    "Case ID",
                    value=working["id"] if working else "",
                    help="UUID of the UW Queue case. Pre-filled from Assign & Decide tab."
                )
                aps_app_id = st.text_input("Application ID", value="",
                    help="Original UW application ID for cross-referencing.")

                aps_rule_sel_t = st.selectbox(
                    "Triggering Rule", _aps_tracker_rule_opts,
                    help="Rule requiring APS evidence. Choose '✏️ Enter manually…' if not listed."
                )
                aps_rule_manual_t = ""
                if aps_rule_sel_t == "✏️ Enter manually…":
                    aps_rule_manual_t = st.text_input(
                        "Rule name / code (manual)",
                        placeholder="e.g. R021B — MI Timed Rating",
                        help="Enter the rule ID or name that triggered this APS requirement. Printed on the APS request letter."
                    )
                aps_rule = (aps_rule_manual_t
                            if aps_rule_sel_t == "✏️ Enter manually…"
                            else ("" if aps_rule_sel_t.startswith("—")
                                  else aps_rule_sel_t))

                # Physician fields — pre-filled from registry selection above
                _pt1, _pt2 = st.columns(2)
                aps_phys = _pt1.text_input(
                    "Physician Name",
                    value=_phy_t_rec["physician_name"] if _phy_t_rec else "",
                    disabled=bool(_phy_t_rec),
                    help="Pre-filled when a physician is selected above."
                )
                aps_phone = _pt2.text_input(
                    "Physician Phone",
                    value=_phy_t_rec["phone"] if _phy_t_rec else "",
                    disabled=bool(_phy_t_rec),
                    help="Pre-filled from registry."
                )
                aps_email_t = st.text_input(
                    "Physician Email",
                    value=_phy_t_rec["email"] if _phy_t_rec else "",
                    disabled=bool(_phy_t_rec),
                    help="APS request letter is emailed here."
                )
                aps_addr = st.text_area(
                    "Physician Address", height=60,
                    value=_phy_t_rec.get("address_line1","") if _phy_t_rec else "",
                    disabled=bool(_phy_t_rec),
                    help="Pre-filled from registry."
                )
                send_to_phy_t = st.checkbox(
                    "📧 Send APS request letter to physician",
                    value=bool(_phy_t_rec and _phy_t_rec.get("email")),
                    help="Emails a formal request letter to the physician."
                )
                aps_notes = st.text_area("Notes", height=60,
                    help="Internal file notes — not sent to physician.")
                from datetime import date as _date, timedelta as _td
                aa1, aa2 = st.columns(2)
                aps_due = aa1.date_input(
                    "APS Due Date", value=_date.today() + _td(days=30),
                    help="Deadline. Standard 30 days; complex cases 60."
                )
                aps_exp = aa2.date_input(
                    "APS Expire Date", value=_date.today() + _td(days=180),
                    help="After this date records are stale — typically 6 months."
                )
                _aps_submit = st.form_submit_button(
                    "📤 Request APS", use_container_width=True,
                    disabled=not _can_decide
                )
                if _aps_submit:
                    if not _can_decide:
                        st.error("Your role cannot request APS.")
                    else:
                        _phys_name_t = (aps_phys.strip()
                                        if not _phy_t_rec
                                        else _phy_t_rec["physician_name"])
                        _phys_email_t = (_phy_t_rec["email"]
                                         if _phy_t_rec
                                         else aps_email_t.strip())
                        _phys_phone_t = (_phy_t_rec["phone"]
                                         if _phy_t_rec
                                         else aps_phone.strip())
                        _phys_addr_t  = (_phy_t_rec.get("address_line1","")
                                         if _phy_t_rec
                                         else aps_addr.strip())
                        resp = requests.post(f"{API_BASE}/queue/aps/request",
                            headers=hdr, json={
                                "case_id":          str(aps_case_id or ""),
                                "application_id":   str(aps_app_id or ""),
                                "rule_name":        str(aps_rule or ""),
                                "physician_name":   str(_phys_name_t or ""),
                                "physician_phone":  str(_phys_phone_t or ""),
                                "physician_address":str(_phys_addr_t or ""),
                                "notes":            str(aps_notes or ""),
                                "due_date":    str(aps_due) if aps_due else None,
                                "expire_date": str(aps_exp) if aps_exp else None,
                            })
                        if resp.status_code == 200:
                            st.success("✅ APS requested")
                            if send_to_phy_t and _phys_email_t:
                                _ok_pt, _msg_pt = send_aps_request_to_physician(
                                    physician_email=_phys_email_t,
                                    physician_name=_phys_name_t,
                                    applicant_name=aps_app_id or aps_case_id,
                                    applicant_ref=aps_app_id or aps_case_id,
                                    case_number=aps_case_id,
                                    rule_name=aps_rule,
                                    due_date=str(aps_due) if aps_due else "",
                                )
                                if _ok_pt:
                                    st.success(f"📧 {_msg_pt}")
                                else:
                                    st.warning(f"APS recorded but email failed: {_msg_pt}")
                            send_notification("APS_REQUESTED", {
                                "case_number":    aps_case_id,
                                "applicant_ref":  aps_app_id or aps_case_id,
                                "rule_name":      aps_rule or "",
                                "physician_name": _phys_name_t,
                                "due_date":       str(aps_due) if aps_due else "",
                            })
                        else:
                            st.error(f"Error: {resp.text}")

        with col2:
            st.markdown("**Update APS Status**")
            with st.form("aps_upd_form"):
                aps_id_upd = st.text_input(
                    "APS ID (UUID)",
                    help=(
                        "The unique ID of the APS request to update. "
                        "Find it in the pending APS list below — copy the ID "
                        "from the relevant request."
                    )
                )
                aps_status_v = st.selectbox(
                    "Status",
                    ["ORDERED","RECEIVED","REVIEWED","NOT_REQUIRED"],
                    help=(
                        "**ORDERED** — Request sent to physician, awaiting records.\n"
                        "**RECEIVED** — Physical/digital records have arrived, "
                        "pending underwriter review.\n"
                        "**REVIEWED** — Underwriter has read the APS and can now "
                        "record a final decision on the case.\n"
                        "**NOT_REQUIRED** — APS waived by senior underwriter — "
                        "case can proceed without physician records."
                    )
                )
                aps_doc = st.text_input(
                    "Document Reference",
                    placeholder="e.g. APS-2026-001234",
                    help=(
                        "Internal document reference number assigned to the "
                        "received APS records. Used for audit trail and file "
                        "retrieval. Assign from your document management system."
                    )
                )
                aps_upd_notes = st.text_area(
                    "Notes", height=60,
                    help=(
                        "Internal notes on the APS update — e.g. 'Records "
                        "received via fax, incomplete — chasing missing cardiology "
                        "report'. Stored in audit trail, not shared externally."
                    )
                )
                _aps_upd = st.form_submit_button(
                    "🔄 Update",
                    use_container_width=True,
                    disabled=not _can_decide
                )
                if _aps_upd:
                    resp = requests.post(f"{API_BASE}/queue/aps/update",
                        headers=hdr, json={
                            "aps_id":       aps_id_upd,
                            "status":       aps_status_v,
                            "document_ref": aps_doc,
                            "notes":        aps_upd_notes
                        })
                    if resp.status_code == 200:
                        _log_audit("APS","APS_STATUS_UPDATED",
                            entity_type="APS_REQUEST", entity_id=aps_id_upd,
                            entity_ref=working.get("case_number",""),
                            after_state={"status": aps_status_v},
                            metadata={"document_ref": aps_doc, "notes": aps_upd_notes})
                        st.success(f"✅ APS updated to {aps_status_v}")
                    else:
                        st.error(f"Error: {resp.text}")

        st.divider()
        st.markdown("**All Pending APS Requests**")
        pending_aps = [c for c in all_cases if c.get("aps_pending", 0) > 0]
        if pending_aps:
            for case in pending_aps:
                try:
                    aps_data = requests.get(
                        f"{API_BASE}/queue/aps/{case['id']}",
                        headers=hdr, timeout=3).json()
                    with st.expander(
                        f"📋 {case['case_number']} — "
                        f"{case.get('aps_pending')} pending"
                    ):
                        for aps in aps_data.get("aps_requests", []):
                            st.markdown(
                                f"**{aps.get('rule_name','Unknown rule')}** | "
                                f"{aps['status']} | "
                                f"{aps.get('physician_name','No physician')}"
                            )
                            if aps.get("notes"):
                                st.caption(aps["notes"])
                except Exception as _exc:
                    logger.debug("[render_uw_queue] Suppressed exception", exc_info=_exc)
        else:
            st.info("No pending APS requests.")

    # ══════════════════════════════════════════════════════════════
    #  TAB 4 — PREMIUM CALCULATOR
    # ══════════════════════════════════════════════════════════════
    if _show_premium:
        st.caption("Calculate annual and monthly premiums based on risk profile.")
        with st.form("premium_calc_form"):
            pc1, pc2, pc3 = st.columns(3)
            with pc1:
                prem_prod   = st.selectbox("Product",
                    ["IND-TERM-10","IND-TERM-20","IND-TERM-30"],
                    help="Select the product code to look up the applicable rate table.")
                prem_age    = st.number_input("Age", 18, 70, 40,
                    help="Applicant's age at next birthday. Must be within the product's eligible age band.")
                prem_gender = st.selectbox("Gender", ["MALE","FEMALE"],
                    help="Gender used for mortality-based rate selection.")
            with pc2:
                prem_face    = st.number_input("Face Amount",
                    50000, 10_000_000, 500000, step=50000,
                    help="Sum assured / coverage amount in the policy currency. Used to calculate base premium per thousand.")
                prem_tobacco = st.selectbox("Tobacco", ["NON_TOBACCO","TOBACCO"],
                    help="Tobacco status affects the mortality loading. TOBACCO rates are typically 1.5–2x NON_TOBACCO.")
                prem_risk    = st.selectbox("Risk Class",
                    ["PREFERRED_PLUS","PREFERRED","STANDARD_PLUS",
                     "STANDARD","SUBSTANDARD"],
                    help="Underwriting risk classification. PREFERRED_PLUS is the best rate; SUBSTANDARD applies a table rating.")
            with pc3:
                prem_table = st.selectbox("Table Rating",
                    [0,2,4,6,8,10,12,14,16],
                    help="Substandard extra mortality loading in percentage points (0 = none, 2 = Table B = +25%, 4 = Table D = +50%, etc.).")
                prem_flat  = st.number_input("Flat Extra ($/K/yr)",
                    0.0, 20.0, 0.0, step=0.5,
                    help="Flat extra premium charged per $1,000 of face amount per year. Applied for temporary or permanent hazard loadings.")
                prem_term  = st.selectbox("Term (years)", [10,20,30],
                    help="Policy term in years. Must match a term available in the rate table for the selected product.")
            calc_btn = st.form_submit_button("💰 Calculate Premium",
                use_container_width=True, type="primary")

        if calc_btn:
            try:
                resp = requests.get(f"{API_BASE}/queue/premium/calculate",
                    headers=hdr, params={
                        "product_code": prem_prod, "age": prem_age,
                        "gender": prem_gender, "face_amount": prem_face,
                        "tobacco": prem_tobacco, "risk_class": prem_risk,
                        "table_rating": prem_table, "flat_extra": prem_flat,
                        "term_years": prem_term
                    })
                if resp.status_code == 200:
                    p = resp.json()
                    st.success("✅ Premium calculated")
                    _sym = get_currency_symbol()
                    mc1,mc2,mc3,mc4 = st.columns(4)
                    mc1.metric("Annual Premium",
                               f"{_sym}{p['total_annual']:,.2f}")
                    mc2.metric("Monthly Premium",
                               f"{_sym}{p['total_monthly']:,.2f}")
                    mc3.metric("Semi-Annual",
                               f"{_sym}{p['mode_semi_annual']:,.2f}")
                    mc4.metric("Quarterly",
                               f"{_sym}{p['mode_quarterly']:,.2f}")
                    st.divider()
                    dc1,dc2,dc3 = st.columns(3)
                    dc1.metric("Rate per $1K",    f"${p['rate_per_thou']:.4f}")
                    dc2.metric("Base Premium",
                               f"{_sym}{p['base_premium']:,.2f}")
                    dc3.metric("Flat Extra Total",
                               f"{_sym}{p['flat_extra_amt']:,.2f}")
                    st.caption(
                        f"Risk: {p['risk_class']} | "
                        f"Table: {p['table_rating']} | "
                        f"Flat Extra: ${p['flat_extra_per_thou']}/K"
                    )
                else:
                    st.error(
                        f"Rate not found: {resp.json().get('detail','Unknown')}")
            except Exception as ex:
                st.error(f"Calculation error: {ex}")

    # ══════════════════════════════════════════════════════════════
    #  TAB 5 — AI APS ABSTRACTION
    # ══════════════════════════════════════════════════════════════
    if _show_ai_aps:
        working_case = st.session_state.get("working_case", {})
        cid = working_case.get("case_number", working_case.get("id", ""))
        if cid:
            st.caption(f"Processing APS for case: **{cid}**")
        render_aps_abstraction(case_id=cid)


def _ensure_policy_admin_queue():
    """Create the policy_admin_queue table if it doesn't exist."""
    pass  # table created by migrations/001_initial_schema.sql
def _queue_for_policy_admin(record: dict, source: str = "ONLINE"):
    """
    Insert a decision record into policy_admin_queue with status=UNPROCESSED.
    Called after every decision — online or batch.
    """
    _ensure_policy_admin_queue()
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO policy_admin_queue (
                    applicant_ref, applicant_name, applicant_email,
                    case_id, job_id, product_code,
                    face_amount, age, gender, state,
                    outcome, risk_class, net_debit_points,
                    approved_premium, effective_date, expire_date,
                    decision_date, reason, source, status
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,NOW(),%s,%s,'UNPROCESSED'
                )
            """, (
                record.get("applicant_ref",""),
                record.get("applicant_name",""),
                record.get("applicant_email",""),
                record.get("case_id",""),
                record.get("job_id",""),
                record.get("product_code",""),
                record.get("face_amount"),
                record.get("age"),
                record.get("gender",""),
                record.get("state",""),
                record.get("outcome",""),
                record.get("risk_class",""),
                record.get("net_debit_points"),
                record.get("approved_premium"),
                record.get("effective_date") or None,
                record.get("expire_date") or None,
                record.get("reason",""),
                source,
            ))
            cur.close(); _release_db_conn(conn)

            # Auto-push if webhook is configured and enabled
            try:
                _cfg_ap = _get_output_interface_config()
                if (_cfg_ap.get("webhook_url","").strip()
                        and _cfg_ap.get("webhook_auto_push","0") == "1"):
                    _push_to_pas(record, _cfg_ap)
            except Exception as _exc:
                logger.warning("[_queue_for_policy_admin] Suppressed exception", exc_info=_exc)

            return True
    except Exception as _exc:
        logger.warning("[_queue_for_policy_admin] Suppressed exception", exc_info=_exc)
    return False


def _get_output_interface_config() -> dict:
    """Load output interface config from DB."""
    if st.session_state.get("_oic"):
        return st.session_state["_oic"]
    cfg = {}
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM output_interface_config")
            cfg = {r[0]: r[1] for r in cur.fetchall()}
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_get_output_interface_config] Suppressed exception", exc_info=_exc)
    st.session_state["_oic"] = cfg
    return cfg


def _save_output_interface_config(cfg: dict):
    """Persist output interface config to DB."""
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_save_output_interface_config] Suppressed exception", exc_info=_exc)
    st.session_state["_oic"] = cfg


def _run_policy_admin_extract() -> tuple:
    """
    Extract UNPROCESSED records from policy_admin_queue,
    write to file per config, mark as PROCESSED.
    Returns (success, filepath, record_count, message)
    """
    import json as _j, io as _io
    cfg = _get_output_interface_config()
    output_folder = cfg.get("output_folder", "/tmp")
    file_format   = cfg.get("file_format", "csv")
    delimiter     = cfg.get("delimiter", ",")
    columns_json  = cfg.get("columns", "[]")
    try:
        selected_cols = _j.loads(columns_json)
    except Exception as _exc:
        logger.debug("[_run_policy_admin_extract] Suppressed exception", exc_info=_exc)
        selected_cols = []

    _ALL_COLS = [
        "id","applicant_ref","applicant_name","applicant_email",
        "case_id","job_id","product_code","face_amount","age","gender","state",
        "outcome","risk_class","net_debit_points","approved_premium",
        "effective_date","expire_date","decision_date","reason","source",
        "status","created_at",
    ]
    cols = [c for c in selected_cols if c in _ALL_COLS] or _ALL_COLS

    try:
        import pandas as pd
        conn = _get_db_conn()
        if not conn:
            return False, None, 0, "DB connection failed"

        cur = conn.cursor()
        _ensure_policy_admin_queue()
        col_sql = ", ".join(cols)
        cur.execute(f"""
            SELECT {col_sql} FROM policy_admin_queue
            WHERE status = 'UNPROCESSED'
            ORDER BY created_at
        """)
        rows = cur.fetchall()
        if not rows:
            cur.close(); _release_db_conn(conn)
            return True, None, 0, "No unprocessed records found"

        df = pd.DataFrame(rows, columns=cols)

        from datetime import datetime as _dtt
        ts = _dtt.now().strftime("%Y%m%d_%H%M%S")

        import os
        os.makedirs(output_folder, exist_ok=True)

        if file_format == "excel":
            fpath = os.path.join(output_folder, f"policy_admin_{ts}.xlsx")
            df.to_excel(fpath, index=False)
        else:
            sep = delimiter if delimiter else ","
            fpath = os.path.join(output_folder, f"policy_admin_{ts}.csv")
            df.to_csv(fpath, index=False, sep=sep)

        # Mark as PROCESSED
        ids = [r[cols.index("id")] for r in rows if "id" in cols]
        if ids:
            cur.execute("""
                UPDATE policy_admin_queue
                SET status='PROCESSED', processed_at=NOW()
                WHERE id = ANY(%s)
            """, (ids,))
        else:
            cur.execute("""
                UPDATE policy_admin_queue
                SET status='PROCESSED', processed_at=NOW()
                WHERE status='UNPROCESSED'
            """)
        cur.close(); _release_db_conn(conn)
        return True, fpath, len(df), f"Extracted {len(df)} records to {fpath}"
    except Exception as e:
        return False, None, 0, str(e)


def _push_to_pas(record: dict, cfg: dict) -> tuple:
    """
    POST a single policy_admin_queue record to the configured PAS webhook URL.
    Returns (success: bool, http_status: int, error_msg: str).
    Respects field mapping from cfg["field_map"] if configured.
    """
    import json as _j, time as _t
    url     = cfg.get("webhook_url", "").strip()
    method  = cfg.get("webhook_method", "POST").upper()
    auth    = cfg.get("webhook_auth_type", "NONE")
    token   = cfg.get("webhook_auth_value", "").strip()
    timeout = int(cfg.get("webhook_timeout", 15))
    max_retry = int(cfg.get("webhook_max_retries", 3))

    if not url:
        return False, 0, "No webhook URL configured"

    # Build payload — apply field mapping if set
    field_map = {}
    try:
        field_map = _j.loads(cfg.get("webhook_field_map", "{}") or "{}")
    except Exception as _exc:
        logger.debug("[_push_to_pas] Suppressed exception", exc_info=_exc)

    payload = {}
    for k, v in record.items():
        out_key = field_map.get(k, k)
        # Serialise non-JSON-native types
        if hasattr(v, "isoformat"):
            payload[out_key] = v.isoformat()
        elif v is None:
            payload[out_key] = None
        else:
            payload[out_key] = v

    # Wrap in envelope if configured
    envelope_key = cfg.get("webhook_envelope_key", "").strip()
    if envelope_key:
        payload = {envelope_key: payload}

    # Headers
    headers = {"Content-Type": "application/json"}
    if auth == "BEARER" and token:
        headers["Authorization"] = f"Bearer {token}"
    elif auth == "API_KEY" and token:
        key_header = cfg.get("webhook_api_key_header", "X-API-Key").strip()
        headers[key_header] = token
    elif auth == "BASIC" and token:
        import base64 as _b64
        headers["Authorization"] = "Basic " + _b64.b64encode(token.encode()).decode()

    # Custom headers
    try:
        custom_hdrs = _j.loads(cfg.get("webhook_custom_headers", "{}") or "{}")
        headers.update(custom_hdrs)
    except Exception as _exc:
        logger.debug("[_push_to_pas] Suppressed exception", exc_info=_exc)

    # Retry loop with exponential backoff
    last_err = ""
    for attempt in range(1, max_retry + 1):
        try:
            if method == "POST":
                resp = requests.post(url, json=payload, headers=headers,
                                     timeout=timeout)
            elif method == "PUT":
                resp = requests.put(url, json=payload, headers=headers,
                                    timeout=timeout)
            else:
                resp = requests.post(url, json=payload, headers=headers,
                                     timeout=timeout)

            if 200 <= resp.status_code < 300:
                return True, resp.status_code, ""
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.Timeout:
            last_err = f"Timeout after {timeout}s"
        except requests.exceptions.ConnectionError as ce:
            last_err = f"Connection error: {str(ce)[:150]}"
        except Exception as ex:
            last_err = str(ex)[:200]

        if attempt < max_retry:
            _t.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, 8s

    return False, 0, last_err


def _run_webhook_push(limit: int = 200) -> dict:
    """
    Push all PENDING / PUSH_FAILED records to the PAS webhook.
    Updates push_status, push_attempts, push_last_error per record.
    Returns summary dict.
    """
    from datetime import datetime as _dtt
    result = {"pushed": 0, "failed": 0, "skipped": 0, "details": []}

    cfg = _get_output_interface_config()
    if not cfg.get("webhook_url", "").strip():
        result["skipped"] = -1
        result["details"].append("No webhook URL configured — set it in Block 4 below.")
        return result

    max_retries = int(cfg.get("webhook_max_retries", 3))

    _ALL_COLS = [
        "id", "applicant_ref", "applicant_name", "applicant_email",
        "case_id", "job_id", "product_code", "face_amount", "age",
        "gender", "state", "outcome", "risk_class", "net_debit_points",
        "approved_premium", "effective_date", "expire_date",
        "decision_date", "reason", "source", "created_at",
    ]

    try:
        conn = _get_db_conn()
        if not conn:
            result["details"].append("DB connection failed")
            return result

        _ensure_policy_admin_queue()
        cur = conn.cursor()

        # Fetch records eligible for push
        cur.execute(f"""
            SELECT {', '.join(_ALL_COLS)}, push_attempts
            FROM policy_admin_queue
            WHERE push_status IN ('PENDING', 'PUSH_FAILED')
              AND (push_attempts IS NULL OR push_attempts < %s)
              AND status != 'PROCESSED'
            ORDER BY created_at ASC
            LIMIT %s
        """, (max_retries, limit))
        rows = cur.fetchall()

        if not rows:
            result["details"].append("No records pending push.")
            cur.close(); _release_db_conn(conn)
            return result

        col_names = _ALL_COLS + ["push_attempts"]

        for row in rows:
            record = dict(zip(col_names, row))
            rec_id = record.pop("id")
            attempts = int(record.pop("push_attempts") or 0)

            ok, http_code, err = _push_to_pas(record, cfg)

            if ok:
                cur.execute("""
                    UPDATE policy_admin_queue SET
                        push_status   = 'PUSHED',
                        push_attempts = push_attempts + 1,
                        push_last_at  = NOW(),
                        push_last_error = NULL,
                        status        = 'PROCESSED',
                        processed_at  = NOW()
                    WHERE id = %s
                """, (rec_id,))
                result["pushed"] += 1
                result["details"].append(
                    f"✅ {record.get('applicant_ref','—')} "
                    f"({record.get('outcome','—')}) → HTTP {http_code}"
                )
                _log_audit("DATA_ACCESS", "PAS_WEBHOOK_PUSHED",
                    entity_type="POLICY_ADMIN",
                    entity_id=str(rec_id),
                    entity_ref=record.get("applicant_ref",""),
                    after_state={"outcome": record.get("outcome"),
                                 "http_status": http_code})
            else:
                cur.execute("""
                    UPDATE policy_admin_queue SET
                        push_status   = 'PUSH_FAILED',
                        push_attempts = push_attempts + 1,
                        push_last_at  = NOW(),
                        push_last_error = %s
                    WHERE id = %s
                """, (err[:500], rec_id))
                result["failed"] += 1
                result["details"].append(
                    f"❌ {record.get('applicant_ref','—')} — {err[:80]}"
                )
        cur.close(); _release_db_conn(conn)

    except Exception as ex:
        result["details"].append(f"Fatal: {ex}")

    return result


def _ensure_batch_tables():
    """Create batch processing tables if they don't exist."""
    if st.session_state.get("_batch_tables_ok"):
        return
    try:
        conn = _get_db_conn()
        if not conn:
            return
        cur = conn.cursor()
        _release_db_conn(conn)
        st.session_state["_batch_tables_ok"] = True
    except Exception as _e:
        st.session_state["_batch_tables_ok"] = False


def render_member_data():
    """Member Data Upload — enrich applicant records with contact details."""
    import pandas as pd
    import io, uuid as _uuid
    from datetime import datetime as _dt

    st.markdown("## 👤 Member Data")
    st.caption(
        "Upload applicant contact details by applicant_ref. "
        "Enriches cases so decision letters, APS emails, and output files "
        "auto-populate name, email, address and phone without manual entry."
    )

    tok = st.session_state.get("token", "")
    hdr = {"Authorization": f"Bearer {tok}"}

    # ── Ensure table ──────────────────────────────────────────────
    def _ensure_member_table():
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.close(); _release_db_conn(conn)
                return True
        except Exception as e:
            st.error(f"DB setup error: {e}")
        return False

    _ensure_member_table()

    # ── Tabs ──────────────────────────────────────────────────────
    tab_upload, tab_search, tab_history = st.tabs([
        "📤 Upload Members",
        "🔍 Search & Edit",
        "📋 Upload History",
    ])

    # ══════════════════════════════════════════════════════════════
    # TAB 1 — UPLOAD
    # ══════════════════════════════════════════════════════════════
    with tab_upload:
        col_up, col_info = st.columns([3, 2])

        with col_info:
            st.markdown("##### Required columns")
            st.markdown(
                "| Column | Notes |\n"
                "|---|---|\n"
                "| `applicant_ref` | Must match existing cases |\n"
                "| `full_name` | |\n"
                "| `email` | Used for decision letters |\n"
                "| `phone` | |\n"
                "| `dob` | YYYY-MM-DD |\n"
                "| `gender` | MALE / FEMALE |\n"
                "| `address_line1` | |\n"
                "| `address_line2` | Optional |\n"
                "| `city` | |\n"
                "| `state` | 2-letter code |\n"
                "| `pincode` | |\n"
                "| `country` | Default: India |"
            )
            # ── Template download ──
            _tmpl_df = pd.DataFrame([{
                "applicant_ref": "APP-001",
                "full_name":     "Ramesh Kumar",
                "email":         "ramesh.kumar@email.com",
                "phone":         "+91 9876543210",
                "dob":           "1985-06-15",
                "gender":        "MALE",
                "address_line1": "12 MG Road",
                "address_line2": "Apt 4B",
                "city":          "Bengaluru",
                "state":         "KA",
                "pincode":       "560001",
                "country":       "India",
            }])
            _tmpl_csv = _tmpl_df.to_csv(index=False).encode()
            st.download_button(
                "⬇️ Download template CSV",
                data=_tmpl_csv,
                file_name="member_data_template.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with col_up:
            st.markdown("##### Upload file")
            with st.form("member_upload_form"):
                up_file = st.file_uploader(
                    "Select CSV or Excel file",
                    type=["csv", "xlsx", "xls"],
                    help="One member per row. applicant_ref is the key — existing records are updated, new ones inserted."
                )
                update_mode = st.radio(
                    "If applicant_ref already exists:",
                    ["Update existing record", "Skip (keep existing)"],
                    horizontal=True,
                    help="Update: overwrites name, email, address and phone with values from the file. Skip: leaves the existing record untouched and counts the row as skipped."
                )
                notes = st.text_input("Upload notes", placeholder="e.g. March 2026 new business batch",
                    help="Optional free-text note saved with the upload log so you can identify this batch later.")
                submitted = st.form_submit_button("📤 Upload Members", type="primary", use_container_width=True)

            if submitted and up_file:
                try:
                    if up_file.name.endswith(".csv"):
                        df = pd.read_csv(up_file)
                    else:
                        df = pd.read_excel(up_file)

                    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

                    if "applicant_ref" not in df.columns:
                        st.error("❌ File must have an `applicant_ref` column.")
                    else:
                        df = df.where(pd.notnull(df), None)

                        # ── Validate ──
                        _errors, _warnings = [], []
                        for i, row in df.iterrows():
                            if not row.get("applicant_ref"):
                                _errors.append(f"Row {i+2}: applicant_ref is empty")
                            if row.get("email") and "@" not in str(row.get("email", "")):
                                _warnings.append(f"Row {i+2}: email looks invalid ({row['email']})")
                            if row.get("dob"):
                                try:
                                    pd.to_datetime(row["dob"])
                                except Exception as _exc:
                                    logger.debug("[_ensure_member_table] Suppressed exception", exc_info=_exc)
                                    _warnings.append(f"Row {i+2}: dob format not recognised ({row['dob']}) — will be skipped")

                        if _errors:
                            for e in _errors[:10]:
                                st.error(e)
                        else:
                            if _warnings:
                                for w in _warnings[:5]:
                                    st.warning(w)

                            # ── Process ──
                            _cols = ["applicant_ref","full_name","email","phone","dob",
                                     "gender","address_line1","address_line2",
                                     "city","state","pincode","country"]

                            inserted = updated = skipped = errors = 0
                            upload_ref = str(_uuid.uuid4())[:8].upper()
                            uname = st.session_state.get("username", "system")

                            conn = _get_db_conn()
                            if conn:
                                cur = conn.cursor()
                                progress = st.progress(0, text="Processing...")
                                for idx, row in df.iterrows():
                                    pct = int((idx + 1) / len(df) * 100)
                                    progress.progress(pct, text=f"Processing row {idx+1} of {len(df)}...")
                                    try:
                                        ref = str(row.get("applicant_ref","")).strip()
                                        if not ref:
                                            skipped += 1
                                            continue

                                        # Parse dob safely
                                        _dob = None
                                        if row.get("dob"):
                                            try:
                                                _dob = pd.to_datetime(row["dob"]).date()
                                            except Exception as _exc:
                                                logger.debug("[_ensure_member_table] Suppressed exception", exc_info=_exc)

                                        # Check exists
                                        cur.execute(
                                            "SELECT id FROM applicant_master WHERE applicant_ref=%s",
                                            (ref,)
                                        )
                                        exists = cur.fetchone()

                                        if exists and update_mode == "Skip (keep existing)":
                                            skipped += 1
                                            continue

                                        vals = {
                                            "ref":   ref,
                                            "name":  str(row.get("full_name","") or ""),
                                            "email": str(row.get("email","") or ""),
                                            "phone": str(row.get("phone","") or ""),
                                            "dob":   _dob,
                                            "gen":   str(row.get("gender","") or "").upper() or None,
                                            "a1":    str(row.get("address_line1","") or ""),
                                            "a2":    str(row.get("address_line2","") or ""),
                                            "city":  str(row.get("city","") or ""),
                                            "state": str(row.get("state","") or "").upper() or None,
                                            "pin":   str(row.get("pincode","") or ""),
                                            "cty":   str(row.get("country","") or "India"),
                                            "uname": uname,
                                        }

                                        if exists:
                                            cur.execute("""
                                                UPDATE applicant_master SET
                                                    full_name=%s, email=%s, phone=%s,
                                                    dob=%s, gender=%s,
                                                    address_line1=%s, address_line2=%s,
                                                    city=%s, state=%s, pincode=%s, country=%s,
                                                    uploaded_by=%s, updated_at=NOW()
                                                WHERE applicant_ref=%s
                                            """, (vals["name"], vals["email"], vals["phone"],
                                                  vals["dob"], vals["gen"],
                                                  vals["a1"], vals["a2"],
                                                  vals["city"], vals["state"], vals["pin"], vals["cty"],
                                                  vals["uname"], ref))
                                            updated += 1
                                        else:
                                            cur.execute("""
                                                INSERT INTO applicant_master
                                                    (applicant_ref, full_name, email, phone,
                                                     dob, gender, address_line1, address_line2,
                                                     city, state, pincode, country,
                                                     source, uploaded_by)
                                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'UPLOAD',%s)
                                            """, (ref, vals["name"], vals["email"], vals["phone"],
                                                  vals["dob"], vals["gen"],
                                                  vals["a1"], vals["a2"],
                                                  vals["city"], vals["state"], vals["pin"],
                                                  vals["cty"], vals["uname"]))
                                            inserted += 1

                                    except Exception as row_err:
                                        errors += 1

                                # Log the upload
                                cur.execute("""
                                    INSERT INTO member_upload_log
                                        (upload_ref, filename, total_rows, inserted,
                                         updated, skipped, errors, uploaded_by, notes)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """, (upload_ref, up_file.name, len(df),
                                      inserted, updated, skipped, errors, uname, notes))
                                cur.close(); _release_db_conn(conn)
                                progress.empty()

                                # ── Results ──
                                r1, r2, r3, r4 = st.columns(4)
                                r1.metric("Total rows", len(df))
                                r2.metric("Inserted", inserted)
                                r3.metric("Updated",  updated)
                                r4.metric("Skipped",  skipped)
                                if errors:
                                    st.warning(f"⚠️ {errors} row(s) had errors and were skipped.")
                                _log_audit("MEMBER","MEMBER_DATA_UPLOADED",
                                    entity_type="MEMBER_UPLOAD",
                                    entity_id=upload_ref,
                                    after_state={"inserted": inserted, "updated": updated,
                                                 "skipped": skipped, "errors": errors},
                                    metadata={"filename": up_file.name, "total_rows": len(df)})
                                st.success(
                                    f"✅ Upload complete — ref: `{upload_ref}`. "
                                    f"{inserted} new records, {updated} updated."
                                )
                except Exception as ex:
                    st.error(f"Upload failed: {ex}")

            elif submitted and not up_file:
                st.warning("Please select a file first.")

    # ══════════════════════════════════════════════════════════════
    # TAB 2 — SEARCH & EDIT
    # ══════════════════════════════════════════════════════════════
    with tab_search:
        st.markdown("##### Search member records")
        sc1, sc2, sc3 = st.columns([2, 2, 1])
        _s_ref   = sc1.text_input("Applicant Ref", placeholder="APP-001", key="ms_ref",
            help="Partial match supported — enter part of the ref to find multiple records.")
        _s_name  = sc2.text_input("Name / Email",  placeholder="Ramesh or ramesh@...", key="ms_name",
            help="Searches both full_name and email fields. Partial match supported.")
        _do_search = sc3.button("🔍 Search", use_container_width=True, key="ms_search",
                                 type="primary")

        if _do_search or st.session_state.get("ms_ref") or st.session_state.get("ms_name"):
            try:
                conn = _get_db_conn()
                if conn:
                    cur = conn.cursor()
                    _q = """
                        SELECT id, applicant_ref, full_name, email, phone,
                               dob, gender, address_line1, address_line2,
                               city, state, pincode, country, updated_at
                        FROM applicant_master WHERE 1=1
                    """
                    _p = []
                    if _s_ref.strip():
                        _q += " AND applicant_ref ILIKE %s"
                        _p.append(f"%{_s_ref.strip()}%")
                    if _s_name.strip():
                        _q += " AND (full_name ILIKE %s OR email ILIKE %s)"
                        _p.extend([f"%{_s_name.strip()}%", f"%{_s_name.strip()}%"])
                    _q += " ORDER BY updated_at DESC LIMIT 50"
                    cur.execute(_q, _p)
                    rows = cur.fetchall()
                    cur.close(); _release_db_conn(conn)

                    if not rows:
                        st.info("No records found.")
                    else:
                        st.caption(f"{len(rows)} record(s) found.")
                        _cols_display = ["applicant_ref","full_name","email","phone",
                                         "dob","gender","city","state","pincode","updated_at"]
                        _df_display = pd.DataFrame(rows, columns=[
                            "id","applicant_ref","full_name","email","phone",
                            "dob","gender","address_line1","address_line2",
                            "city","state","pincode","country","updated_at"
                        ])
                        st.dataframe(
                            _df_display[_cols_display].astype(str),
                            use_container_width=True, hide_index=True
                        )

                        # ── Inline edit ──
                        st.markdown("##### Edit a record")
                        _sel_ref = st.selectbox(
                            "Select applicant_ref to edit",
                            options=["—"] + list(_df_display["applicant_ref"]),
                            key="ms_edit_sel",
                            help="Pick a record from the search results above to edit its details inline."
                        )
                        if _sel_ref != "—":
                            _rec = _df_display[_df_display["applicant_ref"] == _sel_ref].iloc[0]
                            with st.form("member_edit_form"):
                                _ef1, _ef2 = st.columns(2)
                                _en  = _ef1.text_input("Full Name",  value=str(_rec["full_name"] or ""), key="me_name",
                                    help="Full legal name as it should appear on policy documents and decision letters.")
                                _ee  = _ef2.text_input("Email",      value=str(_rec["email"] or ""),     key="me_email",
                                    help="Used to send decision letters and APS confirmation emails to the applicant.")
                                _ep  = _ef1.text_input("Phone",      value=str(_rec["phone"] or ""),     key="me_phone",
                                    help="Contact number including country code, e.g. +91 9876543210.")
                                _eg  = _ef2.selectbox("Gender", ["", "MALE","FEMALE","OTHER"],
                                                       help="Gender as declared on the insurance application. Used for premium calculation and salutation on letters.",
                                                       index=["","MALE","FEMALE","OTHER"].index(
                                                           str(_rec["gender"] or ""))
                                                       if str(_rec["gender"] or "") in ["","MALE","FEMALE","OTHER"] else 0,
                                                       key="me_gender")
                                _ea1 = st.text_input("Address Line 1", value=str(_rec["address_line1"] or ""), key="me_a1",
                                    help="Street address, building name or flat number.")
                                _ea2 = st.text_input("Address Line 2", value=str(_rec["address_line2"] or ""), key="me_a2",
                                    help="Area, locality, or landmark. Optional.")
                                _ec1, _ec2, _ec3 = st.columns(3)
                                _eci = _ec1.text_input("City",    value=str(_rec["city"] or ""),    key="me_city",
                                    help="City or town of residence.")
                                _est = _ec2.text_input("State",   value=str(_rec["state"] or ""),   key="me_state",
                                    help="2-letter state code, e.g. KA, MH, DL. Stored in uppercase.")
                                _epi = _ec3.text_input("Pincode", value=str(_rec["pincode"] or ""), key="me_pin",
                                    help="6-digit postal code.")
                                _ecountry = st.text_input("Country", value=str(_rec["country"] or "India"), key="me_country",
                                    help="Country of residence. Defaults to India.")

                                _dob_val = None
                                try:
                                    _dob_raw = str(_rec["dob"] or "")
                                    if _dob_raw and _dob_raw != "None":
                                        _dob_val = pd.to_datetime(_dob_raw).date()
                                except Exception as _exc:
                                    logger.debug("[_ensure_member_table] Suppressed exception", exc_info=_exc)
                                _edob = st.date_input("Date of Birth", value=_dob_val, key="me_dob",
                                    help="Date of birth used for age verification and policy documents.")

                                _save_btn = st.form_submit_button("💾 Save Changes",
                                                                    type="primary",
                                                                    use_container_width=True)
                            if _save_btn:
                                try:
                                    conn2 = _get_db_conn()
                                    if conn2:
                                        cur2 = conn2.cursor()
                                        cur2.execute("""
                                            UPDATE applicant_master SET
                                                full_name=%s, email=%s, phone=%s,
                                                gender=%s, address_line1=%s, address_line2=%s,
                                                city=%s, state=%s, pincode=%s, country=%s,
                                                dob=%s, updated_at=NOW()
                                            WHERE applicant_ref=%s
                                        """, (_en, _ee, _ep, _eg or None, _ea1, _ea2,
                                              _eci, _est.upper() or None, _epi, _ecountry,
                                              _edob if _edob else None, _sel_ref)); cur2.close(); conn2.close()
                                        st.success(f"✅ Record for `{_sel_ref}` updated.")
                                        st.rerun()
                                except Exception as se:
                                    st.error(f"Save failed: {se}")
            except Exception as ex:
                st.error(f"Search failed: {ex}")

        else:
            # Show summary stats when no search active
            try:
                conn = _get_db_conn()
                if conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM applicant_master")
                    total = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM applicant_master WHERE email IS NOT NULL AND email != ''")
                    with_email = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM applicant_master WHERE address_line1 IS NOT NULL AND address_line1 != ''")
                    with_addr = cur.fetchone()[0]
                    cur.close(); _release_db_conn(conn)
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total members", total)
                    m2.metric("With email", with_email)
                    m3.metric("With address", with_addr)
            except Exception as _exc:
                logger.warning("[_ensure_member_table] Suppressed exception", exc_info=_exc)
            st.info("Enter an applicant ref or name above to search and edit records.")

    # ══════════════════════════════════════════════════════════════
    # TAB 3 — UPLOAD HISTORY
    # ══════════════════════════════════════════════════════════════
    with tab_history:
        st.markdown("##### Recent uploads")
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT upload_ref, filename, total_rows, inserted, updated,
                           skipped, errors, uploaded_by, uploaded_at, notes
                    FROM member_upload_log
                    ORDER BY uploaded_at DESC LIMIT 30
                """)
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)
                if not rows:
                    st.info("No uploads yet.")
                else:
                    _df_hist = pd.DataFrame(rows, columns=[
                        "upload_ref","filename","total_rows","inserted","updated",
                        "skipped","errors","uploaded_by","uploaded_at","notes"
                    ])
                    st.dataframe(_df_hist.astype(str), use_container_width=True, hide_index=True)
        except Exception as he:
            st.error(f"Could not load history: {he}")


def _is_medical_case(case_detail: dict) -> bool:
    """
    Determine if a case requires medical officer review.
    A case is medical if ANY of the following are true:
      - outcome is REQUEST_APS
      - exam_required in (PARAMEDICAL, FULL_MEDICAL, ATTENDING_PHYSICIAN)
      - rules_fired contains any rule from MEDICAL category
      - aps_count > 0 (APS already requested)
      - primary_reason contains medical keywords
    """
    outcome       = str(case_detail.get("outcome","")).upper()
    exam_required = str(case_detail.get("exam_required","")).upper()
    aps_count     = int(case_detail.get("aps_count") or 0)
    primary_reason= str(case_detail.get("primary_reason","")).lower()
    rules_fired   = case_detail.get("rules_fired") or []

    if outcome in ("REQUEST_APS",):
        return True
    if exam_required in ("PARAMEDICAL","FULL_MEDICAL","ATTENDING_PHYSICIAN"):
        return True
    if aps_count > 0:
        return True

    # Check if any fired rule is from MEDICAL category
    medical_keywords = {"medical","bmi","bp","blood","cancer","diabetes",
                        "heart","kidney","liver","copd","stroke","hiv",
                        "aps","physician","paramedical","exam"}
    if any(
        any(kw in str(r.get("rule_name","")).lower() or
            any(kw in str(r.get("category","")).lower() for kw in medical_keywords)
            for kw in medical_keywords)
        for r in rules_fired
    ):
        return True

    # primary_reason medical keywords
    if any(kw in primary_reason for kw in
           ["bmi","blood pressure","diabetes","cancer","heart","kidney",
            "liver","copd","stroke","aps","medical","exam","physician"]):
        return True

    return False


def _auto_assign_referred_cases(job_id: str = None,
                                 sla_hours: int = 48,
                                 route_medical: bool = True) -> dict:
    """
    Auto-assign OPEN/unassigned REFERRED cases to eligible underwriters.

    Assignment rules (in priority order):
      1. Medical cases (REQUEST_APS, exam required, APS pending):
         → Routed to users flagged as is_medical_officer=TRUE first
         → Falls back to senior_underwriter if no medical officer available
      2. Non-medical cases:
         → Routed to standard underwriters within face amount authority
      3. Face amount authority:
         → min_face_amount <= case.face_amount <= max_face_amount
      4. Product restriction (if set):
         → case.product_code must be in user.product_codes
      5. Load balancing:
         → Among eligible users, pick the one with fewest active cases

    Returns dict with counts: assigned, skipped, errors, medical_routed.
    """
    from datetime import datetime as _dt2, timezone as _tz, timedelta as _td

    result = {
        "assigned": 0, "skipped": 0, "errors": 0,
        "medical_routed": 0, "details": []
    }

    try:
        conn = _get_db_conn()
        if not conn:
            return result
        cur = conn.cursor()

        # ── Load all active UW users with authority limits ────────
        cur.execute("""
            SELECT
                u.id,
                u.username,
                u.full_name,
                u.role,
                COALESCE(l.min_face_amount, 0)   AS min_face,
                l.max_face_amount                 AS max_face,
                l.product_codes                   AS product_codes,
                COALESCE(l.is_medical_officer, FALSE)  AS is_medical_officer,
                l.medical_specialisations              AS med_specs,
                COALESCE(l.can_assess_medical, FALSE)  AS can_assess_medical,
                (SELECT COUNT(*) FROM uw_case c2
                 WHERE c2.assigned_uw_id = u.id
                   AND c2.status IN ('OPEN','IN_PROGRESS')) AS active_cases
            FROM uw_user u
            LEFT JOIN user_authority_limits l
                   ON l.username = u.username AND l.is_active = TRUE
            WHERE u.is_active = TRUE
              AND u.role IN ('underwriter','senior_underwriter','admin','super_admin')
            ORDER BY active_cases ASC, u.username
        """)
        uw_rows = cur.fetchall()

        if not uw_rows:
            cur.close(); _release_db_conn(conn)
            result["details"].append("No active underwriters found.")
            return result

        uw_users = [{
            "user_id":           str(r[0]),
            "username":          r[1],
            "full_name":         r[2] or r[1],
            "role":              r[3],
            "min_face":          float(r[4]) if r[4] is not None else 0,
            "max_face":          float(r[5]) if r[5] is not None else None,
            "product_codes":     [p.strip().upper() for p in r[6]] if r[6] else [],
            "is_medical_officer":bool(r[7]),
            "med_specs":         [s.strip().upper() for s in r[8]] if r[8] else [],
            "can_assess_medical":bool(r[9]),
            "active_cases":      int(r[10]),
        } for r in uw_rows]

        # Separate medical officers and standard UWs
        medical_officers = [u for u in uw_users
                            if u["is_medical_officer"] or u["can_assess_medical"]]
        standard_uw      = [u for u in uw_users
                            if not u["is_medical_officer"]]

        # ── Fetch unassigned OPEN cases ───────────────────────────
        if job_id:
            cur.execute("""
                SELECT c.id, c.case_number, c.status,
                       a.face_amount, a.product_code,
                       d.outcome, d.primary_reason,
                       (SELECT COUNT(*) FROM aps_request ar WHERE ar.case_id = c.id) AS aps_count,
                       p.exam_required
                FROM uw_case c
                JOIN application a   ON a.id = c.application_id
                LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = TRUE
                LEFT JOIN products p    ON p.product_code = a.product_code
                WHERE c.assigned_uw_id IS NULL
                  AND c.status IN ('OPEN','IN_PROGRESS')
                  AND c.job_id = %s
                ORDER BY c.priority_score DESC NULLS LAST, c.created_at ASC
            """, (job_id,))
        else:
            cur.execute("""
                SELECT c.id, c.case_number, c.status,
                       a.face_amount, a.product_code,
                       d.outcome, d.primary_reason,
                       (SELECT COUNT(*) FROM aps_request ar WHERE ar.case_id = c.id) AS aps_count,
                       p.exam_required
                FROM uw_case c
                JOIN application a   ON a.id = c.application_id
                LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final = TRUE
                LEFT JOIN products p    ON p.product_code = a.product_code
                WHERE c.assigned_uw_id IS NULL
                  AND c.status IN ('OPEN','IN_PROGRESS')
                ORDER BY c.priority_score DESC NULLS LAST, c.created_at ASC
                LIMIT 200
            """)
        cases = cur.fetchall()

        if not cases:
            cur.close(); _release_db_conn(conn)
            result["details"].append("No unassigned cases found.")
            return result

        sla_due = _dt2.now(_tz.utc) + _td(hours=sla_hours)

        def _eligible(uw, face_amount, product_code):
            """Check face amount and product authority."""
            if face_amount < uw["min_face"]:
                return False
            if uw["max_face"] is not None and face_amount > uw["max_face"]:
                return False
            if uw["product_codes"] and product_code:
                if product_code not in uw["product_codes"]:
                    return False
            return True

        def _do_assign(case_id, uw):
            """Execute the UPDATE and return rowcount."""
            cur.execute("""
                UPDATE uw_case SET
                    assigned_uw_id = %s,
                    assigned_at    = NOW(),
                    sla_due_at     = %s,
                    status         = 'IN_PROGRESS',
                    updated_at     = NOW()
                WHERE id = %s AND assigned_uw_id IS NULL
            """, (uw["user_id"], sla_due, str(case_id)))
            return cur.rowcount

        # ── Assign each case ──────────────────────────────────────
        for row in cases:
            (case_id, case_num, status, face_amount, product_code,
             outcome, primary_reason, aps_count, exam_required) = row

            face_amount   = float(face_amount) if face_amount else 0
            product_code  = str(product_code  or "").upper().strip()
            outcome       = str(outcome        or "").upper()
            primary_reason= str(primary_reason or "").lower()
            aps_count     = int(aps_count       or 0)
            exam_required = str(exam_required   or "").upper()

            # Build a lightweight case dict for _is_medical_case
            _case_dict = {
                "outcome":        outcome,
                "exam_required":  exam_required,
                "aps_count":      aps_count,
                "primary_reason": primary_reason,
            }
            is_medical = route_medical and _is_medical_case(_case_dict)

            assigned = False
            try:
                # ── Medical routing ───────────────────────────────
                if is_medical and medical_officers:
                    # Try medical officers first (sorted by active_cases)
                    for uw in sorted(medical_officers,
                                     key=lambda u: u["active_cases"]):
                        if not _eligible(uw, face_amount, product_code):
                            continue
                        rows_updated = _do_assign(case_id, uw)
                        if rows_updated > 0:
                            uw["active_cases"] += 1
                            result["assigned"]       += 1
                            result["medical_routed"] += 1
                            result["details"].append(
                                f"🩺 {case_num} (medical, {face_amount:,.0f}) "
                                f"→ {uw['username']} (medical officer)"
                            )
                            assigned = True
                            break

                    # If no medical officer could take it, fall through to standard
                    if not assigned:
                        result["details"].append(
                            f"ℹ️ {case_num} is medical but no eligible medical officer "
                            f"— trying standard UW pool."
                        )

                # ── Standard routing (also fallback for medical) ──
                if not assigned:
                    # For medical cases without a medical officer, prefer
                    # senior_underwriter over plain underwriter
                    pool = sorted(
                        standard_uw,
                        key=lambda u: (
                            0 if (is_medical and u["role"] == "senior_underwriter") else 1,
                            u["active_cases"]
                        )
                    )
                    for uw in pool:
                        if not _eligible(uw, face_amount, product_code):
                            continue
                        rows_updated = _do_assign(case_id, uw)
                        if rows_updated > 0:
                            uw["active_cases"] += 1
                            standard_uw.sort(key=lambda u: u["active_cases"])
                            result["assigned"] += 1
                            tag = "🩺 medical→senior" if is_medical else "✅"
                            result["details"].append(
                                f"{tag} {case_num} ({face_amount:,.0f}) "
                                f"→ {uw['username']}"
                            )
                            assigned = True
                            break

                if not assigned:
                    result["skipped"] += 1
                    reason = ("no eligible medical officer or UW within authority limits"
                              if is_medical else
                              "face amount outside all authority limits")
                    result["details"].append(
                        f"⚠️ {case_num} ({face_amount:,.0f}) — {reason}"
                    )

            except Exception as ae:
                result["errors"] += 1
                result["details"].append(f"❌ {case_num}: {ae}")
                try:
                    conn.rollback()
                except Exception as _exc:
                    logger.warning("[_auto_assign_referred_cases] Suppressed exception", exc_info=_exc)

        cur.close(); _release_db_conn(conn)

    except Exception as ex:
        result["errors"] += 1
        result["details"].append(f"Fatal error: {ex}")

    return result



def render_batch_jobs():
    """Enterprise Batch Processing — upload, monitor, download results."""
    import pandas as pd
    from datetime import datetime as _dt

    _ensure_batch_tables()

    tok = st.session_state.get("token","")
    hdr = {"Authorization": f"Bearer {tok}"}

    # ── Heading ──
    st.markdown("## 📦 Batch Underwriting Jobs")
    st.caption("Upload CSV or Excel files for bulk underwriting. Results downloadable as CSV/Excel.")

    # ── Auto-refresh check — BEFORE any rendering, preserves all tabs ──
    import time as _ar_time
    _auto_on_check = st.session_state.get("jm_auto_refresh", False)

    # ── Tab navigation — button row with Auto toggle ──
    _TAB_NAMES = ["📤 Upload Batch", "📋 Job Monitor", "📊 Results & Downloads", "⏰ Schedule"]
    _active_tab = st.session_state.get("batch_active_tab", 0)
    _tb1, _tb2, _tb3, _tb4, _tb5 = st.columns([2,2,2,2,1])
    for _ti, (_tc, _tn) in enumerate(zip([_tb1,_tb2,_tb3,_tb4], _TAB_NAMES)):
        if _tc.button(_tn, key=f"btab_{_ti}", use_container_width=True,
                      type="primary" if _active_tab == _ti else "secondary"):
            st.session_state["batch_active_tab"] = _ti
            _active_tab = _ti
            st.rerun()
    # Auto toggle always visible next to tabs
    _auto_on_check = _tb5.toggle("⚡", key="jm_auto_refresh",
        help="Auto-refresh Job Monitor every 5 seconds")
    if _auto_on_check:
        st.caption("🔄 Auto-refresh ON — Job Monitor refreshes every 5 seconds")
    st.markdown("---")

    # Only render the active tab's content
    _render_upload  = (_active_tab == 0)
    _render_jobs    = (_active_tab == 1)
    _render_results = (_active_tab == 2)
    _render_sched   = (_active_tab == 3)

    # ── Tab 1: Upload ─────────────────────────────────────────
    if _render_upload:
        col1, col2 = st.columns([2,1])

        # Validation results stored in session state so col2 always renders
        _batch_val_errors   = st.session_state.get("batch_val_errors", [])
        _batch_val_warnings = st.session_state.get("batch_val_warnings", [])
        _batch_val_ok       = st.session_state.get("batch_val_ok", None)

        with col1:
            st.markdown("**Upload Batch File**")
            with st.form("batch_upload_form"):
                job_name  = st.text_input("Job Name", placeholder="e.g. March 2026 New Business", help="Descriptive name for this batch run. Appears in the job history table for tracking.")
                up_file   = st.file_uploader("Select CSV or Excel file", type=["csv","xlsx","xls"], help="Upload a file with one applicant per row. Required columns: age, gender, face_amount, product_code. Download the template for the full column list.")
                from datetime import date as _date
                bu1, bu2 = st.columns(2)
                batch_eff = bu1.date_input("Policy Effective Date",
                    value=_date.today(),
                    help="Applied to all applications in this batch as the policy effective date")
                batch_exp = bu2.date_input("Policy Expire Date",
                    value=None,
                    help="Applied as the policy expire date for all records — leave blank if specified per row in the file")
                dry_run      = st.checkbox("Dry Run (validate only, no UW decisions)", help="Validates all rows for format errors and eligibility without running the underwriting engine. Use this to check your file before a live batch run.")
                skip_prod_err = st.checkbox(
                    "⚠️ Skip product errors — process valid rows anyway",
                    value=False,
                    help=(
                        "When checked: rows with invalid/expired/inactive product codes are "
                        "skipped and recorded in the error output file, but all other valid rows "
                        "are processed normally. "
                        "When unchecked (default): any product error blocks the entire batch — "
                        "nothing is submitted until all product codes are fixed."
                    )
                )
                st.divider()
                auto_assign = st.checkbox(
                    "🎯 Auto-assign referred cases to eligible underwriters",
                    value=True,
                    help=(
                        "After the batch runs, any case that lands in REFERRED / further evaluation "
                        "is automatically assigned to the underwriter with the fewest active cases "
                        "whose face amount authority covers the case. Cases outside all authority "
                        "limits are left unassigned and flagged for manual review."
                    )
                )
                auto_assign_sla = st.number_input(
                    "SLA hours for auto-assigned cases",
                    min_value=1, max_value=240, value=48, step=8,
                    help="Number of hours from now set as the SLA deadline for auto-assigned cases. Standard is 48 hours."
                )
                route_medical_batch = st.checkbox(
                    "🩺 Route medical cases to medical officers",
                    value=True,
                    help=(
                        "When checked, cases flagged as medical (REQUEST_APS outcome, "
                        "exam required, or APS already pending) are routed to users "
                        "flagged as Medical Officer in User Management → Authority Limits. "
                        "Falls back to senior underwriter if no medical officer is available."
                    )
                ) if auto_assign else False
                st.divider()
                enable_ai_scoring = st.checkbox(
                    "🤖 Enable AI Risk Scoring for each row",
                    value=False,
                    help="Runs AI risk scoring on each applicant after the rules engine. Adds ai_risk_score, ai_risk_band, ai_recommendation columns to the results CSV."
                )
                ai_engine_batch = st.selectbox(
                    "AI Engine for Batch Scoring",
                    options=["xgboost", "rules_only", "ollama", "claude"],
                    format_func=lambda x: {"xgboost": "XGBoost ML Model", "rules_only": "Rules Only", "ollama": "Ollama LLM (AI Server)", "claude": "Claude AI (Anthropic)"}.get(x, x),
                    help="XGBoost runs locally and is fastest for batch. Ollama requires AI server. Claude uses Anthropic API."
                )
                st.caption("AI scoring adds ~20-50ms per row. For 1000 rows expect ~30-60 seconds extra.")
                st.caption("Max file size: 10MB. Download template for correct column format.")
                _submitted_batch = st.form_submit_button("📤 Submit Batch", use_container_width=True, type="primary")

            # ── Diagnostic: test single record to diagnose SY001 ──
            with st.expander("🔬 Diagnose SY001 errors — test a single record"):
                st.caption("Use this to find out exactly what error the engine returns for a specific record.")
                with st.form("diag_form"):
                    _d1,_d2,_d3 = st.columns(3)
                    _diag_prod = _d1.text_input("Product Code", "BSLI-END-10")
                    _diag_age  = _d2.number_input("Age", 18, 80, 30)
                    _diag_gen  = _d3.selectbox("Gender", ["MALE","FEMALE"])
                    _d4,_d5,_d6 = st.columns(3)
                    _diag_state = _d4.text_input("State", "WB")
                    _diag_face  = _d5.number_input("Face Amount", 100000, 5000000, 200000, step=50000)
                    _diag_tob   = _d6.selectbox("Tobacco", ["NON_TOBACCO","SMOKER","NEVER"])
                    if st.form_submit_button("🔬 Test Record", use_container_width=True):
                        _test_payload = {
                            "applicant_ref": "DIAG-001",
                            "product_code": _diag_prod.strip().upper(),
                            "age": _diag_age,
                            "gender": _diag_gen,
                            "state": _diag_state.strip().upper(),
                            "face_amount": _diag_face,
                            "tobacco_status": _diag_tob,
                            "coverage_term_yrs": 20,
                            "height_inches": 68,
                            "weight_lbs": 170,
                            "systolic_bp": 120,
                            "diastolic_bp": 80,
                            "diabetes_type": "NONE",
                            "hazardous_activity": False,
                            "annual_income": 100000,
                            "existing_coverage": 0
                        }
                        try:
                            _diag_r = requests.post(
                                f"{API_BASE}/underwriting/evaluate",
                                headers=hdr, json=_test_payload, timeout=15
                            )
                            if _diag_r.status_code == 200:
                                _dr = _diag_r.json()
                                _outcome = _dr.get("outcome","—")
                                _score   = _dr.get("net_debit_points", _dr.get("total_debits","—"))
                                st.success(f"✅ Engine responded: **{_outcome}** | Score: {_score}")
                                if _dr.get("error_codes"):
                                    st.error(f"Error codes: {_dr['error_codes']}")
                                with st.expander("Full response"):
                                    st.json(_dr)
                            else:
                                st.error(f"❌ Status {_diag_r.status_code}: {_diag_r.text[:500]}")
                                # Try batch endpoint instead
                                st.caption("Trying batch evaluate endpoint...")
                                _diag_r2 = requests.post(
                                    f"{API_BASE}/batch/evaluate",
                                    headers=hdr, json={"records": [_test_payload]}, timeout=15
                                )
                                if _diag_r2.status_code == 200:
                                    st.json(_diag_r2.json())
                                else:
                                    st.error(f"Batch evaluate: {_diag_r2.status_code}: {_diag_r2.text[:500]}")
                        except Exception as _de:
                            st.error(f"Request failed: {_de}")

            # ── Validation results displayed OUTSIDE form so col2 still renders ──
            if _submitted_batch:
                st.session_state.pop("batch_val_errors", None)
                st.session_state.pop("batch_val_warnings", None)
                st.session_state.pop("batch_val_ok", None)
                _val_errs, _val_warns, _val_ok = [], [], False

                if not up_file:
                    _val_errs.append("Please select a file to upload.")
                else:
                    _seed_product_error_codes()
                    try:
                        import pandas as _pd_batch, io as _io_batch
                        _bf = up_file.getvalue()
                        if up_file.name.lower().endswith(".csv"):
                            _bdf = _pd_batch.read_csv(_io_batch.BytesIO(_bf))
                        else:
                            _bdf = _pd_batch.read_excel(_io_batch.BytesIO(_bf))
                        _bcols = [c.lower().strip() for c in _bdf.columns]

                        # Check product_code column exists
                        if "product_code" not in _bcols:
                            if "product_type" in _bcols:
                                _val_errs.append(
                                    "[PROD_TYPE_INVALID] Your file has `product_type` but not `product_code`. "
                                    "Rules and thresholds are product-specific — the engine cannot underwrite "
                                    "without the exact product code. Replace `product_type` with `product_code` "
                                    "(e.g. IND-TERM-20, BSLI-END-10). Download the updated template."
                                )
                            else:
                                _val_errs.append(
                                    "[PROD_NOT_FOUND] Missing `product_code` column. "
                                    "Columns found: " + ", ".join(_bdf.columns.tolist()) + ". "
                                    "Download the updated template from the right panel."
                                )
                        else:
                            # Validate each unique product_code
                            _unique_codes = _bdf["product_code"].dropna().unique().tolist()
                            _error_prod_codes = []  # track which codes are bad for error file
                            for _pcode in _unique_codes:
                                _pcode_str = str(_pcode).strip().upper()
                                _perrs = validate_product_for_submission(_pcode_str)
                                if _perrs:
                                    _row_count = len(_bdf[_bdf["product_code"].astype(str).str.upper().str.strip() == _pcode_str])
                                    for _pe in _perrs:
                                        _msg = (f"[{_pe['error_code']}] Product '{_pcode_str}' "
                                                f"({_row_count} rows): {_pe['message']} "
                                                f"| Fix: {_pe['resolution']}")
                                        if _pe["severity"] == "ERROR":
                                            _val_errs.append(_msg)
                                            if _pcode_str not in _error_prod_codes:
                                                _error_prod_codes.append(_pcode_str)
                                        else:
                                            _val_warns.append(_msg)

                            if _val_errs and skip_prod_err:
                                # Skip mode: mark errors as warnings, proceed with valid rows
                                _val_warns = _val_errs + _val_warns
                                _val_errs  = []
                                _val_warns.insert(0,
                                    f"⚠️ SKIP MODE ACTIVE — {len(_error_prod_codes)} invalid product(s) "
                                    f"({', '.join(_error_prod_codes)}) will be excluded from processing "
                                    f"and recorded in the error output file."
                                )
                                st.session_state["batch_error_prod_codes"] = _error_prod_codes
                                _val_ok = True
                            elif not _val_errs:
                                _val_ok = True
                                st.session_state.pop("batch_error_prod_codes", None)
                    except Exception as _bve:
                        _val_warns.append(f"Pre-validation skipped ({_bve}) — submitting anyway.")
                        _val_ok = True

                st.session_state["batch_val_errors"]   = _val_errs
                st.session_state["batch_val_warnings"]  = _val_warns
                st.session_state["batch_val_ok"]        = _val_ok

                # If valid — submit to API
                if _val_ok:
                    _err_codes_skip = st.session_state.get("batch_error_prod_codes", [])
                    with st.spinner("Uploading and queuing..."):
                        try:
                            # If skip mode, filter out bad product rows client-side
                            # and generate an error CSV for them
                            _file_bytes = up_file.getvalue()
                            _error_csv_bytes = None
                            if skip_prod_err and _err_codes_skip:
                                import pandas as _pd2, io as _io2
                                _full_df = _pd2.read_csv(_io2.BytesIO(_file_bytes)) if up_file.name.lower().endswith(".csv") else _pd2.read_excel(_io2.BytesIO(_file_bytes))
                                _mask_bad = _full_df["product_code"].astype(str).str.upper().str.strip().isin(
                                    [c.upper() for c in _err_codes_skip]
                                )
                                _error_rows = _full_df[_mask_bad].copy()
                                _good_rows  = _full_df[~_mask_bad].copy()
                                # Add error annotation columns
                                _error_rows["error_code"]    = "PROD_NOT_FOUND"
                                _error_rows["error_message"] = _error_rows["product_code"].apply(
                                    lambda c: f"Product '{str(c).upper()}' not found in system — row skipped"
                                )
                                _error_rows["batch_status"]  = "SKIPPED"
                                _err_buf = _io2.BytesIO()
                                _error_rows.to_csv(_err_buf, index=False)
                                _error_csv_bytes = _err_buf.getvalue()
                                # Submit only the good rows
                                _good_buf = _io2.BytesIO()
                                _good_rows.to_csv(_good_buf, index=False)
                                _file_bytes = _good_buf.getvalue()
                                st.info(
                                    f"📋 Skip mode: submitting **{len(_good_rows)} valid rows**, "
                                    f"**{len(_error_rows)} rows skipped** (invalid product codes). "
                                    f"Download the error file below to see skipped records."
                                )
                                # Store error CSV for immediate download
                                st.session_state["batch_error_csv"] = _error_csv_bytes
                                st.session_state["batch_error_csv_name"] = f"skipped_rows_{up_file.name}"

                            # ── State code normalisation ──
                            # The backend validates against US states by default.
                            # Read our configured state_codes table and remap the
                            # state column so the engine accepts them.
                            try:
                                import pandas as _pd_sc2, io as _io_sc
                                _sc_df = _pd_sc2.read_csv(_io_sc.BytesIO(_file_bytes))                                     if up_file.name.lower().endswith(".csv")                                     else _pd_sc2.read_excel(_io_sc.BytesIO(_file_bytes))

                                if "state" in [c.lower() for c in _sc_df.columns]:
                                    # Load valid codes from DB
                                    _valid_states = _get_state_codes()
                                    _valid_upper  = [s.upper() for s in _valid_states]

                                    # Normalise state column to uppercase
                                    _state_col = [c for c in _sc_df.columns if c.lower() == "state"][0]
                                    _sc_df[_state_col] = _sc_df[_state_col].astype(str).str.strip().str.upper()

                                    # Count invalid states
                                    _invalid_states = _sc_df[
                                        ~_sc_df[_state_col].isin(_valid_upper)
                                    ][_state_col].unique().tolist()

                                    if _invalid_states:
                                        # Try mapping: if backend uses US codes, replace state
                                        # with a placeholder "XX" for non-US to bypass validation
                                        # OR flag them as warnings
                                        st.warning(
                                            f"⚠️ {len(_invalid_states)} state code(s) in your file "
                                            f"are not in the configured state list: "
                                            f"**{', '.join(_invalid_states[:10])}**. "
                                            f"Rows with these states may get DQ008 errors from the engine. "
                                            f"The state codes ARE saved in System Config → State Codes, "
                                            f"but the backend engine validates against its own list. "
                                            f"**Workaround:** Add a `state_bypass=true` column to skip "
                                            f"state validation, or contact your admin to update the "
                                            f"backend's VALID_STATES list."
                                        )
                                    # Re-serialise the normalised file
                                    _sc_buf = _io_sc.BytesIO()
                                    _sc_df.to_csv(_sc_buf, index=False)
                                    _file_bytes = _sc_buf.getvalue()
                            except Exception as _sc_err:
                                pass  # state normalisation is best-effort

                            # ── Field value normalisation ──
                            # Batch files often use shorthand values that the engine rejects
                            # with SY001 (unhandled exception). Normalise to expected enums.
                            try:
                                import pandas as _pd_norm, io as _io_norm
                                _norm_df = _pd_norm.read_csv(_io_norm.BytesIO(_file_bytes))                                     if up_file.name.lower().endswith(".csv")                                     else _pd_norm.read_excel(_io_norm.BytesIO(_file_bytes))
                                _normalised = False
                                _norm_cols = [c.lower() for c in _norm_df.columns]

                                # ── Gender: M→MALE, F→FEMALE ──
                                if "gender" in _norm_cols:
                                    _gc = [c for c in _norm_df.columns if c.lower()=="gender"][0]
                                    _before = _norm_df[_gc].astype(str).str.strip()
                                    _norm_df[_gc] = _before.str.upper().map(
                                        lambda v: {
                                            "M":"MALE","MALE":"MALE",
                                            "F":"FEMALE","FEMALE":"FEMALE",
                                            "1":"MALE","2":"FEMALE"
                                        }.get(v, v)
                                    )
                                    if not _before.equals(_norm_df[_gc]):
                                        _normalised = True

                                # ── Tobacco: Y/YES/S/1→SMOKER, N/NO/0→NON_TOBACCO ──
                                if "tobacco_status" in _norm_cols:
                                    _tc = [c for c in _norm_df.columns if c.lower()=="tobacco_status"][0]
                                    _before2 = _norm_df[_tc].astype(str).str.strip()
                                    _norm_df[_tc] = _before2.str.upper().map(
                                        lambda v: {
                                            "Y":"SMOKER","YES":"SMOKER","S":"SMOKER",
                                            "N":"NON_TOBACCO","NO":"NON_TOBACCO",
                                            "1":"SMOKER","0":"NON_TOBACCO",
                                            "TRUE":"SMOKER","FALSE":"NON_TOBACCO",
                                            "NON_TOBACCO":"NON_TOBACCO",
                                            "NON_SMOKER":"NON_TOBACCO",
                                            "NEVER":"NEVER",
                                            "SMOKER":"SMOKER","TOBACCO":"SMOKER",
                                            "CIGAR":"CIGAR","CHEW":"CHEW","VAPE":"VAPE",
                                        }.get(v, v)
                                    )
                                    if not _before2.equals(_norm_df[_tc]):
                                        _normalised = True

                                # ── Diabetes: map shorthand to engine enum ──
                                if "diabetes_type" in _norm_cols:
                                    _dc = [c for c in _norm_df.columns if c.lower()=="diabetes_type"][0]
                                    _before3 = _norm_df[_dc].astype(str).str.strip()
                                    _norm_df[_dc] = _before3.str.upper().map(
                                        lambda v: {
                                            "NONE":"NONE","NO":"NONE","N":"NONE","0":"NONE",
                                            "TYPE1":"TYPE1","TYPE 1":"TYPE1","T1":"TYPE1","1":"TYPE1",
                                            "TYPE2":"TYPE2","TYPE 2":"TYPE2","T2":"TYPE2","2":"TYPE2",
                                            "PRE":"PRE_DIABETIC","PRE_DIABETIC":"PRE_DIABETIC",
                                            "PRE-DIABETIC":"PRE_DIABETIC",
                                        }.get(v, v)
                                    )
                                    if not _before3.equals(_norm_df[_dc]):
                                        _normalised = True

                                # ── Hazardous activity: Y/N → true/false ──
                                if "hazardous_activity" in _norm_cols:
                                    _hc = [c for c in _norm_df.columns if c.lower()=="hazardous_activity"][0]
                                    _before4 = _norm_df[_hc].astype(str).str.strip()
                                    _norm_df[_hc] = _before4.str.upper().map(
                                        lambda v: {
                                            "Y":"true","YES":"true","1":"true","TRUE":"true",
                                            "N":"false","NO":"false","0":"false","FALSE":"false",
                                        }.get(v, v)
                                    )
                                    if not _before4.equals(_norm_df[_hc]):
                                        _normalised = True

                                # ── Heart condition: map shorthand ──
                                if "heart_condition" in _norm_cols:
                                    _hcc = [c for c in _norm_df.columns if c.lower()=="heart_condition"][0]
                                    _norm_df[_hcc] = _norm_df[_hcc].astype(str).str.strip().str.upper().map(
                                        lambda v: {
                                            "NONE":"NONE","NO":"NONE","N":"NONE","0":"NONE",
                                            "HT":"HYPERTENSION","HTN":"HYPERTENSION",
                                            "MI":"MI","HEART ATTACK":"MI",
                                        }.get(v, v)
                                    )

                                if _normalised:
                                    _norm_info = []
                                    if "gender" in _norm_cols:
                                        _norm_info.append("gender (M→MALE/F→FEMALE)")
                                    if "tobacco_status" in _norm_cols:
                                        _norm_info.append("tobacco (Y/YES→SMOKER, N/NO→NON_TOBACCO)")
                                    if "diabetes_type" in _norm_cols:
                                        _norm_info.append("diabetes (TYPE1/TYPE2)")
                                    st.info(f"🔧 Auto-normalised fields: {', '.join(_norm_info)} — shorthand values mapped to engine format")

                                _norm_buf = _io_norm.BytesIO()
                                _norm_df.to_csv(_norm_buf, index=False)
                                _file_bytes = _norm_buf.getvalue()

                            except Exception as _norm_err:
                                st.warning(f"⚠️ Field normalisation skipped: {_norm_err}")

                            resp = requests.post(
                                f"{API_BASE}/batch/upload",
                                headers=hdr,
                                params={"job_name": job_name or "Batch Job", "dry_run": dry_run,
                                        "skip_product_errors": skip_prod_err,
                                        "policy_effective_date": str(batch_eff) if batch_eff else None,
                                        "policy_expire_date":    str(batch_exp) if batch_exp else None},
                                files={"file": (up_file.name, _file_bytes, "text/csv")}
                            )
                            if resp.status_code == 200:
                                r = resp.json()
                                st.success(f"✅ Job queued: **{r['job_number']}**")
                                st.info(f"Total submitted: {r['total_records']} | Valid: {r.get('valid_records',0)} | Errors: {r.get('invalid_records',0)}")
                                if r.get('invalid_records', 0) > 0:
                                    st.warning(f"⚠️ {r['invalid_records']} records have validation errors — see Job Monitor for details")
                                st.session_state["active_job_id"] = r.get("job_id","")
                                st.session_state.pop("batch_val_errors", None)
                                st.session_state.pop("batch_val_warnings", None)
                                st.session_state.pop("batch_val_ok", None)
                                # BUG3 FIX: redirect to Job Monitor (tab 1) after successful submission
                                st.session_state["batch_active_tab"] = 1

                                # ── Auto-assign referred cases ────────────────
                                if auto_assign:
                                    import time as _wait
                                    with st.spinner("⏳ Waiting for batch to process before assigning..."):
                                        _wait.sleep(3)
                                    with st.spinner("🎯 Auto-assigning referred cases..."):
                                        _aa = _auto_assign_referred_cases(
                                            job_id=r.get("job_id"),
                                            sla_hours=int(auto_assign_sla),
                                            route_medical=route_medical_batch,
                                        )
                                    if _aa["assigned"] > 0:
                                        med_note = (f" ({_aa['medical_routed']} to medical officers)"
                                                    if _aa.get("medical_routed", 0) > 0 else "")
                                        st.success(
                                            f"🎯 Auto-assigned **{_aa['assigned']}** referred "
                                            f"case(s){med_note}."
                                        )
                                    if _aa["skipped"] > 0:
                                        st.warning(
                                            f"⚠️ **{_aa['skipped']}** case(s) could not be "
                                            f"auto-assigned — face amount outside all authority limits. "
                                            f"Assign manually in UW Queue."
                                        )
                                    if _aa["details"]:
                                        with st.expander(
                                            f"Assignment details ({_aa['assigned']} assigned, "
                                            f"{_aa['skipped']} skipped, {_aa['errors']} errors)"
                                        ):
                                            for d in _aa["details"]:
                                                st.caption(d)
                            else:
                                try:    st.error(f"❌ {resp.json().get('detail', resp.text[:300])}")
                                except: st.error(f"❌ Upload failed: {resp.text[:300]}")
                        except Exception as _ue:
                            st.error(f"❌ Could not reach API: {_ue}")

                    # Show download button for skipped rows error file
                    _err_csv = st.session_state.get("batch_error_csv")
                    if _err_csv:
                        st.download_button(
                            "📥 Download Skipped Rows (Error File)",
                            data=_err_csv,
                            file_name=st.session_state.get("batch_error_csv_name","skipped_rows.csv"),
                            mime="text/csv",
                            help="CSV containing all rows that were skipped due to invalid product codes, "
                                 "with error_code and error_message columns added."
                        )

            # Display persisted validation results
            _batch_val_errors   = st.session_state.get("batch_val_errors", [])
            _batch_val_warnings = st.session_state.get("batch_val_warnings", [])
            _batch_val_ok       = st.session_state.get("batch_val_ok", None)

            if _batch_val_warnings:
                for w in _batch_val_warnings:
                    st.warning(f"⚠️ {w}")
            if _batch_val_errors:
                st.error(f"🚫 {len(_batch_val_errors)} error(s) — fix before submitting:")
                for e in _batch_val_errors:
                    st.error(e)
            elif _batch_val_ok:
                st.success("✅ All product codes validated successfully")

        with col2:
            st.markdown("**Resources**")

            # ── Generate correct template with product_code ──
            # Load all available products for the template
            try:
                _wb_prods, _ = _load_all_products()
                _prod_codes = list(_wb_prods.keys())
                _example_code = _prod_codes[0] if _prod_codes else "IND-TERM-20"
            except Exception as _exc:
                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                _example_code = "IND-TERM-20"

            # Build template CSV with product_code (not product_type)
            _template_csv = (
                "applicant_ref,product_code,age,gender,state,face_amount,"
                "coverage_term_yrs,tobacco_status,tobacco_quit_years,"
                "height_inches,weight_lbs,systolic_bp,diastolic_bp,"
                "heart_condition,heart_event_years_ago,"
                "diabetes_type,diabetes_dx_age,a1c,"
                "cancer_status,cancer_free_years,"
                "depression_history,depression_hospitalized,"
                "kidney_disease,copd,stroke_history,"
                "alcohol_drinks_week,hazardous_activity,"
                "occupation_class,occupation_title,"
                "annual_income,existing_coverage\n"
                f"SAMPLE-001,{_example_code},40,MALE,CA,500000,"
                "20,NON_TOBACCO,,70,175,120,78,"
                "NONE,,NONE,,,"
                "NONE,,"
                "false,false,"
                "false,false,false,"
                "4,false,"
                "1,Software Engineer,"
                "100000,0\n"
                f"SAMPLE-002,{_example_code},52,FEMALE,TX,250000,"
                "10,NON_TOBACCO,,65,155,138,88,"
                "HYPERTENSION,,"
                "TYPE2,45,7.8,"
                "NONE,,"
                "false,false,"
                "false,false,false,"
                "6,false,"
                "2,Manager,"
                "80000,200000\n"
            )
            st.download_button(
                "📥 Download CSV Template",
                _template_csv, "batch_template.csv", "text/csv",
                use_container_width=True,
                help="Download the correct template with product_code column"
            )

            # Also try API template as secondary option
            try:
                resp_t = requests.get(f"{API_BASE}/batch/template", headers=hdr, timeout=3)
                if resp_t.status_code == 200:
                    st.download_button(
                        "📥 API Template (legacy)",
                        resp_t.content, "batch_template_api.csv", "text/csv",
                        use_container_width=True,
                        help="Original template from API — uses product_type instead of product_code"
                    )
            except Exception as _exc:
                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

            st.divider()
            st.error("⚠️ **product_code required**", icon="🚨")
            st.caption(
                "The batch file must include **product_code** (e.g. `IND-TERM-20`, `BSLI-END-10`) "
                "— NOT `product_type`. Rules, thresholds and build tables are all looked up "
                "by product_code. Without it the engine cannot apply product-specific rules."
            )
            st.divider()

            # Show available product codes for reference
            with st.expander("📋 Available Product Codes"):
                try:
                    _wb_prods2, _wb_cats2 = _load_all_products()
                    for _cat, _codes in _wb_cats2.items():
                        st.markdown(f"**{_cat}**")
                        for _c in _codes:
                            _pname = _wb_prods2.get(_c, {}).get("name", "")
                            st.caption(f"`{_c}` — {_pname}")
                except Exception as _exc:
                    logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                    st.caption("Could not load product list")

            st.divider()
            st.markdown("**Processing Modes**")
            st.caption("🟢 **Live** — full UW evaluation, creates cases")
            st.caption("🟡 **Dry Run** — validate only, no cases created")

    # ── Tab 2: Job Monitor ────────────────────────────────────
    if _render_jobs:
        _jm_col1, _jm_col2 = st.columns([5, 1])
        _jm_col1.caption("Live job status — refresh to see latest progress.")
        if _jm_col2.button("🔄 Refresh", key="refresh_jobs", help="Reload job list now"):
            st.rerun()

        jobs = []
        _jobs_source = "none"
        # Try API
        try:
            jobs_r = requests.get(f"{API_BASE}/batch/jobs", headers=hdr, timeout=10)
            if jobs_r.status_code == 200:
                jobs = jobs_r.json().get("jobs", [])
                _jobs_source = "api"
        except Exception as _exc:
            logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

        # Fall back to direct DB
        if not jobs:
            try:
                _conn_j = _get_db_conn()
                if _conn_j:
                    _cur_j = _conn_j.cursor()
                    _cur_j.execute("""
                        SELECT id, job_number, job_name, status,
                               COALESCE(total_records,0),
                               COALESCE(approved_count,0),
                               COALESCE(declined_count,0),
                               COALESCE(referred_count,0),
                               COALESCE(errored_count,0),
                               COALESCE(processed_count,0),
                               COALESCE(dry_run,false),
                               submitted_at, completed_at,
                               COALESCE(submitted_by,''),
                               COALESCE(input_filename,''),
                               COALESCE(error_message,'')
                        FROM batch_jobs
                        ORDER BY submitted_at DESC LIMIT 50
                    """)
                    rows = _cur_j.fetchall()
                    _cur_j.close(); _conn_j.close()
                    jobs = [{
                        "id": r[0], "job_number": r[1], "job_name": r[2] or "",
                        "status": r[3], "total_records": r[4] or 0,
                        "approved": r[5] or 0, "declined": r[6] or 0,
                        "referred": r[7] or 0, "errored": r[8] or 0,
                        "processed": r[9] or 0, "dry_run": r[10],
                        "submitted_at": str(r[11] or ""), "completed_at": str(r[12] or ""),
                        "submitted_by": r[13] or "", "input_filename": r[14] or "",
                        "error_message": r[15] or "",
                    } for r in rows]
                    _jobs_source = "db"
            except Exception as _je:
                st.warning(f"⚠️ Could not load jobs from API or DB: {_je}")

        if _jobs_source == "db":
            st.caption("ℹ️ Loaded from database (API unavailable)")

        if not jobs:
            st.info("No batch jobs yet. Upload a file in the Upload Batch tab to get started.")
        else:
            # Summary metrics — use markdown table to avoid column truncation
            _total_jobs  = len(jobs)
            _processing  = sum(1 for j in jobs if j["status"]=="PROCESSING")
            _completed   = sum(1 for j in jobs if j["status"]=="COMPLETED")
            _failed      = sum(1 for j in jobs if j["status"] in ("FAILED","CANCELLED"))
            _rec_total   = sum(j.get("total_records",0) for j in jobs)
            _rec_proc    = sum(j.get("processed",0) or j.get("processed_count",0) for j in jobs)

            _sm1,_sm2,_sm3 = st.columns(3)
            _sm1.metric("Total Jobs",    f"{_total_jobs:,}")
            _sm2.metric("🟡 Processing", f"{_processing:,}")
            _sm3.metric("🟢 Completed",  f"{_completed:,}")
            _sm4,_sm5,_sm6 = st.columns(3)
            _sm4.metric("🔴 Failed",        f"{_failed:,}")
            _sm5.metric("Records Total", f"{_rec_total:,}")
            _sm6.metric("Processed",     f"{_rec_proc:,}")
            st.divider()

            # Sort: active jobs first, then newest-first within each status group
            _status_order = {"PROCESSING":0,"QUEUED":1,"PENDING":1,"FAILED":2,"COMPLETED":3,"CANCELLED":4}
            def _job_sort_key(j):
                s_ord = _status_order.get(j.get("status",""), 5)
                s_dt  = str(j.get("submitted_at") or "0000-00-00T00:00:00")[:19]
                return (s_ord, [-ord(c) for c in s_dt])
            jobs_sorted = sorted(jobs, key=_job_sort_key)

            for job in jobs_sorted:
                _jstatus = job["status"]
                st_emoji = {
                    "COMPLETED":"🟢","PROCESSING":"🟡","QUEUED":"⏳",
                    "FAILED":"🔴","CANCELLED":"⚫","PENDING":"⏳"
                }.get(_jstatus,"⚪")
                total = job.get("total_records",0) or 1
                processed = job.get("processed",0) or job.get("processed_count",0)
                pct = int((processed/total)*100)

                # Auto-expand jobs that are actively processing
                _is_active = _jstatus in ("PROCESSING","QUEUED","PENDING")
                with st.expander(
                    f"{st_emoji} **{job['job_number']}** — {job.get('job_name','Batch Job')} "
                    f"| {_jstatus} | {job.get('total_records',0):,} records "
                    f"{'| DRY RUN' if job.get('dry_run') else ''}",
                    expanded=_is_active
                ):
                    # ── Per-job refresh button (top right of expander) ──
                    _jcol_hd, _jcol_ref = st.columns([6,1])
                    with _jcol_ref:
                        if st.button("🔄", key=f"ref_{job['id']}",
                                     help="Refresh this job's progress"):
                            # Fetch latest for just this job
                            try:
                                _jr = requests.get(
                                    f"{API_BASE}/batch/jobs/{job['id']}",
                                    headers=hdr, timeout=5
                                )
                                if _jr.status_code == 200:
                                    _updated = _jr.json()
                                    job.update(_updated)
                            except Exception as _exc:
                                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                            st.rerun()

                    # Progress bar for active jobs
                    if _is_active:
                        st.progress(
                            pct/100,
                            f"{'Processing' if _jstatus=='PROCESSING' else 'Queued'}: "
                            f"{processed:,}/{total:,} records ({pct}%)"
                        )
                        st.caption("🔄 Tick **⚡ Auto** above to auto-refresh every 5 seconds")

                    # Decision metrics
                    _jm1,_jm2,_jm3 = st.columns(3)
                    _jm1.metric("✅ Approved",  f"{job.get('approved',0):,}")
                    _jm2.metric("🔴 Declined",  f"{job.get('declined',0):,}")
                    _jm3.metric("🟡 Referred",  f"{job.get('referred',0):,}")
                    _jm4,_jm5 = st.columns(2)
                    _jm4.metric("⚫ Errors",    f"{job.get('errored',0):,}")
                    _jm5.metric("📊 Processed", f"{processed:,} / {total:,}")

                    # Approval rate bar for completed jobs
                    if _jstatus == "COMPLETED" and total > 0:
                        appr = job.get("approved",0)
                        decl = job.get("declined",0)
                        ref  = job.get("referred",0)
                        err  = job.get("errored",0)
                        st.markdown(
                            f"<div style='display:flex;height:8px;border-radius:4px;overflow:hidden;margin:8px 0'>"
                            f"<div style='width:{int(appr/total*100)}%;background:#22c55e'></div>"
                            f"<div style='width:{int(ref/total*100)}%;background:#f59e0b'></div>"
                            f"<div style='width:{int(decl/total*100)}%;background:#ef4444'></div>"
                            f"<div style='width:{int(err/total*100)}%;background:#94a3b8'></div>"
                            f"</div>"
                            f"<div style='font-size:11px;color:#64748b'>"
                            f"🟢 {int(appr/total*100)}% approved &nbsp; "
                            f"🟡 {int(ref/total*100)}% referred &nbsp; "
                            f"🔴 {int(decl/total*100)}% declined &nbsp; "
                            f"⚫ {int(err/total*100)}% errors"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                        # Fire BATCH_COMPLETED notification once per job
                        _notif_key = f"_batch_notif_sent_{job['id']}"
                        if not st.session_state.get(_notif_key):
                            send_notification("BATCH_COMPLETED", {
                                "job_number": job.get("job_number",""),
                                "job_name":   job.get("job_name",""),
                                "total":      total,
                                "approved":   appr,
                                "declined":   decl,
                                "referred":   ref,
                                "errored":    err,
                            })
                            st.session_state[_notif_key] = True

                    if job.get("error_message"):
                        st.error(f"Error: {job['error_message']}")

                    sub_at = str(job.get("submitted_at",""))[:19].replace("T"," ")
                    cmp_at = str(job.get("completed_at",""))[:19].replace("T"," ")
                    st.caption(
                        f"📅 Submitted: {sub_at}  |  "
                        f"👤 {job.get('submitted_by','—').split('@')[0]}  |  "
                        f"📄 {job.get('input_filename','')}  |  "
                        f"✅ Completed: {cmp_at or 'In progress...'}"
                    )

                    # Action buttons
                    if _jstatus == "COMPLETED":
                        dc1, dc2 = st.columns(2)
                        if dc1.button("📊 View Results", key=f"view_{job['id']}",
                                      use_container_width=True, type="primary"):
                            st.session_state["view_job_id"]      = job["id"]
                            st.session_state["batch_active_tab"] = 2
                            st.rerun()
                        if dc2.button("📥 Go to Downloads", key=f"dl_{job['id']}",
                                      use_container_width=True, type="primary"):
                            st.session_state["view_job_id"]      = job["id"]
                            st.session_state["batch_active_tab"] = 2
                            st.rerun()
                    elif _jstatus in ("PENDING","QUEUED"):
                        if st.button("⏹️ Cancel Job", key=f"cancel_{job['id']}",
                                     type="secondary"):
                            requests.post(f"{API_BASE}/batch/jobs/{job['id']}/cancel",
                                          headers=hdr)
                            st.rerun()





    # ── Tab 3: Results & Downloads ────────────────────────────
    if _render_results:
        st.caption("Select a completed job to view results and download reports.")

        # Use cached list unless explicitly refreshed
        _res_col1, _res_col2 = st.columns([5,1])
        if _res_col2.button("🔄", key="results_refresh", help="Reload completed jobs list"):
            st.session_state.pop("_completed_jobs_cache", None)

        done = st.session_state.get("_completed_jobs_cache", [])
        if not done:
            try:
                jobs_r2 = requests.get(f"{API_BASE}/batch/jobs", headers=hdr, timeout=10)
                if jobs_r2.status_code == 200:
                    done = [j for j in jobs_r2.json().get("jobs",[]) if j["status"] == "COMPLETED"]
                    if done:
                        st.session_state["_completed_jobs_cache"] = done
            except Exception as _exc:
                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

        # DB fallback
        if not done:
            try:
                _conn_r = _get_db_conn()
                if _conn_r:
                    _cur_r = _conn_r.cursor()
                    _cur_r.execute("""
                        SELECT id, job_number, job_name,
                               COALESCE(total_records,0),
                               COALESCE(approved_count,0),
                               COALESCE(declined_count,0),
                               COALESCE(referred_count,0),
                               COALESCE(errored_count,0),
                               completed_at
                        FROM batch_jobs WHERE status = 'COMPLETED'
                        ORDER BY completed_at DESC LIMIT 50
                    """)
                    rows_r = _cur_r.fetchall()
                    _cur_r.close(); _conn_r.close()
                    done = [{
                        "id": r[0], "job_number": r[1], "job_name": r[2] or "",
                        "total_records": r[3] or 0, "approved": r[4] or 0,
                        "declined": r[5] or 0, "referred": r[6] or 0,
                        "errored": r[7] or 0, "completed_at": str(r[8] or ""),
                        "status": "COMPLETED"
                    } for r in rows_r]
                    if done:
                        st.caption("ℹ️ Loaded from database (API unavailable)")
            except Exception as _exc:
                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

        if not done:
            st.info("No completed jobs yet. Jobs appear here once processing is complete.")
        else:
            # Pre-select job if navigated from View Results button
            _view_jid = st.session_state.pop("view_job_id", None)
            _done_ids = [j["id"] for j in done]
            _default_idx = 0
            if _view_jid and _view_jid in _done_ids:
                _default_idx = _done_ids.index(_view_jid)

            sel_job = st.selectbox(
                "Select job",
                _done_ids,
                index=_default_idx,
                format_func=lambda jid: next(
                    (f"{j['job_number']} — {j.get('job_name','Batch Job')} "
                     f"({j.get('total_records',0):,} records)"
                     for j in done if j["id"]==jid),
                    jid
                ),
                key="results_job_sel"
            )

            job_detail = {}
            try:
                _jd_r = requests.get(f"{API_BASE}/batch/jobs/{sel_job}",
                    headers=hdr, timeout=10)
                if _jd_r.status_code == 200:
                    job_detail = _jd_r.json()
            except Exception as _exc:
                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

            # DB fallback for job detail
            if not job_detail:
                _sel_from_list = next((j for j in done if j["id"] == sel_job), {})
                if _sel_from_list:
                    job_detail = _sel_from_list
                    st.caption("ℹ️ Loaded from database (API unavailable)")

            if job_detail:
                _total_r = job_detail.get("total_records",1) or 1
                rm1,rm2,rm3,rm4 = st.columns(4)
                rm1.metric("✅ Approved",  f"{job_detail.get('approved',0):,}")
                rm2.metric("🔴 Declined",  f"{job_detail.get('declined',0):,}")
                rm3.metric("🟡 Referred",  f"{job_detail.get('referred',0):,}")
                rm4.metric("⚫ Errors",    f"{job_detail.get('errored',0):,}")

                # Approval rate
                total = job_detail.get("total_records",1) or 1
                appr_pct = int(job_detail.get("approved",0)/total*100)
                decl_pct = int(job_detail.get("declined",0)/total*100)
                ref_pct  = int(job_detail.get("referred",0)/total*100)
                err_pct  = int(job_detail.get("errored",0)/total*100)
                st.markdown(f"**Decision Distribution:** \U0001f7e2 {appr_pct}% approved | "
                            f"\U0001f534 {decl_pct}% declined | "
                            f"\U0001f7e1 {ref_pct}% referred | "
                            f"\u26ab {err_pct}% errors")

                st.divider()
                st.markdown("**Download Reports**")

                # Try API download endpoints first
                _api_dl_ok = False
                dc1,dc2,dc3 = st.columns(3)
                for col, rtype, label in [
                    (dc1,"results","Full Results"),
                    (dc2,"errors","Errors Only"),
                    (dc3,"summary","Summary")
                ]:
                    with col:
                        try:
                            resp_csv = requests.get(
                                f"{API_BASE}/batch/jobs/{sel_job}/download/{rtype}",
                                headers=hdr, params={"fmt":"csv"}, timeout=30)
                            if resp_csv.status_code == 200:
                                _api_dl_ok = True
                                st.markdown(f"**{label}**")
                                fc1, fc2 = st.columns(2)
                                fc1.download_button(
                                    "📥 CSV", resp_csv.content,
                                    f"batch_{rtype}_{sel_job[:8]}.csv","text/csv",
                                    use_container_width=True,
                                    key=f"dl_csv_{rtype}_{sel_job}")
                                try:
                                    resp_xl = requests.get(
                                        f"{API_BASE}/batch/jobs/{sel_job}/download/{rtype}",
                                        headers=hdr, params={"fmt":"xlsx"}, timeout=30)
                                    if resp_xl.status_code == 200:
                                        fc2.download_button(
                                            "📥 Excel", resp_xl.content,
                                            f"batch_{rtype}_{sel_job[:8]}.xlsx",
                                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            use_container_width=True,
                                            key=f"dl_xl_{rtype}_{sel_job}")
                                except Exception as _exc:
                                    logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                        except Exception as _exc:
                            logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

                if not _api_dl_ok:
                    import io as _io_dl
                    _db_rows_loaded = False
                    try:
                        _conn_dl = _get_db_conn()
                        if _conn_dl:
                            _cur_dl = _conn_dl.cursor()
                            _cur_dl.execute("""
                                SELECT row_number, applicant_ref, product_code,
                                       status, outcome, risk_class,
                                       net_debit_points, primary_reason,
                                       error_codes, processing_ms
                                FROM batch_job_records
                                WHERE job_id = %s ORDER BY row_number
                            """, (sel_job,))
                            _rows_dl = _cur_dl.fetchall()
                            _cur_dl.close(); _conn_dl.close()
                            if _rows_dl:
                                _db_rows_loaded = True
                                _df_dl = pd.DataFrame(_rows_dl, columns=[
                                    "row_number","applicant_ref","product_code",
                                    "status","outcome","risk_class",
                                    "net_debit_points","primary_reason",
                                    "error_codes","processing_ms"])
                                _col_a,_col_b,_col_c = st.columns(3)
                                _buf_all = _io_dl.BytesIO()
                                _df_dl.to_csv(_buf_all, index=False)
                                _col_a.download_button("📥 Full Results (CSV)",
                                    _buf_all.getvalue(),
                                    f"batch_full_{sel_job[:8]}.csv","text/csv",
                                    use_container_width=True,
                                    key=f"db_dl_full_{sel_job}")
                                _df_err = _df_dl[
                                    _df_dl["status"].isin(["ERROR","FAILED"]) |
                                    _df_dl["error_codes"].notna()]
                                _buf_err = _io_dl.BytesIO()
                                _df_err.to_csv(_buf_err, index=False)
                                _col_b.download_button("📥 Errors Only (CSV)",
                                    _buf_err.getvalue(),
                                    f"batch_errors_{sel_job[:8]}.csv","text/csv",
                                    use_container_width=True,
                                    key=f"db_dl_err_{sel_job}")
                                _buf_sum = _io_dl.BytesIO()
                                pd.DataFrame([{
                                    "job_id": sel_job,
                                    "total": len(_df_dl),
                                    "approved": len(_df_dl[_df_dl["outcome"]=="APPROVED"]),
                                    "declined": len(_df_dl[_df_dl["outcome"]=="DECLINED"]),
                                    "referred": len(_df_dl[_df_dl["outcome"]=="REFER"]),
                                    "errors": len(_df_dl[_df_dl["status"].isin(
                                        ["ERROR","FAILED"])]),
                                }]).to_csv(_buf_sum, index=False)
                                _col_c.download_button("📥 Summary (CSV)",
                                    _buf_sum.getvalue(),
                                    f"batch_summary_{sel_job[:8]}.csv","text/csv",
                                    use_container_width=True,
                                    key=f"db_dl_sum_{sel_job}")
                    except Exception as _dl_e:
                        st.caption(f"DB download unavailable: {_dl_e}")

                    if not _db_rows_loaded:
                        st.info("ℹ️ Generating summary from job metadata.")
                        _buf_fb = __import__("io").BytesIO()
                        pd.DataFrame([{
                            "job_id":        sel_job,
                            "job_number":    job_detail.get("job_number",""),
                            "job_name":      job_detail.get("job_name",""),
                            "status":        job_detail.get("status",""),
                            "total_records": job_detail.get("total_records",0),
                            "approved":      job_detail.get("approved",0),
                            "declined":      job_detail.get("declined",0),
                            "referred":      job_detail.get("referred",0),
                            "errored":       job_detail.get("errored",0),
                            "submitted_at":  job_detail.get("submitted_at",""),
                            "completed_at":  job_detail.get("completed_at",""),
                        }]).to_csv(_buf_fb, index=False)
                        st.download_button("📥 Summary (CSV)", _buf_fb.getvalue(),
                            f"batch_summary_{sel_job[:8]}.csv","text/csv",
                            use_container_width=True,
                            key=f"fb_dl_sum_{sel_job}")

                    # ── Batch Email Notifications ─────────────────────────────
                    if True:  # Always show email section for completed jobs
                        st.divider()
                        st.markdown("#### 📧 Send Batch Email Notifications")
                        _email_col1, _email_col2 = st.columns([3,1])
                        with _email_col1:
                            st.caption(
                                "Sends decision letters to APPROVED and DECLINED applicants. "
                                "Requires valid email in applicant master and SMTP configured."
                            )
                        with _email_col2:
                            _send_emails_btn = st.button(
                                "📤 Send Emails", type="primary",
                                use_container_width=True,
                                key=f"send_batch_emails_{sel_job}"
                            )
                        if _send_emails_btn:
                            try:
                                from batch_email_validator import BatchEmailValidator, EmailErrorReport, render_email_error_report
                                _bev      = BatchEmailValidator(check_mx=False)
                                _bev.reset_batch()
                                _berr     = EmailErrorReport()
                                _conn_em  = _get_db_conn()
                                _sent_ok  = 0
                                _sent_fail= 0
                                if _conn_em:
                                    _cur_em = _conn_em.cursor()
                                    # Join batch_job_records with applicant_master
                                    _cur_em.execute("""
                                        SELECT b.row_number, b.applicant_ref, b.outcome,
                                               b.primary_reason, b.net_debit_points,
                                               a.full_name, a.email
                                        FROM batch_job_records b
                                        LEFT JOIN applicant_master a
                                            ON a.applicant_ref = b.applicant_ref
                                        WHERE b.job_id = %s
                                          AND b.outcome IN ('APPROVED','DECLINED')
                                        ORDER BY b.row_number
                                    """, (sel_job,))
                                    _email_rows = _cur_em.fetchall()
                                    _cur_em.close(); _conn_em.close()

                                    _prog = st.progress(0)
                                    _total_em = len(_email_rows)
                                    for _ei, (_rn, _ref, _out, _reason, _debits, _name, _email) in enumerate(_email_rows):
                                        _prog.progress((_ei+1)/_total_em if _total_em else 1)
                                        # Validate email
                                        _vr = _bev.validate(_email or "", check_duplicates=True)
                                        if not _vr.is_valid:
                                            _berr.add_error(_rn, _ref, _name or "—", _email or "", _out, _vr)
                                            _sent_fail += 1
                                            continue
                                        # Generate letter
                                        try:
                                            _case_num = f"BATCH-{sel_job[:8]}-{_rn}"
                                            _lbytes, _lfname = get_pdf_download_data(
                                                {"outcome": _out, "applicant_id": _ref,
                                                 "net_debit_points": _debits or 0,
                                                 "risk_class": "—", "rules_fired": [],
                                                 "application_id": _ref,
                                                 "case_id": _case_num,
                                                 "decision_id": f"D-{_rn}",
                                                 "rules_version": "1.0",
                                                 "pathway": "batch",
                                                 "is_stp": False,
                                                 "evaluated_at": datetime.now().isoformat()},
                                                {}
                                            )
                                            _ok, _msg = send_decision_email(
                                                to_email=_email,
                                                applicant_name=_name or _ref,
                                                outcome=_out,
                                                case_number=_case_num,
                                                reason=_reason or "",
                                                letter_bytes=_lbytes,
                                                letter_filename=_lfname,
                                                applicant_ref=_ref,
                                                batch_job_name=job_detail.get("job_name","Batch"),
                                            )
                                            if _ok:
                                                _sent_ok += 1
                                            else:
                                                _smtp_fail = _bev.record_smtp_failure(_email, _msg)
                                                _berr.add_error(_rn, _ref, _name or "—", _email or "", _out, _smtp_fail)
                                                _sent_fail += 1
                                        except Exception as _le:
                                            from batch_email_validator import EmailValidationResult
                                            _berr.add_error(_rn, _ref, _name or "—", _email or "", _out,
                                                EmailValidationResult(is_valid=False, email=_email or "",
                                                    error_code="EMAIL-005", error_detail=str(_le)[:100],
                                                    severity="CRITICAL", action="Check letter generation", retryable=True))
                                            _sent_fail += 1
                                    _prog.empty()
                                    st.success(f"✅ Emails sent: **{_sent_ok}** | Failed: **{_sent_fail}**")
                                    render_email_error_report(_berr, job_detail.get("job_name","Batch"))
                            except Exception as _bem:
                                st.error(f"Batch email error: {_bem}")

                # ── Batch Email Notifications ──────────────────────────
                st.divider()
                st.markdown("#### 📧 Send Batch Email Notifications")
                _em_c1, _em_c2 = st.columns([3,1])
                with _em_c1:
                    st.caption("Sends decision letters to APPROVED and DECLINED applicants. Requires valid email in applicant master and SMTP configured.")
                with _em_c2:
                    _send_btn = st.button("📤 Send Emails", type="primary", use_container_width=True, key=f"send_em_{sel_job}")
                if _send_btn:
                    try:
                        from batch_email_validator import BatchEmailValidator, EmailErrorReport, render_email_error_report
                        _bev = BatchEmailValidator(check_mx=False)
                        _bev.reset_batch()
                        _berr = EmailErrorReport()
                        _conn_em = _get_db_conn()
                        _sent_ok = 0
                        _sent_fail = 0
                        if _conn_em:
                            _cur_em = _conn_em.cursor()
                            _cur_em.execute("""
                                SELECT b.row_number, b.applicant_ref, b.outcome,
                                       b.primary_reason, b.net_debit_points,
                                       a.full_name, a.email
                                FROM batch_job_records b
                                LEFT JOIN applicant_master a ON a.applicant_ref = b.applicant_ref
                                WHERE b.job_id = %s AND b.outcome IN ('APPROVED','DECLINED')
                                ORDER BY b.row_number
                            """, (sel_job,))
                            _email_rows = _cur_em.fetchall()
                            _cur_em.close(); _conn_em.close()
                            _prog = st.progress(0)
                            _total_em = len(_email_rows)
                            if _total_em == 0:
                                st.warning("No APPROVED or DECLINED cases found in this batch.")
                            for _ei, (_rn, _ref, _out, _reason, _debits, _name, _email) in enumerate(_email_rows):
                                _prog.progress((_ei+1)/_total_em)
                                _vr = _bev.validate(_email or "", check_duplicates=True)
                                if not _vr.is_valid:
                                    _berr.add_error(_rn, _ref, _name or "—", _email or "", _out, _vr)
                                    _sent_fail += 1
                                    continue
                                try:
                                    _case_num = f"BATCH-{sel_job[:8]}-{_rn}"
                                    _lbytes, _lfname = get_pdf_download_data(
                                        {"outcome": _out, "applicant_id": _ref,
                                         "net_debit_points": _debits or 0, "risk_class": "—",
                                         "rules_fired": [], "application_id": _ref,
                                         "case_id": _case_num, "decision_id": f"D-{_rn}",
                                         "rules_version": "1.0", "pathway": "batch",
                                         "is_stp": False, "evaluated_at": datetime.now().isoformat()}, {})
                                    _ok, _msg = send_decision_email(
                                        to_email=_email, applicant_name=_name or _ref,
                                        outcome=_out, case_number=_case_num,
                                        reason=_reason or "", letter_bytes=_lbytes,
                                        letter_filename=_lfname,
                                        applicant_ref=_ref, batch_job_name=sel_job[:8])
                                    if _ok:
                                        _sent_ok += 1
                                    else:
                                        from batch_email_validator import EmailValidationResult
                                        _berr.add_error(_rn, _ref, _name or "—", _email or "", _out,
                                            EmailValidationResult(is_valid=False, email=_email or "",
                                                error_code="EMAIL-005", error_detail=_msg,
                                                severity="CRITICAL", action="Check SMTP config", retryable=True))
                                        _sent_fail += 1
                                except Exception as _le:
                                    from batch_email_validator import EmailValidationResult
                                    _berr.add_error(_rn, _ref, _name or "—", _email or "", _out,
                                        EmailValidationResult(is_valid=False, email=_email or "",
                                            error_code="EMAIL-005", error_detail=str(_le)[:100],
                                            severity="CRITICAL", action="Check letter generation", retryable=True))
                                    _sent_fail += 1
                            _prog.empty()
                            st.success(f"✅ Emails sent: **{_sent_ok}** | Failed: **{_sent_fail}**")
                            render_email_error_report(_berr, sel_job[:8])
                    except Exception as _bem:
                        st.error(f"Batch email error: {_bem}")
                # Preview records
                st.divider()
                st.markdown("**Record Preview (first 100)**")
                recs = job_detail.get("records", [])
                if recs:
                    df_prev = pd.DataFrame([{
                        "Row":    r.get("row_number"),
                        "Ref":    r.get("applicant_ref"),
                        "Status": r.get("status"),
                        "Outcome":r.get("outcome","—"),
                        "Risk Class": r.get("risk_class","—"),
                        "Debits": r.get("net_debit_points","—"),
                        "Reason": str(r.get("primary_reason",""))[:60],
                        "Errors": str(r.get("error_codes","")) if r.get("error_codes") else "",
                        "ms":     r.get("processing_ms",""),
                    } for r in recs])
                    st.dataframe(df_prev, use_container_width=True, hide_index=True)

                # ── Queue batch results for policy admin export ───────────────
                st.divider()
                st.markdown("**📤 Policy Admin Export**")
                st.caption(
                    "Queue all decided records from this batch into the policy admin "
                    "export table. Records with status APPROVED / DECLINED / POSTPONED "
                    "/ COUNTER_OFFER are included. Run the extract from "
                    "**System Config → Output Interface** to write the export file."
                )
                _paq_key = f"_paq_queued_{sel_job[:8]}"
                if st.session_state.get(_paq_key):
                    st.success(f"✅ Records from this job are already queued for policy admin export.")
                else:
                    if st.button("📤 Queue for Policy Admin Export",
                                 key=f"queue_paq_{sel_job[:8]}",
                                 use_container_width=True):
                        _queued = 0
                        _skipped = 0
                        # Try from API records first
                        _source_recs = recs or []
                        # DB fallback
                        if not _source_recs:
                            try:
                                _conn_paq = _get_db_conn()
                                if _conn_paq:
                                    _cur_paq = _conn_paq.cursor()
                                    _cur_paq.execute("""
                                        SELECT applicant_ref, product_code,
                                               status, outcome, risk_class,
                                               net_debit_points, primary_reason
                                        FROM batch_job_records
                                        WHERE job_id = %s
                                    """, (sel_job,))
                                    _db_recs = _cur_paq.fetchall()
                                    _cur_paq.close(); _conn_paq.close()
                                    _source_recs = [{
                                        "applicant_ref": r[0],
                                        "product_code": r[1],
                                        "status": r[2],
                                        "outcome": r[3],
                                        "risk_class": r[4],
                                        "net_debit_points": r[5],
                                        "primary_reason": r[6],
                                    } for r in _db_recs]
                            except Exception as _exc:
                                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

                        _decided_outcomes = {
                            "APPROVED","DECLINED","POSTPONED",
                            "COUNTER_OFFER","APPROVED_STANDARD",
                            "APPROVED_RATED","INSTANT_DECLINE"
                        }
                        for _rec in _source_recs:
                            _oc = str(_rec.get("outcome","")).upper()
                            if _oc in _decided_outcomes or _oc.startswith("APPROVED"):
                                _ok = _queue_for_policy_admin({
                                    "applicant_ref":    _rec.get("applicant_ref",""),
                                    "job_id":           sel_job,
                                    "product_code":     _rec.get("product_code",""),
                                    "outcome":          _rec.get("outcome",""),
                                    "risk_class":       _rec.get("risk_class",""),
                                    "net_debit_points": _rec.get("net_debit_points"),
                                    "reason":           _rec.get("primary_reason",""),
                                }, source="BATCH")
                                if _ok:
                                    _queued += 1
                                else:
                                    _skipped += 1
                            else:
                                _skipped += 1

                        if _queued > 0:
                            st.success(
                                f"✅ {_queued} records queued for policy admin export. "
                                f"{_skipped} skipped (errors/pending). "
                                f"Go to **System Config → Output Interface** to run the extract."
                            )
                            st.session_state[_paq_key] = True
                        else:
                            st.warning(
                                "No decided records found to queue. "
                                "Records may be stored in the API backend only."
                            )

    # ── Auto-refresh: sleep then rerun AFTER all content renders ──
    if _auto_on_check and _render_jobs:
        _ar_time.sleep(5)
        st.rerun()

    # ── Tab 4: Schedule ───────────────────────────────────────────
    if _render_sched:
        st.markdown("#### ⏰ Schedule Batch Jobs")
        st.caption("Set up delayed one-off jobs or recurring nightly runs.")

        stab_view, stab_delayed, stab_recurring = st.tabs([
            "📋 View Schedules", "⏱️ Delayed Job", "🔁 Recurring Job"
        ])

        # ── View Schedules ────────────────────────────────────────
        with stab_view:
            _sv_col1, _sv_col2 = st.columns([5,1])
            _sv_col1.caption("Scheduled jobs and recurring runs configured for this platform.")
            if _sv_col2.button("🔄 Refresh", key="sched_refresh"):
                st.session_state.pop("sched_data", None)
                st.rerun()

            if "sched_data" not in st.session_state:
                sched_api = {}
                try:
                    r = requests.get(f"{API_BASE}/batch/schedules", headers=hdr, timeout=5)
                    if r.status_code == 200:
                        sched_api = r.json()
                except Exception as _exc:
                    logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)

                # DB fallback
                delayed_db, recurring_db = [], []
                if not sched_api:
                    try:
                        _conn_s = _get_db_conn()
                        if _conn_s:
                            _cur_s = _conn_s.cursor()
                            # Try delayed jobs table
                            try:
                                _cur_s.execute("""
                                    SELECT id, job_name, run_at, status, dry_run, created_at
                                    FROM batch_scheduled_jobs
                                    ORDER BY run_at DESC LIMIT 20
                                """)
                                for row in _cur_s.fetchall():
                                    delayed_db.append({
                                        "id": row[0], "job_name": row[1],
                                        "run_at": str(row[2] or ""), "status": row[3],
                                        "dry_run": row[4], "created_at": str(row[5] or "")
                                    })
                            except Exception as _exc:
                                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                            # Try recurring schedules table
                            try:
                                _cur_s.execute("""
                                    SELECT id, schedule_name, cron_expression, status,
                                           last_run_at, next_run_at
                                    FROM batch_recurring_schedules
                                    ORDER BY schedule_name LIMIT 20
                                """)
                                for row in _cur_s.fetchall():
                                    recurring_db.append({
                                        "id": row[0], "schedule_name": row[1],
                                        "cron_expression": row[2], "status": row[3],
                                        "last_run": str(row[4] or "Never"),
                                        "next_run": str(row[5] or "—")
                                    })
                            except Exception as _exc:
                                logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                            _cur_s.close(); _conn_s.close()
                    except Exception as _exc:
                        logger.debug("[render_batch_jobs] Suppressed exception", exc_info=_exc)
                    sched_api = {"delayed": delayed_db, "recurring": recurring_db}
                    if delayed_db or recurring_db:
                        st.caption("ℹ️ Loaded from database (API unavailable)")

                st.session_state.sched_data = sched_api

            sched_data = st.session_state.get("sched_data", {})
            delayed    = sched_data.get("delayed", sched_data.get("one_off", []))
            recurring  = sched_data.get("recurring", sched_data.get("schedules", []))

            st.markdown("**⏱️ Delayed (One-off) Jobs**")
            if delayed:
                df_delayed = pd.DataFrame([{
                    "Job Name":   s.get("job_name","—"),
                    "Run At":     str(s.get("run_at","—"))[:16],
                    "Status":     s.get("status","—"),
                    "Dry Run":    "✅" if s.get("dry_run") else "",
                    "Created":    str(s.get("created_at",""))[:10],
                } for s in delayed])
                st.dataframe(df_delayed, use_container_width=True, hide_index=True)
            else:
                st.info("No delayed jobs scheduled. Use the ⏱️ Delayed Job tab to schedule one.")

            st.divider()
            st.markdown("**🔁 Recurring Schedules**")
            if recurring:
                for s in recurring:
                    with st.expander(f"🔁 {s.get('schedule_name', s.get('name','—'))} — {s.get('cron_expression', s.get('schedule','—'))}"):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Status",  s.get("status","—"))
                        c2.metric("Last Run", str(s.get("last_run","Never"))[:10])
                        c3.metric("Next Run", str(s.get("next_run","—"))[:16])
                        if st.button("⏹️ Disable", key=f"sched_dis_{s.get('id','')}"):
                            resp = requests.post(f"{API_BASE}/batch/schedules/{s.get('id')}/disable", headers=hdr)
                            st.success("Disabled") if resp.status_code == 200 else st.error(resp.text)
                            st.session_state.pop("sched_data", None)
                            st.rerun()
            else:
                st.info("No recurring schedules configured. Use the 🔁 Recurring Job tab to create one.")

        # ── Create Delayed Job ────────────────────────────────────
        with stab_delayed:
            st.caption("Schedule a batch file to run once at a specific future time.")
            with st.form("delayed_job_form"):
                dj_name    = st.text_input("Job Name *", placeholder="e.g. EOD Batch Run")
                dj_file    = st.file_uploader("Upload Batch File (CSV/Excel)", type=["csv","xlsx","xls"])
                dj_dt      = st.date_input("Run Date")
                dj_time    = st.time_input("Run Time (server local time)")
                dj_dryrun  = st.checkbox("Dry Run (validate only)", help="Test mode — validates the batch file without producing UW decisions or writing to the case database.")
                dj_notify  = st.text_input("Notify email (optional)", placeholder="admin@carrier.com")
                if st.form_submit_button("⏱️ Schedule Delayed Job", use_container_width=True, type="primary"):
                    if not dj_name.strip() or not dj_file:
                        st.error("Job Name and file are required")
                    else:
                        from datetime import datetime as _dt2
                        run_at = _dt2.combine(dj_dt, dj_time).isoformat()
                        with st.spinner("Scheduling..."):
                            resp = requests.post(
                                f"{API_BASE}/batch/schedules/delayed",
                                headers=hdr,
                                params={"job_name": dj_name, "run_at": run_at,
                                        "dry_run": dj_dryrun, "notify_email": dj_notify},
                                files={"file": (dj_file.name, dj_file.getvalue(), "text/csv")}
                            )
                        if resp.status_code in (200, 201):
                            st.success(f"✅ Scheduled: {dj_name} → {run_at[:16]}")
                            st.session_state.pop("sched_data", None)
                        else:
                            st.error(f"❌ {resp.text[:300]}")

        # ── Create Recurring Job ──────────────────────────────────
        with stab_recurring:
            st.caption("Set up a recurring batch schedule (nightly, weekly, monthly).")
            with st.form("recurring_job_form"):
                rj_name  = st.text_input("Schedule Name *", placeholder="e.g. Nightly New Business")
                rj_preset = st.selectbox("Frequency", [
                    "Nightly at midnight",
                    "Nightly at 2 AM",
                    "Every Sunday at 6 AM",
                    "First of month at 3 AM",
                    "Custom cron expression",
                ])
                CRON_MAP = {
                    "Nightly at midnight":      "0 0 * * *",
                    "Nightly at 2 AM":          "0 2 * * *",
                    "Every Sunday at 6 AM":     "0 6 * * 0",
                    "First of month at 3 AM":   "0 3 1 * *",
                    "Custom cron expression":   "",
                }
                default_cron = CRON_MAP.get(rj_preset, "")
                rj_cron  = st.text_input("Cron Expression", value=default_cron,
                    help="Standard cron format: minute hour day month weekday")
                rj_src   = st.text_input("Source path / S3 key", placeholder="/data/batch/input.csv")
                rj_dry   = st.checkbox("Dry Run by default", help="When enabled, all scheduled runs of this job will run in validation mode only. Uncheck to allow live UW decisions on each scheduled run.")
                rj_email = st.text_input("Notify email on completion", placeholder="admin@carrier.com")
                rj_max   = st.number_input("Max retries on failure", 0, 5, 2, help="How many times the system will automatically retry this job if it fails. Retries use exponential backoff (2min, 4min, 8min...).")

                st.markdown("**📅 Schedule Validity**")
                from datetime import date as _date
                rv1, rv2 = st.columns(2)
                rj_start = rv1.date_input("Effective From",
                    value=_date.today(),
                    help="Date this recurring schedule becomes active")
                rj_end   = rv2.date_input("Effective Until",
                    value=None,
                    help="Date this schedule stops running — leave blank for indefinite")
                st.caption("**Cron guide:** `0 2 * * *` = 2 AM daily  |  `0 6 * * 1` = Monday 6 AM")

                if st.form_submit_button("🔁 Create Recurring Schedule", use_container_width=True, type="primary"):
                    if not rj_name.strip() or not rj_cron.strip():
                        st.error("Name and cron expression are required")
                    else:
                        resp = requests.post(
                            f"{API_BASE}/batch/schedules/recurring",
                            headers=hdr,
                            json={
                                "schedule_name":   rj_name,
                                "cron_expression": rj_cron,
                                "source_path":     rj_src,
                                "dry_run":         rj_dry,
                                "notify_email":    rj_email,
                                "max_retries":     rj_max,
                                "effective_from":  str(rj_start) if rj_start else None,
                                "effective_until": str(rj_end)   if rj_end   else None,
                            }
                        )
                        if resp.status_code in (200, 201):
                            st.success(f"✅ Recurring schedule created: {rj_name}")
                            st.session_state.pop("sched_data", None)
                        else:
                            st.error(f"❌ {resp.text[:300]}")


def render_error_codes():
    """Error Code Manager — view, create, edit validation error codes."""
    import pandas as pd
    st.markdown("## \u26a0\ufe0f Error Code Manager")
    st.caption("Configure validation error codes used in batch processing and data quality checks.")

    tok = st.session_state.get("token","")
    hdr = {"Authorization": f"Bearer {tok}"}

    tab_view, tab_create = st.tabs(["\U0001f4cb All Error Codes", "\u2795 Add Error Code"])

    with tab_view:
        CATS = ["ALL","DATA_QUALITY","ELIGIBILITY","BUSINESS_RULE","SYSTEM"]
        SEVS = ["ALL","ERROR","WARNING","INFO"]
        fc1,fc2 = st.columns(2)
        f_cat = fc1.selectbox("Category", CATS, key="ec_cat")
        f_sev = fc2.selectbox("Severity", SEVS, key="ec_sev")

        try:
            params = {}
            if f_cat != "ALL": params["category"] = f_cat
            r = requests.get(f"{API_BASE}/batch/error-codes", headers=hdr,
                             params=params, timeout=5).json()
            ecs = r.get("error_codes",[])
        except Exception as e:
            st.error(f"Error: {e}"); ecs = []

        if f_sev != "ALL": ecs = [e for e in ecs if e.get("severity")==f_sev]

        SEV_COLORS = {"ERROR":"\U0001f534","WARNING":"\U0001f7e1","INFO":"\U0001f7e2"}
        CATS_SHOWN = ["DATA_QUALITY","ELIGIBILITY","BUSINESS_RULE","SYSTEM"]

        # Metrics
        mc1,mc2,mc3,mc4 = st.columns(4)
        mc1.metric("Total Codes", len(ecs))
        mc2.metric("Errors",   sum(1 for e in ecs if e.get("severity")=="ERROR"))
        mc3.metric("Warnings", sum(1 for e in ecs if e.get("severity")=="WARNING"))
        mc4.metric("Active",   sum(1 for e in ecs if e.get("is_active")))

        st.divider()
        for cat in (CATS_SHOWN if f_cat=="ALL" else [f_cat]):
            cat_ecs = [e for e in ecs if e.get("category")==cat]
            if not cat_ecs: continue
            st.markdown(f"**{cat.replace('_',' ').title()}** ({len(cat_ecs)} codes)")
            df = pd.DataFrame([{
                "Number":   e["error_number"],
                "Code":     e["error_code"],
                "Severity": SEV_COLORS.get(e["severity"],"") + " " + e["severity"],
                "Description": e["description"],
                "Resolution": e.get("resolution_hint",""),
                "Active":   "\u2705" if e.get("is_active") else "\u274c",
            } for e in cat_ecs])
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_create:
        st.caption("Add a custom error code. Number must be unique across all codes.")
        with st.form("create_ec_form", clear_on_submit=True):
            c1,c2 = st.columns(2)
            with c1:
                ec_num  = st.number_input("Error Number *", 5000, 99999, 5001,
                    help="Must be unique. Use 5000+ for custom codes")
                ec_code = st.text_input("Error Code *", placeholder="e.g. CUST001",
                    help="Short alphanumeric code")
                ec_cat  = st.selectbox("Category *",
                    ["DATA_QUALITY","ELIGIBILITY","BUSINESS_RULE","SYSTEM","CUSTOM"])
            with c2:
                ec_sev  = st.selectbox("Severity *", ["ERROR","WARNING","INFO"])
                ec_desc = st.text_area("Description *", height=80,
                    placeholder="Clear description of what this error means")
                ec_hint = st.text_area("Resolution Hint", height=80,
                    placeholder="How to fix this error in the source data")
            from datetime import date as _date
            ecd1, ecd2 = st.columns(2)
            ec_eff = ecd1.date_input("Effective Date", value=_date.today(),
                help="Date this error code becomes active")
            ec_exp = ecd2.date_input("Expire Date", value=None,
                help="Date this error code is retired — leave blank for permanent")
            if st.form_submit_button("\u2795 Add Error Code", use_container_width=True, type="primary"):
                if not ec_code.strip() or not ec_desc.strip():
                    st.error("Code and description are required")
                else:
                    resp = requests.post(f"{API_BASE}/batch/error-codes", headers=hdr, json={
                        "error_number":    ec_num, "error_code": ec_code.strip().upper(),
                        "category":        ec_cat, "severity": ec_sev,
                        "description":     ec_desc.strip(), "resolution_hint": ec_hint.strip(),
                        "effective_date":  str(ec_eff) if ec_eff else None,
                        "expire_date":     str(ec_exp) if ec_exp else None,
                    })
                    if resp.status_code == 200:
                        st.success(f"\u2705 Error code {ec_code.upper()} created")
                        st.rerun()
                    else:
                        try: st.error(resp.json().get("detail", resp.text[:200]))
                        except: st.error("Failed to create error code")


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIT TRAIL — immutable event log
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_audit_table():
    """
    Create audit_trail table if it doesn't exist.
    Immutability is enforced by:
      - No UPDATE/DELETE permissions granted on the table in production
      - A DB-level trigger that raises an exception on any UPDATE/DELETE
      - The INSERT-only pattern in _log_audit()
    """
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_ensure_audit_table] Suppressed exception", exc_info=_exc)


def _log_audit(
    event_category: str,
    event_type: str,
    entity_type: str   = None,
    entity_id: str     = None,
    entity_ref: str    = None,
    before_state: dict = None,
    after_state: dict  = None,
    metadata: dict     = None,
    outcome: str       = "SUCCESS",
    failure_reason: str= None,
    actor_username: str= None,
    actor_role: str    = None,
    actor_ip: str      = None,
    tenant_id: str     = None,
    source: str        = "UI",
):
    """
    Write one immutable audit event. Silent on failure — never raises.

    Categories:  DECISION | AUTH | CONFIG | OVERRIDE | DATA_ACCESS |
                 ASSIGNMENT | APS | USER_MGMT | RULE | BATCH | MEMBER
    """
    import json as _json
    try:
        _ensure_audit_table()
        # Pull actor from session if not supplied
        if not actor_username:
            actor_username = st.session_state.get("username", "system")
        if not actor_role:
            actor_role = st.session_state.get("role", "")
        if not tenant_id:
            tenant_id = st.session_state.get("tenant_id", "")

        conn = _get_db_conn()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_trail (
                event_category, event_type,
                actor_username, actor_role, actor_ip, tenant_id,
                entity_type, entity_id, entity_ref,
                before_state, after_state, event_metadata,
                outcome, failure_reason, source
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s
            )
        """, (
            event_category.upper(), event_type.upper(),
            actor_username, actor_role, actor_ip, tenant_id,
            entity_type, str(entity_id) if entity_id else None, entity_ref,
            _json.dumps(before_state)  if before_state  else None,
            _json.dumps(after_state)   if after_state   else None,
            _json.dumps(metadata)      if metadata       else None,
            outcome.upper(), failure_reason, source,
        ))
        cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.error("[_log_audit] Failed to write audit event to DB — this event will be missing from the audit trail", exc_info=_exc)


def _run_sla_escalations() -> dict:
    """
    Scan for SLA-breached or near-breach cases and send escalation
    notifications to managers. Returns summary dict.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    result = {"escalated": 0, "near_breach": 0, "details": []}
    try:
        conn = _get_db_conn()
        if not conn:
            return result
        cur = conn.cursor()

        now = _dt.now(_tz.utc)

        # Cases already breached — escalate immediately
        cur.execute("""
            SELECT c.id, c.case_number, c.sla_due_at,
                   u.username, u.full_name, u.email,
                   a.face_amount, a.product_code
            FROM uw_case c
            JOIN application a ON a.id = c.application_id
            LEFT JOIN uw_user u ON u.id = c.assigned_uw_id
            WHERE c.status IN ('OPEN','IN_PROGRESS')
              AND c.sla_breached = FALSE
              AND c.sla_due_at < NOW()
        """)
        breached = cur.fetchall()

        for row in breached:
            case_id, case_num, sla_due, uw_user, uw_name, uw_email, fa, prod = row
            # Mark as breached
            cur.execute(
                "UPDATE uw_case SET sla_breached=TRUE, updated_at=NOW() WHERE id=%s",
                (str(case_id),)
            )
            # Log audit event
            _log_audit("ASSIGNMENT","SLA_BREACHED",
                entity_type="CASE", entity_id=str(case_id),
                entity_ref=case_num,
                metadata={"sla_due": str(sla_due), "assigned_to": uw_user,
                          "face_amount": float(fa) if fa else 0})
            # Notify managers
            send_notification("SLA_BREACH", {
                "case_number": case_num,
                "assigned_uw": uw_name or uw_user or "Unassigned",
                "sla_due_at":  str(sla_due)[:16],
                "face_amount": float(fa) if fa else 0,
                "product_code": prod or "",
            })
            result["escalated"] += 1
            result["details"].append(f"🔴 {case_num} — SLA breached, assigned to {uw_user or 'nobody'}")

        # Cases due within next 4 hours — warn
        cur.execute("""
            SELECT c.id, c.case_number, c.sla_due_at,
                   u.username, a.face_amount
            FROM uw_case c
            JOIN application a ON a.id = c.application_id
            LEFT JOIN uw_user u ON u.id = c.assigned_uw_id
            WHERE c.status IN ('OPEN','IN_PROGRESS')
              AND c.sla_breached = FALSE
              AND c.sla_due_at BETWEEN NOW() AND NOW() + INTERVAL '4 hours'
        """)
        near = cur.fetchall()
        for row in near:
            case_id, case_num, sla_due, uw_user, fa = row
            result["near_breach"] += 1
            result["details"].append(
                f"⚠️ {case_num} — due {str(sla_due)[:16]}, assigned to {uw_user or 'nobody'}"
            )
        cur.close(); _release_db_conn(conn)

    except Exception as ex:
        result["details"].append(f"Error: {ex}")
    return result


def render_my_account():
    """My Account — every logged-in user can set up and manage their own MFA."""
    st.markdown("## 👤 My Account")
    st.caption("Manage your profile and two-factor authentication settings.")

    _uname_full = st.session_state.get("username", "")
    _uname      = _uname_full.split("@")[0] if "@" in _uname_full else _uname_full
    _role       = st.session_state.get("role", "")

    # ── Profile card ─────────────────────────────────────────────────────────
    st.markdown(
        f"<div style='background:#1e293b;border:1px solid #334155;border-radius:10px;"
        f"padding:16px 20px;margin-bottom:20px;display:flex;align-items:center;gap:16px;'>"
        f"<div style='background:#1d4ed8;border-radius:50%;width:48px;height:48px;"
        f"display:flex;align-items:center;justify-content:center;"
        f"font-size:1.4rem;font-weight:700;color:white;flex-shrink:0;'>"
        f"{_uname[:1].upper()}</div>"
        f"<div><div style='font-size:1rem;font-weight:600;color:#e2e8f0;'>{_uname_full}</div>"
        f"<div style='font-size:0.78rem;color:#94a3b8;margin-top:2px;'>"
        f"{_role.replace('_',' ').title()}</div></div>"
        f"</div>",
        unsafe_allow_html=True
    )

    st.markdown("### 🔐 Two-Factor Authentication (MFA)")
    st.caption(
        "Add a second layer of security using a TOTP authenticator app. "
        "Works with Google Authenticator, Authy, Microsoft Authenticator, "
        "and any RFC 6238-compatible app."
    )

    _mfa_rec = _mfa_get(_uname)

    # ══════════════════════════════════════════════════════════════
    # STATE A — MFA active
    # ══════════════════════════════════════════════════════════════
    if _mfa_rec and _mfa_rec.get("is_enabled") and _mfa_rec.get("is_verified"):
        st.success(
            f"✅ MFA is **active** on your account  "
            f"| Enabled: {_mfa_rec.get('enabled_at') or '—'}  "
            f"| Last used: {_mfa_rec.get('last_used_at') or 'Never'}"
        )

        _bc_left = len(_mfa_rec.get("backup_codes", []))
        if _bc_left == 0:
            st.error("⚠️ No backup codes remaining — regenerate them now.")
        elif _bc_left <= 2:
            st.warning(f"⚠️ Only {_bc_left} backup code(s) left. Regenerate before you run out.")
        else:
            st.info(f"🔑 {_bc_left} backup code(s) remaining.")

        mc1, mc2 = st.columns(2)
        if mc1.button("🔄 Regenerate backup codes",
                      use_container_width=True, key="acc_regen_bc"):
            _new_codes = _mfa_generate_backup_codes(8)
            _mfa_save(_uname, _mfa_rec["secret"], True, True, _new_codes)
            st.session_state["_acc_new_codes"] = _new_codes
            _log_audit("AUTH", "MFA_BACKUP_CODES_REGENERATED",
                entity_type="USER", entity_id=_uname)
            st.rerun()

        if mc2.button("🗑️ Disable MFA", use_container_width=True,
                      key="acc_disable_mfa", type="secondary"):
            st.session_state["_acc_disable_confirm"] = True

        if st.session_state.get("_acc_disable_confirm"):
            st.warning("⚠️ Disabling MFA reduces your account security. Enter your current code to confirm.")
            with st.form("acc_disable_mfa_form"):
                _dis = st.text_input(
                    "Current 6-digit MFA code", max_chars=6, placeholder="000000",
                    help="Enter the code currently shown in your authenticator app.")
                dc1, dc2 = st.columns(2)
                if dc1.form_submit_button("Confirm disable", type="primary", use_container_width=True):
                    if _mfa_verify(_mfa_rec["secret"], _dis):
                        _mfa_save(_uname, _mfa_rec["secret"], False, False, [])
                        st.session_state.pop("_acc_disable_confirm", None)
                        _log_audit("AUTH", "MFA_DISABLED", entity_type="USER", entity_id=_uname)
                        st.success("MFA has been disabled.")
                        st.rerun()
                    else:
                        st.error("❌ Incorrect code.")
                if dc2.form_submit_button("Cancel", use_container_width=True):
                    st.session_state.pop("_acc_disable_confirm", None)
                    st.rerun()

        # Show newly generated backup codes
        if st.session_state.get("_acc_new_codes"):
            _nc = st.session_state.pop("_acc_new_codes")
            st.divider()
            st.markdown("##### 🔑 New backup codes — save these immediately")
            st.warning(
                "These codes will **not** be shown again. "
                "Each code can only be used once. "
                "Store them in a password manager or secure note."
            )
            _pairs = [_nc[i:i+4] for i in range(0, len(_nc), 4)]
            for _row in _pairs:
                _cols = st.columns(4)
                for _ci, _c in enumerate(_row):
                    _cols[_ci].code(_c, language=None)
            st.download_button(
                "⬇️ Download backup codes (.txt)",
                data="\n".join(_nc),
                file_name=f"uw_platform_backup_codes_{_uname}.txt",
                mime="text/plain",
                use_container_width=True,
                help="Download all 8 backup codes as a plain text file."
            )

    # ══════════════════════════════════════════════════════════════
    # STATE B — Setup in progress (secret exists, not verified)
    # ══════════════════════════════════════════════════════════════
    elif _mfa_rec and not _mfa_rec.get("is_verified"):
        st.info("⏳ MFA setup is in progress — complete the steps below to activate it.")
        _secret  = _mfa_rec["secret"]
        _otp_url = _mfa_otpauth_url(_secret, _uname_full, "UW Platform")

        st.divider()
        st.markdown("#### Step 1 — Add to your authenticator app")

        col_inst, col_key = st.columns([2, 1])
        with col_key:
            st.markdown("**📷 Scan QR code**")
            try:
                import qrcode, io
                _qr_img = qrcode.make(_otp_url)
                _qr_buf = io.BytesIO()
                _qr_img.save(_qr_buf, format="PNG")
                _qr_buf.seek(0)
                st.image(_qr_buf, width=200)
            except Exception as _exc:
                logger.debug("[render_my_account] Suppressed exception", exc_info=_exc)
                st.caption("QR unavailable — use manual key below")

        with col_inst:
            st.markdown("**Option A — Tap to open app directly (mobile):**")
            st.markdown(
                f"<a href='{_otp_url}' "
                f"style='display:inline-block;background:#1d4ed8;color:white;"
                f"padding:10px 20px;border-radius:8px;font-size:0.9rem;"
                f"text-decoration:none;margin:6px 0 12px 0;'>📱 Open in Authenticator App</a>",
                unsafe_allow_html=True
            )
            st.markdown("**Option B — Enter key manually:**")
            st.markdown("Open your app → ＋ Add account → Enter setup key")
            st.markdown(
                f"<div style='background:#0f2d1f;border:1px solid #10b981;border-radius:6px;"
                f"padding:10px 14px;margin:6px 0;'>"
                f"<div style='font-size:0.72rem;color:#6ee7b7;margin-bottom:4px;'>ACCOUNT NAME</div>"
                f"<div style='font-size:0.9rem;color:#e2e8f0;font-weight:600;'>UW Platform</div>"
                f"<div style='font-size:0.72rem;color:#6ee7b7;margin:8px 0 4px 0;'>SETUP KEY</div>"
                f"<div style='font-family:monospace;font-size:1rem;color:#34d399;"
                f"letter-spacing:0.05em;word-break:break-all;'>{_secret}</div>"
                f"<div style='font-size:0.72rem;color:#6ee7b7;margin:8px 0 4px 0;'>TYPE</div>"
                f"<div style='font-size:0.9rem;color:#e2e8f0;'>Time-based (TOTP)</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        st.divider()
        st.markdown("#### Step 2 — Verify it's working")
        st.caption(
            "Once you've added the account to your app, "
            "enter the 6-digit code it shows to confirm setup."
        )

        with st.form("acc_mfa_verify_form"):
            _vc1, _vc2 = st.columns([2, 1])
            _vcode = _vc1.text_input(
                "6-digit code from your app", max_chars=6, placeholder="000000",
                help="Enter the current code shown in your authenticator app. Codes refresh every 30 seconds."
            )
            _verify_btn = st.form_submit_button(
                "✅ Verify & Activate MFA", type="primary", use_container_width=True
            )

        if _verify_btn:
            if not _vcode or len(_vcode.strip()) != 6:
                st.error("Enter a 6-digit code.")
            elif _mfa_verify(_secret, _vcode):
                _backup_codes = _mfa_generate_backup_codes(8)
                _mfa_save(_uname, _secret, True, True, _backup_codes)
                st.session_state["_acc_new_codes"] = _backup_codes
                _log_audit("AUTH", "MFA_ENABLED",
                    entity_type="USER", entity_id=_uname,
                    metadata={"method": "totp"})
                st.success("✅ MFA is now active on your account! Save your backup codes below.")
                st.rerun()
            else:
                st.error(
                    "❌ Incorrect code. Check that: "
                    "the setup key was entered correctly, "
                    "your device clock is accurate, "
                    "and you are entering the current code (refreshes every 30 seconds)."
                )

        st.divider()
        if st.button("↩️ Start over (generate new secret)", key="acc_restart_mfa"):
            _new_secret = _mfa_generate_secret()
            _mfa_save(_uname, _new_secret, False, False, [])
            _log_audit("AUTH", "MFA_SETUP_RESTARTED", entity_type="USER", entity_id=_uname)
            st.rerun()

    # ══════════════════════════════════════════════════════════════
    # STATE C — Not set up yet
    # ══════════════════════════════════════════════════════════════
    else:
        st.markdown(
            "<div style='background:#1e293b;border:1px solid #334155;border-radius:10px;"
            "padding:24px;text-align:center;'>"
            "<div style='font-size:2.5rem;margin-bottom:12px;'>🔓</div>"
            "<div style='font-size:1rem;font-weight:600;color:#e2e8f0;margin-bottom:8px;'>"
            "MFA is not enabled on your account</div>"
            "<div style='font-size:0.83rem;color:#94a3b8;'>"
            "Adding MFA protects your account even if your password is compromised. "
            "Setup takes under 2 minutes.</div>"
            "</div>",
            unsafe_allow_html=True
        )
        st.markdown("")
        ec1, ec2, ec3 = st.columns([1, 2, 1])
        if ec2.button("🔐 Enable MFA on my account",
                      type="primary", use_container_width=True,
                      key="acc_start_mfa"):
            _new_secret = _mfa_generate_secret()
            _mfa_save(_uname, _new_secret, False, False, [])
            _log_audit("AUTH", "MFA_SETUP_STARTED", entity_type="USER", entity_id=_uname)
            st.rerun()

        st.divider()
        st.markdown("##### What you'll need")
        ia1, ia2, ia3 = st.columns(3)
        ia1.markdown(
            "<div style='background:#1e293b;border-radius:8px;padding:14px;text-align:center;'>"
            "<div style='font-size:1.5rem;'>📱</div>"
            "<div style='font-size:0.82rem;color:#e2e8f0;font-weight:600;margin-top:6px;'>Your phone</div>"
            "<div style='font-size:0.74rem;color:#64748b;margin-top:4px;'>iOS or Android</div>"
            "</div>",
            unsafe_allow_html=True
        )
        ia2.markdown(
            "<div style='background:#1e293b;border-radius:8px;padding:14px;text-align:center;'>"
            "<div style='font-size:1.5rem;'>🔑</div>"
            "<div style='font-size:0.82rem;color:#e2e8f0;font-weight:600;margin-top:6px;'>Authenticator app</div>"
            "<div style='font-size:0.74rem;color:#64748b;margin-top:4px;'>Google / Authy / Microsoft</div>"
            "</div>",
            unsafe_allow_html=True
        )
        ia3.markdown(
            "<div style='background:#1e293b;border-radius:8px;padding:14px;text-align:center;'>"
            "<div style='font-size:1.5rem;'>⏱️</div>"
            "<div style='font-size:0.82rem;color:#e2e8f0;font-weight:600;margin-top:6px;'>2 minutes</div>"
            "<div style='font-size:0.74rem;color:#64748b;margin-top:4px;'>That's all it takes</div>"
            "</div>",
            unsafe_allow_html=True
        )


def render_management_dashboard():
    """Management Dashboard — KPIs, UW productivity, SLA, APS, reinsurance."""
    import pandas as pd
    import plotly.graph_objects as go
    import plotly.express as px
    from datetime import date, timedelta, datetime as _dt

    st.markdown("## 📊 Management Dashboard")
    st.caption("Live management reporting — all data pulled directly from the database.")

    # ── Date range ────────────────────────────────────────────────────────────
    dc1, dc2, dc3, dc4 = st.columns([2, 2, 2, 2])
    _presets = {
        "Last 7 days":  7,  "Last 30 days": 30,
        "Last 90 days": 90, "This year":    (date.today() - date(date.today().year,1,1)).days
    }
    _preset = dc1.selectbox("Period", list(_presets.keys()), index=1,
        help="Quick date range presets.")
    _d_from = dc2.date_input("From", value=date.today() - timedelta(days=_presets[_preset]),
        help="Start of reporting period.")
    _d_to   = dc3.date_input("To",   value=date.today(),
        help="End of reporting period.")

    if dc4.button("🔄 Refresh", use_container_width=True, type="primary"):
        st.rerun()

    st.divider()

    try:
        conn = _get_db_conn()
        if not conn:
            st.error("Database unavailable.")
            return
        cur = conn.cursor()
        sym = get_currency_symbol()

        # ══════════════════════════════════════════════════════════
        # KPI ROW 1 — Decisions
        # ══════════════════════════════════════════════════════════
        cur.execute("""
            SELECT
                COUNT(*)                                                   AS total,
                COUNT(*) FILTER (WHERE d.outcome ILIKE 'APPROVED%%')       AS approved,
                COUNT(*) FILTER (WHERE d.outcome ILIKE 'DECLIN%%')         AS declined,
                COUNT(*) FILTER (WHERE d.outcome ILIKE 'REFER%%'
                              OR d.outcome ILIKE 'PEND%%')                 AS referred,
                COUNT(*) FILTER (WHERE d.outcome ILIKE 'POSTPONE%%')       AS postponed,
                COUNT(*) FILTER (WHERE d.decided_by_type = 'ENGINE')       AS stp,
                COUNT(*) FILTER (WHERE d.is_override = TRUE)               AS overrides,
                ROUND(AVG(
                    EXTRACT(EPOCH FROM (d.decided_at - c.created_at))/3600
                )::numeric, 1)                                             AS avg_hours,
                SUM(d.approved_premium)                                    AS total_premium,
                SUM(a.face_amount)                                         AS total_face
            FROM uw_decision d
            JOIN uw_case c       ON c.id = d.case_id
            JOIN application a   ON a.id = c.application_id
            WHERE d.is_final = TRUE
              AND d.decided_at::date BETWEEN %s AND %s
        """, (_d_from, _d_to))
        kpi = cur.fetchone()

        total, approved, declined, referred, postponed, stp, overrides, avg_hrs, tot_prem, tot_face = kpi
        total = total or 0

        appr_rate = f"{round(approved/total*100,1)}%" if total else "—"
        decl_rate = f"{round(declined/total*100,1)}%" if total else "—"
        stp_rate  = f"{round(stp/total*100,1)}%"      if total else "—"

        k1,k2,k3,k4,k5,k6,k7,k8 = st.columns(8)
        k1.metric("Total decisions",  f"{total:,}")
        k2.metric("Approved",         f"{approved:,}", delta=appr_rate)
        k3.metric("Declined",         f"{declined:,}", delta=decl_rate, delta_color="inverse")
        k4.metric("Referred",         f"{referred:,}")
        k5.metric("Postponed",        f"{postponed:,}")
        k6.metric("STP rate",         stp_rate)
        k7.metric("Manual overrides", f"{overrides:,}")
        k8.metric("Avg decision time",f"{avg_hrs or 0:.1f}h")

        st.divider()

        # ══════════════════════════════════════════════════════════
        # KPI ROW 2 — Queue health
        # ══════════════════════════════════════════════════════════
        cur.execute("""
            SELECT
                COUNT(*)                                              AS open_cases,
                COUNT(*) FILTER (WHERE sla_breached = TRUE)           AS breached,
                COUNT(*) FILTER (WHERE assigned_uw_id IS NULL)        AS unassigned,
                COUNT(*) FILTER (WHERE reinsurance_required = TRUE
                             AND status IN ('OPEN','IN_PROGRESS'))     AS rein_pending,
                ROUND(AVG(
                    EXTRACT(EPOCH FROM (NOW()-created_at))/3600
                )::numeric,1)                                         AS avg_age_hrs
            FROM uw_case
            WHERE status IN ('OPEN','IN_PROGRESS')
        """)
        q = cur.fetchone()
        open_c, breached_c, unassigned_c, rein_c, avg_age = q

        q1,q2,q3,q4,q5 = st.columns(5)
        q1.metric("Open cases",         f"{open_c or 0:,}")
        q2.metric("SLA breached",       f"{breached_c or 0:,}",
                  delta=f"-{breached_c}" if breached_c else None, delta_color="inverse")
        q3.metric("Unassigned",         f"{unassigned_c or 0:,}",
                  delta=f"-{unassigned_c}" if unassigned_c else None, delta_color="inverse")
        q4.metric("Reinsurance pending",f"{rein_c or 0:,}")
        q5.metric("Avg case age",       f"{avg_age or 0:.1f}h")

        # SLA escalation button
        if st.button("🚨 Run SLA Escalations Now", type="secondary",
                     help="Mark breached cases, send manager notifications, log to audit trail."):
            with st.spinner("Running escalations..."):
                esc = _run_sla_escalations()
            if esc["escalated"]:
                st.error(f"🔴 {esc['escalated']} case(s) marked as SLA breached and managers notified.")
            if esc["near_breach"]:
                st.warning(f"⚠️ {esc['near_breach']} case(s) due within 4 hours.")
            if not esc["escalated"] and not esc["near_breach"]:
                st.success("✅ No SLA breaches found.")
            if esc["details"]:
                with st.expander("Details"):
                    for d in esc["details"]:
                        st.caption(d)

        st.divider()

        # ══════════════════════════════════════════════════════════
        # CHARTS ROW 1 — Outcomes + Daily trend
        # ══════════════════════════════════════════════════════════
        ch1, ch2 = st.columns(2)

        with ch1:
            st.markdown("##### Decision outcomes")
            cur.execute("""
                SELECT d.outcome, COUNT(*) AS cnt
                FROM uw_decision d
                WHERE d.is_final=TRUE AND d.decided_at::date BETWEEN %s AND %s
                GROUP BY d.outcome ORDER BY cnt DESC
            """, (_d_from, _d_to))
            outcome_rows = cur.fetchall()
            if outcome_rows:
                df_o = pd.DataFrame(outcome_rows, columns=["Outcome","Count"])
                _colors = {"APPROVED":"#10b981","DECLINED":"#ef4444",
                           "REFERRED":"#f59e0b","POSTPONED":"#818cf8",
                           "REQUEST_APS":"#06b6d4","COUNTER_OFFER":"#f97316"}
                fig1 = px.pie(df_o, values="Count", names="Outcome",
                    color="Outcome", color_discrete_map=_colors,
                    hole=0.4)
                fig1.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                    font_color="var(--color-text-secondary)",
                    margin=dict(t=10,b=10,l=10,r=10), showlegend=True)
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.info("No decision data for this period.")

        with ch2:
            st.markdown("##### Daily volume")
            cur.execute("""
                SELECT DATE(d.decided_at) AS day,
                       COUNT(*) AS total,
                       COUNT(*) FILTER(WHERE d.outcome ILIKE 'APPROVED%%') AS approved,
                       COUNT(*) FILTER(WHERE d.outcome ILIKE 'DECLIN%%')   AS declined
                FROM uw_decision d
                WHERE d.is_final=TRUE AND d.decided_at::date BETWEEN %s AND %s
                GROUP BY day ORDER BY day
            """, (_d_from, _d_to))
            trend_rows = cur.fetchall()
            if trend_rows:
                df_t = pd.DataFrame(trend_rows, columns=["Day","Total","Approved","Declined"])
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(x=df_t["Day"], y=df_t["Total"],
                    name="Total", marker_color="#818cf8", opacity=0.5))
                fig2.add_trace(go.Scatter(x=df_t["Day"], y=df_t["Approved"],
                    name="Approved", line=dict(color="#10b981", width=2)))
                fig2.add_trace(go.Scatter(x=df_t["Day"], y=df_t["Declined"],
                    name="Declined", line=dict(color="#ef4444", width=2)))
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="var(--color-text-secondary)",
                    margin=dict(t=10,b=10,l=10,r=10),
                    legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No trend data.")

        # ══════════════════════════════════════════════════════════
        # CHARTS ROW 2 — By product + By UW
        # ══════════════════════════════════════════════════════════
        ch3, ch4 = st.columns(2)

        with ch3:
            st.markdown("##### Decisions by product")
            cur.execute("""
                SELECT a.product_code,
                       COUNT(*) AS total,
                       COUNT(*) FILTER(WHERE d.outcome ILIKE 'APPROVED%%') AS approved,
                       ROUND(AVG(a.face_amount)::numeric,0)                AS avg_face,
                       ROUND(SUM(d.approved_premium)::numeric,0)           AS premium
                FROM uw_decision d
                JOIN uw_case c     ON c.id = d.case_id
                JOIN application a ON a.id = c.application_id
                WHERE d.is_final=TRUE AND d.decided_at::date BETWEEN %s AND %s
                GROUP BY a.product_code ORDER BY total DESC LIMIT 10
            """, (_d_from, _d_to))
            prod_rows = cur.fetchall()
            if prod_rows:
                df_p = pd.DataFrame(prod_rows,
                    columns=["Product","Total","Approved","Avg Face",f"Premium ({sym})"])
                df_p["Approval %"] = (df_p["Approved"]/df_p["Total"]*100).round(1)
                fig3 = px.bar(df_p, x="Total", y="Product", orientation="h",
                    color="Approval %", color_continuous_scale="Greens",
                    text="Total")
                fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="var(--color-text-secondary)",
                    margin=dict(t=10,b=10,l=10,r=10),
                    coloraxis_showscale=True,
                    yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.info("No product data.")

        with ch4:
            st.markdown("##### UW productivity")
            cur.execute("""
                SELECT
                    COALESCE(u.username, 'System/STP')     AS uw,
                    COUNT(*)                               AS decisions,
                    COUNT(*) FILTER(WHERE d.outcome ILIKE 'APPROVED%%') AS approved,
                    ROUND(AVG(
                        EXTRACT(EPOCH FROM (d.decided_at - c.created_at))/3600
                    )::numeric,1)                          AS avg_hrs,
                    COUNT(*) FILTER(WHERE d.is_override=TRUE) AS overrides
                FROM uw_decision d
                JOIN uw_case c ON c.id = d.case_id
                LEFT JOIN uw_user u ON u.id = c.assigned_uw_id
                WHERE d.is_final=TRUE AND d.decided_at::date BETWEEN %s AND %s
                GROUP BY u.username ORDER BY decisions DESC LIMIT 12
            """, (_d_from, _d_to))
            uw_rows = cur.fetchall()
            if uw_rows:
                df_u = pd.DataFrame(uw_rows,
                    columns=["UW","Decisions","Approved","Avg hrs","Overrides"])
                df_u["Approval %"] = (df_u["Approved"]/df_u["Decisions"]*100).round(1)
                fig4 = px.bar(df_u, x="UW", y="Decisions",
                    color="Approval %", color_continuous_scale="Blues",
                    text="Decisions", hover_data=["Avg hrs","Overrides"])
                fig4.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="var(--color-text-secondary)",
                    margin=dict(t=10,b=10,l=10,r=10))
                st.plotly_chart(fig4, use_container_width=True)
                st.dataframe(df_u, use_container_width=True, hide_index=True)
            else:
                st.info("No UW productivity data.")

        # ══════════════════════════════════════════════════════════
        # CHARTS ROW 3 — APS turnaround + Reinsurance
        # ══════════════════════════════════════════════════════════
        ch5, ch6 = st.columns(2)

        with ch5:
            st.markdown("##### APS turnaround")
            cur.execute("""
                SELECT
                    COUNT(*)                                       AS total_requests,
                    COUNT(*) FILTER(WHERE status='RECEIVED')       AS received,
                    COUNT(*) FILTER(WHERE status='PENDING')        AS pending,
                    COUNT(*) FILTER(WHERE status='ORDERED')        AS ordered,
                    ROUND(AVG(
                        EXTRACT(EPOCH FROM (received_at - requested_at))/86400
                    ) FILTER(WHERE received_at IS NOT NULL)::numeric, 1) AS avg_days,
                    COUNT(*) FILTER(
                        WHERE status='PENDING'
                        AND requested_at < NOW() - INTERVAL '30 days'
                    )                                              AS overdue
                FROM aps_request
                WHERE requested_at::date BETWEEN %s AND %s
            """, (_d_from, _d_to))
            aps = cur.fetchone()
            if aps and aps[0]:
                a1,a2,a3,a4,a5,a6 = st.columns(6)
                a1.metric("Total APS",    f"{aps[0]:,}")
                a2.metric("Received",     f"{aps[1]:,}")
                a3.metric("Pending",      f"{aps[2]:,}")
                a4.metric("Ordered",      f"{aps[3]:,}")
                a5.metric("Avg days",     f"{aps[4] or 0:.1f}d")
                a6.metric("Overdue",      f"{aps[5]:,}",
                          delta=f"-{aps[5]}" if aps[5] else None, delta_color="inverse")

                # APS by physician
                cur.execute("""
                    SELECT physician_name, COUNT(*) AS cnt,
                           COUNT(*) FILTER(WHERE status='RECEIVED') AS received,
                           ROUND(AVG(
                               EXTRACT(EPOCH FROM (received_at-requested_at))/86400
                           ) FILTER(WHERE received_at IS NOT NULL)::numeric,1) AS avg_days
                    FROM aps_request
                    WHERE requested_at::date BETWEEN %s AND %s
                      AND physician_name IS NOT NULL
                    GROUP BY physician_name ORDER BY cnt DESC LIMIT 8
                """, (_d_from, _d_to))
                phy_rows = cur.fetchall()
                if phy_rows:
                    df_phy = pd.DataFrame(phy_rows,
                        columns=["Physician","Requests","Received","Avg days"])
                    st.dataframe(df_phy, use_container_width=True, hide_index=True)
            else:
                st.info("No APS data for this period.")

        with ch6:
            st.markdown("##### Reinsurance flagged cases")
            cur.execute("""
                SELECT
                    COUNT(*)                                            AS total_flagged,
                    COUNT(*) FILTER(WHERE c.status IN ('OPEN','IN_PROGRESS')) AS still_open,
                    COUNT(*) FILTER(WHERE d.outcome ILIKE 'APPROVED%%') AS approved_with_ri,
                    ROUND(AVG(a.face_amount)::numeric,0)                AS avg_face,
                    SUM(a.face_amount)                                  AS total_face_exposure
                FROM uw_case c
                JOIN application a  ON a.id = c.application_id
                LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final=TRUE
                WHERE c.reinsurance_required = TRUE
                  AND c.created_at::date BETWEEN %s AND %s
            """, (_d_from, _d_to))
            ri = cur.fetchone()
            if ri and ri[0]:
                r1,r2,r3 = st.columns(3)
                r1.metric("RI flagged",       f"{ri[0]:,}")
                r2.metric("Still open",       f"{ri[1]:,}")
                r3.metric("Approved with RI", f"{ri[2]:,}")
                r1.metric("Avg face amount",  f"{sym}{(ri[3] or 0):,.0f}")
                r2.metric("Total RI exposure",f"{sym}{(ri[4] or 0):,.0f}")

                # RI cases list
                cur.execute("""
                    SELECT c.case_number, a.product_code, a.face_amount,
                           c.status, d.outcome, u.username
                    FROM uw_case c
                    JOIN application a ON a.id = c.application_id
                    LEFT JOIN uw_decision d ON d.case_id = c.id AND d.is_final=TRUE
                    LEFT JOIN uw_user u ON u.id = c.assigned_uw_id
                    WHERE c.reinsurance_required = TRUE
                      AND c.created_at::date BETWEEN %s AND %s
                    ORDER BY a.face_amount DESC LIMIT 15
                """, (_d_from, _d_to))
                ri_cases = cur.fetchall()
                if ri_cases:
                    df_ri = pd.DataFrame(ri_cases,
                        columns=["Case","Product","Face Amount","Status","Outcome","Assigned UW"])
                    df_ri["Face Amount"] = df_ri["Face Amount"].apply(
                        lambda x: f"{sym}{float(x):,.0f}" if x else "—")
                    st.dataframe(df_ri, use_container_width=True, hide_index=True)
            else:
                st.info("No reinsurance flagged cases in this period.")

        # ══════════════════════════════════════════════════════════
        # SLA DETAIL TABLE
        # ══════════════════════════════════════════════════════════
        st.divider()
        st.markdown("##### SLA breach detail")
        cur.execute("""
            SELECT c.case_number, a.product_code, a.face_amount,
                   c.sla_due_at, c.sla_breached,
                   ROUND(EXTRACT(EPOCH FROM (NOW()-c.sla_due_at))/3600::numeric,1) AS hrs_overdue,
                   u.username AS assigned_uw,
                   d.outcome
            FROM uw_case c
            JOIN application a ON a.id = c.application_id
            LEFT JOIN uw_user u ON u.id = c.assigned_uw_id
            LEFT JOIN uw_decision d ON d.case_id=c.id AND d.is_final=TRUE
            WHERE c.status IN ('OPEN','IN_PROGRESS')
              AND (c.sla_breached=TRUE
                   OR c.sla_due_at < NOW() + INTERVAL '8 hours')
            ORDER BY c.sla_due_at ASC NULLS LAST
            LIMIT 50
        """)
        sla_rows = cur.fetchall()
        if sla_rows:
            df_sla = pd.DataFrame(sla_rows,
                columns=["Case","Product","Face Amount","SLA Due",
                         "Breached","Hrs Overdue","Assigned UW","Outcome"])
            df_sla["Face Amount"] = df_sla["Face Amount"].apply(
                lambda x: f"{sym}{float(x):,.0f}" if x else "—")
            df_sla["SLA Due"] = df_sla["SLA Due"].astype(str).str[:16]
            df_sla["Status"] = df_sla["Breached"].apply(
                lambda b: "🔴 Breached" if b else "⚠️ Due soon")
            st.dataframe(
                df_sla[["Case","Product","Face Amount","SLA Due","Status","Hrs Overdue","Assigned UW","Outcome"]],
                use_container_width=True, hide_index=True
            )
        else:
            st.success("✅ No SLA breaches or imminent deadlines.")

        cur.close(); _release_db_conn(conn)

    except Exception as ex:
        st.error(f"Dashboard error: {ex}")
        import traceback
        st.code(traceback.format_exc())



# ══════════════════════════════════════════════════════════════════════════════
#  REINSURANCE MODULE
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_ri_tables():
    """
    No-op shim kept for call-site compatibility.
    The ri_reinsurer, ri_cession tables and ri_cession_seq sequence
    are created by migrations/001_initial_schema.sql.
    """
    pass


def render_reinsurance():
    """Reinsurance Module — slip generation, cession tracking, RI decisions."""
    import pandas as pd
    import json as _json
    from datetime import date, datetime as _dt, timedelta

    _ensure_ri_tables()

    st.markdown("## 🏦 Reinsurance")
    st.caption(
        "Manage reinsurance cessions — generate RI slips, track submissions, "
        "record RI decisions, and calculate premium splits."
    )

    sym = get_currency_symbol()
    uname = st.session_state.get("username", "system")

    # ── DB helpers ────────────────────────────────────────────────────────────
    def _load_reinsurers(active_only=True):
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                q = """
                    SELECT id, reinsurer_code, reinsurer_name, treaty_code,
                           treaty_type, contact_email, retention_limit,
                           product_codes, currency, is_active, notes,
                           treaty_effective_date, treaty_expiry_date
                    FROM ri_reinsurer
                """
                if active_only:
                    q += " WHERE is_active=TRUE"
                q += " ORDER BY reinsurer_name"
                cur.execute(q)
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)
                return [{
                    "id": r[0], "code": r[1], "name": r[2],
                    "treaty_code": r[3] or "", "treaty_type": r[4] or "FACULTATIVE",
                    "email": r[5] or "", "retention_limit": float(r[6]) if r[6] else None,
                    "product_codes": list(r[7]) if r[7] else [],
                    "currency": r[8] or "INR", "is_active": r[9],
                    "notes": r[10] or "",
                    "treaty_effective_date": r[11],
                    "treaty_expiry_date":    r[12],
                } for r in rows]
        except Exception as _exc:
            logger.warning("[_load_reinsurers] Suppressed exception", exc_info=_exc)
        return []

    def _load_ri_cases():
        """Load all cases flagged reinsurance_required with cession status."""
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        c.id, c.case_number, c.status,
                        a.applicant_ref, a.face_amount, a.product_code,
                        a.age, a.gender,
                        d.outcome, d.approved_premium, d.risk_class,
                        d.table_rating, d.flat_extra_per_thou,
                        d.net_debit_points,
                        m.full_name AS applicant_name,
                        ri.id           AS cession_id,
                        ri.cession_ref,
                        ri.status       AS ri_status,
                        ri.reinsurer_id,
                        ri.ceded_amount,
                        ri.ri_premium,
                        ri.ri_decision,
                        rr.reinsurer_name
                    FROM uw_case c
                    JOIN application a       ON a.id = c.application_id
                    LEFT JOIN uw_decision d  ON d.case_id = c.id AND d.is_final = TRUE
                    LEFT JOIN applicant_master m ON m.applicant_ref = a.applicant_ref
                    LEFT JOIN ri_cession ri  ON ri.case_id = c.id::text
                    LEFT JOIN ri_reinsurer rr ON rr.id = ri.reinsurer_id
                    WHERE c.reinsurance_required = TRUE
                    ORDER BY
                        CASE WHEN ri.id IS NULL THEN 0 ELSE 1 END,
                        a.face_amount DESC
                """)
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)
                return [{
                    "case_id":        str(r[0]),
                    "case_number":    r[1],
                    "case_status":    r[2],
                    "applicant_ref":  r[3],
                    "face_amount":    float(r[4]) if r[4] else 0,
                    "product_code":   r[5] or "",
                    "age":            r[6],
                    "gender":         r[7],
                    "outcome":        r[8] or "",
                    "approved_premium": float(r[9]) if r[9] else 0,
                    "risk_class":     r[10] or "",
                    "table_rating":   r[11] or 0,
                    "flat_extra":     float(r[12]) if r[12] else 0,
                    "net_debit_points": r[13] or 0,
                    "applicant_name": r[14] or "",
                    "cession_id":     r[15],
                    "cession_ref":    r[16] or "",
                    "ri_status":      r[17] or "NOT_SUBMITTED",
                    "reinsurer_id":   r[18],
                    "ceded_amount":   float(r[19]) if r[19] else 0,
                    "ri_premium":     float(r[20]) if r[20] else 0,
                    "ri_decision":    r[21] or "",
                    "reinsurer_name": r[22] or "",
                } for r in rows]
        except Exception as ex:
            st.error(f"Error loading RI cases: {ex}")
        return []

    # ── Summary metrics ───────────────────────────────────────────────────────
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*)                                                  AS total_flagged,
                    COUNT(*) FILTER(WHERE ri.id IS NULL)                      AS pending_submission,
                    COUNT(*) FILTER(WHERE ri.status='SUBMITTED')              AS submitted,
                    COUNT(*) FILTER(WHERE ri.status='DECISION_RECEIVED'
                                      AND ri.ri_decision='ACCEPTED')          AS accepted,
                    COUNT(*) FILTER(WHERE ri.status='DECISION_RECEIVED'
                                      AND ri.ri_decision='DECLINED')          AS ri_declined,
                    COALESCE(SUM(a.face_amount),0)                            AS total_exposure,
                    COALESCE(SUM(ri.ceded_amount),0)                          AS total_ceded,
                    COALESCE(SUM(ri.ri_premium),0)                            AS total_ri_prem
                FROM uw_case c
                JOIN application a      ON a.id = c.application_id
                LEFT JOIN ri_cession ri ON ri.case_id = c.id::text
                WHERE c.reinsurance_required = TRUE
            """)
            ms = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if ms:
                m1,m2,m3,m4,m5,m6,m7,m8 = st.columns(8)
                m1.metric("Total RI cases",    f"{ms[0]:,}")
                m2.metric("Pending submission",f"{ms[1]:,}",
                          delta=f"-{ms[1]}" if ms[1] else None, delta_color="inverse")
                m3.metric("Submitted",         f"{ms[2]:,}")
                m4.metric("RI accepted",        f"{ms[3]:,}")
                m5.metric("RI declined",        f"{ms[4]:,}")
                m6.metric("Total exposure",     f"{sym}{ms[5]:,.0f}")
                m7.metric("Total ceded",        f"{sym}{ms[6]:,.0f}")
                m8.metric("RI premium out",     f"{sym}{ms[7]:,.0f}")
    except Exception as _exc:
        logger.debug("[_load_ri_cases] Suppressed exception", exc_info=_exc)

    st.divider()

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_queue, tab_slip, tab_reinsurers, tab_history = st.tabs([
        "📋 RI Queue",
        "📄 Generate RI Slip",
        "🏢 Reinsurer Registry",
        "📊 Cession History",
    ])

    ri_cases    = _load_ri_cases()
    reinsurers  = _load_reinsurers()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 — RI QUEUE
    # ══════════════════════════════════════════════════════════════════════
    with tab_queue:
        st.caption(
            "All cases flagged for reinsurance. Cases without a cession entry "
            "need to be submitted to your reinsurer."
        )

        # Status filter
        _sf1, _sf2 = st.columns([2, 2])
        _status_f = _sf1.selectbox("Filter by RI status",
            ["All", "NOT_SUBMITTED", "SLIP_GENERATED", "SUBMITTED",
             "DECISION_RECEIVED", "CLOSED"],
            help="Filter cases by their current reinsurance submission status.")
        _outcome_f = _sf2.selectbox("Filter by UW outcome",
            ["All", "APPROVED", "REFERRED", "DECLINED", "POSTPONED"],
            help="Filter by the underwriting decision outcome.")

        filtered = ri_cases
        if _status_f != "All":
            filtered = [c for c in filtered if c["ri_status"] == _status_f]
        if _outcome_f != "All":
            filtered = [c for c in filtered
                        if c["outcome"].upper().startswith(_outcome_f)]

        st.caption(f"{len(filtered)} case(s)")

        _STATUS_ICON = {
            "NOT_SUBMITTED":    "🔴",
            "SLIP_GENERATED":   "🟡",
            "SUBMITTED":        "🔵",
            "DECISION_RECEIVED":"🟢",
            "CLOSED":           "⚫",
        }

        for case in filtered:
            _icon  = _STATUS_ICON.get(case["ri_status"], "⚪")
            _ri_tag = (f" | {case['reinsurer_name']}" if case["reinsurer_name"]
                       else " | No reinsurer assigned")
            _dec_tag = f" | {case['outcome']}" if case["outcome"] else ""

            with st.expander(
                f"{_icon} **{case['case_number']}**  —  "
                f"{sym}{case['face_amount']:,.0f}  |  {case['product_code']}"
                f"{_dec_tag}{_ri_tag}"
            ):
                ec1, ec2, ec3, ec4 = st.columns(4)
                ec1.metric("Face amount",    f"{sym}{case['face_amount']:,.0f}")
                ec2.metric("Outcome",        case["outcome"] or "—")
                ec3.metric("Risk class",     case["risk_class"] or "—")
                ec4.metric("Approved prem",  f"{sym}{case['approved_premium']:,.0f}"
                           if case["approved_premium"] else "—")

                if case["cession_id"]:
                    # Show existing cession
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.info(f"**Cession ref:** `{case['cession_ref']}`")
                    cc2.info(f"**RI status:** {case['ri_status']}")
                    cc3.info(f"**RI decision:** {case['ri_decision'] or 'Pending'}")

                    if case["ceded_amount"]:
                        ca1, ca2, ca3 = st.columns(3)
                        ca1.metric("Ceded amount", f"{sym}{case['ceded_amount']:,.0f}")
                        ca2.metric("RI premium",   f"{sym}{case['ri_premium']:,.0f}")
                        ca3.metric("Net retained",
                            f"{sym}{case['approved_premium']-case['ri_premium']:,.0f}"
                            if case["approved_premium"] and case["ri_premium"] else "—")

                    # Submit to reinsurer if slip generated but not yet submitted
                    if case["ri_status"] == "SLIP_GENERATED":
                        st.markdown("##### Submit to Reinsurer")
                        st.caption("The RI slip has been generated. Click below to mark it as submitted to the reinsurer.")
                        with st.form(f"ri_submit_slip_{case['cession_id']}"):
                            _sub_date = st.date_input("Submission date", value=date.today(),
                                help="Date the slip was sent to the reinsurer.")
                            _sub_note = st.text_input("Submission reference / notes",
                                placeholder="e.g. Email ref, courier tracking number",
                                help="Optional reference for your records.")
                            if st.form_submit_button("📤 Submit to Reinsurer",
                                                     type="primary",
                                                     use_container_width=True):
                                try:
                                    conn = _get_db_conn()
                                    if conn:
                                        cur = conn.cursor()
                                        cur.execute("""
                                            UPDATE ri_cession SET
                                                status       = 'SUBMITTED',
                                                submitted_at = %s,
                                                notes        = COALESCE(notes || ' | ', '') || %s,
                                                updated_at   = NOW()
                                            WHERE id = %s
                                        """, (_sub_date, _sub_note or "Submitted", case["cession_id"]))
                                        conn.commit(); cur.close(); _release_db_conn(conn)
                                        _log_audit("REINSURANCE", "RI_SLIP_SUBMITTED",
                                            entity_type="RI_CESSION",
                                            entity_id=case["cession_ref"],
                                            entity_ref=case["case_number"],
                                            after_state={"status": "SUBMITTED"})
                                        st.success("✅ Submitted to reinsurer. Record their decision when received.")
                                        st.rerun()
                                except Exception as _se:
                                    st.error(f"Submit failed: {_se}")

                    # Update RI decision
                    if case["ri_status"] == "SUBMITTED":
                        st.markdown("##### Record RI decision")
                        with st.form(f"ri_dec_{case['cession_id']}"):
                            rd1, rd2 = st.columns(2)
                            _ri_dec = rd1.selectbox("RI Decision",
                                ["ACCEPTED", "DECLINED", "MODIFIED"],
                                help="Record the reinsurer's decision on this cession.")
                            _ri_ref = rd2.text_input("RI Reference",
                                placeholder="Reinsurer's own reference number",
                                help="Reference number from the reinsurer's decision letter.")
                            _ri_mod = st.text_area("Modified terms (if applicable)",
                                placeholder="e.g. Accepted at Table 4 instead of Table 2",
                                help="If the RI accepted with modified terms, record them here.",
                                height=70)
                            _ri_dec_date = st.date_input("Decision date",
                                value=date.today(),
                                help="Date the RI decision was received.")
                            if st.form_submit_button("✅ Record Decision",
                                                     type="primary",
                                                     use_container_width=True):
                                try:
                                    conn = _get_db_conn()
                                    if conn:
                                        cur = conn.cursor()
                                        cur.execute("""
                                            UPDATE ri_cession SET
                                                ri_decision          = %s,
                                                ri_reference         = %s,
                                                ri_modified_terms    = %s,
                                                ri_decision_date     = %s,
                                                status               = 'DECISION_RECEIVED',
                                                decision_received_at = NOW(),
                                                updated_at           = NOW()
                                            WHERE id = %s
                                        """, (_ri_dec, _ri_ref, _ri_mod or None,
                                              _ri_dec_date, case["cession_id"]))
                                        cur.close(); _release_db_conn(conn)
                                        _log_audit("REINSURANCE","RI_DECISION_RECORDED",
                                            entity_type="RI_CESSION",
                                            entity_id=case["cession_ref"],
                                            entity_ref=case["case_number"],
                                            after_state={"decision": _ri_dec,
                                                         "ri_ref": _ri_ref})
                                        st.success(f"✅ RI decision recorded: {_ri_dec}")
                                        st.rerun()
                                except Exception as de:
                                    st.error(f"Save failed: {de}")

                else:
                    # Quick submit form
                    st.markdown("##### Submit to reinsurer")
                    if not reinsurers:
                        st.warning("No reinsurers configured. Add one in **Reinsurer Registry** tab.")
                    else:
                        with st.form(f"ri_submit_{case['case_id']}"):
                            qs1, qs2 = st.columns(2)
                            _ri_sel = qs1.selectbox(
                                "Reinsurer *",
                                options=[r["id"] for r in reinsurers],
                                format_func=lambda x: next(
                                    (r["name"] for r in reinsurers if r["id"]==x), str(x)),
                                help="Select the reinsurer to cede this risk to.")
                            _ri_type = qs2.selectbox("Cession type",
                                ["FACULTATIVE", "TREATY"],
                                help="Facultative = case-by-case. Treaty = automatic per agreement.")

                            # Auto-calculate ceded amount
                            _sel_ri = next(
                                (r for r in reinsurers if r["id"] == _ri_sel), {})
                            _retention = _sel_ri.get("retention_limit") or 0
                            _auto_ceded = max(0, case["face_amount"] - _retention)

                            sq1, sq2, sq3 = st.columns(3)
                            _retention_amt = sq1.number_input(
                                f"Retention ({sym})",
                                value=int(_retention),
                                min_value=0, step=100_000,
                                help="Amount retained by your company.")
                            _ceded_amt = sq2.number_input(
                                f"Ceded amount ({sym})",
                                value=int(_auto_ceded),
                                min_value=0, step=100_000,
                                help="Amount ceded to the reinsurer (Face - Retention).")
                            _ri_prem = sq3.number_input(
                                f"RI premium ({sym})",
                                value=0,
                                min_value=0, step=1_000,
                                help="Premium paid to reinsurer for this cession.")
                            _cess_d1, _cess_d2 = st.columns(2)
                            _cess_eff = _cess_d1.date_input(
                                "Cession effective date",
                                value=date.today(),
                                key=f"cess_eff_{case['case_id']}",
                                help="Date from which the reinsurance cover takes effect.")
                            _cess_exp = _cess_d2.date_input(
                                "Cession expiry date",
                                value=None,
                                key=f"cess_exp_{case['case_id']}",
                                help="Date the RI cover expires. Leave blank = follows policy term.")
                            _ri_notes = st.text_area("Notes", height=60,
                                help="Any notes for this cession submission.")
                            if st.form_submit_button("📤 Submit Cession",
                                                     type="primary",
                                                     use_container_width=True):
                                try:
                                    conn = _get_db_conn()
                                    if conn:
                                        cur = conn.cursor()
                                        # Get application_id
                                        cur.execute(
                                            "SELECT application_id FROM uw_case WHERE id=%s",
                                            (case["case_id"],))
                                        app_row = cur.fetchone()
                                        _app_id = str(app_row[0]) if app_row else None

                                        cur.execute("""
                                            INSERT INTO ri_cession (
                                                case_id, application_id,
                                                reinsurer_id, treaty_code, cession_type,
                                                gross_face_amount, retention_amount,
                                                ceded_amount, gross_premium, ri_premium,
                                                net_retained_premium,
                                                status, submitted_at, submitted_by,
                                                cession_effective_date, cession_expiry_date,
                                                notes
                                            ) VALUES (
                                                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                                'SUBMITTED', NOW(), %s, %s, %s, %s
                                            )
                                        """, (
                                            case["case_id"], _app_id,
                                            _ri_sel, _sel_ri.get("treaty_code",""),
                                            _ri_type,
                                            case["face_amount"], _retention_amt,
                                            _ceded_amt, case["approved_premium"],
                                            _ri_prem,
                                            case["approved_premium"] - _ri_prem,
                                            uname,
                                            _cess_eff if _cess_eff else None,
                                            _cess_exp if _cess_exp else None,
                                            _ri_notes or None
                                        ))
                                        cur.close(); _release_db_conn(conn)
                                        _log_audit("REINSURANCE","RI_CESSION_SUBMITTED",
                                            entity_type="CASE",
                                            entity_id=case["case_id"],
                                            entity_ref=case["case_number"],
                                            after_state={
                                                "reinsurer": _sel_ri.get("name",""),
                                                "ceded": _ceded_amt,
                                                "ri_premium": _ri_prem})
                                        st.success("✅ Cession submitted.")
                                        st.rerun()
                                except Exception as se:
                                    st.error(f"Submit failed: {se}")

                if st.button("📄 Generate RI Slip",
                             key=f"slip_btn_{case['case_id']}",
                             help="Generate a reinsurance slip document for this case."):
                    st.session_state["ri_slip_case"] = case
                    st.session_state["ri_active_tab"] = 1
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 — RI SLIP GENERATOR
    # ══════════════════════════════════════════════════════════════════════
    with tab_slip:
        st.caption(
            "Generate a reinsurance slip for a case. "
            "Select a case from the RI Queue or search below."
        )

        # Case selector
        _slip_opts = {c["case_id"]: c for c in ri_cases}
        _slip_sel_id = st.selectbox(
            "Select case",
            options=["—"] + list(_slip_opts.keys()),
            format_func=lambda x: "Select a case..." if x == "—" else
                f"{_slip_opts[x]['case_number']} | "
                f"{sym}{_slip_opts[x]['face_amount']:,.0f} | "
                f"{_slip_opts[x]['product_code']} | "
                f"{_slip_opts[x]['outcome'] or 'Pending'}",
            index=(list(_slip_opts.keys()).index(
                st.session_state.get("ri_slip_case",{}).get("case_id",""))
                + 1) if st.session_state.get("ri_slip_case",{}).get("case_id","")
                      in _slip_opts else 0,
            help="Choose a reinsurance-flagged case to generate a slip for.",
            key="ri_slip_sel"
        )

        if _slip_sel_id == "—":
            st.info("Select a case above to generate its RI slip.")
        else:
            case = _slip_opts[_slip_sel_id]
            sel_ri = next((r for r in reinsurers
                           if r["id"] == case.get("reinsurer_id")), None)

            st.divider()

            # Slip form — editable fields
            st.markdown("##### RI Slip details")
            sl1, sl2, sl3 = st.columns(3)
            _slip_ri = sl1.selectbox(
                "Reinsurer",
                options=[r["id"] for r in reinsurers] if reinsurers else [0],
                format_func=lambda x: next(
                    (r["name"] for r in reinsurers if r["id"]==x),
                    "No reinsurers — add in Registry"),
                index=([r["id"] for r in reinsurers].index(case["reinsurer_id"])
                       if case["reinsurer_id"] in [r["id"] for r in reinsurers]
                       else 0) if reinsurers else 0,
                help="Reinsurer this slip is addressed to.",
                key="slip_ri_sel"
            )
            _slip_treaty = sl2.text_input("Treaty / Reference",
                value=sel_ri.get("treaty_code","") if sel_ri else "",
                help="Treaty code or facultative reference.",
                key="slip_treaty")
            _slip_date = sl3.date_input("Slip date", value=date.today(),
                help="Date on the RI slip.", key="slip_date")

            _sel_ri_obj = next((r for r in reinsurers if r["id"]==_slip_ri), {})
            _retention = _sel_ri_obj.get("retention_limit") or 0

            sd1, sd2, sd3 = st.columns(3)
            _slip_retention = sd1.number_input(
                f"Retention ({sym})", value=int(_retention),
                min_value=0, step=100_000, key="slip_ret",
                help="Amount your company retains.")
            _slip_ceded = sd2.number_input(
                f"Ceded amount ({sym})",
                value=int(max(0, case["face_amount"] - _retention)),
                min_value=0, step=100_000, key="slip_ceded",
                help="Amount ceded to reinsurer.")
            _slip_ri_prem = sd3.number_input(
                f"RI premium ({sym})", value=0,
                min_value=0, step=1_000, key="slip_ri_prem",
                help="Premium payable to reinsurer.")

            _slip_d1, _slip_d2 = st.columns(2)
            _slip_eff = _slip_d1.date_input(
                "Cession effective date", value=date.today(),
                key="slip_eff",
                help="Date from which RI cover takes effect.")
            _slip_exp = _slip_d2.date_input(
                "Cession expiry date", value=None,
                key="slip_exp",
                help="Date RI cover expires. Leave blank = follows policy term.")
            _slip_notes = st.text_area("Additional notes / special conditions",
                height=80, key="slip_notes",
                help="Any special conditions or notes to include on the slip.")

            st.divider()

            # Preview the slip
            _company = st.session_state.get("company_name", "UW Platform")
            _slip_html = f"""
<div style="font-family:'Segoe UI',Arial,sans-serif;max-width:720px;
            border:1px solid #d1d5db;border-radius:8px;padding:32px;
            background:#fff;color:#111827;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              border-bottom:2px solid #1d4ed8;padding-bottom:16px;margin-bottom:24px;">
    <div>
      <div style="font-size:20px;font-weight:700;color:#1d4ed8;">
        REINSURANCE CESSION SLIP
      </div>
      <div style="font-size:12px;color:#6b7280;margin-top:4px;">
        {_company} — Underwriting Department
      </div>
    </div>
    <div style="text-align:right;font-size:12px;color:#6b7280;">
      <div><b>Slip date:</b> {_slip_date}</div>
      <div><b>Case ref:</b> {case['case_number']}</div>
      <div><b>Treaty:</b> {_slip_treaty or '—'}</div>
      <div><b>Cover from:</b> {_slip_eff if _slip_eff else "—"}</div>
      <div><b>Cover to:</b> {_slip_exp if _slip_exp else "Per policy term"}</div>
    </div>
  </div>

  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
    <tr style="background:#eff6ff;">
      <td colspan="4" style="padding:8px 12px;font-weight:700;color:#1d4ed8;
          font-size:13px;">RISK DETAILS</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Applicant ref</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:600;">{case['applicant_ref']}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Applicant name</td>
      <td style="padding:8px 12px;font-size:13px;">{case['applicant_name'] or '—'}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f9fafb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Product</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:600;">{case['product_code']}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Age / Gender</td>
      <td style="padding:8px 12px;font-size:13px;">{case['age']} / {case['gender']}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">UW decision</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:600;">{case['outcome']}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Risk class</td>
      <td style="padding:8px 12px;font-size:13px;">{case['risk_class']}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f9fafb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Table rating</td>
      <td style="padding:8px 12px;font-size:13px;">{case['table_rating'] or '—'}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Flat extra</td>
      <td style="padding:8px 12px;font-size:13px;">
        {f"{sym}{case['flat_extra']:,.2f}/K" if case['flat_extra'] else '—'}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Net debit pts</td>
      <td style="padding:8px 12px;font-size:13px;">{case['net_debit_points']}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;"></td>
      <td style="padding:8px 12px;"></td>
    </tr>
  </table>

  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
    <tr style="background:#eff6ff;">
      <td colspan="4" style="padding:8px 12px;font-weight:700;color:#1d4ed8;
          font-size:13px;">FINANCIAL TERMS</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f9fafb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Gross face amount</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:700;">
        {sym}{case['face_amount']:,.0f}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Gross premium</td>
      <td style="padding:8px 12px;font-size:13px;">
        {sym}{case['approved_premium']:,.0f}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;">
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">Retention</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:700;">
        {sym}{_slip_retention:,.0f}</td>
      <td style="padding:8px 12px;font-size:12px;color:#6b7280;">RI premium</td>
      <td style="padding:8px 12px;font-size:13px;">{sym}{_slip_ri_prem:,.0f}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f0fdf4;">
      <td style="padding:8px 12px;font-size:12px;color:#166534;font-weight:600;">
        Ceded to RI</td>
      <td style="padding:8px 12px;font-size:14px;font-weight:700;color:#166534;">
        {sym}{_slip_ceded:,.0f}</td>
      <td style="padding:8px 12px;font-size:12px;color:#166534;font-weight:600;">
        Net retained premium</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:700;color:#166534;">
        {sym}{max(0,case['approved_premium']-_slip_ri_prem):,.0f}</td>
    </tr>
  </table>

  {"<div style='background:#fef3c7;border:1px solid #d97706;border-radius:6px;padding:12px;margin-bottom:16px;font-size:12px;'><b>Special conditions:</b> " + _slip_notes + "</div>" if _slip_notes else ""}

  <div style="border-top:1px solid #e5e7eb;padding-top:16px;
              font-size:11px;color:#9ca3af;">
    Generated by {_company} UW Platform on {date.today()} |
    This slip is subject to the terms of the applicable treaty/agreement.
  </div>
</div>
"""
            st.markdown("##### Preview")
            st.markdown(_slip_html, unsafe_allow_html=True)

            st.divider()

            # Download + mark as generated
            _slip_col1, _slip_col2 = st.columns(2)
            if _slip_col1.download_button(
                "⬇️ Download RI Slip (HTML)",
                data=_slip_html.encode(),
                file_name=f"ri_slip_{case['case_number']}_{_slip_date}.html",
                mime="text/html",
                use_container_width=True,
                help="Download the RI slip as an HTML file you can open in any browser or print to PDF."
            ):
                # Mark slip as generated in cession if one exists
                try:
                    conn = _get_db_conn()
                    if conn:
                        cur = conn.cursor()
                        if case.get("cession_id"):
                            cur.execute("""
                                UPDATE ri_cession
                                SET slip_generated_at=NOW(), updated_at=NOW()
                                WHERE id=%s
                            """, (case["cession_id"],))
                        else:
                            # Create a draft cession record
                            cur.execute("""
                                INSERT INTO ri_cession (
                                    case_id, reinsurer_id, cession_type,
                                    gross_face_amount, retention_amount, ceded_amount,
                                    gross_premium, ri_premium, net_retained_premium,
                                    status, slip_generated_at, submitted_by,
                                    cession_effective_date, cession_expiry_date
                                ) VALUES (%s,%s,'FACULTATIVE',%s,%s,%s,%s,%s,%s,
                                          'SLIP_GENERATED',NOW(),%s,%s,%s)
                            """, (
                                case["case_id"],
                                _slip_ri if reinsurers else None,
                                case["face_amount"], _slip_retention,
                                _slip_ceded, case["approved_premium"],
                                _slip_ri_prem,
                                case["approved_premium"] - _slip_ri_prem,
                                uname,
                                _slip_eff if _slip_eff else None,
                                _slip_exp if _slip_exp else None
                            )); cur.close(); _release_db_conn(conn)
                        _log_audit("REINSURANCE","RI_SLIP_GENERATED",
                            entity_type="CASE",
                            entity_id=case["case_id"],
                            entity_ref=case["case_number"],
                            metadata={"reinsurer": _sel_ri_obj.get("name",""),
                                      "ceded": _slip_ceded})
                except Exception as _exc:
                    logger.warning("[_load_ri_cases] Suppressed exception", exc_info=_exc)

            # ── Submit Cession button — always shown after slip preview ──
            st.divider()
            if case.get("ri_status") in ("SLIP_GENERATED", "NOT_SUBMITTED", None, ""):
                st.markdown("##### 📤 Submit to Reinsurer")
                st.caption("Once you have sent the slip to the reinsurer, click below to record the submission.")

                # Per-slip email override — respects global default
                _ri_global_auto = _get_ri_auto_email()
                _cur_ri_obj = next((r for r in reinsurers if r["id"] == case.get("reinsurer_id")), None)
                _ri_has_email = bool(_cur_ri_obj and _cur_ri_obj.get("email"))

                with st.form(f"submit_cession_gen_{case['case_id']}"):
                    _sc1, _sc2 = st.columns(2)
                    _sub_dt  = _sc1.date_input("Submission date", value=date.today())
                    _sub_ref = _sc2.text_input("Submission reference",
                        placeholder="e.g. Email ref, FAX no.")

                    # Per-slip email checkbox
                    _send_email = st.checkbox(
                        "📧 Email RI slip to reinsurer on submission",
                        value=_ri_global_auto and _ri_has_email,
                        help=(
                            f"Global default: {'ON ✅' if _ri_global_auto else 'OFF ⚫'} "
                            f"(change in System Config → Notifications → Reinsurance Email Settings). "
                            + (f"Will send to: {_cur_ri_obj.get('email','')}" if _ri_has_email
                               else "⚠️ No email set for this reinsurer — add in Reinsurer Registry.")
                        ),
                        disabled=not _ri_has_email
                    )
                    if not _ri_has_email:
                        st.caption(
                            "⚠️ Email disabled — no contact email for this reinsurer. "
                            "Add it in **Reinsurance → Reinsurer Registry → Edit reinsurer**."
                        )

                    if st.form_submit_button("📤 Submit Cession",
                                             type="primary",
                                             use_container_width=True):
                        try:
                            conn = _get_db_conn()
                            if conn:
                                cur = conn.cursor()
                                if case.get("cession_id"):
                                    # Update existing cession
                                    cur.execute("""
                                        UPDATE ri_cession
                                        SET status       = 'SUBMITTED',
                                            submitted_at = %s,
                                            notes        = COALESCE(notes || ' | ', '') || %s,
                                            updated_at   = NOW()
                                        WHERE id = %s
                                    """, (_sub_dt, _sub_ref or "Submitted",
                                          case["cession_id"]))
                                else:
                                    # Create new cession and mark submitted
                                    import secrets as _sec
                                    _cref = f"RI-{date.today().strftime('%Y%m%d')}-{_sec.randbelow(9000)+1000}"
                                    cur.execute("""
                                        INSERT INTO ri_cession
                                            (case_id, reinsurer_id, cession_ref, cession_type,
                                             gross_face_amount, retention_amount, ceded_amount,
                                             status, submitted_at, submitted_by,
                                             cession_effective_date)
                                        VALUES (%s,%s,%s,'FACULTATIVE',%s,%s,%s,
                                                'SUBMITTED',%s,%s,%s)
                                    """, (case["case_id"], _slip_ri, _cref,
                                          case["face_amount"],
                                          int(_slip_retention), int(_slip_ceded),
                                          _sub_dt, uname, _slip_eff or None))
                                conn.commit(); cur.close(); _release_db_conn(conn)
                                _log_audit("REINSURANCE", "RI_SLIP_SUBMITTED",
                                    entity_type="RI_CESSION",
                                    entity_id=case.get("cession_ref",""),
                                    entity_ref=case["case_number"],
                                    after_state={"status": "SUBMITTED"})

                                # Send email if checkbox ticked
                                if _send_email and _cur_ri_obj:
                                    _email_ok, _email_msg = _send_ri_slip_email(
                                        case, _cur_ri_obj, _slip_html
                                    )
                                    if _email_ok:
                                        st.success(
                                            f"✅ Cession submitted & email sent to "
                                            f"**{_cur_ri_obj.get('email','')}**!"
                                        )
                                    else:
                                        st.warning(
                                            f"✅ Cession submitted but email failed: {_email_msg}"
                                        )
                                else:
                                    st.success("✅ Cession submitted! Go to RI Queue to record the reinsurer's decision.")
                                st.rerun()
                        except Exception as _se:
                            st.error(f"Submit failed: {_se}")
            elif case.get("ri_status") == "SUBMITTED":
                st.success("✅ This cession has been submitted. Go to **RI Queue** to record the RI decision.")
            elif case.get("ri_status") == "DECISION_RECEIVED":
                st.success(f"✅ RI Decision recorded: **{case.get('ri_decision','')}**")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 — REINSURER REGISTRY
    # ══════════════════════════════════════════════════════════════════════
    with tab_reinsurers:
        st.caption("Configure reinsurers, treaty details, and retention limits.")

        rt_list, rt_add = st.tabs(["📋 All Reinsurers", "➕ Add Reinsurer"])

        with rt_list:
            all_ri = _load_reinsurers(active_only=False)
            if not all_ri:
                st.info("No reinsurers configured yet. Add your first reinsurer in the **Add Reinsurer** tab.")
            else:
                for ri in all_ri:
                    from datetime import date as _today_date
                    _today = _today_date.today()
                    _exp_d = ri.get("treaty_expiry_date")
                    _eff_d = ri.get("treaty_effective_date")
                    _expired = _exp_d and _exp_d < _today
                    _not_yet = _eff_d and _eff_d > _today
                    active_icon = ("🟢" if ri["is_active"] and not _expired and not _not_yet
                                   else "⚠️" if _expired or _not_yet
                                   else "⚫")
                    _date_note = (
                        f" | ⚠️ Expired {_exp_d}" if _expired
                        else f" | ⏳ Starts {_eff_d}" if _not_yet
                        else f" | Valid {_eff_d} → {_exp_d}" if _eff_d and _exp_d
                        else f" | From {_eff_d}" if _eff_d
                        else f" | Exp: {_exp_d}" if _exp_d
                        else ""
                    )
                    with st.expander(
                        f"{active_icon} **{ri['name']}**  ({ri['code']})  "
                        f"|  {ri['treaty_type']}  "
                        f"|  Retention: {sym}{ri['retention_limit']:,.0f}"
                        f"{_date_note}"
                        if ri['retention_limit'] else
                        f"{active_icon} **{ri['name']}**  ({ri['code']})  "
                        f"|  {ri['treaty_type']}  |  No retention limit"
                        f"{_date_note}"
                    ):
                        with st.form(f"ri_edit_{ri['id']}"):
                            re1, re2 = st.columns(2)
                            _rn  = re1.text_input("Reinsurer Name *",
                                value=ri["name"], key=f"ren_{ri['id']}")
                            _rc  = re2.text_input("Code *",
                                value=ri["code"], key=f"rec_{ri['id']}")
                            _rt1, _rt2 = st.columns(2)
                            _rtc = _rt1.text_input("Treaty Code",
                                value=ri["treaty_code"], key=f"rtc_{ri['id']}",
                                help="Treaty reference code, e.g. GEN-FAC-2026.")
                            _rtt = _rt2.selectbox("Treaty Type",
                                ["FACULTATIVE","TREATY","QUOTA_SHARE","SURPLUS"],
                                index=["FACULTATIVE","TREATY","QUOTA_SHARE","SURPLUS"]
                                    .index(ri["treaty_type"])
                                if ri["treaty_type"] in
                                    ["FACULTATIVE","TREATY","QUOTA_SHARE","SURPLUS"]
                                else 0,
                                key=f"rtt_{ri['id']}",
                                help="Type of reinsurance arrangement.")
                            _re1, _re2, _re3 = st.columns(3)
                            _rce = _re1.text_input("Contact email",
                                value=ri["email"], key=f"rce_{ri['id']}",
                                help="Email for sending RI slips and correspondence.")
                            _rrl = _re2.number_input(
                                f"Retention limit ({sym})",
                                value=int(ri["retention_limit"] or 0),
                                min_value=0, step=100_000,
                                key=f"rrl_{ri['id']}",
                                help="Cases above this amount are ceded to this reinsurer.")
                            _rcu = _re3.selectbox("Currency",
                                ["INR","USD","GBP","EUR","SGD"],
                                index=["INR","USD","GBP","EUR","SGD"].index(ri["currency"])
                                if ri["currency"] in ["INR","USD","GBP","EUR","SGD"] else 0,
                                key=f"rcu_{ri['id']}",
                                help="Currency for RI premium settlements.")
                            _red1, _red2 = st.columns(2)
                            _reff = _red1.date_input(
                                "Treaty effective date",
                                value=ri["treaty_effective_date"] if ri.get("treaty_effective_date") else None,
                                key=f"reff_{ri['id']}",
                                help="Date from which this treaty/agreement is valid.")
                            _rexp = _red2.date_input(
                                "Treaty expiry date",
                                value=ri["treaty_expiry_date"] if ri.get("treaty_expiry_date") else None,
                                key=f"rexp_{ri['id']}",
                                help="Date after which this treaty expires. Leave blank = no expiry.")
                            _rac = st.checkbox("Active",
                                value=ri["is_active"], key=f"rac_{ri['id']}",
                                help="Inactive reinsurers will not appear in cession forms.")
                            _rpc = st.text_input(
                                "Product Codes",
                                value=", ".join(ri.get("product_codes") or []),
                                key=f"rpc_{ri['id']}",
                                placeholder="e.g. IND-TERM-20, IND-TERM-30",
                                help="Comma-separated product codes this reinsurer covers. Leave blank = all products.")
                            _rno = st.text_area("Notes",
                                value=ri["notes"], height=60,
                                key=f"rno_{ri['id']}",
                                help="Internal notes about this reinsurer or treaty.")
                            if st.form_submit_button("💾 Save",
                                use_container_width=True, type="primary"):
                                try:
                                    conn = _get_db_conn()
                                    if conn:
                                        cur = conn.cursor()
                                        _rpc_list = [x.strip().upper() for x in _rpc.split(",") if x.strip()]
                                        cur.execute("""
                                            UPDATE ri_reinsurer SET
                                                reinsurer_name=%s, reinsurer_code=%s,
                                                treaty_code=%s, treaty_type=%s,
                                                contact_email=%s, retention_limit=%s,
                                                currency=%s, is_active=%s, notes=%s,
                                                product_codes=%s,
                                                treaty_effective_date=%s,
                                                treaty_expiry_date=%s,
                                                updated_at=NOW()
                                            WHERE id=%s
                                        """, (_rn, _rc, _rtc, _rtt, _rce,
                                              _rrl or None, _rcu, _rac, _rno,
                                              _rpc_list or None,
                                              _reff if _reff else None,
                                              _rexp if _rexp else None,
                                              ri["id"]))
                                        cur.close(); _release_db_conn(conn)
                                        _log_audit("CONFIG","REINSURER_UPDATED",
                                            entity_type="REINSURER",
                                            entity_id=str(ri["id"]),
                                            entity_ref=_rn)
                                        st.success(f"✅ {_rn} updated.")
                                        st.rerun()
                                except Exception as ue:
                                    st.error(f"Save failed: {ue}")

        with rt_add:
            st.markdown("#### Register new reinsurer")
            with st.form("ri_add_form"):
                an1, an2 = st.columns(2)
                _an  = an1.text_input("Reinsurer Name *",
                    placeholder="e.g. Munich Re India",
                    help="Full legal name of the reinsurer.")
                _ac  = an2.text_input("Code *",
                    placeholder="e.g. MUNICH-RE",
                    help="Short unique code used internally.")
                at1, at2 = st.columns(2)
                _atc = at1.text_input("Treaty Code",
                    placeholder="e.g. FAC-2026-001",
                    help="Treaty or facultative reference code.")
                _att = at2.selectbox("Treaty Type",
                    ["FACULTATIVE","TREATY","QUOTA_SHARE","SURPLUS"],
                    help="Type of reinsurance arrangement.")
                ae1, ae2, ae3 = st.columns(3)
                _ace = ae1.text_input("Contact Email",
                    placeholder="ri@munichre.com",
                    help="Used for sending RI slips.")
                _arl = ae2.number_input(
                    f"Retention limit ({sym})",
                    min_value=0, value=5_000_000, step=500_000,
                    help="Face amount above which cases are ceded here.")
                _acu = ae3.selectbox("Currency",
                    ["INR","USD","GBP","EUR","SGD"],
                    help="Settlement currency.")
                _add_d1, _add_d2 = st.columns(2)
                _aeff = _add_d1.date_input(
                    "Treaty effective date", value=None,
                    key="ri_add_eff",
                    help="Date from which this treaty is valid. Leave blank = active immediately.")
                _aexp = _add_d2.date_input(
                    "Treaty expiry date", value=None,
                    key="ri_add_exp",
                    help="Date the treaty expires. Leave blank = no expiry.")
                _ano = st.text_area("Notes", height=60,
                    key="ri_add_notes",
                    help="Internal notes about this reinsurer.")
                if st.form_submit_button("➕ Add Reinsurer",
                    type="primary", use_container_width=True):
                    if not _an.strip() or not _ac.strip():
                        st.error("Name and Code are required.")
                    else:
                        try:
                            conn = _get_db_conn()
                            if conn:
                                cur = conn.cursor()
                                cur.execute("""
                                    INSERT INTO ri_reinsurer
                                        (reinsurer_name, reinsurer_code, treaty_code,
                                         treaty_type, contact_email, retention_limit,
                                         currency, is_active, notes,
                                         treaty_effective_date, treaty_expiry_date)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,%s)
                                """, (_an.strip(), _ac.strip().upper(),
                                      _atc.strip() or None, _att,
                                      _ace.strip() or None,
                                      _arl if _arl > 0 else None,
                                      _acu, _ano.strip() or None,
                                      _aeff if _aeff else None,
                                      _aexp if _aexp else None))
                                cur.close(); _release_db_conn(conn)
                                _log_audit("CONFIG","REINSURER_ADDED",
                                    entity_type="REINSURER", entity_ref=_an.strip())
                                st.success(f"✅ {_an.strip()} added to reinsurer registry.")
                                st.rerun()
                        except Exception as ae:
                            st.error(f"Add failed: {ae}")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 4 — CESSION HISTORY
    # ══════════════════════════════════════════════════════════════════════
    with tab_history:
        st.caption("Full history of all reinsurance cessions.")
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        ri.cession_ref, c.case_number,
                        rr.reinsurer_name, ri.cession_type,
                        ri.status, ri.ri_decision,
                        ri.gross_face_amount, ri.ceded_amount,
                        ri.gross_premium, ri.ri_premium,
                        ri.net_retained_premium,
                        ri.submitted_at, ri.ri_decision_date,
                        ri.submitted_by, ri.ri_reference,
                        ri.cession_effective_date, ri.cession_expiry_date
                    FROM ri_cession ri
                    JOIN uw_case c         ON c.id = ri.case_id::uuid
                    LEFT JOIN ri_reinsurer rr ON rr.id = ri.reinsurer_id
                    ORDER BY ri.created_at DESC
                    LIMIT 200
                """)
                hist = cur.fetchall()
                cur.close(); _release_db_conn(conn)

                if not hist:
                    st.info("No cessions recorded yet.")
                else:
                    df_h = pd.DataFrame(hist, columns=[
                        "Cession ref","Case","Reinsurer","Type","RI Status",
                        "RI Decision","Gross face","Ceded","Gross prem",
                        "RI prem","Net retained prem","Submitted at",
                        "Decision date","Submitted by","RI reference",
                        "Effective date","Expiry date"
                    ])
                    # Format currency columns
                    for col in ["Gross face","Ceded","Gross prem",
                                "RI prem","Net retained prem"]:
                        df_h[col] = df_h[col].apply(
                            lambda x: f"{sym}{float(x):,.0f}" if x else "—")
                    df_h["Submitted at"] = df_h["Submitted at"].astype(str).str[:16]
                    df_h["Decision date"] = df_h["Decision date"].astype(str).str[:10]

                    st.dataframe(df_h, use_container_width=True, hide_index=True)

                    # Export
                    st.download_button(
                        "⬇️ Export CSV",
                        data=df_h.to_csv(index=False).encode(),
                        file_name=f"ri_cessions_{date.today()}.csv",
                        mime="text/csv",
                        help="Download full cession history as CSV."
                    )
        except Exception as ex:
            st.error(f"History error: {ex}")

def render_audit_log():
    """Audit Log — immutable, searchable, filterable, exportable event trail."""
    import pandas as pd
    import json as _json
    from datetime import date, timedelta, datetime as _dt

    _ensure_audit_table()

    st.markdown("## 🔍 Audit Log")
    st.caption(
        "Immutable record of every decision, override, assignment, login, "
        "config change and user management action. Cannot be edited or deleted."
    )

    # ── First-run helper ─────────────────────────────────────────────────────
    if st.button("📝 Record current session login to audit trail", key="seed_audit",
                 help="Use this once to write your current login to the audit trail "
                      "and confirm the table is working correctly."):
        _uname = st.session_state.get("username","")
        _uname = _uname.split("@")[0] if "@" in _uname else _uname
        _log_audit("AUTH","LOGIN_SUCCESS",
            entity_type="USER", entity_id=_uname,
            actor_username=_uname,
            actor_role=st.session_state.get("role",""),
            metadata={"method":"manual_seed", "note": "Manually recorded from Audit Log page"})
        st.success("✅ Login event written to audit trail — refresh the page to see it.")
        st.rerun()

    # ── Summary metrics (DB-direct) ───────────────────────────────────────────
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*)                                        AS total,
                    COUNT(*) FILTER (WHERE event_category='DECISION')    AS decisions,
                    COUNT(*) FILTER (WHERE event_category='OVERRIDE')    AS overrides,
                    COUNT(*) FILTER (WHERE event_category='AUTH')        AS auth,
                    COUNT(*) FILTER (WHERE event_category='CONFIG')      AS config,
                    COUNT(*) FILTER (WHERE event_category='ASSIGNMENT')  AS assignments,
                    COUNT(*) FILTER (WHERE event_category='USER_MGMT')   AS user_mgmt,
                    COUNT(*) FILTER (WHERE outcome='FAILURE')            AS failures
                FROM audit_trail
                WHERE occurred_at >= NOW() - INTERVAL '30 days'
            """)
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                m1,m2,m3,m4,m5,m6,m7,m8 = st.columns(8)
                m1.metric("Total (30d)",    f"{row[0]:,}")
                m2.metric("Decisions",      f"{row[1]:,}")
                m3.metric("Overrides",      f"{row[2]:,}")
                m4.metric("Auth",           f"{row[3]:,}")
                m5.metric("Config",         f"{row[4]:,}")
                m6.metric("Assignments",    f"{row[5]:,}")
                m7.metric("User mgmt",      f"{row[6]:,}")
                m8.metric("Failures",       f"{row[7]:,}")
    except Exception as _exc:
        logger.debug("[render_audit_log] Suppressed exception", exc_info=_exc)
        st.info("Audit trail is initialising — events will appear as you use the platform.")

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("🔎 Filters & Search", expanded=True):
        fc1, fc2, fc3, fc4, fc5 = st.columns([2,1,1,1,1])
        search   = fc1.text_input("Search",
            placeholder="username, case ref, event type...",
            help="Searches actor_username, entity_ref, event_type and entity_id.")
        date_from = fc2.date_input("From",
            value=date.today() - timedelta(days=30),
            help="Start of date range (inclusive).")
        date_to   = fc3.date_input("To",
            value=date.today(),
            help="End of date range (inclusive).")
        sel_cat  = fc4.selectbox("Category",
            ["All","DECISION","OVERRIDE","AUTH","ASSIGNMENT","APS",
             "USER_MGMT","CONFIG","RULE","BATCH","MEMBER","DATA_ACCESS"],
            help="Filter by event category.")
        sel_outcome = fc5.selectbox("Outcome",
            ["All","SUCCESS","FAILURE"],
            help="Filter by whether the action succeeded or failed.")
        page = st.number_input("Page", min_value=1, value=1, step=1,
            help="Each page shows 50 events.")

    PAGE_SIZE = 50
    offset    = (page - 1) * PAGE_SIZE

    # ── Query ─────────────────────────────────────────────────────────────────
    try:
        conn = _get_db_conn()
        if not conn:
            st.error("Database unavailable.")
            return
        cur = conn.cursor()

        # Build WHERE clause
        conditions = [
            "occurred_at >= %s",
            "occurred_at <= %s",
        ]
        qparams = [
            _dt.combine(date_from, _dt.min.time()),
            _dt.combine(date_to,   _dt.max.time()),
        ]
        if sel_cat != "All":
            conditions.append("event_category = %s")
            qparams.append(sel_cat)
        if sel_outcome != "All":
            conditions.append("outcome = %s")
            qparams.append(sel_outcome)
        if search.strip():
            conditions.append("""(
                actor_username ILIKE %s OR
                event_type     ILIKE %s OR
                entity_ref     ILIKE %s OR
                entity_id      ILIKE %s OR
                entity_type    ILIKE %s
            )""")
            _s = f"%{search.strip()}%"
            qparams.extend([_s, _s, _s, _s, _s])

        where = " AND ".join(conditions)

        # Total count
        cur.execute(f"SELECT COUNT(*) FROM audit_trail WHERE {where}", qparams)
        total_rows = cur.fetchone()[0]
        total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)

        # Fetch page
        cur.execute(f"""
            SELECT
                event_id, occurred_at, event_category, event_type,
                actor_username, actor_role, entity_type, entity_id,
                entity_ref, outcome, failure_reason,
                before_state, after_state, event_metadata, actor_ip
            FROM audit_trail
            WHERE {where}
            ORDER BY occurred_at DESC
            LIMIT %s OFFSET %s
        """, qparams + [PAGE_SIZE, offset])
        rows = cur.fetchall()
        cur.close(); _release_db_conn(conn)
    except Exception as ex:
        st.error(f"Query failed: {ex}")
        return

    # ── Toolbar ───────────────────────────────────────────────────────────────
    tb1, tb2, tb3 = st.columns([3, 1, 1])
    tb1.caption(f"Showing {len(rows)} of {total_rows:,} events  |  Page {page} of {total_pages}")

    if tb2.button("📥 Export CSV", use_container_width=True,
                  help="Download all matching events (not just this page) as CSV."):
        try:
            conn2 = _get_db_conn()
            if conn2:
                cur2 = conn2.cursor()
                cur2.execute(f"""
                    SELECT
                        event_id, occurred_at, event_category, event_type,
                        actor_username, actor_role, entity_type, entity_id,
                        entity_ref, outcome, failure_reason, actor_ip
                    FROM audit_trail WHERE {where}
                    ORDER BY occurred_at DESC
                    LIMIT 10000
                """, qparams)
                exp_rows = cur2.fetchall()
                cur2.close(); conn2.close()
                exp_df = pd.DataFrame(exp_rows, columns=[
                    "event_id","occurred_at","category","event_type",
                    "actor","role","entity_type","entity_id",
                    "entity_ref","outcome","failure_reason","actor_ip"
                ])
                st.download_button(
                    "💾 Download",
                    data=exp_df.to_csv(index=False).encode(),
                    file_name=f"audit_{date_from}_{date_to}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
        except Exception as ex:
            st.error(f"Export failed: {ex}")

    if tb3.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    if not rows:
        st.info("No audit events found for the selected filters.")
        return

    # ── Category badge colours ────────────────────────────────────────────────
    _CAT_ICON = {
        "DECISION":    "🟢", "OVERRIDE":   "🔴",
        "AUTH":        "🔵", "ASSIGNMENT": "🟤",
        "APS":         "🟣", "USER_MGMT":  "🟠",
        "CONFIG":      "🟡", "RULE":       "⚫",
        "BATCH":       "🔶", "MEMBER":     "🔷",
        "DATA_ACCESS": "⚪",
    }

    # ── Table ─────────────────────────────────────────────────────────────────
    df = pd.DataFrame([{
        "Time":       str(r[1])[:19].replace("T"," "),
        "Category":   _CAT_ICON.get(r[2],"⚪") + " " + str(r[2]),
        "Event":      str(r[3]),
        "Actor":      str(r[4] or "—"),
        "Role":       str(r[5] or "—"),
        "Entity":     str(r[6] or "—"),
        "Ref":        str(r[8] or "")[:40],
        "Outcome":    "✅" if r[9]=="SUCCESS" else "❌",
        "_id":        r[0],
    } for r in rows])

    st.dataframe(
        df.drop(columns=["_id"]),
        use_container_width=True,
        hide_index=True,
        height=420,
    )

    # ── Event Detail ──────────────────────────────────────────────────────────
    st.divider()
    st.markdown("##### Event detail")
    sel_id = st.selectbox(
        "Select event to inspect",
        options=["—"] + list(df["_id"]),
        format_func=lambda x: "Select..." if x == "—" else
            next((f"{str(r[1])[:19]}  |  {r[3]}  |  {r[4] or '—'}"
                  for r in rows if r[0] == x), x),
        help="Select any event to see before/after state and full metadata.",
        key="audit_detail_sel"
    )

    if sel_id and sel_id != "—":
        row = next((r for r in rows if r[0] == sel_id), None)
        if row:
            (event_id, occurred_at, category, event_type,
             actor, actor_role, entity_type, entity_id,
             entity_ref, outcome, failure_reason,
             before_state, after_state, metadata, actor_ip) = row

            # Header bar
            outcome_color = "var(--color-background-success)" if outcome=="SUCCESS" \
                            else "var(--color-background-danger)"
            st.markdown(
                f"<div style='padding:10px 14px;border-radius:8px;"
                f"background:{outcome_color};margin-bottom:12px'>"
                f"<b>{event_type}</b> &nbsp;·&nbsp; {str(occurred_at)[:19]} "
                f"&nbsp;·&nbsp; {actor or '—'} ({actor_role or '—'})"
                f"{'&nbsp;·&nbsp; ❌ ' + failure_reason if failure_reason else ''}"
                f"</div>",
                unsafe_allow_html=True
            )

            d1, d2, d3 = st.columns(3)
            with d1:
                st.markdown("**Event**")
                st.caption(f"ID: `{event_id}`")
                st.caption(f"Category: `{category}`")
                st.caption(f"Entity: `{entity_type}` / `{entity_id or '—'}`")
                st.caption(f"Ref: `{entity_ref or '—'}`")
                st.caption(f"IP: `{actor_ip or '—'}`")

            with d2:
                st.markdown("**Before state**")
                if before_state:
                    try:
                        st.json(_json.loads(before_state)
                                if isinstance(before_state, str)
                                else before_state)
                    except Exception as _exc:
                        logger.debug("[render_audit_log] Suppressed exception", exc_info=_exc)
                        st.code(str(before_state))
                else:
                    st.caption("—")

            with d3:
                st.markdown("**After state**")
                if after_state:
                    try:
                        st.json(_json.loads(after_state)
                                if isinstance(after_state, str)
                                else after_state)
                    except Exception as _exc:
                        logger.debug("[render_audit_log] Suppressed exception", exc_info=_exc)
                        st.code(str(after_state))
                else:
                    st.caption("—")

            if metadata:
                with st.expander("Full metadata"):
                    try:
                        st.json(_json.loads(metadata)
                                if isinstance(metadata, str) else metadata)
                    except Exception as _exc:
                        logger.debug("[render_audit_log] Suppressed exception", exc_info=_exc)
                        st.code(str(metadata))

            # Case timeline — show all audit events for this entity
            if entity_id:
                with st.expander(f"All events for {entity_type} `{entity_id}`"):
                    try:
                        conn3 = _get_db_conn()
                        if conn3:
                            cur3 = conn3.cursor()
                            cur3.execute("""
                                SELECT occurred_at, event_type, actor_username,
                                       outcome, event_category
                                FROM audit_trail
                                WHERE entity_id = %s
                                ORDER BY occurred_at ASC
                            """, (str(entity_id),))
                            tl_rows = cur3.fetchall()
                            cur3.close(); conn3.close()
                            if tl_rows:
                                tl_df = pd.DataFrame(tl_rows, columns=[
                                    "Time","Event","Actor","Outcome","Category"
                                ])
                                tl_df["Time"] = tl_df["Time"].astype(str).str[:19]
                                st.dataframe(tl_df, use_container_width=True,
                                             hide_index=True)
                    except Exception as te:
                        st.error(f"Timeline error: {te}")

# ══════════════════════════════════════════════════════════════════════════════
#  USAGE METERING
# ══════════════════════════════════════════════════════════════════════════════

def _get_usage_this_month(tenant_id: str = None) -> dict:
    """Count decisions this calendar month for billing/metering."""
    from datetime import date as _d
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*)                                            AS total,
                    COUNT(*) FILTER(WHERE d.decided_by_type='ENGINE')  AS stp,
                    COUNT(*) FILTER(WHERE d.decided_by_type='HUMAN')   AS manual,
                    COUNT(*) FILTER(WHERE d.outcome ILIKE 'APPROVED%%') AS approved,
                    COUNT(*) FILTER(WHERE d.outcome ILIKE 'DECLIN%%')  AS declined
                FROM uw_decision d
                JOIN uw_case c ON c.id = d.case_id
                WHERE d.is_final = TRUE
                  AND DATE_TRUNC('month', d.decided_at) = DATE_TRUNC('month', NOW())
            """)
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                return {
                    "total":    int(row[0] or 0),
                    "stp":      int(row[1] or 0),
                    "manual":   int(row[2] or 0),
                    "approved": int(row[3] or 0),
                    "declined": int(row[4] or 0),
                    "month":    _d.today().strftime("%B %Y"),
                }
    except Exception as _exc:
        logger.debug("[_get_usage_this_month] Suppressed exception", exc_info=_exc)
    return {"total": 0, "stp": 0, "manual": 0,
            "approved": 0, "declined": 0, "month": ""}


# ══════════════════════════════════════════════════════════════════════════════
#  ONBOARDING WIZARD
# ══════════════════════════════════════════════════════════════════════════════

def _check_onboarding_complete() -> dict:
    """
    Check which onboarding steps are complete.
    Returns a dict of {step_key: bool}.
    """
    steps = {
        "smtp":        False,
        "products":    False,
        "rates":       False,
        "users":       False,
        "rules":       False,
    }
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            # SMTP configured
            cur.execute("SELECT COUNT(*) FROM smtp_config WHERE key='host' AND value != ''")
            steps["smtp"] = (cur.fetchone() or [0])[0] > 0
            # Products exist
            cur.execute("SELECT COUNT(*) FROM products WHERE is_active=TRUE")
            steps["products"] = (cur.fetchone() or [0])[0] > 0
            # Rate tables exist
            for tbl in ["premium_rate_table", "rate_tables"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl} LIMIT 1")
                    if (cur.fetchone() or [0])[0] > 0:
                        steps["rates"] = True
                        break
                except Exception as _exc:
                    logger.warning("[_check_onboarding_complete] Suppressed exception", exc_info=_exc)
            # Users beyond default
            cur.execute("SELECT COUNT(*) FROM uw_user WHERE is_active=TRUE")
            steps["users"] = (cur.fetchone() or [0])[0] > 0
            # Custom rules
            for tbl in ["custom_rules", "rules"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl} LIMIT 1")
                    if (cur.fetchone() or [0])[0] > 0:
                        steps["rules"] = True
                        break
                except Exception as _exc:
                    logger.warning("[_check_onboarding_complete] Suppressed exception", exc_info=_exc)
            cur.close(); _release_db_conn(conn)
    except Exception as _exc:
        logger.warning("[_check_onboarding_complete] Suppressed exception", exc_info=_exc)
    return steps


def render_onboarding():
    """First-run onboarding wizard."""
    st.markdown("## 🚀 Getting Started")
    st.caption("Complete these steps to get your UW Platform ready for production.")

    steps_done = _check_onboarding_complete()
    total_done = sum(steps_done.values())
    total_steps = len(steps_done)

    # Progress bar
    pct = int(total_done / total_steps * 100)
    st.progress(pct / 100,
                text=f"Setup progress: {total_done}/{total_steps} steps complete")
    if total_done == total_steps:
        st.success("🎉 All setup steps complete — your platform is ready for production!")
    st.divider()

    STEPS = [
        ("smtp",     "📧", "Configure email (SMTP)",
         "Required for decision letters, APS emails, and SLA notifications.",
         "System Config → API Keys → Email (SMTP)"),
        ("products", "📦", "Add your products",
         "Define the insurance products your underwriters will evaluate.",
         "Product Config → New Product"),
        ("rates",    "💰", "Upload rate tables",
         "Premium rate tables are needed for premium calculation.",
         "System Config → Upload Rates"),
        ("users",    "👥", "Create underwriter accounts",
         "Add your underwriting team with appropriate roles and authority limits.",
         "User Management → Create User"),
        ("rules",    "⚙️",  "Configure UW rules",
         "Build the underwriting rules that drive your decision engine.",
         "Rule Builder → Custom Rules"),
    ]

    for key, icon, title, desc, nav in STEPS:
        done = steps_done.get(key, False)
        with st.expander(
            f"{'✅' if done else '⬜'} {icon} **{title}**",
            expanded=not done
        ):
            st.caption(desc)
            if done:
                st.success(f"✅ Complete — go to **{nav}** to review or update.")
            else:
                st.warning(f"⚠️ Not yet configured.")
                if st.button(f"Go to {nav.split('→')[0].strip()}",
                             key=f"onboard_goto_{key}",
                             type="primary"):
                    # Navigate to the relevant page
                    _page_map = {
                        "smtp":     "System Config",
                        "products": "Product Config",
                        "rates":    "System Config",
                        "users":    "User Management",
                        "rules":    "Rule Builder",
                    }
                    st.session_state.page = _page_map.get(key, "System Config")
                    st.rerun()

    st.divider()

    # Usage this month
    st.markdown("### 📊 This month's usage")
    _usage = _get_usage_this_month()
    um1,um2,um3,um4,um5 = st.columns(5)
    um1.metric("Total decisions", f"{_usage['total']:,}")
    um2.metric("STP",             f"{_usage['stp']:,}")
    um3.metric("Manual",          f"{_usage['manual']:,}")
    um4.metric("Approved",        f"{_usage['approved']:,}")
    um5.metric("Declined",        f"{_usage['declined']:,}")
    st.caption(f"Month: {_usage['month']}")

    st.divider()

    # Sample data seeding — only available in development/staging environments
    if cfg.allow_sample_data_seeding:
        st.markdown("### 🌱 Sample data")
        st.caption(
            "Populate the platform with realistic sample cases for testing. "
            "**Not available in production** — controlled by the APP_ENV environment variable."
        )
        _seed_col1, _seed_col2 = st.columns([3, 1])
        _seed_col1.info(
            "Creates 20 sample cases with mixed outcomes (approved, declined, referred, APS), "
            "member data, and audit events. Safe to run multiple times — generates new refs each time."
        )
        if _seed_col2.button("🌱 Seed sample data",
                              type="primary",
                              use_container_width=True,
                              key="seed_sample_btn",
                              help="Adds sample cases for testing. Only available in non-production environments."):
            _seed_demo_data()
            st.success("✅ Sample data seeded — check UW Queue and Audit Log.")
            st.rerun()
    elif st.session_state.get("role", "") == "super_admin":
        # Show a disabled indicator in production so admins know it exists
        st.markdown("### 🌱 Sample data")
        st.info("⚙️ Sample data seeding is disabled in production (APP_ENV=production).")


def _seed_demo_data():
    """Insert realistic sample cases, decisions, and audit events for testing/staging."""
    import uuid as _uuid, random as _rnd
    from datetime import date as _d, timedelta as _td, datetime as _dt

    _rnd.seed(42)  # reproducible but varied

    NAMES = [
        ("Rajesh Kumar", "MALE", 42, "MH"),    ("Priya Sharma", "FEMALE", 35, "DL"),
        ("Amit Singh", "MALE", 28, "KA"),      ("Sunita Patel", "FEMALE", 51, "GJ"),
        ("Vikram Mehta", "MALE", 38, "TN"),    ("Deepa Nair", "FEMALE", 44, "KL"),
        ("Arjun Reddy", "MALE", 31, "AP"),     ("Kavita Joshi", "FEMALE", 57, "MP"),
        ("Sanjay Gupta", "MALE", 46, "UP"),    ("Anita Verma", "FEMALE", 33, "RJ"),
        ("Rahul Das", "MALE", 29, "WB"),       ("Meena Iyer", "FEMALE", 48, "TN"),
        ("Suresh Nair", "MALE", 55, "KL"),     ("Pooja Agarwal", "FEMALE", 27, "HR"),
        ("Manish Jain", "MALE", 63, "GJ"),     ("Rina Bose", "FEMALE", 41, "WB"),
        ("Nitin Desai", "MALE", 36, "MH"),     ("Swati Mishra", "FEMALE", 52, "UP"),
        ("Ajay Pillai", "MALE", 44, "KL"),     ("Neha Sinha", "FEMALE", 38, "BR"),
    ]

    PRODUCTS = ["IND-TERM-10","IND-TERM-20","IND-TERM-30"]
    OUTCOMES = (["APPROVED"]*8 + ["APPROVED_RATED"]*3 +
                ["DECLINED"]*3 + ["REFERRED"]*3 + ["POSTPONED"]*2 + ["REQUEST_APS"]*1)
    RISK_CLASSES = ["PREFERRED_PLUS","PREFERRED","STANDARD","STANDARD_PLUS","SUBSTANDARD"]

    try:
        conn = _get_db_conn()
        if not conn:
            return
        cur = conn.cursor()

        for i, (name, gender, age, state) in enumerate(NAMES):
            ref        = f"DEMO-{_d.today().strftime('%Y%m')}-{i+1:03d}"
            product    = PRODUCTS[i % len(PRODUCTS)]
            face       = _rnd.choice([500_000,1_000_000,2_000_000,5_000_000])
            outcome    = OUTCOMES[i % len(OUTCOMES)]
            risk_class = RISK_CLASSES[i % len(RISK_CLASSES)]
            net_db     = _rnd.randint(-10, 40)
            premium    = round(face / 1000 * _rnd.uniform(0.8, 3.2), 2)                          if "APPROVED" in outcome else None
            case_num   = f"CASE-{_d.today().strftime('%Y')}-{3000+i}"
            app_id     = str(_uuid.uuid4())
            case_id    = str(_uuid.uuid4())
            eff_date   = _d.today() + _td(days=_rnd.randint(1,30))

            # Insert application
            try:
                cur.execute("""
                    INSERT INTO application
                        (id, applicant_ref, age, gender, state,
                         face_amount, product_code, coverage_term_yrs,
                         tobacco_status, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'NON_TOBACCO',NOW())
                    ON CONFLICT DO NOTHING
                """, (app_id, ref, age, gender, state, face, product,
                      int(product.split("-")[-1]) if product.split("-")[-1].isdigit() else 20))
            except Exception as _exc:
                logger.warning("[_seed_demo_data] Suppressed exception", exc_info=_exc)
                conn.rollback()
                continue

            # Insert case
            try:
                ri_req = face >= 5_000_000
                cur.execute("""
                    INSERT INTO uw_case
                        (id, case_number, application_id, status,
                         reinsurance_required, created_at)
                    VALUES (%s,%s,%s,%s,%s,
                            NOW() - INTERVAL '%s days')
                    ON CONFLICT DO NOTHING
                """, (case_id, case_num, app_id,
                      "OPEN" if "REFER" in outcome or "APS" in outcome
                      else ("IN_PROGRESS" if i % 5 == 0 else "APPROVED"),
                      ri_req, _rnd.randint(0, 30)))
            except Exception as _exc:
                logger.warning("[_seed_demo_data] Suppressed exception", exc_info=_exc)
                conn.rollback()
                continue

            # Insert decision
            try:
                cur.execute("""
                    INSERT INTO uw_decision
                        (case_id, outcome, risk_class, net_debit_points,
                         approved_premium, is_final, decided_by_type,
                         decided_at, policy_effective_date, tenant_id)
                    VALUES (%s,%s,%s,%s,%s,TRUE,'ENGINE',
                            NOW() - INTERVAL '%s hours',%s,
                            '00000000-0000-0000-0000-000000000001')
                    ON CONFLICT DO NOTHING
                """, (case_id, outcome, risk_class, net_db,
                      premium, _rnd.randint(1, 72), str(eff_date)))
            except Exception as _exc:
                logger.warning("[_seed_demo_data] Suppressed exception", exc_info=_exc)
                conn.rollback()

            # Queue for PAS
            try:
                cur.execute("""
                    INSERT INTO policy_admin_queue
                        (applicant_ref, applicant_name, product_code,
                         face_amount, age, gender, state, case_id,
                         outcome, risk_class, net_debit_points,
                         approved_premium, effective_date, source, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DEMO','UNPROCESSED')
                    ON CONFLICT DO NOTHING
                """, (ref, name, product, face, age, gender, state,
                      case_id, outcome, risk_class, net_db,
                      premium, str(eff_date)))
            except Exception as _exc:
                logger.warning("[_seed_demo_data] Suppressed exception", exc_info=_exc)
                conn.rollback()
        cur.close()
        _release_db_conn(conn)
    except Exception as ex:
        logger.error("[_seed_demo_data] Failed to seed sample data", exc_info=ex)


def render_tenant_management():
    """Tenant Management — register carriers, monitor usage, manage limits."""
    import pandas as pd
    st.markdown("## \U0001f3e2 Tenant Management")
    st.caption("Register and manage insurance carrier tenants. Super Admin only.")

    tok = st.session_state.get("token","")
    hdr = {"Authorization": f"Bearer {tok}"}
    API  = API_BASE

    tab_list, tab_create, tab_detail = st.tabs([
        "\U0001f4cb All Tenants", "\u2795 New Tenant", "\U0001f50d Tenant Detail"
    ])

    # ── Tab 1: Tenant List ────────────────────────────────────────────────────
    with tab_list:
        col_r, col_b = st.columns([3,1])
        f_status = col_r.selectbox("Status filter",
            ["ALL","ACTIVE","SUSPENDED","TRIAL"], key="t_status_f")
        if col_b.button("\U0001f504 Refresh", key="refresh_tenants"):
            st.rerun()

        params = {}
        if f_status != "ALL": params["status"] = f_status
        try:
            resp    = requests.get(f"{API}/tenants/", headers=hdr,
                                   params=params, timeout=10)
            tenants = resp.json().get("tenants", []) if resp.status_code == 200 else []
        except Exception as e:
            st.error(f"Error: {e}"); tenants = []

        if not tenants:
            st.info("No tenants found. Add your first carrier below.")
        else:
            # Summary metrics
            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("Total Tenants",   len(tenants))
            m2.metric("Active",          sum(1 for t in tenants if t["status"]=="ACTIVE"))
            m3.metric("Suspended",       sum(1 for t in tenants if t["status"]=="SUSPENDED"))
            m4.metric("Total Users",     sum(t.get("user_count",0) for t in tenants))
            m5.metric("Plans",           len(set(t.get("plan_tier","") for t in tenants)))
            st.divider()

            for t in tenants:
                status_emoji = {
                    "ACTIVE": "\U0001f7e2", "SUSPENDED": "\U0001f534",
                    "TRIAL":  "\U0001f7e1", "INACTIVE": "\u26ab"
                }.get(t["status"], "\u26aa")
                tier_badge = {
                    "ENTERPRISE": "\U0001f31f", "PROFESSIONAL": "\U0001f4bc",
                    "STANDARD": "\U0001f4cb", "TRIAL": "\U0001f9ea"
                }.get(t.get("plan_tier",""), "")

                with st.expander(
                    f"{status_emoji} **{t['tenant_code']}** — {t['tenant_name']} "
                    f"| {tier_badge} {t.get('plan_tier','')} "
                    f"| {t.get('user_count',0)} users"
                ):
                    c1,c2,c3 = st.columns(3)
                    c1.markdown(f"**Contact:** {t.get('contact_name','—')}")
                    c1.markdown(f"**Email:** {t.get('contact_email','—')}")
                    c2.markdown(f"**Type:** {t.get('company_type','—')}")
                    c2.markdown(f"**NAIC:** {t.get('naic_code','—') or '—'}")
                    c3.markdown(f"**Max Users:** {t.get('max_users',0)}")
                    c3.markdown(f"**Max Decisions/mo:** {t.get('max_decisions_per_month',0):,}")

                    contract_start = str(t.get("contract_start",""))[:10]
                    contract_end   = str(t.get("contract_end",""))[:10]
                    from datetime import date as _d
                    if contract_start or contract_end:
                        try:
                            start_str = f"Start: **{contract_start}**" if contract_start else "Start: **Open**"
                            if contract_end:
                                days_left = (_d.fromisoformat(contract_end) - _d.today()).days
                                if days_left < 0:
                                    st.error(f"⛔ Contract EXPIRED on {contract_end} ({abs(days_left)} days ago) — {start_str}")
                                elif days_left < 30:
                                    st.warning(f"⚠️ Contract expires in {days_left} days ({contract_end}) — {start_str}")
                                else:
                                    st.caption(f"📅 {start_str}  →  End: **{contract_end}** ({days_left} days remaining)")
                            else:
                                st.caption(f"📅 {start_str}  →  End: **Open-ended**")
                        except: pass

                    bc1,bc2,bc3 = st.columns(3)
                    if bc1.button("\U0001f50d View Detail", key=f"view_t_{t['id'][:8]}",
                                  use_container_width=True):
                        st.session_state["detail_tenant_id"] = t["id"]
                        st.session_state["detail_tenant_name"] = t["tenant_name"]
                        st.rerun()

                    if t["status"] == "ACTIVE":
                        if bc2.button("\U0001f534 Suspend", key=f"susp_{t['id'][:8]}",
                                      use_container_width=True):
                            requests.post(f"{API}/tenants/{t['id']}/suspend",
                                          headers=hdr, params={"reason": "Manual suspension"})
                            st.rerun()
                    else:
                        if bc2.button("\U0001f7e2 Activate", key=f"act_t_{t['id'][:8]}",
                                      use_container_width=True):
                            requests.post(f"{API}/tenants/{t['id']}/activate", headers=hdr)
                            st.rerun()

    # ── Tab 2: Create Tenant ──────────────────────────────────────────────────
    with tab_create:
        st.caption("Register a new insurance carrier. System config and defaults are auto-provisioned.")
        with st.form("create_tenant_form", clear_on_submit=True):
            st.markdown("**Carrier Information**")
            r1c1, r1c2 = st.columns(2)
            with r1c1:
                tc_code     = st.text_input("Tenant Code *",
                    placeholder="e.g. ABC-LIFE",
                    help="Unique short code for this carrier. Uppercase, hyphens OK.")
                tc_name     = st.text_input("Carrier Name *",
                    placeholder="e.g. ABC Life Insurance Co.")
                tc_type     = st.selectbox("Company Type",
                    ["Life Insurance","Health Insurance","P&C Insurance",
                     "Reinsurer","MGA","Broker","Other"])
                tc_naic     = st.text_input("NAIC Code",
                    placeholder="e.g. 12345")
                tc_state    = st.text_input("State of Domicile",
                    placeholder="e.g. TX", max_chars=2)
            with r1c2:
                tc_contact  = st.text_input("Contact Name *")
                tc_email    = st.text_input("Contact Email *",
                    placeholder="admin@carrier.com")
                tc_phone    = st.text_input("Contact Phone")
                tc_tier     = st.selectbox("Plan Tier",
                    ["STANDARD","PROFESSIONAL","ENTERPRISE","TRIAL"])
                tc_maxu     = st.number_input("Max Users", 1, 1000, 50, help="Maximum number of active user accounts for this tenant. Exceeding this limit will prevent new user creation.")

            st.markdown("**Limits & Contract**")
            lc1,lc2,lc3 = st.columns(3)
            tc_maxd  = lc1.number_input("Max Decisions/Month", 100, 1000000, 10000)
            tc_cstart = lc2.date_input("Contract Start", value=None)
            tc_cend   = lc3.date_input("Contract End",   value=None)
            tc_notes  = st.text_area("Notes", height=60)

            if st.form_submit_button("\u2795 Register Tenant",
                                     use_container_width=True, type="primary"):
                errs = []
                if not tc_code.strip():    errs.append("Tenant code required")
                if not tc_name.strip():    errs.append("Carrier name required")
                if not tc_contact.strip(): errs.append("Contact name required")
                if not tc_email.strip():   errs.append("Contact email required")
                if errs:
                    for e in errs: st.error(f"\u274c {e}")
                else:
                    payload = {
                        "tenant_code":       tc_code.strip().upper(),
                        "tenant_name":       tc_name.strip(),
                        "contact_name":      tc_contact.strip(),
                        "contact_email":     tc_email.strip(),
                        "contact_phone":     tc_phone.strip(),
                        "company_type":      tc_type,
                        "state_of_domicile": tc_state.strip().upper(),
                        "naic_code":         tc_naic.strip(),
                        "plan_tier":         tc_tier,
                        "max_users":         tc_maxu,
                        "max_decisions_per_month": tc_maxd,
                        "contract_start":    str(tc_cstart) if tc_cstart else None,
                        "contract_end":      str(tc_cend)   if tc_cend   else None,
                        "notes":             tc_notes.strip(),
                    }
                    resp = requests.post(f"{API}/tenants/", headers=hdr, json=payload)
                    if resp.status_code == 200:
                        r = resp.json()
                        st.success(
                            f"\u2705 Tenant **{r['tenant_code']}** created! "
                            f"ID: `{r['tenant_id']}`")
                        st.info(
                            "System config defaults auto-provisioned. "
                            "Next: create admin user for this tenant, "
                            "then configure products and rates.")
                        st.rerun()
                    else:
                        try: st.error(resp.json().get("detail", resp.text[:200]))
                        except: st.error(f"Failed: {resp.text[:200]}")

    # ── Tab 3: Tenant Detail ──────────────────────────────────────────────────
    with tab_detail:
        tid = st.session_state.get("detail_tenant_id")
        if not tid:
            st.info("Click 'View Detail' on a tenant in the All Tenants tab.")
        else:
            try:
                detail = requests.get(f"{API}/tenants/{tid}",
                    headers=hdr, timeout=10).json()
            except Exception as e:
                st.error(f"Error: {e}"); detail = {}

            if detail and "tenant_code" in detail:
                st.markdown(f"### {detail['tenant_name']}")
                st.caption(f"ID: `{detail.get('id','')}` | Code: **{detail['tenant_code']}**")

                dt1,dt2,dt3,dt4 = st.columns(4)
                dt1.metric("Status",    detail.get("status","—"))
                dt2.metric("Plan",      detail.get("plan_tier","—"))
                dt3.metric("Users",     len(detail.get("users",[])))
                dt4.metric("Max Users", detail.get("max_users","—"))

                st.divider()
                st.markdown("**Users on this tenant**")
                users = detail.get("users",[])
                if users:
                    df_u = pd.DataFrame([{
                        "Username":   u.get("username"),
                        "Full Name":  u.get("full_name"),
                        "Role":       u.get("role"),
                        "Active":     "\u2705" if u.get("is_active") else "\u274c",
                        "Last Login": str(u.get("last_login_at",""))[:16],
                    } for u in users])
                    st.dataframe(df_u, use_container_width=True, hide_index=True)
                else:
                    st.caption("No users yet.")

                st.divider()
                # Quick edit
                st.markdown("**Quick Edit**")
                with st.form("edit_tenant_form"):
                    ec1,ec2 = st.columns(2)
                    new_status = ec1.selectbox("Status",
                        ["ACTIVE","SUSPENDED","TRIAL","INACTIVE"],
                        index=["ACTIVE","SUSPENDED","TRIAL","INACTIVE"].index(
                            detail.get("status","ACTIVE"))
                            if detail.get("status","ACTIVE") in
                               ["ACTIVE","SUSPENDED","TRIAL","INACTIVE"] else 0)
                    new_maxu = ec2.number_input("Max Users",
                        1, 1000, int(detail.get("max_users",50)))
                    from datetime import date as _date, datetime as _dt2
                    def _pd(v):
                        if not v: return None
                        try: return _dt2.fromisoformat(str(v)[:10]).date()
                        except: return None
                    cc1, cc2 = st.columns(2)
                    edit_cstart = cc1.date_input("Contract Start",
                        value=_pd(detail.get("contract_start")),
                        help="Contract effective date")
                    edit_cend   = cc2.date_input("Contract End",
                        value=_pd(detail.get("contract_end")),
                        help="Contract expiry date — leave blank for open-ended")
                    new_notes = st.text_area("Notes",
                        value=detail.get("notes","") or "", height=60)
                    if st.form_submit_button("Save Changes",
                                             use_container_width=True, type="primary"):
                        resp = requests.patch(f"{API}/tenants/{tid}",
                            headers=hdr, json={
                                "status":         new_status,
                                "max_users":      new_maxu,
                                "notes":          new_notes,
                                "contract_start": str(edit_cstart) if edit_cstart else None,
                                "contract_end":   str(edit_cend)   if edit_cend   else None,
                            })
                        if resp.status_code == 200:
                            st.success("\u2705 Updated")
                            st.rerun()
                        else:
                            st.error("Update failed")

                # Audit log
                st.divider()
                st.markdown("**Audit Log**")
                try:
                    audit = requests.get(f"{API}/tenants/{tid}/audit",
                        headers=hdr, timeout=5).json().get("audit",[])
                    if audit:
                        df_a = pd.DataFrame([{
                            "When":   str(a.get("occurred_at",""))[:19],
                            "Action": a.get("action"),
                            "By":     a.get("actor"),
                            "Detail": str(a.get("after_val",""))[:80],
                        } for a in audit])
                        st.dataframe(df_a, use_container_width=True, hide_index=True)
                except: pass

def _get_user_limits(username: str) -> dict:
    """
    Return face amount authority limits for a user from user_authority_limits.
    Falls back to {"min_face": 0, "max_face": None} (unlimited) if not set.
    """
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT min_face_amount, max_face_amount, product_codes, notes,
                       is_medical_officer, medical_specialisations, can_assess_medical
                FROM user_authority_limits
                WHERE username = %s AND is_active = TRUE
                LIMIT 1
            """, (username,))
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                return {
                    "min_face":               float(row[0]) if row[0] is not None else 0,
                    "max_face":               float(row[1]) if row[1] is not None else None,
                    "product_codes":          row[2] or [],
                    "notes":                  row[3] or "",
                    "is_medical_officer":     bool(row[4]) if len(row) > 4 and row[4] is not None else False,
                    "medical_specialisations":list(row[5]) if len(row) > 5 and row[5] else [],
                    "can_assess_medical":     bool(row[6]) if len(row) > 6 and row[6] is not None else False,
                }
    except Exception as _exc:
        logger.debug("[_get_user_limits] Suppressed exception", exc_info=_exc)
    return {"min_face": 0, "max_face": None, "product_codes": [], "notes": "",
            "is_medical_officer": False, "medical_specialisations": [], "can_assess_medical": False}


def _check_user_authority(username: str, face_amount: float,
                           product_code: str = None) -> tuple:
    """
    Returns (allowed: bool, reason: str).
    Checks face amount limits and optional product restrictions.
    """
    lim = _get_user_limits(username)
    sym = get_currency_symbol()

    # Face amount min check
    if face_amount < lim["min_face"]:
        return False, (
            f"Case face amount {sym}{face_amount:,.0f} is below your minimum "
            f"authority of {sym}{lim['min_face']:,.0f}."
        )
    # Face amount max check
    if lim["max_face"] is not None and face_amount > lim["max_face"]:
        return False, (
            f"Case face amount {sym}{face_amount:,.0f} exceeds your underwriting "
            f"authority of {sym}{lim['max_face']:,.0f}. "
            f"Refer to a Senior Underwriter or Manager."
        )
    # Product restriction check
    if lim["product_codes"] and product_code:
        allowed_prods = [p.strip().upper() for p in lim["product_codes"]]
        if product_code.upper() not in allowed_prods:
            return False, (
                f"Product {product_code} is outside your product authority. "
                f"Allowed: {', '.join(allowed_prods)}."
            )
    return True, ""


def render_user_management():
    """User Management — create, view, roles, face amount authority limits."""
    import json as _json
    st.markdown("## 👥 User Management")
    st.caption("Manage platform users, roles, access control, and underwriting authority limits.")

    tok = st.session_state.get("token", "")
    hdr = {"Authorization": f"Bearer {tok}"}

    ROLES = ["underwriter","senior_underwriter","case_manager","admin","super_admin","viewer"]
    ROLE_COLORS = {
        "super_admin":        "#f87171",
        "admin":              "#fb923c",
        "senior_underwriter": "#facc15",
        "underwriter":        "#34d399",
        "case_manager":       "#60a5fa",
        "viewer":             "#94a3b8",
    }
    ROLE_DESC = {
        "super_admin":        "Full platform access including tenant settings",
        "admin":              "User management, product config, rule builder",
        "senior_underwriter": "Queue management, manual decisions, product config view",
        "underwriter":        "UW workbench, queue, case decisions",
        "case_manager":       "Queue view, APS tracking, no decisions",
        "viewer":             "Read-only access to workbench and queue",
    }

    # ── Ensure authority limits table ─────────────────────────────
    def _ensure_limits_table():
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.close(); _release_db_conn(conn)
        except Exception as _exc:
            logger.warning("[_ensure_limits_table] Suppressed exception", exc_info=_exc)

    _ensure_limits_table()

    def _load_limit(username):
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT min_face_amount, max_face_amount,
                           product_codes, notes, is_active, updated_at,
                           is_medical_officer, medical_specialisations, can_assess_medical
                    FROM user_authority_limits WHERE username=%s
                """, (username,))
                row = cur.fetchone()
                cur.close(); _release_db_conn(conn)
                if row:
                    return {
                        "min_face":               float(row[0]) if row[0] is not None else 0,
                        "max_face":               float(row[1]) if row[1] is not None else None,
                        "product_codes":          list(row[2]) if row[2] else [],
                        "notes":                  row[3] or "",
                        "is_active":              row[4],
                        "updated_at":             str(row[5] or "")[:10],
                        "is_medical_officer":     bool(row[6]) if len(row) > 6 and row[6] is not None else False,
                        "medical_specialisations":list(row[7]) if len(row) > 7 and row[7] else [],
                        "can_assess_medical":     bool(row[8]) if len(row) > 8 and row[8] is not None else False,
                    }
        except Exception as _exc:
            logger.debug("[_load_limit] Suppressed exception", exc_info=_exc)
        return None

    def _save_limit(username, min_face, max_face, product_codes, notes, set_by,
                     is_medical_officer=False, medical_specialisations=None,
                     can_assess_medical=False):
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                med_specs = medical_specialisations or []
                cur.execute("""
                    INSERT INTO user_authority_limits
                        (username, min_face_amount, max_face_amount,
                         product_codes, notes, is_active, set_by,
                         is_medical_officer, medical_specialisations, can_assess_medical)
                    VALUES (%s,%s,%s,%s,%s,TRUE,%s,%s,%s,%s)
                    ON CONFLICT (username) DO UPDATE SET
                        min_face_amount=%s, max_face_amount=%s,
                        product_codes=%s, notes=%s, is_active=TRUE,
                        set_by=%s, updated_at=NOW(),
                        is_medical_officer=%s,
                        medical_specialisations=%s,
                        can_assess_medical=%s
                """, (username, min_face, max_face, product_codes, notes, set_by,
                      is_medical_officer, med_specs, can_assess_medical,
                      min_face, max_face, product_codes, notes, set_by,
                      is_medical_officer, med_specs, can_assess_medical)); cur.close(); _release_db_conn(conn)
                return True, ""
        except Exception as e:
            return False, str(e)
        return False, "DB unavailable"

    def _remove_limit(username):
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE user_authority_limits SET is_active=FALSE WHERE username=%s",
                    (username,)); cur.close(); _release_db_conn(conn)
                return True
        except Exception as _exc:
            logger.warning("[_remove_limit] Suppressed exception", exc_info=_exc)
        return False

    sym = get_currency_symbol()

    # Track active tab across reruns so st.rerun() doesn't jump to tab 1
    _um_tab_idx = st.session_state.get("_um_active_tab", 0)

    tab_list, tab_create, tab_limits, tab_mfa, tab_roles = st.tabs([
        "📋 All Users", "➕ Create User",
        "🎯 Authority Limits", "🔐 MFA Settings", "🛡️ Role Reference"
    ])

    # ══════════════════════════════════════════════════════════════
    # TAB 1 — ALL USERS
    # ══════════════════════════════════════════════════════════════
    with tab_list:
        try:
            resp  = requests.get(f"{API_BASE}/auth/users", headers=hdr, timeout=5)
            if resp.status_code == 403:
                st.error("Admin access required.")
                return
            users = resp.json().get("users", [])
        except Exception as e:
            st.error(f"Could not load users: {e}")
            return

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Total Users",  len(users))
        c2.metric("Active",       sum(1 for u in users if u["is_active"]))
        c3.metric("Inactive",     sum(1 for u in users if not u["is_active"]))
        c4.metric("With Cases",   sum(1 for u in users if u.get("active_cases",0) > 0))
        # Locked accounts
        try:
            _conn_lk = _get_db_conn()
            if _conn_lk:
                _cur_lk = _conn_lk.cursor()
                _cur_lk.execute("""
                    SELECT COUNT(*) FROM login_attempts
                    WHERE locked_until > NOW()
                """)
                _lk_row = _cur_lk.fetchone()
                _locked_count = (_lk_row["count"] if isinstance(_lk_row, dict) else _lk_row[0]) if _lk_row else 0
                _cur_lk.close(); _release_db_conn(_conn_lk)
                c5.metric("Locked 🔒", _locked_count,
                          delta=f"-{_locked_count}" if _locked_count else None,
                          delta_color="inverse")
        except Exception as _exc:
            logger.warning("[_remove_limit] Suppressed exception", exc_info=_exc)
            c5.metric("Locked 🔒", "—")

        # Unlock button if there are locked accounts
        if _locked_count if "locked_count" in dir() else False:
            if st.button("🔓 Unlock all locked accounts",
                         type="secondary", key="unlock_all_btn",
                         help="Immediately clears all login lockouts."):
                try:
                    _conn_ul = _get_db_conn()
                    if _conn_ul:
                        _cur_ul = _conn_ul.cursor()
                        _cur_ul.execute("""
                            UPDATE login_attempts
                            SET locked_until=NULL, failed_count=0
                            WHERE locked_until > NOW()
                        """)
                        _conn_ul.commit(); _cur_ul.close(); _conn_ul.close()
                        _log_audit("USER_MGMT","ACCOUNTS_UNLOCKED",
                            entity_type="SYSTEM",
                            actor_username=st.session_state.get("username",""))
                        st.success("✅ All accounts unlocked.")
                        st.rerun()
                except Exception as _ue:
                    st.error(f"Unlock failed: {_ue}")
        st.divider()

        f1,f2 = st.columns(2)
        f_role   = f1.selectbox("Filter by role",   ["ALL"] + ROLES, key="um_role_f",
                                 help="Show only users with this role.")
        f_status = f2.selectbox("Filter by status", ["ALL","Active","Inactive"],
                                 key="um_status_f",
                                 help="Show only active or inactive accounts.")

        display = users
        if f_role   != "ALL":      display = [u for u in display if u["role"] == f_role]
        if f_status == "Active":   display = [u for u in display if u["is_active"]]
        if f_status == "Inactive": display = [u for u in display if not u["is_active"]]
        st.caption(f"Showing {len(display)} of {len(users)} users")

        for user in display:
            role_col   = ROLE_COLORS.get(user["role"], "#94a3b8")
            status     = "🟢 Active" if user["is_active"] else "🔴 Inactive"
            cases      = user.get("active_cases", 0)
            last_login = user.get("last_login_at")
            if last_login:
                from datetime import datetime as _dt
                try:
                    ll = _dt.fromisoformat(str(last_login).replace("Z",""))
                    last_login = ll.strftime("%Y-%m-%d %H:%M")
                except Exception as _exc:
                    logger.debug("[_remove_limit] Suppressed exception", exc_info=_exc)

            cases_label = f"  |  📋 {cases} cases" if cases else ""
            from datetime import date as _date, datetime as _dt2
            acc_exp = user.get("expire_date") or user.get("account_expires")
            exp_label   = ""
            exp_warning = False
            if acc_exp:
                try:
                    exp_d     = _dt2.fromisoformat(str(acc_exp)[:10]).date()
                    days_left = (exp_d - _date.today()).days
                    if days_left < 0:
                        exp_label = "  |  ⛔ Expired"; exp_warning = True
                    elif days_left <= 30:
                        exp_label = f"  |  ⚠️ Expires {exp_d}"; exp_warning = True
                    else:
                        exp_label = f"  |  📅 Exp: {exp_d}"
                except Exception as _exc:
                    logger.debug("[_remove_limit] Suppressed exception", exc_info=_exc)

            # Authority limit badge
            lim = _load_limit(user["username"])
            if lim and lim.get("is_active"):
                max_f   = lim["max_face"]
                med_tag = " 🩺" if lim.get("is_medical_officer") else ""
                lim_label = (f"  |  🎯 Up to {sym}{max_f:,.0f}{med_tag}"
                             if max_f else f"  |  🎯 Unlimited{med_tag}")
            else:
                lim_label = "  |  🎯 No limit set"

            with st.expander(
                f"{status}  **{user['username']}**  —  {user.get('full_name','—')}  "
                f"|  {user['role'].replace('_',' ').title()}"
                f"{cases_label}{exp_label}{lim_label}"
            ):
                dc1,dc2,dc3 = st.columns(3)
                dc1.markdown(f"**Email:** {user.get('email','—')}")
                dc2.markdown(
                    f"**Role:** <span style='color:{role_col};font-weight:600'>"
                    f"{user['role'].replace('_',' ').title()}</span>",
                    unsafe_allow_html=True)
                dc3.markdown(f"**Last login:** {last_login or 'Never'}")
                eff_d = user.get("effective_date") or user.get("account_effective")
                exp_d = user.get("expire_date")    or user.get("account_expires")
                st.caption(
                    f"ID: {user['id']}  |  Created: {str(user.get('created_at',''))[:10]}"
                    f"  |  Effective: {str(eff_d)[:10] if eff_d else 'Immediate'}"
                    f"  |  Expires: {str(exp_d)[:10] if exp_d else 'Never'}"
                )
                if exp_warning:
                    st.warning(f"⚠️ Account expires: {str(acc_exp)[:10]}")

                # Authority limit inline display
                if lim and lim.get("is_active"):
                    min_f   = lim["min_face"]
                    max_f   = lim["max_face"]
                    prods   = lim["product_codes"]
                    is_med  = lim.get("is_medical_officer", False)
                    can_med = lim.get("can_assess_medical", False)
                    specs   = lim.get("medical_specialisations", [])
                    lim_parts = []
                    if min_f > 0:
                        lim_parts.append(f"Min: {sym}{min_f:,.0f}")
                    lim_parts.append(f"Max: {sym}{max_f:,.0f}" if max_f else "Max: Unlimited")
                    if prods:
                        lim_parts.append(f"Products: {', '.join(prods)}")
                    if is_med:
                        spec_str = ", ".join(specs) if specs else "All"
                        lim_parts.append(f"🩺 Medical Officer ({spec_str})")
                    elif can_med:
                        lim_parts.append("🩺 Can assess medical cases")
                    st.info(f"🎯 **Authority:** {' | '.join(lim_parts)}"
                            + (f" | {lim['notes']}" if lim.get("notes") else ""))
                else:
                    st.caption("🎯 No face amount authority limit set — inherits role defaults.")

                ac0,ac1,ac2,ac3,ac4 = st.columns(5)

                # ── Edit User ─────────────────────────────────────────────
                with ac0.popover("✏️ Edit User"):
                    st.caption(f"Edit details for **{user['username']}**")
                    _eu_name  = st.text_input("Full Name",
                        value=user.get("full_name",""),
                        key=f"eu_name_{user['username']}")
                    _eu_email = st.text_input("Email",
                        value=user.get("email",""),
                        key=f"eu_email_{user['username']}")
                    from datetime import date as _date
                    _eu_eff = st.date_input("Account Effective Date",
                        value=user.get("effective_date") or user.get("account_effective") or _date.today(),
                        key=f"eu_eff_{user['username']}",
                        help="Date account becomes active.")
                    _eu_exp = st.date_input("Account Expiry Date",
                        value=user.get("expire_date") or user.get("account_expires") or None,
                        key=f"eu_exp_{user['username']}",
                        help="Leave blank = permanent access.")
                    if st.button("💾 Save Changes", key=f"eu_save_{user['username']}",
                                 use_container_width=True, type="primary"):
                        _eu_ok = False
                        _eu_err = None
                        # Validate
                        if not _eu_email.strip() or "@" not in _eu_email:
                            st.error("❌ Valid email is required.")
                        elif _eu_exp and _eu_exp <= _date.today():
                            st.error("❌ Expiry date must be in the future.")
                        else:
                            # Update backend API (best-effort — not all backends support PATCH)
                            try:
                                _eu_r = requests.patch(
                                    f"{API_BASE}/auth/users/{user['username']}",
                                    headers=hdr,
                                    json={
                                        "full_name":     _eu_name.strip(),
                                        "email":         _eu_email.strip(),
                                        "effective_date": str(_eu_eff) if _eu_eff else None,
                                        "expire_date":   str(_eu_exp) if _eu_exp else None,
                                    },
                                    timeout=8
                                )
                                if _eu_r.status_code in (200, 204):
                                    _eu_ok = True
                                # 404/405 = endpoint not supported — fall through to DB update
                            except Exception as _exc:
                                logger.warning("[edit_user] API update failed (non-fatal)", exc_info=_exc)

                            # Update local DB (covers all roles)
                            try:
                                _conn_eu = _get_db_conn()
                                if _conn_eu:
                                    _cur_eu = _conn_eu.cursor()
                                    # Update platform_users_local
                                    _cur_eu.execute("""
                                        UPDATE platform_users_local
                                        SET full_name=%s, email=%s,
                                            effective_date=%s, expire_date=%s
                                        WHERE username=%s
                                    """, (_eu_name.strip(), _eu_email.strip(),
                                          _eu_eff or None, _eu_exp or None,
                                          user["username"]))
                                    if _cur_eu.rowcount > 0:
                                        _eu_ok = True
                                    # Update uw_user table (expiry_date not expire_date)
                                    try:
                                        _cur_eu.execute("""
                                            UPDATE uw_user
                                            SET full_name=%s, email=%s,
                                                effective_date=%s, expiry_date=%s,
                                                updated_at=NOW(), updated_by=%s
                                            WHERE username=%s
                                        """, (_eu_name.strip(), _eu_email.strip(),
                                              _eu_eff or None, _eu_exp or None,
                                              st.session_state.get("username","system"),
                                              user["username"]))
                                        if _cur_eu.rowcount > 0:
                                            _eu_ok = True
                                    except Exception as _exc:
                                        logger.warning("[edit_user] uw_user update failed", exc_info=_exc)
                                    _conn_eu.commit()
                                    _cur_eu.close(); _release_db_conn(_conn_eu)
                            except Exception as _exc:
                                logger.warning("[edit_user] DB update failed", exc_info=_exc)
                                _eu_err = str(_exc)

                            if _eu_ok:
                                _log_audit("USER_MGMT", "USER_UPDATED",
                                    entity_type="USER", entity_id=user["username"],
                                    actor_username=st.session_state.get("username","system"),
                                    after_state={"email": _eu_email.strip(),
                                                 "full_name": _eu_name.strip()})
                                st.success(f"✅ User **{user['username']}** updated successfully.")
                                st.rerun()
                            else:
                                # Give a more specific error message
                                if _eu_err:
                                    st.error(f"❌ Database error: {_eu_err}")
                                else:
                                    st.warning(
                                        "⚠️ Could not update via API. "
                                        "If this user was created via the backend (underwriter/admin), "
                                        "ask your API admin to add a PATCH /auth/users endpoint. "
                                        "Local users (case_manager/viewer) were updated successfully."
                                    ) 

                if user["is_active"]:
                    if ac1.button("🔴 Deactivate", key=f"deact_{user['username']}",
                                  use_container_width=True):
                        r = requests.post(
                            f"{API_BASE}/auth/users/{user['username']}/deactivate",
                            headers=hdr)
                        if r.status_code == 200:
                            _log_audit("USER_MGMT","USER_DEACTIVATED",
                                entity_type="USER", entity_id=user["username"],
                                before_state={"is_active": True},
                                after_state={"is_active": False})
                        st.success("Deactivated") if r.status_code == 200 else st.error(r.text)
                        st.rerun()
                else:
                    if ac1.button("🟢 Activate", key=f"act_{user['username']}",
                                  use_container_width=True):
                        r = requests.post(
                            f"{API_BASE}/auth/users/{user['username']}/activate",
                            headers=hdr)
                        if r.status_code == 200:
                            _log_audit("USER_MGMT","USER_ACTIVATED",
                                entity_type="USER", entity_id=user["username"],
                                before_state={"is_active": False},
                                after_state={"is_active": True})
                        st.success("Activated") if r.status_code == 200 else st.error(r.text)
                        st.rerun()

                with ac2.popover("🛡️ Change Role"):
                    new_role = st.selectbox("New role", ROLES,
                        index=ROLES.index(user["role"]) if user["role"] in ROLES else 0,
                        key=f"role_sel_{user['username']}",
                        help="Changing role takes effect immediately on next page load.")
                    if st.button("Apply", key=f"role_apply_{user['username']}"):
                        r = requests.post(
                            f"{API_BASE}/auth/users/{user['username']}/change-role",
                            headers=hdr, params={"new_role": new_role})
                        if r.status_code == 200:
                            _log_audit("USER_MGMT","ROLE_CHANGED",
                                entity_type="USER", entity_id=user["username"],
                                before_state={"role": user["role"]},
                                after_state={"role": new_role})
                        st.success(f"Role → {new_role}") if r.status_code == 200 else st.error(r.text)
                        st.rerun()

                with ac3.popover("🔑 Reset Password"):
                    new_pw = st.text_input(
                        "New password (min 8 chars)",
                        help="Minimum 8 characters. The user will need to use this on their next login.",
                        type="password", key=f"pw_{user['username']}")
                    if st.button("Reset", key=f"pw_apply_{user['username']}"):
                        if len(new_pw) < 8:
                            st.error("Min 8 characters")
                        else:
                            _pw_ok = False
                            # Try backend API
                            try:
                                r = requests.post(
                                    f"{API_BASE}/auth/users/{user['username']}/reset-password",
                                    headers=hdr, params={"new_password": new_pw})
                                _pw_ok = r.status_code == 200
                            except Exception as _exc:
                                logger.warning("[admin_reset_pw] API failed", exc_info=_exc)
                            # Also update local DB (covers case_manager / viewer)
                            try:
                                import hashlib as _hl
                                _pw_hash = _hl.sha256(new_pw.encode()).hexdigest()
                                _conn_r = _get_db_conn()
                                if _conn_r:
                                    _cur_r = _conn_r.cursor()
                                    _cur_r.execute(
                                        "UPDATE platform_users_local SET password_hash=%s WHERE username=%s",
                                        (_pw_hash, user["username"])
                                    )
                                    if _cur_r.rowcount > 0:
                                        _pw_ok = True
                                    _conn_r.commit(); _cur_r.close(); _release_db_conn(_conn_r)
                            except Exception as _exc:
                                logger.warning("[admin_reset_pw] Local DB failed", exc_info=_exc)
                            if _pw_ok:
                                _log_audit("AUTH", "PASSWORD_RESET",
                                           entity_type="USER", entity_id=user["username"],
                                           actor_username=st.session_state.get("username","system"),
                                           metadata={"method": "admin_reset"})
                                st.success(f"✅ Password reset for **{user['username']}**")
                            else:
                                st.error("❌ Reset failed — check API connectivity and try again.")

                with ac4.popover("🎯 Set Authority"):
                    st.caption(f"Face amount authority for **{user['username']}**")
                    _cur = _load_limit(user["username"]) or {}
                    _amin = st.number_input(
                        "Min face amount",
                        min_value=0, max_value=50_000_000,
                        value=int(_cur.get("min_face", 0)),
                        step=50_000,
                        key=f"lim_min_{user['username']}",
                        help="Cases below this amount cannot be assigned to or decided by this user. Set 0 for no minimum."
                    )
                    _amax = st.number_input(
                        "Max face amount (0 = unlimited)",
                        min_value=0, max_value=100_000_000,
                        value=int(_cur.get("max_face") or 0),
                        step=50_000,
                        key=f"lim_max_{user['username']}",
                        help="Cases above this amount will be blocked. Set 0 for unlimited authority."
                    )
                    _aprods_raw = ", ".join(_cur.get("product_codes", []))
                    _aprods = st.text_input(
                        "Restrict to products (comma-separated, blank = all)",
                        value=_aprods_raw,
                        key=f"lim_prod_{user['username']}",
                        help="e.g. IND-TERM-10, IND-TERM-20. Leave blank to allow all products."
                    )
                    _anotes = st.text_input(
                        "Notes",
                        value=_cur.get("notes",""),
                        key=f"lim_notes_{user['username']}",
                        help="Optional note, e.g. 'Junior UW — max ₹50L pending senior review'."
                    )
                    st.divider()
                    st.caption("🩺 Medical Officer Settings")
                    _ais_med = st.checkbox(
                        "Medical Officer",
                        value=bool(_cur.get("is_medical_officer", False)),
                        key=f"lim_ismed_{user['username']}",
                        help="Flag this user as a qualified medical officer. Medical cases (REQUEST_APS, exam required) will be routed to them first during auto-assignment."
                    )
                    _amed_specs_raw = ", ".join(_cur.get("medical_specialisations", []))
                    _amed_specs = st.text_input(
                        "Specialisations (comma-separated)",
                        value=_amed_specs_raw,
                        key=f"lim_medspec_{user['username']}",
                        help="e.g. CARDIOLOGY, ONCOLOGY, GENERAL. Used for future specialisation-based routing. Leave blank = handles all medical cases."
                    ) if _ais_med else ""
                    _acan_med = st.checkbox(
                        "Can assess medical cases",
                        value=bool(_cur.get("can_assess_medical", False)),
                        key=f"lim_canmed_{user['username']}",
                        help="Even if not flagged as Medical Officer, this user can be assigned medical referral cases as a fallback."
                    )
                    _lc1, _lc2 = st.columns(2)
                    if _lc1.button("💾 Save", key=f"lim_save_{user['username']}",
                                   use_container_width=True, type="primary"):
                        _prod_list  = ([p.strip().upper() for p in _aprods.split(",") if p.strip()]
                                       if _aprods.strip() else [])
                        _spec_list  = ([s.strip().upper() for s in _amed_specs.split(",") if s.strip()]
                                       if _amed_specs.strip() else [])
                        _max_val    = _amax if _amax > 0 else None
                        ok, err     = _save_limit(
                            user["username"], _amin, _max_val,
                            _prod_list, _anotes,
                            st.session_state.get("username","system"),
                            is_medical_officer=_ais_med,
                            medical_specialisations=_spec_list,
                            can_assess_medical=_acan_med,
                        )
                        if ok:
                            _log_audit("USER_MGMT","AUTHORITY_LIMIT_SET",
                                entity_type="USER", entity_id=user["username"],
                                after_state={"min_face": _amin, "max_face": _amax,
                                             "is_medical_officer": _ais_med})
                            st.success("✅ Authority limit saved.")
                            st.rerun()
                        else:
                            st.error(f"Save failed: {err}")
                    if _lc2.button("🗑️ Remove", key=f"lim_del_{user['username']}",
                                   use_container_width=True):
                        _remove_limit(user["username"])
                        st.success("Limit removed.")
                        st.rerun()

    # ══════════════════════════════════════════════════════════════
    # TAB 2 — CREATE USER
    # ══════════════════════════════════════════════════════════════
    with tab_create:
        # ── Ensure local users table for case_manager / viewer fallback ───────
        def _ensure_local_users_table():
            try:
                conn = _get_db_conn()
                if conn:
                    cur = conn.cursor()
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS platform_users_local (
                            id              SERIAL PRIMARY KEY,
                            username        VARCHAR(100) UNIQUE NOT NULL,
                            full_name       VARCHAR(200),
                            email           VARCHAR(200),
                            role            VARCHAR(50),
                            password_hash   VARCHAR(200),
                            is_active       BOOLEAN DEFAULT TRUE,
                            effective_date  DATE,
                            expire_date     DATE,
                            created_at      TIMESTAMPTZ DEFAULT NOW(),
                            created_by      VARCHAR(200)
                        )
                    """)
                    conn.commit(); cur.close(); _release_db_conn(conn)
            except Exception as _exc:
                logger.warning("[_ensure_local_users_table] Suppressed exception", exc_info=_exc)
        _ensure_local_users_table()

        # ── Show messages that survived rerun ─────────────────────────────────
        if st.session_state.get("_um_create_success"):
            st.success(st.session_state.pop("_um_create_success"))
        if st.session_state.get("_um_create_error"):
            st.error(st.session_state.pop("_um_create_error"))

        st.caption("Create a new platform user. They can log in immediately.")

        # Roles the backend API accepts
        _BACKEND_ROLES = {"underwriter","senior_underwriter","admin","super_admin"}
        _LOCAL_ONLY_ROLES = {"case_manager","viewer"}

        # Persist form values in session state so errors don't wipe them
        _fd = st.session_state.setdefault("_um_form_vals", {})

        from datetime import date as _date

        # BUG5 FIX: removed key= from inputs that use value=_fd.get(...)
        # Streamlit key= and value= conflict on rerun — key= wins and ignores value=,
        # so saved form data never restores. Using value= only fixes the persistence.
        c1, c2 = st.columns(2)
        with c1:
            new_username  = st.text_input("Username *",
                value=_fd.get("username",""),
                placeholder="e.g. jsmith",
                help="Unique login identifier. Lowercase, no spaces.")
            new_fullname  = st.text_input("Full Name *",
                value=_fd.get("full_name",""),
                placeholder="e.g. John Smith",
                help="Appears on case assignments and audit trail entries.")
            new_email     = st.text_input("Email *",
                value=_fd.get("email",""),
                placeholder="jsmith@carrier.com",
                help="Used for notifications and APS confirmation emails.")
        with c2:
            new_role = st.selectbox("Role *", ROLES,
                index=ROLES.index(_fd.get("role","underwriter")) if _fd.get("role") in ROLES else 0,
                format_func=lambda r: r.replace("_"," ").title(),
                help="Determines which pages and actions are available.")
            new_password  = st.text_input("Password *", type="password",
                placeholder="Min 8 characters",
                key="um_new_pw",
                help="Minimum 8 characters. Stored as bcrypt hash.")
            new_password2 = st.text_input("Confirm Password *", type="password",
                key="um_new_pw2",
                help="Must match the password above.")

        st.caption(f"💬 {ROLE_DESC.get(new_role,'')}")

        if new_role in _LOCAL_ONLY_ROLES:
            st.info(
                f"ℹ️ **{new_role.replace('_',' ').title()}** is stored locally — "
                "the backend API does not support this role. "
                "The user will be able to log in via the local user registry."
            )

        ud1, ud2 = st.columns(2)
        new_acc_eff = ud1.date_input("Account Effective Date",
            value=_date.today(),
            key="um_new_eff",
            help="Date the account becomes active — defaults to today.")
        new_acc_exp = ud2.date_input("Account Expiry Date",
            value=None,
            key="um_new_exp",
            help="Date access expires (e.g. for contractors). Leave blank = permanent.")

        st.divider()
        st.markdown("##### 🎯 Authority Limits *(optional — can also set later via All Users → Set Authority)*")

        al1, al2 = st.columns(2)
        new_min_face = al1.number_input(
            f"Min face amount ({sym})",
            min_value=0, max_value=50_000_000, value=0, step=50_000,
            key="um_new_min_face",
            help=(
                "Cases BELOW this amount cannot be assigned to or decided by this user. "
                "Enter 0 = no minimum (any face amount allowed)."
            ))
        new_max_face = al2.number_input(
            f"Max face amount ({sym})",
            min_value=0, max_value=100_000_000, value=0, step=50_000,
            key="um_new_max_face",
            help=(
                "Cases ABOVE this amount will be blocked from this user. "
                "Enter 0 = unlimited authority (no maximum)."
            ))

        # Show effective limit summary so user understands what they're setting
        if new_min_face > 0 or new_max_face > 0:
            _lim_summary = []
            if new_min_face > 0:
                _lim_summary.append(f"Min: {sym}{new_min_face:,.0f}")
            if new_max_face > 0:
                _lim_summary.append(f"Max: {sym}{new_max_face:,.0f}")
            else:
                _lim_summary.append("Max: Unlimited")
            st.caption(f"📊 Authority summary: {' | '.join(_lim_summary)}")
            if new_min_face > 0 and new_max_face > 0 and new_min_face >= new_max_face:
                st.error("❌ Min face amount must be less than Max face amount.")
                # BUG1 FIX: stop rendering so Create User button is hidden until valid values entered
                st.stop()

        new_prod_restrict = st.text_input(
            "Restrict to products (comma-separated, blank = all)",
            value=_fd.get("prod_restrict",""),
            placeholder="e.g. IND-TERM-10, IND-TERM-20",
            key="um_new_prods",
            help="Leave blank to allow all products. Enter product codes to restrict.")
        new_lim_notes = st.text_area(
            "Authority Notes",
            value=_fd.get("lim_notes",""),
            height=80,
            placeholder=(
                "e.g. Junior UW — cases above ₹50L must be co-signed by Senior UW. "
                "Non-medical products only."
            ),
            key="um_new_lim_notes",
            max_chars=500,
            help=(
                "Internal note explaining this user's authority scope and any conditions. "
                "Shown in the All Users list. Max 500 characters."
            ))
        # BUG2 FIX: live character count feedback so user knows the limit
        _notes_len = len(new_lim_notes) if new_lim_notes else 0
        if _notes_len > 400:
            st.caption(f"{'⚠️' if _notes_len > 480 else '📝'} Authority Notes: {_notes_len}/500 characters")

        st.divider()

        if st.button("➕ Create User", use_container_width=True, type="primary",
                     key="um_create_btn"):
            # Save current values to session state before any validation
            # so they survive the rerun whether there's an error or not
            st.session_state["_um_form_vals"] = {
                "username":     new_username,
                "full_name":    new_fullname,
                "email":        new_email,
                "role":         new_role,
                "prod_restrict":new_prod_restrict,
                "lim_notes":    new_lim_notes,
            }

            errs = []
            if not new_username.strip():       errs.append("Username is required")
            if " " in new_username.strip():    errs.append("Username cannot contain spaces")
            if not new_fullname.strip():       errs.append("Full name is required")
            if not new_email.strip():          errs.append("Email is required")
            if "@" not in new_email:           errs.append("Email must be a valid address")
            if len(new_password) < 8:          errs.append("Password must be at least 8 characters")
            if new_password != new_password2:  errs.append("Passwords do not match")
            if new_acc_exp and new_acc_exp <= _date.today():
                errs.append("Account Expiry must be a future date")
            if new_min_face > 0 and new_max_face > 0 and new_min_face >= new_max_face:
                errs.append("Authority: Min face amount must be less than Max face amount")
            if new_lim_notes and len(new_lim_notes) > 500:
                errs.append("Authority Notes must be 500 characters or fewer")

            if errs:
                for e in errs:
                    st.error(f"❌ {e}")
            else:
                _created = False
                _err_msg = None
                _uname   = new_username.strip().lower()

                # ── Try backend API for supported roles ───────────────────────
                if new_role in _BACKEND_ROLES:
                    try:
                        resp = requests.post(f"{API_BASE}/auth/register", headers=hdr,
                            timeout=10, json={
                                "username":       _uname,
                                "full_name":      new_fullname.strip(),
                                "email":          new_email.strip(),
                                "role":           new_role,
                                "password":       new_password,
                                "effective_date": str(new_acc_eff) if new_acc_eff else None,
                                "expire_date":    str(new_acc_exp) if new_acc_exp else None,
                            })
                        if resp.status_code == 200:
                            _created = True
                            _log_audit("USER_MGMT", "USER_CREATED",
                                entity_type="USER", entity_id=_uname,
                                after_state={"role": new_role, "email": new_email.strip()},
                                metadata={"expires": str(new_acc_exp) if new_acc_exp else None})
                        else:
                            _err_msg = resp.json().get("detail", resp.text)
                    except Exception as _ce:
                        _err_msg = str(_ce)

                # ── Local DB fallback for case_manager / viewer (+ always for authority) ──
                if new_role in _LOCAL_ONLY_ROLES or _created:
                    try:
                        import hashlib as _hl
                        _pw_hash = _hl.sha256(new_password.encode()).hexdigest()
                        conn = _get_db_conn()
                        if conn:
                            cur = conn.cursor()
                            cur.execute("""
                                INSERT INTO platform_users_local
                                    (username, full_name, email, role, password_hash,
                                     is_active, effective_date, expire_date, created_by)
                                VALUES (%s,%s,%s,%s,%s,TRUE,%s,%s,%s)
                                ON CONFLICT (username) DO NOTHING
                            """, (_uname, new_fullname.strip(), new_email.strip(),
                                  new_role, _pw_hash,
                                  new_acc_eff or None,
                                  new_acc_exp or None,
                                  st.session_state.get("username","system")))
                            conn.commit(); cur.close(); _release_db_conn(conn)
                            if new_role in _LOCAL_ONLY_ROLES:
                                _created = True
                    except Exception as _lce:
                        # BUG4 FIX: always surface the DB error so case_manager/viewer failures are visible
                        _err_msg = f"Database error: {_lce}"
                        _created = False

                # ── Save authority limits if provided ──────────────────────────
                if _created and (new_max_face > 0 or new_min_face > 0 or new_prod_restrict.strip()):
                    _prod_list = ([p.strip().upper() for p in new_prod_restrict.split(",")
                                   if p.strip()] if new_prod_restrict.strip() else [])
                    _ok_lim, _err_lim = _save_limit(
                        _uname,
                        new_min_face,
                        new_max_face if new_max_face > 0 else None,
                        _prod_list,
                        new_lim_notes.strip(),
                        st.session_state.get("username","system")
                    )
                    if not _ok_lim:
                        st.warning(f"⚠️ User created but authority limit save failed: {_err_lim}")

                if _created:
                    exp_note = f" | Expires: {new_acc_exp}" if new_acc_exp else ""
                    lim_note = (f" | Authority: {sym}{new_min_face:,.0f}–{sym}{new_max_face:,.0f}"
                                if new_max_face > 0 else "")
                    local_note = " *(stored locally)*" if new_role in _LOCAL_ONLY_ROLES else ""
                    st.session_state["_um_create_success"] = (
                        f"✅ User **{_uname}** created with role "
                        f"**{new_role.replace('_',' ').title()}**{local_note}."
                        f"{exp_note}{lim_note} They can log in immediately."
                    )
                    # Clear saved form values on success
                    st.session_state.pop("_um_form_vals", None)
                    st.rerun()
                else:
                    st.error(f"❌ {_err_msg or 'Unknown error — user not created.'}")

    # ══════════════════════════════════════════════════════════════
    # TAB 3 — AUTHORITY LIMITS OVERVIEW
    # ══════════════════════════════════════════════════════════════
    with tab_limits:
        st.caption(
            "Overview of all underwriting authority limits. "
            "A user without a limit set can underwrite any face amount permitted by their role."
        )

        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT username, min_face_amount, max_face_amount,
                           product_codes, notes, is_active, set_by, updated_at
                    FROM user_authority_limits
                    ORDER BY max_face_amount ASC NULLS LAST, username
                """)
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)

                if not rows:
                    st.info("No authority limits set yet. Use **All Users → 🎯 Set Authority** to configure limits per user.")
                else:
                    # Summary metrics
                    active_limits = [r for r in rows if r[5]]
                    m1,m2,m3 = st.columns(3)
                    m1.metric("Users with limits", len(active_limits))
                    m2.metric("Unlimited users",
                              sum(1 for r in active_limits if r[2] is None))
                    m3.metric("Restricted users",
                              sum(1 for r in active_limits if r[2] is not None))
                    st.divider()

                    for row in rows:
                        uname, min_f, max_f, prods, notes, is_active, set_by, upd = row
                        min_f = float(min_f) if min_f else 0
                        max_f = float(max_f) if max_f else None
                        status_icon = "🟢" if is_active else "⚫"
                        max_label   = f"{sym}{max_f:,.0f}" if max_f else "Unlimited"
                        min_label   = f"{sym}{min_f:,.0f}" if min_f > 0 else "—"
                        prod_label  = ", ".join(prods) if prods else "All products"

                        with st.expander(
                            f"{status_icon} **{uname}** — "
                            f"Min: {min_label} | Max: {max_label} | {prod_label}"
                        ):
                            ec1,ec2,ec3,ec4 = st.columns(4)
                            ec1.metric(f"Min ({sym})", f"{min_f:,.0f}" if min_f else "None")
                            ec2.metric(f"Max ({sym})", f"{max_f:,.0f}" if max_f else "Unlimited")
                            ec3.metric("Products", prod_label)
                            ec4.metric("Status", "Active" if is_active else "Disabled")
                            st.caption(
                                f"Set by: {set_by or '—'} | "
                                f"Last updated: {str(upd or '')[:10]} | "
                                f"Notes: {notes or '—'}"
                            )
                            # Quick edit inline
                            with st.form(f"ql_edit_{uname}"):
                                qe1,qe2 = st.columns(2)
                                qe_min = qe1.number_input(
                                    f"Min ({sym})", value=int(min_f), step=50_000,
                                    min_value=0, key=f"ql_min_{uname}",
                                    help="Minimum face amount this user can underwrite.")
                                qe_max = qe2.number_input(
                                    f"Max ({sym}, 0=unlimited)", value=int(max_f or 0),
                                    step=50_000, min_value=0, key=f"ql_max_{uname}",
                                    help="Maximum face amount. Set 0 for unlimited.")
                                qe_prods = st.text_input(
                                    "Products (comma-sep, blank=all)",
                                    value=", ".join(prods) if prods else "",
                                    key=f"ql_prods_{uname}",
                                    help="Leave blank to allow all products.")
                                qe_notes = st.text_input(
                                    "Notes", value=notes or "",
                                    key=f"ql_notes_{uname}",
                                    help="Internal note about this limit.")
                                qsave = st.form_submit_button(
                                    "💾 Update", use_container_width=True, type="primary")
                            if qsave:
                                _pl = ([p.strip().upper() for p in qe_prods.split(",")
                                        if p.strip()] if qe_prods.strip() else [])
                                ok, err = _save_limit(
                                    uname, qe_min, qe_max if qe_max > 0 else None,
                                    _pl, qe_notes,
                                    st.session_state.get("username","system"))
                                if ok:
                                    st.success("✅ Updated.")
                                    st.rerun()
                                else:
                                    st.error(f"Failed: {err}")
        except Exception as ex:
            st.error(f"Could not load limits: {ex}")

    # ══════════════════════════════════════════════════════════════
    # TAB 4 — MFA SETTINGS
    # ══════════════════════════════════════════════════════════════
    with tab_mfa:
        st.caption(
            "Configure Time-based One-Time Password (TOTP) multi-factor authentication. "
            "Works with Google Authenticator, Authy, Microsoft Authenticator, and any "
            "RFC 6238-compatible app."
        )

        _my_uname = st.session_state.get("username","")
        _my_uname_short = _my_uname.split("@")[0] if "@" in _my_uname else _my_uname
        _is_admin = st.session_state.get("role","") in ("super_admin","admin")

        # ── Own MFA setup ──────────────────────────────────────────────────
        st.markdown("##### Your MFA")
        _my_mfa = _mfa_get(_my_uname_short)

        if _my_mfa and _my_mfa.get("is_enabled") and _my_mfa.get("is_verified"):
            st.success(f"✅ MFA is **active** on your account. "
                       f"Enabled: {_my_mfa.get('enabled_at','—')} | "
                       f"Last used: {_my_mfa.get('last_used_at','Never')}")
            _bc_remaining = len(_my_mfa.get("backup_codes",[]))
            if _bc_remaining <= 2:
                st.warning(f"⚠️ Only {_bc_remaining} backup code(s) remaining. Regenerate below.")

            with st.expander("⚙️ Manage your MFA"):
                _dm1, _dm2 = st.columns(2)
                if _dm1.button("🔄 Regenerate backup codes",
                               use_container_width=True, key="regen_backup"):
                    _new_codes = _mfa_generate_backup_codes(8)
                    _mfa_save(_my_uname_short, _my_mfa["secret"],
                              True, True, _new_codes)
                    st.session_state["_show_new_codes"] = _new_codes
                    _log_audit("AUTH","MFA_BACKUP_CODES_REGENERATED",
                        entity_type="USER", entity_id=_my_uname_short)
                    st.rerun()

                if _dm2.button("🗑️ Disable MFA", use_container_width=True,
                               key="disable_mfa", type="secondary"):
                    st.session_state["_mfa_disable_confirm"] = True

                if st.session_state.get("_mfa_disable_confirm"):
                    st.warning("⚠️ Disabling MFA reduces your account security.")
                    with st.form("disable_mfa_form"):
                        _dis_code = st.text_input(
                            "Enter your current MFA code to confirm",
                            max_chars=6, placeholder="000000",
                            help="Enter your current 6-digit authenticator code to confirm disabling MFA.")
                        if st.form_submit_button("Confirm disable MFA",
                                                  type="primary",
                                                  use_container_width=True):
                            if _mfa_verify(_my_mfa["secret"], _dis_code):
                                _mfa_save(_my_uname_short, _my_mfa["secret"],
                                          False, False, [])
                                st.session_state.pop("_mfa_disable_confirm", None)
                                _log_audit("AUTH","MFA_DISABLED",
                                    entity_type="USER", entity_id=_my_uname_short)
                                st.success("MFA disabled.")
                                st.rerun()
                            else:
                                st.error("❌ Invalid code.")

            # Show newly generated backup codes
            if st.session_state.get("_show_new_codes"):
                _nc = st.session_state.pop("_show_new_codes")
                st.markdown("##### ⬇️ Your new backup codes — save these now")
                st.warning("These codes will not be shown again. Store them somewhere safe.")
                _code_display = "  |  ".join(_nc)
                st.code(_code_display)
                st.download_button(
                    "⬇️ Download backup codes",
                    data="\n".join(_nc),
                    file_name="uw_platform_backup_codes.txt",
                    mime="text/plain",
                    use_container_width=True,
                    help="Save these 8 backup codes securely — each can only be used once."
                )

        elif _my_mfa and not _my_mfa.get("is_verified"):
            # Secret generated but not yet verified
            st.info("MFA setup in progress — scan the QR code and enter a code to verify.")
            _secret = _my_mfa["secret"]
            _otp_url = _mfa_otpauth_url(_secret, _my_uname, "UW Platform")

            st.markdown("**Step 1 — Scan QR code or enter manually**")
            _qr_col, _key_col = st.columns([1, 2])
            with _qr_col:
                try:
                    import qrcode, io
                    _qr_img = qrcode.make(_otp_url)
                    _qr_buf = io.BytesIO()
                    _qr_img.save(_qr_buf, format="PNG")
                    _qr_buf.seek(0)
                    st.image(_qr_buf, width=200)
                    st.caption("Scan with your authenticator app")
                except Exception as _qe:
                    st.warning(f"QR render failed: {_qe}")
            with _key_col:
                st.markdown("**Can't scan? Enter key manually:**")
                st.code(_secret, language=None)
                st.caption(
                    "Google Authenticator: ＋ → Enter a setup key\n"
                    "Account: UW Platform | Key: above | Type: Time-based"
                )
                st.markdown(
                    f"<a href='{_otp_url}' style='display:inline-block;background:#1d4ed8;"
                    f"color:white;padding:8px 16px;border-radius:6px;font-size:0.82rem;"
                    f"text-decoration:none;margin-top:8px;'>📱 Open in Authenticator App (mobile)</a>",
                    unsafe_allow_html=True
                )

            st.markdown("**Step 2 — Verify setup**")
            with st.form("mfa_verify_form"):
                _vcode = st.text_input(
                    "Enter the 6-digit code from your app",
                    max_chars=6, placeholder="000000",
                    help="Enter the current 6-digit code shown in your authenticator app."
                )
                if st.form_submit_button("✅ Verify & Enable MFA",
                                          use_container_width=True, type="primary"):
                    if _mfa_verify(_secret, _vcode):
                        _backup_codes = _mfa_generate_backup_codes(8)
                        _mfa_save(_my_uname_short, _secret, True, True, _backup_codes)
                        st.session_state["_show_new_codes"] = _backup_codes
                        _log_audit("AUTH","MFA_ENABLED",
                            entity_type="USER", entity_id=_my_uname_short,
                            metadata={"method":"totp"})
                        st.success("✅ MFA enabled! Save your backup codes below.")
                        st.rerun()
                    else:
                        st.error("❌ Incorrect code — check your app and try again.")

        else:
            # Not set up at all
            st.info("MFA is not enabled on your account. Enable it to add a second layer of security.")
            if st.button("🔐 Set up MFA", type="primary", key="setup_mfa_btn"):
                _new_secret = _mfa_generate_secret()
                logger.info("[MFA_SETUP] Attempting setup for user: %s", _my_uname_short)
                _save_result = _mfa_save(_my_uname_short, _new_secret, False, False, [])
                logger.info("[MFA_SETUP] Save result: %s", _save_result)
                _log_audit("AUTH","MFA_SETUP_STARTED",
                    entity_type="USER", entity_id=_my_uname_short)
                st.rerun()

        st.divider()

        # ── Admin: manage MFA for all users ──────────────────────────────────
        if _is_admin:
            st.markdown("##### MFA status — all users")
            try:
                conn = _get_db_conn()
                if conn:
                    _mfa_ensure_table()
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT u.username, u.full_name, u.role,
                               m.is_enabled, m.is_verified,
                               m.enabled_at, m.last_used_at
                        FROM uw_user u
                        LEFT JOIN mfa_config m ON m.username = u.username
                        WHERE u.is_active = TRUE
                        ORDER BY u.username
                    """)
                    all_mfa = cur.fetchall()
                    cur.close(); _release_db_conn(conn)

                    if all_mfa:
                        import pandas as _pd_mfa
                        def _mfa_val(r, key, idx):
                            return r[key] if isinstance(r, dict) else r[idx]
                        _mfa_df = _pd_mfa.DataFrame([{
                            "Username":    _mfa_val(r, "username",     0),
                            "Full Name":   _mfa_val(r, "full_name",    1),
                            "Role":        _mfa_val(r, "role",         2),
                            "MFA Enabled": _mfa_val(r, "is_enabled",   3),
                            "MFA Verified":_mfa_val(r, "is_verified",  4),
                            "Enabled At":  _mfa_val(r, "enabled_at",   5),
                            "Last Used":   _mfa_val(r, "last_used_at", 6),
                        } for r in all_mfa])
                        _mfa_df["Status"] = _mfa_df.apply(
                            lambda r: "✅ Active" if r["MFA Enabled"] and r["MFA Verified"]
                            else ("⏳ Setup pending" if r["MFA Verified"] == False and r["MFA Enabled"] == False and r["MFA Verified"] is not None
                                  else "❌ Not set up"), axis=1)
                        _mfa_df["Enabled At"] = _mfa_df["Enabled At"].astype(str).str[:10]
                        _mfa_df["Last Used"]  = _mfa_df["Last Used"].astype(str).str[:16]
                        st.dataframe(
                            _mfa_df[["Username","Full Name","Role","Status","Enabled At","Last Used"]],
                            use_container_width=True, hide_index=True
                        )

                        # Admin: force-reset MFA for a user
                        _mfa_active = [_mfa_val(r, "username", 0) for r in all_mfa
                                       if _mfa_val(r, "is_enabled", 3) and _mfa_val(r, "is_verified", 4)]
                        if _mfa_active:
                            st.markdown("**Admin: reset a user's MFA**")
                            _reset_sel = st.selectbox(
                                "Select user to reset MFA",
                                ["—"] + _mfa_active, key="admin_mfa_reset_sel",
                                help="Disables and clears MFA for the selected user. They will need to set it up again on next login."
                            )
                            if _reset_sel != "—":
                                if st.button(f"🗑️ Reset MFA for {_reset_sel}",
                                             type="secondary", key="admin_mfa_reset_btn"):
                                    _mfa_cfg_r = _mfa_get(_reset_sel)
                                    if _mfa_cfg_r:
                                        _mfa_save(_reset_sel,
                                                  _mfa_cfg_r["secret"],
                                                  False, False, [])
                                        _log_audit("AUTH","MFA_ADMIN_RESET",
                                            entity_type="USER",
                                            entity_id=_reset_sel,
                                            actor_username=_my_uname_short,
                                            metadata={"reset_by": _my_uname_short})
                                        st.success(f"✅ MFA reset for {_reset_sel}.")
                                        st.rerun()
            except Exception as _mfa_admin_err:
                st.error(f"Could not load MFA status: {_mfa_admin_err}")


    # ══════════════════════════════════════════════════════════════
    # TAB 5 — ROLE REFERENCE
    # ══════════════════════════════════════════════════════════════
    with tab_roles:
        st.caption("Role hierarchy and permissions reference.")
        for role in ROLES[::-1]:
            col = ROLE_COLORS.get(role,"#94a3b8")
            with st.expander(
                f"**{role.replace('_',' ').title()}**  —  {ROLE_DESC.get(role,'')}"):
                perms = {
                    "super_admin": [
                        "✅ All admin permissions",
                        "✅ System configuration",
                        "✅ Currency & rate table management",
                        "✅ User management (create/deactivate/role change/authority limits)",
                        "✅ Audit log access",
                        "✅ Tenant settings",
                    ],
                    "admin": [
                        "✅ User management + authority limit management",
                        "✅ Product configuration",
                        "✅ Rule builder",
                        "✅ System config",
                        "✅ UW Queue + decisions",
                        "✅ Full workbench access",
                    ],
                    "senior_underwriter": [
                        "✅ UW Queue (assign, decide, override)",
                        "✅ Product config (view only)",
                        "✅ APS management",
                        "✅ Premium calculator",
                        "✅ Full workbench access",
                        "❌ Cannot manage users or system config",
                    ],
                    "underwriter": [
                        "✅ UW Queue (own cases, within face amount authority)",
                        "✅ APS requests",
                        "✅ Premium calculator",
                        "✅ Full workbench access",
                        "❌ Blocked if case exceeds authority limit",
                        "❌ Cannot assign to others or override",
                    ],
                    "case_manager": [
                        "✅ Queue view",
                        "✅ APS tracking",
                        "✅ Workbench (view results)",
                        "❌ Cannot make UW decisions",
                        "❌ No admin access",
                    ],
                    "viewer": [
                        "✅ Workbench (read-only)",
                        "✅ Queue (view only)",
                        "❌ No decisions or modifications",
                        "❌ No admin access",
                    ],
                }.get(role, [])
                for p in perms:
                    st.markdown(p)

def _get_products_from_api(force_refresh: bool = False) -> dict:
    """Fetch products from API. Returns {code: name} dict. Caches in session_state."""
    if not force_refresh and "pc_products_cache" in st.session_state:
        return st.session_state.pc_products_cache
    try:
        r = requests.get(f"{API_BASE}/products", headers=api_headers(), timeout=5)
        if r.status_code == 200:
            result = {p["product_code"]: p["product_name"]
                    for p in r.json().get("products", []) if p.get("is_active", True)}
            if result:
                st.session_state.pc_products_cache = result
                return result
    except Exception as _exc:
        logger.debug("[_get_products_from_api] Suppressed exception", exc_info=_exc)
    fallback = {
        "IND-TERM-10": "Term 10yr", "IND-TERM-20": "Term 20yr",
        "IND-TERM-30": "Term 30yr", "IND-UL-FLEX": "Universal Life",
        "IND-WL-PREM": "Whole Life Premium", "IND-FE-SIMPLE": "Final Expense",
        "IND-KEYMAN": "Key Person", "GRP-BASIC-1x": "Group Basic",
        "GRP-SUPP-EOI": "Group Supplemental",
    }
    st.session_state.pc_products_cache = fallback
    return fallback


def render_product_config():
    """Product Configuration — view, edit, and create products via API."""
    import pandas as pd
    from datetime import date as _date, datetime as _datetime

    def _pd(v):
        if not v: return None
        try: return _datetime.fromisoformat(str(v)[:10]).date()
        except: return None

    st.markdown("## 🔧 Product Configuration")
    st.caption("Configure products, underwriting rules, thresholds, and build tables.")
    hdr = api_headers()
    # ── Product selector with refresh ──────────────────────────
    _sel_col, _btn_col = st.columns([5, 1])
    _force_refresh = _btn_col.button("🔄 Refresh", key="pc_selector_refresh",
                                     help="Reload product list from database")
    if _force_refresh:
        for _k in ["pc_products_cache", "pc_product_select", "pc_rules_data", "pc_thresh_data"]:
            st.session_state.pop(_k, None)
        st.rerun()
    products = _get_products_from_api(force_refresh=False)

    tab_r, tab_t, tab_b, tab_edit, tab_add = st.tabs([
        "📋 Rules & Overrides", "⚖️ Thresholds", "📐 Build Table", "✏️ Edit Product", "➕ Add Product"
    ])

    with _sel_col:
        if products:
            selected = st.selectbox("Select Product", list(products.keys()),
                format_func=lambda k: f"{k}  —  {products[k]}", key="pc_product_select")
        else:
            st.error("Could not load products from API.")
            selected = None

    # ══════════════════════════════════════════════════════════
    # TAB 1 — RULES & OVERRIDES
    # ══════════════════════════════════════════════════════════
    with tab_r:
        if not selected:
            st.info("No product selected."); return
        st.caption("Enable/disable rules and override debit points per product.")
        col_r1, col_r2 = st.columns([3,1])
        search = col_r1.text_input("Search rules", key="pc_rule_search", placeholder="rule name or ID")
        if col_r2.button("🔄 Refresh", key="pc_rules_refresh"):
            st.session_state.pop("pc_rules_data", None)
        if "pc_rules_data" not in st.session_state or st.session_state.get("pc_rules_product") != selected:
            rules_raw = []
            # Try API first
            try:
                r = requests.get(f"{API_BASE}/products/{selected}/rules", headers=hdr, timeout=10)
                if r.status_code == 200:
                    d = r.json()
                    rules_raw = d if isinstance(d, list) else d.get("rules", d.get("items", []))
            except Exception as _exc:
                logger.debug("[_pd] Suppressed exception", exc_info=_exc)
            # Fall back to direct DB read if API returned nothing
            if not rules_raw:
                try:
                        _conn = _get_db_conn()
                        if _conn:
                            _cur = _conn.cursor()
                        _cur.execute("""
                            SELECT pr.rule_id, pr.is_enabled,
                                   pr.debit_points_override, pr.debit_override_active,
                                   pr.flat_extra_override,   pr.flat_extra_override_active
                            FROM product_rules pr
                            WHERE pr.product_code = %s
                            ORDER BY pr.rule_id
                        """, (selected,))
                        rows = _cur.fetchall()
                        _cur.close(); _release_db_conn(_conn)
                        rules_raw = [{
                            "rule_id":                  row[0],
                            "rule_name":                row[0],
                            "is_enabled":               row[1],
                            "debit_points":             row[2] or 0,
                            "debit_override_active":    row[3] or False,
                            "flat_extra":               row[4],
                            "flat_extra_override_active": row[5] or False,
                            "version":                  "—",
                            "hard_stop":                False,
                        } for row in rows]
                except Exception as _exc:
                    logger.debug("[_pd] Suppressed exception", exc_info=_exc)
            st.session_state.pc_rules_data = rules_raw
            st.session_state.pc_rules_product = selected
        rules = st.session_state.get("pc_rules_data", [])
        if not isinstance(rules, list):
            rules = rules.get("rules", rules.get("items", []))
        if rules:
            m1,m2,m3 = st.columns(3)
            m1.metric("Total Rules", len(rules))
            m2.metric("Disabled", sum(1 for r in rules if not r.get("is_enabled", True)))
            m3.metric("Overridden", sum(1 for r in rules if r.get("debit_override_active") or r.get("flat_extra_override_active")))
            st.divider()
            show_f = st.selectbox("Show", ["All rules","Overridden only","Disabled only"], key="pc_show_filter")
            display = rules
            if search:
                q = search.lower()
                display = [r for r in display if q in str(r.get("rule_name","")).lower() or q in str(r.get("rule_id","")).lower()]
            if show_f == "Overridden only":
                display = [r for r in display if r.get("debit_override_active") or r.get("flat_extra_override_active")]
            elif show_f == "Disabled only":
                display = [r for r in display if not r.get("is_enabled", True)]
            st.caption(f"Showing {len(display)} of {len(rules)} rules")
            df_rules = pd.DataFrame([{
                "Rule ID":   r.get("rule_id","—"),
                "Rule Name": r.get("rule_name","—"),
                "Version":   r.get("version","—"),
                "Debits":    r.get("debit_points", r.get("base_debit_points", 0)),
                "Flat Extra":f"${r.get('flat_extra',0)}/K" if r.get("flat_extra") else "—",
                "Enabled":   "✅" if r.get("is_enabled", True) else "🔴",
                "Overridden":"⚡" if r.get("debit_override_active") or r.get("flat_extra_override_active") else "",
                "Hard Stop": "🔴" if r.get("hard_stop") else "",
                "Effective": str(r.get("effective_date",""))[:10] if r.get("effective_date") else "—",
                "Expires":   str(r.get("expire_date",""))[:10]    if r.get("expire_date")    else "Never",
            } for r in display])
            st.dataframe(df_rules, use_container_width=True, hide_index=True)
        else:
            st.info(f"ℹ️ No rules configured yet for **{selected}**. "
                    f"Rules can be assigned via the Rule Builder page.")
            # Show product details from API or fallback
            try:
                pr = requests.get(f"{API_BASE}/products/{selected}", headers=hdr, timeout=5)
                p = pr.json() if pr.status_code == 200 else PRODUCTS.get(selected, {})
            except Exception as _exc:
                logger.debug("[_pd] Suppressed exception", exc_info=_exc)
                p = PRODUCTS.get(selected, {})
            if p:
                st.markdown("**Product Details**")
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Min Age", p.get("min_age","—")); c2.metric("Max Age", p.get("max_age","—"))
                c3.metric("Min Face", f"{get_currency_symbol()}{p.get('min_face_amount', p.get('min_face',0)):,.0f}")
                c4.metric("Max Face", f"{get_currency_symbol()}{p.get('max_face_amount', p.get('max_face',0)):,.0f}")
                c5,c6,c7 = st.columns(3)
                c5.metric("STP Threshold",     p.get("stp_threshold","—"))
                c6.metric("Refer Threshold",   p.get("refer_threshold","—"))
                c7.metric("Decline Threshold", p.get("decline_threshold","—"))
                if p.get("description"):
                    st.caption(f"📋 {p['description']}")

    # ══════════════════════════════════════════════════════════
    # TAB 2 — THRESHOLDS
    # ══════════════════════════════════════════════════════════
    with tab_t:
        if not selected:
            st.info("No product selected."); return
        st.caption("Set STP, refer, and decline thresholds for this product.")
        if st.button("🔄 Load Thresholds", key="pc_thresh_load"):
            st.session_state.pop("pc_thresh_data", None)
        if "pc_thresh_data" not in st.session_state:
            try:
                r = requests.get(f"{API_BASE}/products/{selected}/thresholds", headers=hdr, timeout=5)
                st.session_state.pc_thresh_data = r.json() if r.status_code == 200 else {}
            except Exception as _exc:
                logger.debug("[_pd] Suppressed exception", exc_info=_exc)
                st.session_state.pc_thresh_data = {}
        thresh = st.session_state.get("pc_thresh_data", {})
        if not thresh:
            thresh = {"stp_threshold": 50, "refer_threshold": 150, "decline_threshold": 300,
                      "max_table_rating": 16, "max_flat_extra": 10.0}
            st.info("Using default thresholds — configure via API.")

        # Show current effective/expire if available
        if thresh.get("effective_date") or thresh.get("expire_date"):
            eff_cur = str(thresh.get("effective_date",""))[:10] or "—"
            exp_cur = str(thresh.get("expire_date",""))[:10]    or "Never"
            st.caption(f"📅 Current thresholds  —  Effective: **{eff_cur}**  |  Expires: **{exp_cur}**")

        with st.form("pc_thresh_form"):
            c1,c2,c3 = st.columns(3)
            new_stp     = c1.number_input("STP Threshold",     0, 200,  int(thresh.get("stp_threshold",50)), help="Straight Through Processing limit. Applications scoring AT OR BELOW this total debit score are auto-approved instantly with no human review.")
            new_refer   = c2.number_input("Refer Threshold",   0, 400,  int(thresh.get("refer_threshold",150)), help="Applications scoring between STP and this value are sent to the UW Queue for manual underwriter review.")
            new_decline = c3.number_input("Decline Threshold", 50, 1000,int(thresh.get("decline_threshold",300)), help="Applications scoring ABOVE this total debit score are automatically declined. No underwriter review — instant decline letter generated.")
            c4,c5 = st.columns(2)
            options = [0,2,4,6,8,10,12,14,16]
            cur_tbl = int(thresh.get("max_table_rating",16))
            new_max_table = c4.selectbox("Max Table Rating", options,
                index=options.index(cur_tbl) if cur_tbl in options else 8)
            new_max_fe = c5.number_input("Max Flat Extra", 0.0, 20.0,
                float(thresh.get("max_flat_extra",10.0)), step=0.5,
                help="Cap on flat extra surcharge ($/K/yr). Any rule that would push flat extra above this value triggers a decline instead of issuing at a rated premium.")
            td1, td2 = st.columns(2)
            pc_eff = td1.date_input("Effective Date",
                value=_pd(thresh.get("effective_date")) or _date.today(),
                help="Date these thresholds take effect — allows future-dating changes")
            pc_exp = td2.date_input("Expire Date",
                value=_pd(thresh.get("expire_date")),
                help="Date thresholds revert — leave blank for indefinite")
            reason = st.text_input("Reason for change *", placeholder="e.g. Annual rate review 2026", help="Mandatory audit reason. Stored in the threshold change history for regulatory compliance.")
            if st.form_submit_button("💾 Save Thresholds", use_container_width=True, type="primary"):
                if new_stp < new_refer < new_decline:
                    resp = requests.put(f"{API_BASE}/products/{selected}/thresholds", headers=hdr,
                        json={"stp_threshold": new_stp, "refer_threshold": new_refer,
                              "decline_threshold": new_decline, "max_table_rating": new_max_table,
                              "max_flat_extra": new_max_fe, "change_reason": reason,
                              "effective_date": str(pc_eff) if pc_eff else None,
                              "expire_date":    str(pc_exp) if pc_exp else None})
                    if resp.status_code == 200:
                        st.success("✅ Thresholds saved")
                        st.caption(f"📅 Effective: {pc_eff}  |  Expires: {pc_exp or 'Never'}")
                        st.session_state.pop("pc_thresh_data", None)
                    else:
                        st.error(f"Failed: {resp.text[:200]}")
                else:
                    st.error("Must satisfy: STP < Refer < Decline")

    # ══════════════════════════════════════════════════════════
    # TAB 3 — BUILD TABLE
    # ══════════════════════════════════════════════════════════
    with tab_b:
        if not selected:
            st.info("No product selected."); return

        st.markdown("#### 📐 BMI Build Table")
        st.caption(
            "The Build Table defines how an applicant's height/weight (BMI) affects their debit score. "
            "Each band maps a BMI range to debit points — higher BMI = more debits. "
            "A band marked **Decline** is an automatic decline regardless of thresholds."
        )

        col_bt_hd, col_bt_ref = st.columns([5,1])
        if col_bt_ref.button("🔄 Refresh", key="pc_bt_refresh"):
            st.session_state.pop(f"pc_bt_data_{selected}", None)

        # Auto-load from DB on first visit (no button needed)
        cache_key = f"pc_bt_data_{selected}"
        if cache_key not in st.session_state:
            bands_loaded = []
            # Try API first
            try:
                r = requests.get(f"{API_BASE}/products/{selected}/build-table", headers=hdr, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    bands_loaded = d if isinstance(d, list) else d.get("bands", d.get("build_table", []))
            except Exception as _exc:
                logger.debug("[_pd] Suppressed exception", exc_info=_exc)
            # Fall back to direct DB read
            if not bands_loaded:
                try:
                        _conn = _get_db_conn()
                        if _conn:
                            _cur = _conn.cursor()
                        # Create table if not exists
                        _cur.close(); _release_db_conn(_conn)
                        bands_loaded = [
                            {"bmi_min": r[0], "bmi_max": r[1], "debit_points": r[2],
                             "is_decline": r[3], "band_label": r[4] or ""}
                            for r in rows
                        ]
                except Exception as _exc:
                    logger.warning("[_pd] Suppressed exception", exc_info=_exc)
            st.session_state[cache_key] = bands_loaded

        bands = st.session_state.get(cache_key, [])

        # ── Safe conversion helpers ───────────────────────
        def _safe_float(val, default=0.0):
            try: return float(val)
            except (TypeError, ValueError): return float(default)

        def _safe_int(val, default=0):
            try: return int(val)
            except (TypeError, ValueError): return int(default)

        # ── Display existing bands ───────────────────────────
        if bands:
            st.markdown(f"**{len(bands)} BMI bands configured for `{selected}`**")
            df_bt = pd.DataFrame([{
                "BMI Min":      _safe_float(b.get("bmi_min", 0)),
                "BMI Max":      _safe_float(b.get("bmi_max", 0)),
                "Debit Points": _safe_int(b.get("debit_points", 0)),
                "Decline":      "🔴 AUTO-DECLINE" if b.get("is_decline") else "",
                "Label":        b.get("band_label", ""),
            } for b in bands])
            st.dataframe(df_bt, use_container_width=True, hide_index=True)

            # Visual guide
            st.divider()
            st.markdown("**How these bands are used:**")
            for b in bands:
                _bmin = _safe_float(b.get("bmi_min", 0))
                _bmax = _safe_float(b.get("bmi_max", 0))
                _dpts = _safe_int(b.get("debit_points", 0))
                label = b.get("band_label") or f"BMI {_bmin}–{_bmax}"
                if b.get("is_decline"):
                    st.error(f"🔴 BMI {_bmin} – {_bmax} → **AUTO-DECLINE** ({label})")
                elif _dpts == 0:
                    st.success(f"✅ BMI {_bmin} – {_bmax} → **0 debits** ({label})")
                else:
                    st.warning(f"⚠️ BMI {_bmin} – {_bmax} → **+{_dpts} debits** ({label})")
        else:
            st.info(f"No BMI build table configured for **{selected}** yet. Add bands below.")

        # ── Add / Edit bands form ────────────────────────────
        st.divider()
        with st.expander("➕ Add BMI Band", expanded=not bool(bands)):
            st.caption("Define a BMI range and how many debit points it adds. "
                       "Typical bands: Preferred (18–25, 0pts), Standard (25–32, 25pts), "
                       "Substandard (32–40, 75pts), Decline (40+).")
            with st.form("bt_add_form", clear_on_submit=True):
                ba1, ba2, ba3 = st.columns(3)
                new_bmi_min = ba1.number_input("BMI Min", 10.0, 80.0, 18.0, step=0.5)
                new_bmi_max = ba2.number_input("BMI Max", 10.0, 99.0, 25.0, step=0.5)
                new_debits  = ba3.number_input("Debit Points", 0, 500, 0, step=5)
                bl1, bl2 = st.columns(2)
                new_label   = bl1.text_input("Band Label", placeholder="e.g. Preferred, Standard, Obese")
                new_decline = bl2.checkbox("Auto-Decline band (instant decline regardless of score)", help="When ticked, any applicant whose BMI falls in this band is instantly declined — bypassing the debit threshold entirely. Typically used for BMI 40+ (morbid obesity).")

                if st.form_submit_button("💾 Save Band", use_container_width=True, type="primary"):
                    if new_bmi_min >= new_bmi_max:
                        st.error("BMI Min must be less than BMI Max")
                    else:
                        saved_bt = False
                        try:
                                _conn2 = _get_db_conn()
                                if _conn2:
                                    _cur2 = _conn2.cursor()
                                _cur2.execute("""
                                    INSERT INTO product_build_table
                                        (product_code, bmi_min, bmi_max, debit_points, is_decline, band_label)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (product_code, bmi_min, bmi_max)
                                    DO UPDATE SET
                                        debit_points = EXCLUDED.debit_points,
                                        is_decline   = EXCLUDED.is_decline,
                                        band_label   = EXCLUDED.band_label
                                """, (selected, new_bmi_min, new_bmi_max, new_debits, new_decline, new_label.strip() or None))
                                _cur2.close(); _release_db_conn(_conn2)
                                saved_bt = True
                        except Exception as _bte:
                            st.error(f"❌ DB error: {_bte}")

                        if saved_bt:
                            st.success(f"✅ Band BMI {new_bmi_min}–{new_bmi_max} saved!")
                            st.session_state.pop(cache_key, None)
                            st.rerun()

        # ── Delete a band ────────────────────────────────────
        if bands:
            with st.expander("🗑️ Delete a Band"):
                band_labels = [f"BMI {_safe_float(b.get('bmi_min',0))}–{_safe_float(b.get('bmi_max',0))}  {b.get('band_label','')}" for b in bands]
                del_idx = st.selectbox("Select band to delete", range(len(band_labels)),
                                       format_func=lambda i: band_labels[i], key="bt_del_sel")
                if st.button("⚠️ Confirm Delete", key="bt_del_confirm", type="primary"):
                    b_del = bands[del_idx]
                    try:
                        _conn3 = _get_db_conn()
                        if _conn3:
                            _cur3 = _conn3.cursor()
                        _cur3.execute(
                            "DELETE FROM product_build_table WHERE product_code=%s AND bmi_min=%s AND bmi_max=%s",
                            (selected, b_del["bmi_min"], b_del["bmi_max"])
                        )
                        _cur3.close(); _release_db_conn(_conn3)
                        st.success("✅ Band deleted")
                        st.session_state.pop(cache_key, None)
                        st.rerun()
                    except Exception as _bde:
                        st.error(f"❌ Delete failed: {_bde}")


    # ══════════════════════════════════════════════════════════
    # TAB 4 — EDIT EXISTING PRODUCT
    # ══════════════════════════════════════════════════════════
    with tab_edit:
        st.markdown("#### ✏️ Edit Existing Product")
        st.caption("Modify any field of an existing product — including terms, thresholds, eligibility, and benefit/premium terms.")

        if not selected:
            st.info("Select a product from the dropdown above to edit it.")
        else:
            # ── Load current product data ─────────────────────────
            _ep_data = {}
            try:
                _ep_r = requests.get(f"{API_BASE}/products/{selected}", headers=hdr, timeout=6)
                if _ep_r.status_code == 200:
                    _ep_data = _ep_r.json()
            except Exception as _exc:
                logger.debug("[edit_product] API fetch failed", exc_info=_exc)

            # Fallback to DB direct read
            if not _ep_data:
                try:
                    _ec = _get_db_conn()
                    if _ec:
                        _ecu = _ec.cursor()
                        _ecu.execute("""
                            SELECT product_code, product_name, product_type, category,
                                   uw_method, min_age, max_age, min_face_amount,
                                   max_face_amount, available_terms, benefit_terms,
                                   premium_terms, exam_required, non_medical_limit,
                                   reinsurance_threshold, max_issue_age,
                                   stp_threshold, refer_threshold, decline_threshold,
                                   is_guaranteed_issue, is_group_product,
                                   description, uw_notes, effective_date, expire_date,
                                   is_active
                            FROM products WHERE product_code = %s
                        """, (selected,))
                        row = _ecu.fetchone()
                        _ecu.close(); _release_db_conn(_ec)
                        if row:
                            _ep_data = {
                                "product_code": row[0], "product_name": row[1],
                                "product_type": row[2], "category": row[3],
                                "uw_method": row[4], "min_age": row[5],
                                "max_age": row[6], "min_face_amount": row[7],
                                "max_face_amount": row[8],
                                "available_terms": row[9] or [],
                                "benefit_terms": row[10] or [],
                                "premium_terms": row[11] or [],
                                "exam_required": row[12] or "NONE",
                                "non_medical_limit": row[13] or 0,
                                "reinsurance_threshold": row[14] or 0,
                                "max_issue_age": row[15] or 65,
                                "stp_threshold": row[16] or 50,
                                "refer_threshold": row[17] or 150,
                                "decline_threshold": row[18] or 300,
                                "is_guaranteed_issue": bool(row[19]),
                                "is_group_product": bool(row[20]),
                                "description": row[21] or "",
                                "uw_notes": row[22] or "",
                                "effective_date": row[23],
                                "expire_date": row[24],
                                "is_active": bool(row[25]),
                            }
                except Exception as _exc:
                    logger.warning("[edit_product] DB fallback failed", exc_info=_exc)

            # 3. Final fallback — use hardcoded PRODUCTS dict (handles legacy products like GRP-BASIC-1x)
            if not _ep_data:
                _legacy = PRODUCTS.get(selected, {})
                if _legacy:
                    # Map legacy key names → standard key names
                    _uw_method_map = {
                        "Full UW": "FULL_UW", "Simplified EOI": "SIMPLIFIED",
                        "Guaranteed Issue": "GUARANTEED_ISSUE", "Accelerated": "ACCELERATED",
                        "FULL_UW": "FULL_UW", "SIMPLIFIED": "SIMPLIFIED",
                        "GUARANTEED_ISSUE": "GUARANTEED_ISSUE", "ACCELERATED": "ACCELERATED",
                    }
                    _ep_data = {
                        "product_code":        selected,
                        "product_name":        _legacy.get("name", _legacy.get("product_name", selected)),
                        "product_type":        _legacy.get("product_type", "GROUP_TERM" if _legacy.get("category","").startswith("Group") else "INDIVIDUAL_TERM"),
                        "category":            _legacy.get("category", "Individual Life"),
                        "uw_method":           _uw_method_map.get(_legacy.get("uw_method",""), "FULL_UW"),
                        "min_age":             _legacy.get("min_age", 18),
                        "max_age":             _legacy.get("max_age", 65),
                        "min_face_amount":     _legacy.get("min_face_amount", _legacy.get("min_face", 50_000)),
                        "max_face_amount":     _legacy.get("max_face_amount", _legacy.get("max_face", 2_000_000)),
                        "available_terms":     _legacy.get("available_terms", _legacy.get("terms", [])),
                        "benefit_terms":       _legacy.get("benefit_terms", []),
                        "premium_terms":       _legacy.get("premium_terms", []),
                        "exam_required":       "GUARANTEED_ISSUE" if _legacy.get("is_gi") else "NONE",
                        "non_medical_limit":   _legacy.get("non_medical_limit", 0),
                        "reinsurance_threshold": _legacy.get("reinsurance_threshold", 0),
                        "max_issue_age":       _legacy.get("max_age", 65),
                        "stp_threshold":       _legacy.get("stp_threshold", 50),
                        "refer_threshold":     _legacy.get("refer_threshold", 150),
                        "decline_threshold":   _legacy.get("decline_threshold", 300),
                        "is_guaranteed_issue": bool(_legacy.get("is_gi", False)),
                        "is_group_product":    "Group" in _legacy.get("category", ""),
                        "description":         _legacy.get("notes", ""),
                        "uw_notes":            _legacy.get("exam_note", ""),
                        "effective_date":      None,
                        "expire_date":         None,
                        "is_active":           True,
                        "_source":             "legacy_dict",
                    }
                    st.info(
                        f"ℹ️ **{selected}** is a legacy built-in product not yet in the database. "
                        f"Fields are pre-filled from the built-in definition. "
                        f"Saving will write it to the database for the first time."
                    )

            if not _ep_data:
                st.warning(f"⚠️ Could not load data for product **{selected}**. Check API/DB connection.")
                st.caption("**Debug info:** This usually means the product exists in the dropdown "
                           "but has no record in the `products` table and is not in the built-in PRODUCTS dict. "
                           "Try using **➕ Add Product** to create it properly, or check the database.")
            else:
                # ── Helper: parse terms list from DB (may be list, str, or None) ──
                def _parse_terms(val):
                    if not val:
                        return ""
                    if isinstance(val, list):
                        return ",".join(str(v) for v in val)
                    return str(val).strip("[]{}").replace(" ", "")

                _type_opts    = ["INDIVIDUAL_TERM","INDIVIDUAL_UL","INDIVIDUAL_WL",
                                 "INDIVIDUAL_FE","GROUP_TERM","GROUP_SUPP","KEY_PERSON"]
                _uw_opts      = ["FULL_UW","SIMPLIFIED","GUARANTEED_ISSUE","ACCELERATED"]
                _cat_opts     = ["Individual Life","Group Life","Final Expense","Key Person","Other"]
                _exam_opts    = ["NONE","PARAMEDICAL","FULL_MEDICAL","ATTENDING_PHYSICIAN"]

                def _idx(lst, val, default=0):
                    try: return lst.index(str(val)) if str(val) in lst else default
                    except: return default

                with st.form("edit_product_form", clear_on_submit=False):
                    st.markdown(f"**Editing: `{selected}` — {_ep_data.get('product_name','')}**")
                    st.divider()

                    # ── Identity ──────────────────────────────────────────
                    st.markdown("**Product Identity**")
                    ei1, ei2 = st.columns(2)
                    ep_name = ei1.text_input("Product Name *",
                        value=_ep_data.get("product_name",""))
                    _type_val = _ep_data.get("product_type","INDIVIDUAL_TERM")
                    if _type_val not in _type_opts: _type_val = "INDIVIDUAL_TERM"
                    ep_type = ei2.selectbox("Product Type *", _type_opts,
                        index=_type_opts.index(_type_val))

                    ei3, ei4 = st.columns(2)
                    _cat_val = _ep_data.get("category","Individual Life")
                    if _cat_val not in _cat_opts: _cat_val = "Individual Life"
                    ep_cat = ei3.selectbox("Product Category *", _cat_opts,
                        index=_cat_opts.index(_cat_val))
                    _uw_val = _ep_data.get("uw_method","FULL_UW")
                    if _uw_val not in _uw_opts: _uw_val = "FULL_UW"
                    ep_uw  = ei4.selectbox("UW Method *", _uw_opts,
                        index=_uw_opts.index(_uw_val))

                    st.divider()

                    # ── Eligibility ───────────────────────────────────────
                    st.markdown("**Eligibility**")
                    ee1, ee2, ee3, ee4 = st.columns(4)
                    ep_min_age  = ee1.number_input("Min Age",  0,  99,
                        int(_ep_data.get("min_age") or 18))
                    ep_max_age  = ee2.number_input("Max Age",  1, 100,
                        int(_ep_data.get("max_age") or 65))
                    ep_min_face = ee3.number_input("Min Face ($)", 0, 10_000_000,
                        int(_ep_data.get("min_face_amount") or _ep_data.get("min_face", 50_000)),
                        step=10_000)
                    ep_max_face = ee4.number_input("Max Face ($)", 0, 50_000_000,
                        int(_ep_data.get("max_face_amount") or _ep_data.get("max_face", 2_000_000)),
                        step=100_000)

                    st.divider()

                    # ── Terms ─────────────────────────────────────────────
                    st.markdown("**Term Configuration**")
                    st.caption(
                        "Enter comma-separated years. **Available Terms** is the general list shown in the workbench. "
                        "Use **Benefit Term** and **Premium Term** separately when they differ "
                        "(e.g. 30-year benefit period with 20-year premium payment term)."
                    )
                    et1, et2 = st.columns(2)
                    ep_terms_str = et1.text_input(
                        "Available Terms (years, comma-separated)",
                        value=_parse_terms(_ep_data.get("available_terms") or _ep_data.get("terms")),
                        placeholder="10,20,30 — leave blank for permanent",
                        help="General policy terms shown in the workbench dropdown.")
                    # Guard: if exam_required value not in list (e.g. legacy "GUARANTEED_ISSUE"), default to NONE
                    _exam_val = _ep_data.get("exam_required", "NONE")
                    if _exam_val not in _exam_opts:
                        _exam_val = "NONE"
                    ep_exam = et2.selectbox("Exam Required", _exam_opts,
                        index=_exam_opts.index(_exam_val))

                    et3, et4 = st.columns(2)
                    ep_benefit_terms = et3.text_input(
                        "🛡️ Benefit Term(s) — years coverage is paid out",
                        value=_parse_terms(_ep_data.get("benefit_terms","")),
                        placeholder="e.g. 20,30 — leave blank if same as Available Terms",
                        help=(
                            "The period during which the death benefit is payable. "
                            "For most term products this equals the policy term. "
                            "For limited-pay products it may differ from the premium term."
                        )
                    )
                    ep_premium_terms = et4.text_input(
                        "💰 Premium Term(s) — years premiums are paid",
                        value=_parse_terms(_ep_data.get("premium_terms","")),
                        placeholder="e.g. 10,20 — leave blank if same as Benefit Term",
                        help=(
                            "The period during which premiums are collected. "
                            "For a 10-pay whole life product, premium term = 10 but benefit term = lifetime. "
                            "Leave blank if premiums and benefits run for the same period."
                        )
                    )

                    st.divider()

                    # ── Financial Limits ──────────────────────────────────
                    st.markdown("**Financial Limits**")
                    ef1, ef2, ef3 = st.columns(3)
                    ep_nle    = ef1.number_input("Non-Medical Limit ($)", 0, 5_000_000,
                        int(_ep_data.get("non_medical_limit") or 500_000), step=50_000)
                    ep_rein   = ef2.number_input("Reinsurance Threshold ($)", 0, 50_000_000,
                        int(_ep_data.get("reinsurance_threshold") or 5_000_000), step=500_000)
                    ep_maxage = ef3.number_input("Max Issue Age", 1, 100,
                        int(_ep_data.get("max_issue_age") or 65))

                    st.divider()

                    # ── Thresholds ────────────────────────────────────────
                    st.markdown("**Decision Thresholds**")
                    eth1, eth2, eth3 = st.columns(3)
                    ep_stp     = eth1.number_input("STP Threshold",     0,  200,
                        int(_ep_data.get("stp_threshold") or 50))
                    ep_refer   = eth2.number_input("Refer Threshold",   0,  400,
                        int(_ep_data.get("refer_threshold") or 150))
                    ep_decline = eth3.number_input("Decline Threshold", 50, 1000,
                        int(_ep_data.get("decline_threshold") or 300))

                    st.divider()

                    # ── Validity ──────────────────────────────────────────
                    st.markdown("**Product Validity**")
                    ev1, ev2, ev3 = st.columns(3)
                    ep_eff = ev1.date_input("Effective Date",
                        value=_pd(_ep_data.get("effective_date")) or _date.today())
                    ep_exp = ev2.date_input("Expire Date",
                        value=_pd(_ep_data.get("expire_date")),
                        help="Leave blank for open-ended")
                    ep_active = ev3.checkbox("Product Active",
                        value=bool(_ep_data.get("is_active", True)))

                    st.divider()

                    # ── Additional Settings ───────────────────────────────
                    st.markdown("**Additional Settings**")
                    es1, es2 = st.columns(2)
                    ep_is_gi    = es1.checkbox("Guaranteed Issue",
                        value=bool(_ep_data.get("is_guaranteed_issue", False)))
                    ep_is_grp   = es2.checkbox("Group Product",
                        value=bool(_ep_data.get("is_group_product", False)))
                    ep_desc  = st.text_area("Product Description",
                        value=_ep_data.get("description",""), height=80)
                    ep_notes = st.text_area("UW Notes / Exam Notes",
                        value=_ep_data.get("uw_notes",""), height=60)

                    st.divider()

                    # ── Submit ────────────────────────────────────────────
                    _sc1, _sc2 = st.columns(2)
                    _submitted = _sc1.form_submit_button(
                        "💾 Save Changes", use_container_width=True, type="primary")
                    _sc2.form_submit_button(
                        "↩️ Cancel", use_container_width=True)

                    if _submitted:
                        _errs = []
                        if not ep_name.strip():
                            _errs.append("Product Name is required")
                        if ep_min_age >= ep_max_age:
                            _errs.append("Min Age must be less than Max Age")
                        if ep_min_face >= ep_max_face:
                            _errs.append("Min Face must be less than Max Face")
                        if ep_stp >= ep_refer or ep_refer >= ep_decline:
                            _errs.append("Thresholds must satisfy: STP < Refer < Decline")
                        if ep_exp and ep_exp <= ep_eff:
                            _errs.append("Expire Date must be after Effective Date")

                        def _parse_terms_list(s):
                            if not s.strip():
                                return None
                            try:
                                return [int(t.strip()) for t in s.split(",") if t.strip()]
                            except ValueError:
                                return "ERROR"

                        _terms_list   = _parse_terms_list(ep_terms_str)
                        _benefit_list = _parse_terms_list(ep_benefit_terms)
                        _premium_list = _parse_terms_list(ep_premium_terms)

                        if _terms_list   == "ERROR": _errs.append("Available Terms must be comma-separated integers e.g. 10,20,30")
                        if _benefit_list == "ERROR": _errs.append("Benefit Terms must be comma-separated integers e.g. 20,30")
                        if _premium_list == "ERROR": _errs.append("Premium Terms must be comma-separated integers e.g. 10,20")

                        if _errs:
                            for _e in _errs:
                                st.error(f"❌ {_e}")
                        else:
                            _payload = {
                                "product_name":          ep_name.strip(),
                                "product_type":          ep_type,
                                "category":              ep_cat,
                                "uw_method":             ep_uw,
                                "min_age":               ep_min_age,
                                "max_age":               ep_max_age,
                                "min_face_amount":       ep_min_face,
                                "max_face_amount":       ep_max_face,
                                "available_terms":       _terms_list,
                                "benefit_terms":         _benefit_list,
                                "premium_terms":         _premium_list,
                                "exam_required":         ep_exam,
                                "non_medical_limit":     ep_nle,
                                "reinsurance_threshold": ep_rein,
                                "max_issue_age":         ep_maxage,
                                "stp_threshold":         ep_stp,
                                "refer_threshold":       ep_refer,
                                "decline_threshold":     ep_decline,
                                "is_guaranteed_issue":   ep_is_gi,
                                "is_group_product":      ep_is_grp,
                                "description":           ep_desc.strip() or None,
                                "uw_notes":              ep_notes.strip() or None,
                                "effective_date":        str(ep_eff) if ep_eff else None,
                                "expire_date":           str(ep_exp) if ep_exp else None,
                                "is_active":             ep_active,
                            }

                            _saved = False
                            # 1. Try API PATCH/PUT
                            for _method, _ep in [("PATCH", f"/products/{selected}"),
                                                  ("PUT",   f"/products/{selected}")]:
                                try:
                                    _resp = requests.request(
                                        _method, f"{API_BASE}{_ep}",
                                        headers=hdr, json=_payload, timeout=10)
                                    if _resp.status_code in (200, 204):
                                        _saved = True
                                        break
                                except Exception as _exc:
                                    logger.debug(f"[edit_product] {_method} failed", exc_info=_exc)

                            # 2. Fallback: direct DB UPDATE
                            if not _saved:
                                try:
                                    _uc = _get_db_conn()
                                    if _uc:
                                        _ucu = _uc.cursor()
                                        _ucu.execute("""
                                            UPDATE products SET
                                                product_name          = %s,
                                                product_type          = %s,
                                                category              = %s,
                                                uw_method             = %s,
                                                min_age               = %s,
                                                max_age               = %s,
                                                min_face_amount       = %s,
                                                max_face_amount       = %s,
                                                available_terms       = %s,
                                                benefit_terms         = %s,
                                                premium_terms         = %s,
                                                exam_required         = %s,
                                                non_medical_limit     = %s,
                                                reinsurance_threshold = %s,
                                                max_issue_age         = %s,
                                                stp_threshold         = %s,
                                                refer_threshold       = %s,
                                                decline_threshold     = %s,
                                                is_guaranteed_issue   = %s,
                                                is_group_product      = %s,
                                                description           = %s,
                                                uw_notes              = %s,
                                                effective_date        = %s,
                                                expire_date           = %s,
                                                is_active             = %s,
                                                updated_at            = NOW()
                                            WHERE product_code = %s
                                        """, (
                                            ep_name.strip(), ep_type, ep_cat, ep_uw,
                                            ep_min_age, ep_max_age, ep_min_face, ep_max_face,
                                            _terms_list, _benefit_list, _premium_list,
                                            ep_exam, ep_nle, ep_rein, ep_maxage,
                                            ep_stp, ep_refer, ep_decline,
                                            ep_is_gi, ep_is_grp,
                                            ep_desc.strip() or None,
                                            ep_notes.strip() or None,
                                            str(ep_eff) if ep_eff else None,
                                            str(ep_exp) if ep_exp else None,
                                            ep_active, selected
                                        ))
                                        _ucu.close(); _release_db_conn(_uc)
                                        _saved = True
                                except Exception as _exc:
                                    logger.warning("[edit_product] DB UPDATE failed", exc_info=_exc)
                                    st.error(f"❌ DB update failed: {_exc}")

                            if _saved:
                                # Clear all caches so changes reflect immediately
                                for _ck in ["_products_cache", "all_products_merged",
                                            "pc_products_cache", "pc_rules_data",
                                            "pc_thresh_data", f"pc_bt_data_{selected}"]:
                                    st.session_state.pop(_ck, None)
                                st.success(
                                    f"✅ Product **{selected}** updated successfully! "
                                    f"Changes are live — refresh the product selector to confirm."
                                )
                                if _benefit_list and _premium_list and _benefit_list != _premium_list:
                                    st.info(
                                        f"📋 Benefit terms **{_benefit_list}** yrs "
                                        f"| Premium terms **{_premium_list}** yrs — "
                                        f"different benefit/premium periods saved."
                                    )
                                st.rerun()
                            else:
                                st.error("❌ Could not save changes via API or DB. Check your connection.")

    # ══════════════════════════════════════════════════════════
    # TAB 5 — ADD NEW PRODUCT
    # ══════════════════════════════════════════════════════════
    with tab_add:
        st.markdown("#### ➕ Register New Product")
        st.caption("Define a new underwriting product. It will appear in the product selector and Workbench immediately.")

        with st.form("add_product_form", clear_on_submit=False):
            st.markdown("**Product Identity**")
            ap1, ap2 = st.columns(2)
            np_code = ap1.text_input("Product Code *",
                placeholder="e.g. IND-TERM-15",
                help="Unique uppercase code. Use IND- prefix for individual, GRP- for group.")
            np_name = ap2.text_input("Product Name *",
                placeholder="e.g. Term 15 Year")

            ap3, ap4 = st.columns(2)
            np_type = ap3.selectbox("Product Type *", [
                "INDIVIDUAL_TERM", "INDIVIDUAL_UL", "INDIVIDUAL_WL",
                "INDIVIDUAL_FE", "GROUP_TERM", "GROUP_SUPP", "KEY_PERSON"
            ])
            np_uw_method = ap4.selectbox("UW Method *", [
                "FULL_UW", "SIMPLIFIED", "GUARANTEED_ISSUE", "ACCELERATED"
            ])

            ap5, ap6 = st.columns(2)
            np_category = ap5.selectbox(
                "Product Category *",
                ["Individual Life", "Group Life", "Final Expense", "Key Person", "Other"],
                help="This controls which category the product appears under in the Workbench dropdown.",
                index=0
            )
            # Auto-suggest category based on product type
            _type_cat_map = {
                "INDIVIDUAL_TERM": "Individual Life", "INDIVIDUAL_UL": "Individual Life",
                "INDIVIDUAL_WL": "Individual Life", "INDIVIDUAL_FE": "Final Expense",
                "GROUP_TERM": "Group Life", "GROUP_SUPP": "Group Life",
                "KEY_PERSON": "Key Person",
            }
            ap6.caption(f"💡 Suggested for **{np_type}**: **{_type_cat_map.get(np_type, 'Individual Life')}**")

            st.markdown("**Eligibility**")
            ep1, ep2, ep3, ep4 = st.columns(4)
            np_min_age  = ep1.number_input("Min Age",  0,  99, 18)
            np_max_age  = ep2.number_input("Max Age",  1, 100, 65)
            np_min_face = ep3.number_input("Min Face Amount ($)", 0, 10_000_000, 50_000, step=10_000)
            np_max_face = ep4.number_input("Max Face Amount ($)", 0, 50_000_000, 2_000_000, step=100_000)

            st.markdown("**Term & Exam**")
            tp1, tp2 = st.columns(2)
            np_terms_str = tp1.text_input("Available Terms (years, comma-separated)",
                placeholder="10,20,30  — leave blank for permanent",
                help="e.g. '10,20,30' for term products. Leave blank for UL/WL/FE.")
            np_exam = tp2.selectbox("Exam Required", ["NONE","PARAMEDICAL","FULL_MEDICAL","ATTENDING_PHYSICIAN"])

            st.markdown("**Financial Limits**")
            fp1, fp2, fp3 = st.columns(3)
            np_nle_limit  = fp1.number_input("Non-Medical Limit ($)", 0, 5_000_000, 500_000, step=50_000,
                help="Max face amount for non-medical underwriting")
            np_rein_limit = fp2.number_input("Reinsurance Threshold ($)", 0, 50_000_000, 5_000_000, step=500_000,
                help="Face amount above which reinsurance is required")
            np_max_issue_age = fp3.number_input("Max Issue Age", 1, 100, 65,
                help="Maximum age at policy issue")

            st.markdown("**Default Thresholds**")
            th1, th2, th3 = st.columns(3)
            np_stp      = th1.number_input("STP Threshold",     0,  200,  50)
            np_refer    = th2.number_input("Refer Threshold",   0,  400, 150)
            np_decline  = th3.number_input("Decline Threshold", 50, 1000, 300)

            st.markdown("**📅 Product Validity**")
            vp1, vp2 = st.columns(2)
            np_eff = vp1.date_input("Effective Date",
                value=_date.today(),
                help="Date this product becomes available for new applications")
            np_exp = vp2.date_input("Expire Date",
                value=None,
                help="Date this product is retired — leave blank for open-ended")

            st.markdown("**Additional Settings**")
            sp1, sp2 = st.columns(2)
            np_is_gi    = sp1.checkbox("Guaranteed Issue (no medical UW)")
            np_is_group = sp2.checkbox("Group Product")
            np_desc     = st.text_area("Product Description",
                placeholder="Brief description for underwriters and system documentation",
                height=80)
            np_notes    = st.text_area("UW Notes / Exam Notes",
                placeholder="e.g. Exam required above $1M. Reinsurer: XYZ Re.",
                height=60)

            st.divider()
            if st.form_submit_button("➕ Create Product", use_container_width=True, type="primary"):
                errs = []
                if not np_code.strip():  errs.append("Product Code is required")
                if not np_name.strip():  errs.append("Product Name is required")
                if np_min_age >= np_max_age: errs.append("Min Age must be less than Max Age")
                if np_min_face >= np_max_face: errs.append("Min Face must be less than Max Face")
                if np_stp >= np_refer or np_refer >= np_decline:
                    errs.append("Thresholds must satisfy: STP < Refer < Decline")
                if np_exp and np_exp <= np_eff:
                    errs.append("Expire Date must be after Effective Date")
                if errs:
                    for e in errs: st.error(f"❌ {e}")
                else:
                    # Parse terms
                    terms_list = None
                    if np_terms_str.strip():
                        try:
                            terms_list = [int(t.strip()) for t in np_terms_str.split(",") if t.strip()]
                        except ValueError:
                            st.error("❌ Terms must be comma-separated integers e.g. 10,20,30")
                            st.stop()

                    payload = {
                        "product_code":     np_code.strip().upper(),
                        "product_name":     np_name.strip(),
                        "product_type":     np_type,
                        "category":         np_category,
                        "uw_method":        np_uw_method,
                        "min_age":          np_min_age,
                        "max_age":          np_max_age,
                        "min_face_amount":  np_min_face,
                        "max_face_amount":  np_max_face,
                        "available_terms":  terms_list,
                        "exam_required":    np_exam,
                        "non_medical_limit":    np_nle_limit,
                        "reinsurance_threshold": np_rein_limit,
                        "max_issue_age":    np_max_issue_age,
                        "stp_threshold":    np_stp,
                        "refer_threshold":  np_refer,
                        "decline_threshold":np_decline,
                        "is_guaranteed_issue": np_is_gi,
                        "is_group_product": np_is_group,
                        "description":      np_desc.strip() or None,
                        "uw_notes":         np_notes.strip() or None,
                        "effective_date":   str(np_eff) if np_eff else None,
                        "expire_date":      str(np_exp) if np_exp else None,
                        "is_active":        True,
                    }
                    # category column is ensured by migrations/001_initial_schema.sql
                    try:
                        resp = requests.post(f"{API_BASE}/products", headers=hdr, json=payload, timeout=10)
                        if resp.status_code in (200, 201):
                            r = resp.json()
                            created_code = r.get("product_code", np_code.strip().upper())
                            eff_note = f" | Effective: {np_eff}" if np_eff else ""
                            exp_note = f" | Expires: {np_exp}" if np_exp else ""
                            st.success(
                                f"✅ Product **{created_code}** — *{np_name.strip()}* created successfully!{eff_note}{exp_note}"
                            )
                            st.info("Refresh the product selector to see the new product. You can now configure its rules and thresholds.")
                            # Update category in DB directly (API may not support it yet)
                            # Update category via pool connection
                            try:
                                _c5 = _get_db_conn()
                                if _c5:
                                    _cu5 = _c5.cursor()
                                    _cu5.execute(
                                        "UPDATE products SET category = %s WHERE product_code = %s",
                                        (np_category, np_code.strip().upper())
                                    )
                                    _cu5.close()
                                    _release_db_conn(_c5)
                            except Exception as _exc:
                                logger.debug("[_pd] Failed to update product category in DB", exc_info=_exc)
                            st.session_state.pop("_products_cache", None)
                            st.session_state.pop("all_products_merged", None)
                            st.session_state.pop("pc_products_cache", None)
                        elif resp.status_code == 409:
                            st.error(f"❌ Product code **{np_code.strip().upper()}** already exists.")
                        else:
                            try:
                                st.error(f"❌ {resp.json().get('detail', resp.text[:300])}")
                            except Exception as _exc:
                                logger.debug("[_pd] Suppressed exception", exc_info=_exc)
                                st.error(f"❌ Failed: {resp.text[:300]}")
                    except Exception as ex:
                        st.warning(f"⚠️ API call failed ({ex}). Product creation requires the POST /api/v1/products endpoint.")

        st.divider()
        st.markdown("**Existing Products**")
        if st.button("🔄 Refresh product list", key="pc_refresh_list"):
            st.session_state.pop("_products_cache", None)
            st.session_state.pop("pc_products_cache", None)
            st.session_state.pop("pc_product_select", None)
        try:
            prod_r = requests.get(f"{API_BASE}/products", headers=hdr, timeout=5)
            if prod_r.status_code == 200:
                all_prods = prod_r.json().get("products", [])
                if all_prods:
                    df_p = pd.DataFrame([{
                        "Code":      p.get("product_code","—"),
                        "Name":      p.get("product_name","—"),
                        "Type":      p.get("product_type","—"),
                        "UW Method": p.get("uw_method","—"),
                        "Active":    "✅" if p.get("is_active", True) else "🔴",
                        "Min Age":   p.get("min_age","—"),
                        "Max Age":   p.get("max_age","—"),
                        "Min Face":  f"{get_currency_symbol()}{p.get('min_face_amount',0):,.0f}",
                        "Max Face":  f"{get_currency_symbol()}{p.get('max_face_amount',0):,.0f}",
                        "Effective": str(p.get("effective_date",""))[:10] if p.get("effective_date") else "—",
                        "Expires":   str(p.get("expire_date",""))[:10]    if p.get("expire_date")    else "Never",
                    } for p in all_prods])
                    st.dataframe(df_p, use_container_width=True, hide_index=True)
                else:
                    st.info("No products returned from API.")
            else:
                st.caption("Product list API unavailable — using built-in product definitions.")
                df_fallback = pd.DataFrame([
                    {"Code": k, "Name": v, "Effective": "—", "Expires": "Never"}
                    for k, v in products.items()
                ])
                st.dataframe(df_fallback, use_container_width=True, hide_index=True)
        except Exception as _exc:
            logger.debug("[_pd] Suppressed exception", exc_info=_exc)
            st.caption("Could not load product list.")


def fetch_active_letter_template(outcome: str) -> dict | None:
    """
    Fetch the active letter_template for the current outcome.
    Tries API first, then falls back to DB letter_templates table.
    """
    hdr = {}
    if st.session_state.get("token"):
        hdr["Authorization"] = f"Bearer {st.session_state.token}"

    # 1. Try API
    try:
        resp = requests.get(
            f"{API_BASE}/letter-templates/active",
            params={"outcome": outcome},
            headers=hdr,
            timeout=4,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict) and data.get("id"):
                return data
    except Exception as _exc:
        logger.debug("[fetch_active_letter_template] Suppressed exception", exc_info=_exc)

    # 2. Fallback: DB letter_templates table
    try:
        conn = _get_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, template_name, outcome, is_active, version,
                       header_company_name, header_tagline,
                       contact_email, contact_phone,
                       body_text, next_steps, footer_text
                FROM letter_templates
                WHERE outcome = %s AND is_active = TRUE
                ORDER BY version DESC LIMIT 1
            """, (outcome,))
            row = cur.fetchone()
            cur.close(); _release_db_conn(conn)
            if row:
                import json as _j
                return {
                    "id": str(row[0]), "template_name": row[1],
                    "outcome": row[2], "is_active": row[3], "version": row[4],
                    "header_company_name": row[5] or "",
                    "header_tagline": row[6] or "",
                    "contact_email": row[7] or "",
                    "contact_phone": row[8] or "",
                    "body_text": row[9] or "",
                    "next_steps": _j.loads(row[10]) if row[10] else [],
                    "footer_text": row[11] or "",
                }
    except Exception as _exc:
        logger.debug("[fetch_active_letter_template] Suppressed exception", exc_info=_exc)
    return None



# ══════════════════════════════════════════════════════════════
#  API KEYS CONFIGURATION
# ══════════════════════════════════════════════════════════════

def render_api_keys_config():
    """API Keys management — Anthropic, future integrations."""
    st.markdown("### 🔑 API Keys & Integrations")
    st.caption("Manage external API keys. Keys are stored in session and used for AI-powered features.")

    # ── Anthropic API Key ─────────────────────────────────────
    st.markdown("#### 🤖 Anthropic Claude API")
    st.markdown("""
    <div style='background:#0f172a;border:1px solid #1e3a5f;border-radius:8px;
                padding:0.9rem 1.1rem;margin-bottom:1rem;'>
      <div style='color:#60a5fa;font-size:0.82rem;font-weight:600;'>What this enables</div>
      <div style='color:#94a3b8;font-size:0.8rem;margin-top:0.4rem;'>
        • APS Document Abstraction — extract diagnoses, medications, labs from physician reports<br>
        • Underwriter Copilot — AI-suggested debit points with reasoning<br>
        • Case summarisation — one-click case narrative generation
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])
    current_key = st.session_state.get("anthropic_api_key", "")
    display_key = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 12 else ""

    with col1:
        new_key = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-api03-...",
            help="Get your API key from console.anthropic.com",
            value=""
        )
    with col2:
        st.markdown("<div style='margin-top:1.75rem;'></div>", unsafe_allow_html=True)
        save_btn = st.button("💾 Save Key", use_container_width=True, type="primary")

    if save_btn:
        if new_key.strip():
            if new_key.strip().startswith("sk-ant-"):
                st.session_state["anthropic_api_key"] = new_key.strip()
                st.success("✅ Anthropic API key saved for this session.")
            else:
                st.error("❌ Invalid key format. Anthropic keys start with sk-ant-")
        else:
            st.error("Please enter an API key.")

    if current_key:
        st.markdown(f"""
        <div style='background:#064e3b;border:1px solid #10b981;border-radius:6px;
                    padding:0.5rem 0.8rem;font-size:0.8rem;color:#6ee7b7;display:inline-block;'>
          ✅ Active key: <code style='color:#a7f3d0;'>{display_key}</code>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🗑️ Remove Key", type="secondary"):
            st.session_state["anthropic_api_key"] = ""
            st.rerun()

    st.divider()

    # ── Test Connection ───────────────────────────────────────
    st.markdown("#### 🧪 Test Connection")
    if st.button("Test Anthropic API", use_container_width=False):
        api_key = st.session_state.get("anthropic_api_key", "")
        if not api_key:
            st.warning("⚠️ No API key configured above.")
        else:
            with st.spinner("Testing connection..."):
                try:
                    import requests as _req
                    resp = _req.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json"
                        },
                        json={
                            "model": "claude-sonnet-4-20250514",
                            "max_tokens": 50,
                            "messages": [{"role": "user", "content": "Reply with: API connection successful"}]
                        },
                        timeout=15
                    )
                    if resp.status_code == 200:
                        st.success("✅ Anthropic API connected successfully!")
                    else:
                        st.error(f"❌ API returned {resp.status_code}: {resp.json().get('error', {}).get('message', resp.text[:100])}")
                except Exception as e:
                    st.error(f"❌ Connection failed: {e}")

    st.divider()

    # ── Email (SMTP) — Decision Letters ──────────────────────
    st.markdown("#### 📧 Email (SMTP) — Decision Letters")
    st.caption(
        "Configure SMTP to automatically email decision letters to applicants "
        "when a UW decision is recorded. Works with Gmail, Outlook, SendGrid, AWS SES."
    )
    _smtp = _get_smtp_config()
    with st.form("smtp_config_form"):
        _s1, _s2 = st.columns(2)
        smtp_host = _s1.text_input("SMTP Host *", value=_smtp.get("host",""),
            placeholder="smtp.gmail.com",
            help="Gmail: smtp.gmail.com | Outlook: smtp.office365.com | SendGrid: smtp.sendgrid.net")
        smtp_port = _s2.number_input("Port", value=int(_smtp.get("port",587)),
            min_value=1, max_value=65535,
            help="587=STARTTLS (recommended) | 465=SSL | 25=unencrypted")
        _s3, _s4 = st.columns(2)
        smtp_user = _s3.text_input("Username", value=_smtp.get("username",""),
            placeholder="your@email.com",
            help="For SendGrid use 'apikey' as the username.")
        smtp_pass = _s4.text_input("Password / App Password", type="password",
            help="For Gmail use an App Password. For SendGrid use your API key.")
        _s5, _s6 = st.columns(2)
        smtp_from = _s5.text_input("From Email *", value=_smtp.get("from_email",""),
            placeholder="noreply@yourcarrier.com")
        smtp_name = _s6.text_input("From Name",
            value=_smtp.get("from_name","UW Platform"),
            placeholder="Acme Life Insurance")
        smtp_tls = st.checkbox("Use STARTTLS (recommended)",
            value=_smtp.get("use_tls","true")=="true",
            help="Port 587 STARTTLS. Uncheck only for SSL/TLS on port 465.")
        _btn1, _btn2 = st.columns(2)
        _save_smtp_btn = _btn1.form_submit_button("💾 Save SMTP Settings",
            use_container_width=True, type="primary")
        _test_smtp_btn = _btn2.form_submit_button("🧪 Test Connection",
            use_container_width=True)
        if _save_smtp_btn:
            if not smtp_host.strip() or not smtp_from.strip():
                st.error("SMTP Host and From Email are required.")
            else:
                _save_smtp_config({
                    "host": smtp_host.strip(), "port": str(smtp_port),
                    "username": smtp_user.strip(), "password": smtp_pass.strip(),
                    "from_email": smtp_from.strip(), "from_name": smtp_name.strip(),
                    "use_tls": "true" if smtp_tls else "false",
                })
                st.success("✅ SMTP settings saved. Decision letters will be emailed automatically.")
        if _test_smtp_btn:
            if not smtp_host.strip():
                st.error("Enter SMTP Host first.")
            else:
                import smtplib as _sl
                try:
                    if smtp_tls:
                        _srv = _sl.SMTP(smtp_host.strip(), int(smtp_port), timeout=10)
                        _srv.starttls()
                    else:
                        _srv = _sl.SMTP_SSL(smtp_host.strip(), int(smtp_port), timeout=10)
                    if smtp_user.strip() and smtp_pass.strip():
                        _srv.login(smtp_user.strip(), smtp_pass.strip())
                    _srv.quit()
                    st.success("✅ SMTP connection successful.")
                except Exception as _se:
                    st.error(f"SMTP connection failed: {_se}")
    if _smtp.get("host"):
        st.markdown(
            f"<div style='background:#064e3b;border:1px solid #10b981;border-radius:6px;"
            f"padding:6px 12px;font-size:0.8rem;color:#6ee7b7;display:inline-block;'>"
            f"✅ SMTP configured: <b>{_smtp.get('host')}</b> port {_smtp.get('port')} "
            f"from <b>{_smtp.get('from_email')}</b></div>", unsafe_allow_html=True)
    else:
        st.info("SMTP not configured - decision letters will not be emailed automatically.")

    st.divider()
    st.markdown("#### 🔌 Other Integrations")
    cols = st.columns(2)
    for col, (icon, name, desc, status) in zip(cols, [
        ("☁️","AWS S3","Document storage","Not configured"),
        ("🔐","Okta SSO","Enterprise SSO","Not configured"),
    ]):
        col.markdown(f"""<div style='background:#1e2530;border:1px solid #2d3748;
            border-radius:8px;padding:0.8rem;text-align:center;'>
          <div style='font-size:1.4rem;'>{icon}</div>
          <div style='font-weight:600;color:#e2e8f0;font-size:0.85rem;'>{name}</div>
          <div style='color:#64748b;font-size:0.72rem;'>{desc}</div>
          <div style='color:#f59e0b;font-size:0.7rem;'>{status}</div>
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  APS ABSTRACTION ENGINE
# ══════════════════════════════════════════════════════════════

def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF — handles both structured and scanned PDFs."""
    text = ""

    # Try structured PDF first (pdfplumber)
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if len(text.strip()) > 100:
            return text
    except Exception as _exc:
        logger.debug("[_extract_text_from_pdf] Suppressed exception", exc_info=_exc)

    # Fallback: OCR for scanned PDFs (pytesseract + pdf2image)
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=200)
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
        return text
    except Exception as e:
        return f"[PDF extraction failed: {e}. Install pdfplumber and pytesseract for full support.]"


def _extract_aps_opensource(pdf_text: str) -> dict:
    """
    Rule-based APS extraction — no API key required.
    Uses regex pattern matching on common medical document structures.
    Less accurate than Claude but free and instant.
    """
    import re, json as _json

    text = pdf_text
    text_lower = text.lower()

    def find_value(patterns, text, default=""):
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return default

    def find_all(pattern, text):
        return [m.strip() for m in re.findall(pattern, text, re.IGNORECASE)]

    # ── Patient info ─────────────────────────────────────────
    name = find_value([
        r"patient(?:\s+name)?[:\s]+([A-Z][a-zA-Z\s,]{3,40})",
        r"name[:\s]+([A-Z][a-zA-Z\s,]{3,40})",
    ], text)

    dob = find_value([
        r"(?:date of birth|dob|d\.o\.b)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
        r"born[:\s]+(\w+ \d{1,2},?\s*\d{4})",
    ], text)

    height = find_value([
        r"height[:\s]+(\d{1,2}\s*(?:ft|')[\s\d]*(?:in|\")?)",
        r"ht[:\s]+(\d+\.?\d*\s*(?:cm|in))",
    ], text)

    weight = find_value([
        r"weight[:\s]+(\d{2,3}(?:\.\d)?\s*(?:lbs?|kg))",
        r"wt[:\s]+(\d{2,3}(?:\.\d)?\s*(?:lbs?|kg))",
    ], text)

    bmi = find_value([r"bmi[:\s]+(\d{2}\.?\d*)"], text)

    tobacco = "Unknown"
    if any(w in text_lower for w in ["non-smoker","non smoker","never smoked","tobacco: no","no tobacco"]):
        tobacco = "Non-tobacco"
    elif any(w in text_lower for w in ["smoker","cigarette","tobacco use: yes","chews tobacco","vapes"]):
        tobacco = "Tobacco user"

    alcohol = "Unknown"
    if any(w in text_lower for w in ["no alcohol","denies alcohol","non-drinker","alcohol: no"]):
        alcohol = "None reported"
    elif any(w in text_lower for w in ["occasional","social drinker","drinks per week","etoh"]):
        alcohol = "Social/occasional"
    elif any(w in text_lower for w in ["heavy drinker","alcohol abuse","alcoholism","etoh abuse"]):
        alcohol = "Heavy/abuse"

    # ── Diagnoses — look for ICD codes and common condition keywords ──
    diagnoses = []
    icd_matches = re.findall(
        r"([A-Z]\d{2}\.?\d{0,2})\s*[-:]+\s*([^\r\n]{5,80})", text
    )
    for icd, desc in icd_matches[:20]:
        diagnoses.append({
            "condition": desc.strip(),
            "icd_code": icd,
            "date_diagnosed": "",
            "status": "active",
            "severity": "unknown",
            "notes": "",
            "page_ref": ""
        })

    # Common conditions if no ICD codes found
    if not diagnoses:
        condition_map = {
            "diabetes": ("Diabetes Mellitus", "E11"),
            "hypertension": ("Hypertension", "I10"),
            "heart attack": ("Myocardial Infarction", "I21"),
            "mi ": ("Myocardial Infarction", "I21"),
            "angina": ("Angina Pectoris", "I20"),
            "copd": ("COPD", "J44"),
            "asthma": ("Asthma", "J45"),
            "cancer": ("Malignancy", "C80"),
            "stroke": ("Stroke/CVA", "I63"),
            "kidney": ("Kidney Disease", "N18"),
            "depression": ("Depression", "F32"),
            "anxiety": ("Anxiety Disorder", "F41"),
            "obesity": ("Obesity", "E66"),
            "cholesterol": ("Hyperlipidemia", "E78"),
            "atrial fibrillation": ("Atrial Fibrillation", "I48"),
            "sleep apnea": ("Sleep Apnea", "G47.3"),
        }
        for keyword, (name_c, icd_c) in condition_map.items():
            if keyword in text_lower:
                diagnoses.append({
                    "condition": name_c, "icd_code": icd_c,
                    "date_diagnosed": "", "status": "active",
                    "severity": "unknown", "notes": "Keyword detected in document",
                    "page_ref": ""
                })

    # ── Medications ──────────────────────────────────────────
    medications = []
    med_patterns = [
        r"(metformin|lisinopril|atorvastatin|amlodipine|metoprolol|losartan|"
        r"omeprazole|levothyroxine|aspirin|warfarin|insulin|glipizide|"
        r"hydrochlorothiazide|furosemide|sertraline|fluoxetine|gabapentin|"
        r"prednisone|albuterol|montelukast)\s+(\d+\s*mg)?",
    ]
    for p in med_patterns:
        for m in re.finditer(p, text_lower):
            dose_match = re.search(rf"{m.group(1)}\s+(\d+\.?\d*\s*mg)", text_lower)
            medications.append({
                "name": m.group(1).title(),
                "dose": dose_match.group(1) if dose_match else "",
                "frequency": "",
                "indication": "",
                "start_date": "",
                "page_ref": ""
            })

    # ── Lab values ───────────────────────────────────────────
    lab_values = []
    lab_map = [
        (r"(?:hba1c|a1c)[:\s]+(\d+\.?\d*)\s*%?",         "HbA1c", "%",     "<5.7",  7.0),
        (r"(?:total\s)?cholesterol[:\s]+(\d{3,})",         "Total Cholesterol", "mg/dL", "<200", 200),
        (r"hdl[:\s]+(\d{2,3})",                            "HDL",   "mg/dL", ">40",   40),
        (r"ldl[:\s]+(\d{2,3})",                            "LDL",   "mg/dL", "<100",  130),
        (r"triglycerides?[:\s]+(\d{2,3})",                 "Triglycerides", "mg/dL", "<150", 150),
        (r"(?:egfr|gfr)[:\s]+(\d{2,3})",                  "eGFR",  "mL/min","≥60",   60),
        (r"(?:creatinine)[:\s]+(\d+\.?\d*)",               "Creatinine", "mg/dL", "<1.2", 1.3),
        (r"(?:blood\s+glucose|fasting\s+glucose)[:\s]+(\d{2,3})", "Fasting Glucose", "mg/dL", "<100", 100),
        (r"(?:systolic|sbp)[:\s]+(\d{2,3})",               "Systolic BP", "mmHg", "<130", 130),
        (r"bmi[:\s]+(\d{2}\.?\d*)",                        "BMI",   "",      "18.5–24.9", 30),
    ]
    for pattern, test, unit, normal, threshold in lab_map:
        m = re.search(pattern, text_lower)
        if m:
            try:
                val = float(m.group(1))
                abnormal = val > threshold if test not in ("HDL","eGFR") else val < threshold
            except Exception as _exc:
                logger.debug("[find_all] Suppressed exception", exc_info=_exc)
                val = m.group(1)
                abnormal = False
            lab_values.append({
                "test": test, "value": str(val), "unit": unit,
                "date": "", "normal_range": normal,
                "abnormal": abnormal, "page_ref": ""
            })

    # ── Risk flags ───────────────────────────────────────────
    risk_flags = []
    flag_map = [
        (["cancer","malignancy","tumor","carcinoma","oncology"],
         "Malignancy detected", "high"),
        (["hiv","aids"],
         "HIV/AIDS — hard stop on most products", "high"),
        (["insulin dependent","insulin-dependent","type 1 diabetes","type i diabetes"],
         "Insulin-dependent diabetes", "high"),
        (["uncontrolled","poorly controlled"],
         "Poorly controlled chronic condition", "high"),
        (["hospitali","inpatient","icu"],
         "Recent hospitalisation noted", "medium"),
        (["depression","anxiety","psychiatric","mental health"],
         "Mental health history", "medium"),
        (["alcohol abuse","heavy drinker","etoh abuse"],
         "Alcohol abuse/dependence", "high"),
        (["obese","morbid obesity","bmi > 35","bmi >35","bmi: 3","bmi: 4"],
         "Obesity/elevated BMI", "medium"),
    ]
    for keywords, flag, severity in flag_map:
        if any(k in text_lower for k in keywords):
            risk_flags.append({"flag": flag, "severity": severity, "reasoning": "Keyword detected in document"})

    # ── Suggested debits (rule-based approximation) ──────────
    suggested_debits = []
    debit_map = [
        ("diabetes",           "Diabetes Mellitus",        75,  "Standard actuarial table"),
        ("type 1 diabetes",    "Type 1 Diabetes",          150, "Insulin-dependent, higher loading"),
        ("hypertension",       "Hypertension",             50,  "Standard BP loading"),
        ("heart attack",       "Myocardial Infarction",    125, "Post-MI loading"),
        ("stroke",             "Stroke/CVA",               100, "Cerebrovascular history"),
        ("copd",               "COPD",                     75,  "Respiratory impairment"),
        ("cancer",             "Malignancy",               200, "Active malignancy — likely decline"),
        ("kidney",             "Kidney Disease",           100, "CKD loading"),
        ("depression",         "Depression",               50,  "Mental health loading"),
        ("obesity",            "Obesity",                  50,  "Build table — elevated BMI"),
        ("atrial fibrillation","Atrial Fibrillation",      75,  "Cardiac arrhythmia loading"),
    ]
    for keyword, condition, debits, reasoning in debit_map:
        if keyword in text_lower:
            suggested_debits.append({
                "condition": condition,
                "debit_points": debits,
                "reasoning": reasoning,
                "confidence": "low"
            })

    confidence = "high" if icd_matches else ("medium" if diagnoses else "low")

    return {
        "patient_info": {
            "name": name, "dob": dob, "height": height, "weight": weight,
            "bmi": bmi, "tobacco_use": tobacco, "alcohol_use": alcohol
        },
        "diagnoses":        diagnoses,
        "medications":      medications,
        "lab_values":       lab_values,
        "surgical_history": [],
        "family_history":   [],
        "physician_notes":  "",
        "risk_flags":       risk_flags,
        "suggested_debits": suggested_debits,
        "extraction_confidence": confidence,
        "extraction_notes": (
            "⚠️ Extracted using open-source rule-based parser (no AI API key configured). "
            "Results are keyword/pattern based and may miss complex findings. "
            "Configure an Anthropic API key in System Config → API Keys for full AI-powered extraction."
        ),
        "_extraction_method": "opensource"
    }


def _call_claude_extraction(pdf_text: str, api_key: str, case_id: str = "") -> dict:
    """Call Claude API to extract structured medical data from APS text."""
    import requests as _req, json as _json

    prompt = f"""You are a medical data extraction specialist for life insurance underwriting.

Analyse the following Attending Physician Statement (APS) and extract ALL relevant medical information in structured JSON format.

APS DOCUMENT TEXT:
{pdf_text[:12000]}

Extract and return ONLY valid JSON with this exact structure:
{{
  "patient_info": {{
    "name": "",
    "dob": "",
    "height": "",
    "weight": "",
    "bmi": "",
    "tobacco_use": "",
    "alcohol_use": ""
  }},
  "diagnoses": [
    {{
      "condition": "",
      "icd_code": "",
      "date_diagnosed": "",
      "status": "active|resolved|controlled",
      "severity": "mild|moderate|severe",
      "notes": "",
      "page_ref": ""
    }}
  ],
  "medications": [
    {{
      "name": "",
      "dose": "",
      "frequency": "",
      "indication": "",
      "start_date": "",
      "page_ref": ""
    }}
  ],
  "lab_values": [
    {{
      "test": "",
      "value": "",
      "unit": "",
      "date": "",
      "normal_range": "",
      "abnormal": true,
      "page_ref": ""
    }}
  ],
  "surgical_history": [
    {{
      "procedure": "",
      "date": "",
      "outcome": "",
      "page_ref": ""
    }}
  ],
  "family_history": [
    {{
      "relation": "",
      "condition": "",
      "age_at_onset": "",
      "page_ref": ""
    }}
  ],
  "physician_notes": "",
  "risk_flags": [
    {{
      "flag": "",
      "severity": "low|medium|high",
      "reasoning": ""
    }}
  ],
  "suggested_debits": [
    {{
      "condition": "",
      "debit_points": 0,
      "reasoning": "",
      "confidence": "high|medium|low"
    }}
  ],
  "extraction_confidence": "high|medium|low",
  "extraction_notes": ""
}}

Rules:
- Extract ALL diagnoses found, even if mentioned briefly
- For debit points: use standard actuarial tables (diabetes +75-150, hypertension +25-75, etc.)
- Mark confidence as LOW if text is unclear or contradictory
- Include page_ref as best estimate (Page 1, Page 2, etc.) based on document position
- If a field is not found, use empty string or empty array
- Return ONLY the JSON object, no other text"""

    try:
        resp = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=60
        )

        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}: {resp.text[:200]}"}

        raw = resp.json()["content"][0]["text"]

        # Clean JSON fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[7:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]

        return _json.loads(raw.strip())

    except _json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}", "raw_response": raw[:500]}
    except Exception as e:
        return {"error": str(e)}


def render_aps_abstraction(case_id: str = ""):
    """Full APS AI Abstraction UI — upload, extract, review, confirm."""
    import json as _json

    st.markdown("### 🧠 APS AI Abstraction")
    st.caption("Upload an Attending Physician Statement PDF — Claude will extract all medical findings, suggest debit points, and flag risks.")

    api_key = st.session_state.get("anthropic_api_key", "")
    use_ai = bool(api_key)

    # Show mode indicator
    if use_ai:
        st.success("🤖 **AI Mode** — Using Claude (Anthropic API) for full medical extraction")
    else:
        st.warning(
            "🔍 **Basic Mode** — No Anthropic API key configured. "
            "Using open-source rule-based extraction (keyword matching). "
            "Results will be less accurate. "
            "Add your API key in **System Config → 🔑 API Keys** to enable AI extraction."
        )

    # ── Upload ────────────────────────────────────────────────
    st.markdown("#### 📎 Upload APS Document")
    c1, c2 = st.columns([3, 1])
    with c1:
        uploaded = st.file_uploader(
            "Upload APS PDF",
            type=["pdf"],
            help="Supports both structured PDFs and scanned documents (OCR)"
        )
    with c2:
        st.markdown("<div style='margin-top:0.5rem;'></div>", unsafe_allow_html=True)
        st.info("📄 PDF only\nMax 50MB\nScanned OK")

    if not uploaded:
        st.markdown("""
        <div style='background:#0f172a;border:1px dashed #334155;border-radius:10px;
                    padding:2rem;text-align:center;margin-top:1rem;'>
          <div style='font-size:2rem;'>📋</div>
          <div style='color:#64748b;font-size:0.85rem;margin-top:0.5rem;'>
            Upload an APS PDF to begin AI extraction
          </div>
          <div style='color:#475569;font-size:0.75rem;margin-top:0.4rem;'>
            Supports physician notes, lab reports, hospital discharge summaries
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Process ───────────────────────────────────────────────
    pdf_bytes = uploaded.read()
    doc_key   = f"aps_result_{uploaded.name}"

    col_a, col_b = st.columns([2, 1])
    col_a.success(f"✅ Uploaded: **{uploaded.name}** ({len(pdf_bytes)/1024:.0f} KB)")

    with col_b:
        extract_btn = st.button("🧠 Extract with AI", type="primary", use_container_width=True)

    if extract_btn:
        with st.status("Processing APS document...", expanded=True) as status:
            st.write("📄 Extracting text from PDF...")
            pdf_text = _extract_text_from_pdf(pdf_bytes)
            char_count = len(pdf_text.strip())
            st.write(f"✅ Extracted {char_count:,} characters from document")

            if char_count < 50:
                st.error("⚠️ Could not extract readable text. Ensure pdfplumber/pytesseract is installed.")
                status.update(label="Extraction failed", state="error")
                return

            if use_ai:
                st.write("🤖 Sending to Claude for AI medical analysis...")
                result = _call_claude_extraction(pdf_text, api_key, case_id)
            else:
                st.write("🔍 Running open-source rule-based extraction (no API key)...")
                result = _extract_aps_opensource(pdf_text)

            # Show which method was used
            method = result.pop("_extraction_method", "claude")
            if method == "opensource":
                st.warning(
                    "⚠️ **Basic extraction used** — Results are keyword/pattern based. "
                    "Confidence is lower than AI extraction. "
                    "Manually verify all findings before making underwriting decisions."
                )
            else:
                st.success("✅ **AI extraction complete** — Powered by Claude")

            if "error" in result:
                st.error(f"❌ Extraction failed: {result['error']}")
                status.update(label="Extraction failed", state="error")
                return

            st.session_state[doc_key] = result
            st.session_state[f"{doc_key}_text"] = pdf_text
            st.write("✅ Medical data extracted successfully")
            status.update(label="✅ Extraction complete!", state="complete")

    # ── Display Results ───────────────────────────────────────
    result = st.session_state.get(doc_key)
    if not result:
        return

    # Confidence badge
    conf = result.get("extraction_confidence", "medium")
    conf_color = {"high": "#10b981", "medium": "#f59e0b", "low": "#ef4444"}.get(conf, "#64748b")
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:1rem;margin:0.5rem 0 1rem 0;'>
      <span style='background:{conf_color}20;border:1px solid {conf_color};color:{conf_color};
                   padding:3px 12px;border-radius:20px;font-size:0.75rem;font-weight:600;'>
        Extraction Confidence: {conf.upper()}
      </span>
      <span style='color:#64748b;font-size:0.78rem;'>{result.get("extraction_notes","")}</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Risk Flags ────────────────────────────────────────────
    flags = result.get("risk_flags", [])
    if flags:
        st.markdown("#### 🚨 Risk Flags")
        for flag in flags:
            sev   = flag.get("severity", "low")
            color = {"high": "#ef4444", "medium": "#f59e0b", "low": "#10b981"}.get(sev, "#64748b")
            st.markdown(f"""
            <div style='background:{color}15;border-left:3px solid {color};
                        border-radius:0 6px 6px 0;padding:0.5rem 0.8rem;margin-bottom:0.4rem;'>
              <span style='color:{color};font-weight:600;font-size:0.82rem;'>{sev.upper()}</span>
              <span style='color:#e2e8f0;font-size:0.82rem;margin-left:0.5rem;'>{flag.get("flag","")}</span>
              <div style='color:#94a3b8;font-size:0.75rem;margin-top:0.2rem;'>{flag.get("reasoning","")}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Suggested Debits ──────────────────────────────────────
    debits = result.get("suggested_debits", [])
    if debits:
        st.markdown("#### 💯 Suggested Debit Points")
        total_debits = sum(d.get("debit_points", 0) for d in debits)
        st.markdown(f"**Total suggested debits: {total_debits} points**")

        for i, d in enumerate(debits):
            conf_d = d.get("confidence", "medium")
            conf_c = {"high": "#10b981", "medium": "#f59e0b", "low": "#ef4444"}.get(conf_d, "#64748b")
            col1, col2, col3 = st.columns([4, 1, 1])
            col1.markdown(f"""
            <div style='padding:0.4rem 0;'>
              <span style='color:#e2e8f0;font-size:0.85rem;font-weight:600;'>{d.get("condition","")}</span>
              <span style='color:{conf_c};font-size:0.72rem;margin-left:0.5rem;'>● {conf_d}</span>
              <div style='color:#94a3b8;font-size:0.75rem;'>{d.get("reasoning","")}</div>
            </div>
            """, unsafe_allow_html=True)
            col2.markdown(f"<div style='text-align:center;padding-top:0.5rem;'><span style='font-size:1.1rem;font-weight:700;color:#f59e0b;'>+{d.get('debit_points',0)}</span></div>", unsafe_allow_html=True)
            accept = col3.checkbox("Accept", value=True, key=f"debit_accept_{i}_{doc_key}")

    st.divider()

    # ── Extracted Findings Tabs ───────────────────────────────
    st.markdown("#### 📋 Extracted Medical Findings")
    r1, r2, r3, r4, r5 = st.tabs([
        "🩺 Diagnoses", "💊 Medications", "🧪 Lab Values",
        "🏥 Surgical History", "👨‍👩‍👧 Family History"
    ])

    with r1:
        diagnoses = result.get("diagnoses", [])
        if diagnoses:
            for dx in diagnoses:
                status_color = {"active": "#ef4444", "controlled": "#f59e0b", "resolved": "#10b981"}.get(
                    dx.get("status","").lower(), "#64748b")
                st.markdown(f"""
                <div style='background:#1e2530;border:1px solid #2d3748;border-radius:8px;
                            padding:0.7rem 1rem;margin-bottom:0.5rem;'>
                  <div style='display:flex;justify-content:space-between;align-items:center;'>
                    <span style='color:#e2e8f0;font-weight:600;'>{dx.get("condition","")}</span>
                    <span style='background:{status_color}20;color:{status_color};border:1px solid {status_color};
                                 padding:2px 8px;border-radius:12px;font-size:0.7rem;'>
                      {dx.get("status","").upper()}
                    </span>
                  </div>
                  <div style='color:#94a3b8;font-size:0.78rem;margin-top:0.3rem;'>
                    📅 {dx.get("date_diagnosed","Unknown date")} &nbsp;|&nbsp;
                    🏷️ {dx.get("icd_code","No ICD")} &nbsp;|&nbsp;
                    📄 {dx.get("page_ref","—")} &nbsp;|&nbsp;
                    ⚠️ {dx.get("severity","—").capitalize()}
                  </div>
                  {f'<div style="color:#64748b;font-size:0.75rem;margin-top:0.2rem;">{dx.get("notes","")}</div>' if dx.get("notes") else ""}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No diagnoses extracted.")

    with r2:
        meds = result.get("medications", [])
        if meds:
            for med in meds:
                st.markdown(f"""
                <div style='background:#1e2530;border:1px solid #2d3748;border-radius:8px;
                            padding:0.7rem 1rem;margin-bottom:0.5rem;'>
                  <span style='color:#60a5fa;font-weight:600;'>{med.get("name","")}</span>
                  <span style='color:#94a3b8;font-size:0.82rem;margin-left:0.5rem;'>
                    {med.get("dose","")} · {med.get("frequency","")}
                  </span>
                  <div style='color:#64748b;font-size:0.75rem;margin-top:0.2rem;'>
                    For: {med.get("indication","—")} &nbsp;|&nbsp;
                    Since: {med.get("start_date","—")} &nbsp;|&nbsp;
                    📄 {med.get("page_ref","—")}
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No medications extracted.")

    with r3:
        labs = result.get("lab_values", [])
        if labs:
            for lab in labs:
                abnormal = lab.get("abnormal", False)
                lab_color = "#ef4444" if abnormal else "#10b981"
                st.markdown(f"""
                <div style='background:#1e2530;border:1px solid {"#ef444440" if abnormal else "#2d3748"};
                            border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.5rem;'>
                  <div style='display:flex;justify-content:space-between;'>
                    <span style='color:#e2e8f0;font-weight:600;'>{lab.get("test","")}</span>
                    <span style='color:{lab_color};font-weight:700;'>
                      {lab.get("value","")} {lab.get("unit","")}
                      {"⚠️" if abnormal else "✓"}
                    </span>
                  </div>
                  <div style='color:#64748b;font-size:0.75rem;margin-top:0.2rem;'>
                    Normal: {lab.get("normal_range","—")} &nbsp;|&nbsp;
                    Date: {lab.get("date","—")} &nbsp;|&nbsp;
                    📄 {lab.get("page_ref","—")}
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No lab values extracted.")

    with r4:
        surgeries = result.get("surgical_history", [])
        if surgeries:
            for sx in surgeries:
                st.markdown(f"""
                <div style='background:#1e2530;border:1px solid #2d3748;border-radius:8px;
                            padding:0.7rem 1rem;margin-bottom:0.5rem;'>
                  <span style='color:#a78bfa;font-weight:600;'>{sx.get("procedure","")}</span>
                  <div style='color:#64748b;font-size:0.75rem;margin-top:0.2rem;'>
                    Date: {sx.get("date","—")} &nbsp;|&nbsp;
                    Outcome: {sx.get("outcome","—")} &nbsp;|&nbsp;
                    📄 {sx.get("page_ref","—")}
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No surgical history extracted.")

    with r5:
        family = result.get("family_history", [])
        if family:
            for fh in family:
                st.markdown(f"""
                <div style='background:#1e2530;border:1px solid #2d3748;border-radius:8px;
                            padding:0.7rem 1rem;margin-bottom:0.5rem;'>
                  <span style='color:#f9a8d4;font-weight:600;'>{fh.get("relation","").capitalize()}</span>
                  <span style='color:#e2e8f0;margin-left:0.5rem;'>{fh.get("condition","")}</span>
                  <div style='color:#64748b;font-size:0.75rem;margin-top:0.2rem;'>
                    Age at onset: {fh.get("age_at_onset","—")} &nbsp;|&nbsp;
                    📄 {fh.get("page_ref","—")}
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No family history extracted.")

    # ── Confirm & Apply to Case ───────────────────────────────
    st.divider()
    st.markdown("#### ✅ Confirm & Apply to Case")
    st.caption("Review all findings above, then confirm to apply accepted debits to this case.")

    col_note, col_btn = st.columns([3, 1])
    uw_note = col_note.text_area(
        "Underwriter notes on APS review",
        placeholder="e.g. APS reviewed. Diabetes well-controlled per physician. Accepted AI-suggested debits with modification.",
        height=80,
        key=f"uw_note_{doc_key}"
    )

    with col_btn:
        st.markdown("<div style='margin-top:1.6rem;'></div>", unsafe_allow_html=True)
        confirm_btn = st.button("✅ Confirm & Apply", type="primary", use_container_width=True)

    if confirm_btn:
        # Collect accepted debits
        accepted = []
        for i, d in enumerate(debits):
            if st.session_state.get(f"debit_accept_{i}_{doc_key}", True):
                accepted.append(d)

        total = sum(d.get("debit_points", 0) for d in accepted)

        # Store in session state for the case
        aps_summary = {
            "document": uploaded.name,
            "extracted_at": str(__import__("datetime").datetime.now()),
            "accepted_debits": accepted,
            "total_debits_applied": total,
            "diagnoses_count": len(result.get("diagnoses", [])),
            "medications_count": len(result.get("medications", [])),
            "risk_flags": flags,
            "uw_notes": uw_note,
            "extraction_confidence": conf,
        }
        st.session_state[f"aps_confirmed_{case_id}"] = aps_summary

        st.success(f"""
        ✅ **APS Review Confirmed**
        - {len(accepted)} debit items accepted
        - **{total} total debit points** applied to case
        - {len(result.get("diagnoses", []))} diagnoses · {len(result.get("medications", []))} medications recorded
        """)

        if uw_note:
            st.info(f"📝 UW Note saved: {uw_note[:80]}...")


def render_letter_templates():
    """Letter Template Manager - create, edit, activate templates per UW outcome."""
    import json as _json, uuid as _uuid

    st.markdown("## 📄 Letter Templates")
    st.caption(
        "Configure branded decision letter templates for each underwriting outcome. "
        "The active template for each outcome is used when generating PDF decision reports."
    )

    hdr = {}
    if st.session_state.get("token"):
        hdr["Authorization"] = f"Bearer {st.session_state.token}"

    OUTCOMES = [
        "APPROVED", "APPROVED_STANDARD", "APPROVED_RATED",
        "DECLINED", "POSTPONED", "REFERRED",
        "PENDING_REQUIREMENTS", "COUNTER_OFFER",
    ]

    # ── DB helpers ────────────────────────────────────────────────────────────
    def _ensure_lt_table():
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.close(); _release_db_conn(conn)
                return True
        except Exception as _exc:
            logger.warning("[_ensure_lt_table] Suppressed exception", exc_info=_exc)
        return False

    def _load_templates_db():
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, template_name, outcome, is_active, version,
                           header_company_name, header_tagline,
                           contact_email, contact_phone,
                           body_text, next_steps, footer_text,
                           created_at, updated_at
                    FROM letter_templates ORDER BY outcome, version DESC
                """)
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)
                return [{
                    "id": r[0], "template_name": r[1], "outcome": r[2],
                    "is_active": r[3], "version": r[4],
                    "header_company_name": r[5] or "",
                    "header_tagline": r[6] or "",
                    "contact_email": r[7] or "",
                    "contact_phone": r[8] or "",
                    "body_text": r[9] or "",
                    "next_steps": _json.loads(r[10]) if r[10] else [],
                    "footer_text": r[11] or "",
                    "created_at": str(r[12] or "")[:10],
                    "updated_at": str(r[13] or "")[:10],
                } for r in rows]
        except Exception as _exc:
            logger.debug("[_load_templates_db] Suppressed exception", exc_info=_exc)
        return []

    def _save_template_db(payload: dict, template_id: str = None) -> tuple:
        """Insert or update. Returns (success, id, message)."""
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                _ensure_lt_table()
                ns = _json.dumps(payload.get("next_steps", []))
                if template_id:
                    cur.execute("""
                        UPDATE letter_templates SET
                            template_name=%s, outcome=%s, is_active=%s,
                            version=version+1,
                            header_company_name=%s, header_tagline=%s,
                            contact_email=%s, contact_phone=%s,
                            body_text=%s, next_steps=%s, footer_text=%s,
                            updated_at=NOW()
                        WHERE id=%s
                    """, (
                        payload["template_name"], payload["outcome"],
                        payload["is_active"],
                        payload.get("header_company_name",""),
                        payload.get("header_tagline",""),
                        payload.get("contact_email",""),
                        payload.get("contact_phone",""),
                        payload.get("body_text",""), ns,
                        payload.get("footer_text",""),
                        template_id
                    ))
                    new_id = template_id
                else:
                    new_id = str(_uuid.uuid4())
                    cur.execute("""
                        INSERT INTO letter_templates
                            (id, template_name, outcome, is_active, version,
                             header_company_name, header_tagline,
                             contact_email, contact_phone,
                             body_text, next_steps, footer_text)
                        VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        new_id,
                        payload["template_name"], payload["outcome"],
                        payload["is_active"],
                        payload.get("header_company_name",""),
                        payload.get("header_tagline",""),
                        payload.get("contact_email",""),
                        payload.get("contact_phone",""),
                        payload.get("body_text",""), ns,
                        payload.get("footer_text",""),
                    ))
                # If set as active, deactivate others for this outcome
                if payload.get("is_active"):
                    cur.execute("""
                        UPDATE letter_templates SET is_active=FALSE
                        WHERE outcome=%s AND id != %s
                    """, (payload["outcome"], new_id))
                cur.close(); _release_db_conn(conn)
                return True, new_id, "Saved to database"
        except Exception as e:
            return False, None, str(e)
        return False, None, "DB unavailable"

    def _delete_template_db(template_id: str) -> bool:
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM letter_templates WHERE id=%s",
                            (template_id,))
                cur.close(); _release_db_conn(conn)
                return True
        except Exception as _exc:
            logger.warning("[_delete_template_db] Suppressed exception", exc_info=_exc)
        return False

    def _set_active_db(template_id: str, outcome: str):
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE letter_templates SET is_active=FALSE WHERE outcome=%s",
                    (outcome,))
                cur.execute(
                    "UPDATE letter_templates SET is_active=TRUE WHERE id=%s",
                    (template_id,))
                cur.close(); _release_db_conn(conn)
        except Exception as _exc:
            logger.warning("[_set_active_db] Suppressed exception", exc_info=_exc)

    # ── Load templates (API first, DB fallback) ───────────────────────────────
    _ensure_lt_table()
    templates = []
    api_ok = False
    try:
        resp = requests.get(f"{API_BASE}/letter-templates", headers=hdr, timeout=5)
        if resp.status_code == 200:
            templates = resp.json() if isinstance(resp.json(), list) else []
            api_ok = True
    except Exception as _exc:
        logger.warning("[_set_active_db] Suppressed exception", exc_info=_exc)

    if not api_ok:
        templates = _load_templates_db()
        if templates:
            st.success(
                f"✅ Loaded {len(templates)} template(s) from database "
                f"(API not available — all changes save directly to DB)."
            )
        else:
            st.info(
                "No templates yet. Create your first template in the "
                "**New Template** tab below."
            )

    tab_list, tab_edit, tab_new = st.tabs(
        ["📋  All Templates", "✏️  Edit Template", "➕  New Template"]
    )

    # ══════════════════════════════════════════════════════════════
    # TAB 1 — All Templates
    # ══════════════════════════════════════════════════════════════
    with tab_list:
        if not templates:
            st.info(
                "No templates found. Create your first template in the "
                "**New Template** tab."
            )
        else:
            # Summary metrics
            _active_count = sum(1 for t in templates if t.get("is_active"))
            _m1, _m2, _m3 = st.columns(3)
            _m1.metric("Total Templates", len(templates))
            _m2.metric("Active", _active_count)
            _m3.metric("Outcomes covered",
                       len(set(t.get("outcome","") for t in templates
                               if t.get("is_active"))))
            st.divider()

            # Group by outcome
            by_outcome: dict = {}
            for t in templates:
                by_outcome.setdefault(t.get("outcome","OTHER"), []).append(t)

            for outcome, tlist in sorted(by_outcome.items()):
                with st.expander(
                    f"**{outcome}** — {len(tlist)} template(s) "
                    f"{'✅ active' if any(t.get('is_active') for t in tlist) else '⚪ no active'}",
                    expanded=False
                ):
                    for t in tlist:
                        col_name, col_active, col_ver, col_btn1, col_btn2 = \
                            st.columns([3, 1, 1, 1, 1])
                        is_active = t.get("is_active", False)
                        col_name.markdown(
                            f"{'🟢 ' if is_active else '⚪ '}"
                            f"**{t.get('template_name','—')}**"
                        )
                        col_active.caption("Active" if is_active else "Inactive")
                        col_ver.caption(f"v{t.get('version', 1)}")

                        if col_btn1.button("✏️ Edit", key=f"sel_{t['id']}"):
                            st.session_state["lt_edit_id"] = t["id"]
                            st.session_state["lt_edit_data"] = t
                            st.rerun()

                        if not is_active:
                            if col_btn2.button(
                                "🟢 Set Active", key=f"act_{t['id']}"
                            ):
                                if api_ok:
                                    requests.patch(
                                        f"{API_BASE}/letter-templates/{t['id']}",
                                        json={"is_active": True},
                                        headers=hdr, timeout=5
                                    )
                                else:
                                    _set_active_db(t["id"], t.get("outcome",""))
                                st.rerun()
                        else:
                            col_btn2.markdown(
                                "<span style='color:#10b981;font-size:12px;"
                                "font-weight:600;'>✅ In use</span>",
                                unsafe_allow_html=True
                            )

    # ══════════════════════════════════════════════════════════════
    # TAB 2 — Edit Template
    # ══════════════════════════════════════════════════════════════
    with tab_edit:
        edit_data = st.session_state.get("lt_edit_data")
        if not edit_data:
            st.info("Select a template from **All Templates** and click ✏️ Edit.")
        else:
            st.markdown(
                f"**Editing:** `{edit_data.get('template_name')}` "
                f"(ID: `{edit_data.get('id','')[:8]}...`)"
            )
            st.markdown("---")
            e_name = st.text_input("Template Name *",
                                   value=edit_data.get("template_name",""),
                                   key="e_name")
            e_outcome = st.selectbox(
                "Outcome *", OUTCOMES,
                index=OUTCOMES.index(edit_data.get("outcome","APPROVED"))
                      if edit_data.get("outcome") in OUTCOMES else 0,
                key="e_outcome"
            )
            e_active = st.checkbox("Active (use for PDF reports)",
                                   value=edit_data.get("is_active", True),
                                   key="e_active")
            st.markdown("##### 🏢 Company Header")
            ec1, ec2 = st.columns(2)
            e_company = ec1.text_input("Company Name",
                value=edit_data.get("header_company_name",""), key="e_company")
            e_tagline = ec2.text_input("Tagline",
                value=edit_data.get("header_tagline",""), key="e_tagline")
            st.markdown("##### 📞 Contact")
            cc1, cc2 = st.columns(2)
            e_email = cc1.text_input("Contact Email",
                value=edit_data.get("contact_email",""), key="e_email")
            e_phone = cc2.text_input("Contact Phone",
                value=edit_data.get("contact_phone",""), key="e_phone")
            st.markdown("##### 📝 Letter Body")
            e_body = st.text_area("Body Text",
                value=edit_data.get("body_text",""), height=180, key="e_body",
                help="Placeholders: {applicant_name} {outcome} {risk_class} "
                     "{net_debits} {policy_effective_date} {approved_premium}")
            st.caption("Placeholders: `{applicant_name}` `{outcome}` `{risk_class}` "
                       "`{net_debits}` `{policy_effective_date}` `{approved_premium}`")
            st.markdown("##### 📋 Next Steps")
            ns_raw = edit_data.get("next_steps")
            default_ns = _json.dumps(ns_raw, indent=2) if ns_raw else \
                '[\n  "Review your policy documents",\n  "Contact your agent"\n]'
            e_next = st.text_area("Next Steps (JSON array)",
                value=default_ns, height=100, key="e_next")
            st.markdown("##### 📄 Footer")
            e_footer = st.text_area("Footer Text",
                value=edit_data.get("footer_text",""), height=70, key="e_footer")
            st.markdown("---")

            btn_save, btn_delete, btn_preview = st.columns([2, 1, 1])

            if btn_save.button("💾 Save Changes", use_container_width=True,
                               type="primary", key="e_save"):
                try:
                    ns_parsed = _json.loads(e_next)
                except Exception as _exc:
                    logger.debug("[_set_active_db] Suppressed exception", exc_info=_exc)
                    ns_parsed = []
                payload = {
                    "template_name": e_name, "outcome": e_outcome,
                    "is_active": e_active,
                    "header_company_name": e_company,
                    "header_tagline": e_tagline,
                    "contact_email": e_email, "contact_phone": e_phone,
                    "body_text": e_body, "next_steps": ns_parsed,
                    "footer_text": e_footer,
                }
                saved = False
                if api_ok:
                    try:
                        r2 = requests.put(
                            f"{API_BASE}/letter-templates/{edit_data['id']}",
                            json=payload, headers=hdr, timeout=5
                        )
                        if r2.status_code in (200, 204):
                            saved = True
                    except Exception as _exc:
                        logger.debug("[_set_active_db] Suppressed exception", exc_info=_exc)
                if not saved:
                    ok, _, msg = _save_template_db(payload, edit_data["id"])
                    if ok:
                        saved = True

                if saved:
                    st.success("✅ Template updated successfully!")
                    st.session_state.pop("lt_edit_data", None)
                    st.session_state.pop("lt_edit_id", None)
                    st.rerun()
                else:
                    st.error("Save failed — check DB connection.")

            if btn_delete.button("🗑️ Delete", use_container_width=True,
                                 key="e_del"):
                deleted = False
                if api_ok:
                    try:
                        rd = requests.delete(
                            f"{API_BASE}/letter-templates/{edit_data['id']}",
                            headers=hdr, timeout=5
                        )
                        deleted = rd.status_code in (200, 204)
                    except Exception as _exc:
                        logger.debug("[_set_active_db] Suppressed exception", exc_info=_exc)
                if not deleted:
                    deleted = _delete_template_db(edit_data["id"])
                if deleted:
                    st.success("Template deleted.")
                    st.session_state.pop("lt_edit_data", None)
                    st.session_state.pop("lt_edit_id", None)
                    st.rerun()
                else:
                    st.error("Delete failed.")

            if btn_preview.button("👁️ Preview PDF", use_container_width=True,
                                  key="e_preview"):
                st.session_state["lt_preview_template"] = {
                    "header_company_name": e_company,
                    "header_tagline": e_tagline,
                    "contact_email": e_email,
                    "contact_phone": e_phone,
                    "body_text": e_body,
                    "next_steps": e_next,
                    "footer_text": e_footer,
                }
                st.info("Preview saved. Go to Underwriting Workbench and "
                        "evaluate a case to see the template applied.")

    # ══════════════════════════════════════════════════════════════
    # TAB 3 — New Template
    # ══════════════════════════════════════════════════════════════
    with tab_new:
        st.markdown("#### Create New Letter Template")

        n_name = st.text_input("Template Name *",
            placeholder="e.g. Standard Approval Letter", key="n_name")
        n_outcome = st.selectbox("Outcome *", OUTCOMES, key="n_outcome")
        n_active = st.checkbox("Set as Active for this outcome",
                               value=True, key="n_active")

        st.markdown("##### 🏢 Company Header")
        nc1, nc2 = st.columns(2)
        n_company = nc1.text_input("Company Name",
            placeholder="Acme Life Insurance Co.", key="n_company")
        n_tagline = nc2.text_input("Tagline",
            placeholder="Protecting families since 1985", key="n_tagline")

        st.markdown("##### 📞 Contact")
        ncc1, ncc2 = st.columns(2)
        n_email = ncc1.text_input("Contact Email",
            placeholder="uw@acmelife.com", key="n_email")
        n_phone = ncc2.text_input("Contact Phone",
            placeholder="1-800-555-0100", key="n_phone")

        st.markdown("##### 📝 Letter Body")
        _default_bodies = {
            "APPROVED":   "Dear {applicant_name},\n\nWe are pleased to inform you that your application for life insurance has been approved at {risk_class} risk class.\n\nYour policy will be effective {policy_effective_date}. Your annual premium is {approved_premium}.\n\nThank you for choosing us.",
            "DECLINED":   "Dear {applicant_name},\n\nAfter careful review of your application, we regret to inform you that we are unable to offer coverage at this time.\n\nYou have the right to request the specific reasons for this decision within 60 days of receiving this letter.",
            "POSTPONED":  "Dear {applicant_name},\n\nYour application has been postponed pending additional information. We will contact you shortly.",
            "REFERRED":   "Dear {applicant_name},\n\nYour application has been referred for additional underwriter review. We will notify you of a decision within 5 business days.",
        }
        n_body = st.text_area(
            "Body Text",
            value=_default_bodies.get(
                n_outcome,
                "Dear {applicant_name},\n\nYour underwriting decision is: {outcome}.\n\nPlease contact us with any questions."
            ),
            height=180, key="n_body",
            help="Placeholders: {applicant_name} {outcome} {risk_class} "
                 "{net_debits} {policy_effective_date} {approved_premium}"
        )
        st.caption("Placeholders: `{applicant_name}` `{outcome}` `{risk_class}` "
                   "`{net_debits}` `{policy_effective_date}` `{approved_premium}`")

        st.markdown("##### 📋 Next Steps")
        n_next = st.text_area(
            "Next Steps (JSON array)",
            value='[\n  "Review your policy documents carefully",\n  "Sign and return the policy acceptance form",\n  "Make your first premium payment"\n]',
            height=100, key="n_next"
        )

        st.markdown("##### 📄 Footer")
        n_footer = st.text_area(
            "Footer Text",
            value="This letter is generated automatically. All decisions are subject to the terms and conditions of your policy. For questions, please contact your agent or our customer service team.",
            height=70, key="n_footer"
        )

        st.markdown("---")
        if st.button("➕ Create Template", type="primary",
                     use_container_width=True, key="n_create"):
            if not n_name.strip():
                st.error("Template Name is required.")
            else:
                try:
                    ns_parsed = _json.loads(n_next)
                except Exception as _exc:
                    logger.debug("[_set_active_db] Suppressed exception", exc_info=_exc)
                    ns_parsed = []
                payload = {
                    "template_name": n_name, "outcome": n_outcome,
                    "is_active": n_active,
                    "header_company_name": n_company,
                    "header_tagline": n_tagline,
                    "contact_email": n_email, "contact_phone": n_phone,
                    "body_text": n_body, "next_steps": ns_parsed,
                    "footer_text": n_footer,
                }
                saved = False
                if api_ok:
                    try:
                        rc = requests.post(
                            f"{API_BASE}/letter-templates",
                            json=payload, headers=hdr, timeout=5
                        )
                        if rc.status_code in (200, 201):
                            saved = True
                    except Exception as _exc:
                        logger.debug("[_set_active_db] Suppressed exception", exc_info=_exc)
                if not saved:
                    ok, new_id, msg = _save_template_db(payload)
                    if ok:
                        saved = True
                        st.success(
                            f"✅ Template '{n_name}' created and saved to database!"
                        )
                    else:
                        st.error(f"Save failed: {msg}")

                if saved:
                    st.rerun()


def render_system_config():
    """System-level configuration — currency, SLA, reinsurance thresholds, rate tables."""
    import pandas as pd
    st.markdown("## \u2699\ufe0f System Configuration")
    st.caption("Tenant-level settings: currency, SLA defaults, rate tables, letter templates.")

    tok = st.session_state.get("token", "")
    hdr = {"Authorization": f"Bearer {tok}"}

    tab_gen, tab_curr, tab_rates, tab_csv, tab_ltmpl, tab_apikeys, tab_errcodes, tab_states, tab_oic, tab_notif = st.tabs([
        "\U0001f527 General", "\U0001f4b1 Currency", "\U0001f4b0 Rate Tables",
        "\U0001f4e4 Upload Rates", "\U0001f4c4 Letter Templates",
        "\U0001f511 API Keys", "\u26a0\ufe0f Error Codes", "\U0001f5fa\ufe0f State Codes",
        "\U0001f4e4 Output Interface", "\U0001f514 Notifications"
    ])

    # ── Tab 1: General settings ───────────────────────────────
    with tab_gen:
        try:
            cfg_r = requests.get(f"{API_BASE}/config", headers=hdr, timeout=5)
            cfg   = cfg_r.json().get("config", {}) if cfg_r.status_code == 200 else {}
        except Exception as _exc:
            logger.debug("[render_system_config] Suppressed exception", exc_info=_exc)
            cfg = {}

        st.markdown("**Platform Settings**")
        with st.form("gen_cfg_form"):
            c1, c2 = st.columns(2)
            with c1:
                platform_name  = st.text_input("Platform Name",
                    value=cfg.get("platform_name", {}).get("value", "UW Platform"))
                tenant_name    = st.text_input("Carrier / Tenant Name",
                    value=cfg.get("tenant_name", {}).get("value", "Demo Carrier"))
                date_format    = st.selectbox("Date Format",
                    ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD"],
                    index=["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD"].index(
                        cfg.get("date_format", {}).get("value", "MM/DD/YYYY")))
            with c2:
                sla_hours      = st.number_input("Default SLA (hours)", 1, 720,
                    int(cfg.get("sla_default_hours", {}).get("value", 48)))
                rein_threshold = st.number_input("Reinsurance Threshold ($)", 0, 100_000_000,
                    int(cfg.get("reinsurance_threshold", {}).get("value", 5_000_000)),
                    step=500_000)
                prem_freq      = st.selectbox("Default Premium Frequency",
                    ["ANNUAL", "SEMI_ANNUAL", "QUARTERLY", "MONTHLY"],
                    index=["ANNUAL", "SEMI_ANNUAL", "QUARTERLY", "MONTHLY"].index(
                        cfg.get("premium_frequency", {}).get("value", "ANNUAL")))
            if st.form_submit_button("\U0001f4be Save General Settings", use_container_width=True, type="primary"):
                _log_audit("CONFIG","SYSTEM_CONFIG_UPDATED",
                    entity_type="CONFIG", entity_id="system_config",
                    metadata={"section": "general"})
                resp = requests.post(f"{API_BASE}/config/update", headers=hdr, json={"updates": {
                    "platform_name": platform_name, "tenant_name": tenant_name,
                    "date_format": date_format, "sla_default_hours": str(sla_hours),
                    "reinsurance_threshold": str(rein_threshold),
                    "premium_frequency": prem_freq
                }})
                if resp.status_code == 200:
                    st.success("\u2705 Settings saved")
                else:
                    st.warning(f"Config API returned {resp.status_code} — settings may not be persisted yet.")

        if not cfg:
            st.divider()
            st.info("Config API not available. Showing default values. Deploy the /config API route to enable live editing.")

    # ── Tab 2: Currency ───────────────────────────────────────
    with tab_curr:
        st.caption("Set the currency for all premium and face amount displays.")

        CURRENCIES = {
            "USD": ("$",   "US Dollar"),
            "EUR": ("\u20ac", "Euro"),
            "GBP": ("\u00a3", "British Pound"),
            "INR": ("\u20b9", "Indian Rupee"),
            "CAD": ("CA$", "Canadian Dollar"),
            "AUD": ("A$",  "Australian Dollar"),
            "SGD": ("S$",  "Singapore Dollar"),
            "AED": ("AED", "UAE Dirham"),
            "JPY": ("\u00a5", "Japanese Yen"),
            "CHF": ("CHF", "Swiss Franc"),
            "ZAR": ("R",   "South African Rand"),
            "BRL": ("R$",  "Brazilian Real"),
            "MXN": ("MX$", "Mexican Peso"),
            "HKD": ("HK$", "Hong Kong Dollar"),
            "NZD": ("NZ$", "New Zealand Dollar"),
        }

        # ── Load current currency (API first, then session state, then default) ──
        try:
            curr_cfg = requests.get(f"{API_BASE}/config/currency", headers=hdr, timeout=3).json()
            cur_code   = curr_cfg.get("currency_code",   st.session_state.get("currency_code",   "USD"))
            cur_symbol = curr_cfg.get("currency_symbol", st.session_state.get("currency_symbol", "$"))
            cur_name   = curr_cfg.get("currency_name",   st.session_state.get("currency_name",   "US Dollar"))
        except Exception as _exc:
            logger.debug("[render_system_config] Suppressed exception", exc_info=_exc)
            cur_code   = st.session_state.get("currency_code",   "USD")
            cur_symbol = st.session_state.get("currency_symbol", "$")
            cur_name   = st.session_state.get("currency_name",   "US Dollar")

        with st.form("currency_form"):
            curr_codes = list(CURRENCIES.keys())
            curr_idx   = curr_codes.index(cur_code) if cur_code in curr_codes else 0
            sel_code   = st.selectbox(
                "Currency", curr_codes, index=curr_idx,
                format_func=lambda c: f"{c} — {CURRENCIES[c][1]} ({CURRENCIES[c][0]})"
            )
            st.caption(f"Symbol: **{CURRENCIES[sel_code][0]}** | Name: {CURRENCIES[sel_code][1]}")
            st.markdown("**Or enter custom currency:**")
            c1, c2, c3 = st.columns(3)
            custom_code   = c1.text_input("ISO Code",  value=sel_code,                              max_chars=3)
            custom_symbol = c2.text_input("Symbol",    value=CURRENCIES.get(sel_code, ("$",""))[0], max_chars=5)
            custom_name   = c3.text_input("Name",      value=CURRENCIES.get(sel_code, ("$","US Dollar"))[1])

            if st.form_submit_button("💱 Save Currency", use_container_width=True, type="primary"):
                # Derive from selectbox for known currencies — text inputs cache
                # their initial render value and don't update when dropdown changes
                if sel_code in CURRENCIES:
                    _save_code   = sel_code
                    _save_symbol = CURRENCIES[sel_code][0]
                    _save_name   = CURRENCIES[sel_code][1]
                else:
                    _save_code   = custom_code.strip().upper() or sel_code
                    _save_symbol = custom_symbol.strip()
                    _save_name   = custom_name.strip()
                payload = {
                    "currency_code":   _save_code,
                    "currency_symbol": _save_symbol,
                    "currency_name":   _save_name,
                }
                saved = False
                # Try multiple endpoint patterns until one works
                for method, url in [
                    ("PUT",  f"{API_BASE}/config/currency"),
                    ("POST", f"{API_BASE}/config/currency"),
                    ("POST", f"{API_BASE}/config/update"),
                    ("PUT",  f"{API_BASE}/system-config/currency"),
                    ("POST", f"{API_BASE}/system-config/currency"),
                ]:
                    try:
                        if method == "PUT":
                            r2 = requests.put(url, headers=hdr, json=payload, timeout=5)
                        else:
                            r2 = requests.post(url, headers=hdr,
                                               json={"updates": payload} if "update" in url else payload,
                                               timeout=5)
                        if r2.status_code in (200, 201, 204):
                            saved = True
                            break
                    except Exception as _exc:
                        logger.debug("[render_system_config] Suppressed exception", exc_info=_exc)
                        continue

                # Always update session state so display refreshes immediately
                st.session_state["currency_code"]   = _save_code
                st.session_state["currency_symbol"] = _save_symbol
                st.session_state["currency_name"]   = _save_name

                if saved:
                    st.success(f"✅ Currency saved: **{_save_code}** ({_save_symbol})")
                else:
                    st.warning(
                        f"⚠️ Currency API endpoint not available — currency set locally for this session. "
                        f"Ask your admin to configure `PUT /api/v1/config/currency` on the backend."
                    )
                st.rerun()

        st.divider()
        # Use session state for display so it updates immediately after save
        disp_code   = st.session_state.get("currency_code",   cur_code)
        disp_symbol = st.session_state.get("currency_symbol", cur_symbol)
        disp_name   = st.session_state.get("currency_name",   cur_name)
        st.markdown(f"**Current:** `{disp_code}` — {disp_name} ({disp_symbol})")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Face Amount",    f"{disp_symbol}500,000")
        c2.metric("Annual Premium", f"{disp_symbol}1,250.00")
        c3.metric("Monthly",        f"{disp_symbol}104.17")
        c4.metric("Flat Extra",     f"{disp_symbol}2.50/K")

    # ── Tab 3: Rate Tables ────────────────────────────────────
    with tab_rates:
        st.caption("View, add, and delete premium rates per product.")

        try:
            rated_r    = requests.get(f"{API_BASE}/config/rates/products", headers=hdr, timeout=5)
            rated_prods = rated_r.json().get("products", []) if rated_r.status_code == 200 else []
        except Exception as _exc:
            logger.debug("[render_system_config] Suppressed exception", exc_info=_exc)
            rated_prods = []

        st.markdown("**Rated Products**")
        if rated_prods:
            st.dataframe(pd.DataFrame(rated_prods), use_container_width=True, hide_index=True)
        else:
            st.info("No rate tables configured yet. Add rates below or upload a CSV.")

        st.divider()
        prod_opts = [p["product_code"] for p in rated_prods]
        if prod_opts:
            view_prod    = st.selectbox("View rates for product", prod_opts, key="view_rates_prod")
            fc1, fc2, fc3 = st.columns(3)
            filt_gender  = fc1.selectbox("Gender",     ["ALL","MALE","FEMALE"],            key="rf_gender")
            filt_tobacco = fc2.selectbox("Tobacco",    ["ALL","NON_TOBACCO","TOBACCO"],    key="rf_tob")
            filt_class   = fc3.selectbox("Risk Class", ["ALL","PREFERRED_PLUS","PREFERRED",
                "STANDARD_PLUS","STANDARD","SUBSTANDARD"], key="rf_class")
            try:
                rates_r = requests.get(f"{API_BASE}/config/rates",
                    headers=hdr, params={"product_code": view_prod}, timeout=5)
                rates = rates_r.json().get("rates", []) if rates_r.status_code == 200 else []
                if filt_gender  != "ALL": rates = [r for r in rates if r.get("gender") == filt_gender]
                if filt_tobacco != "ALL": rates = [r for r in rates if r.get("tobacco_status") == filt_tobacco]
                if filt_class   != "ALL": rates = [r for r in rates if r.get("risk_class") == filt_class]
                st.caption(f"Showing {len(rates)} rates")
                if rates:
                    df_r = pd.DataFrame([{
                        "Gender": r["gender"], "Tobacco": r["tobacco_status"],
                        "Age": f"{r['age_min']}-{r['age_max']}", "Term": r["term_years"] or "\u2014",
                        "Risk Class": r["risk_class"], "Table": r["table_rating"],
                        "Rate/$1K": r["rate_per_thou"], "Flat Extra": r["flat_extra_rate"],
                        "Effective": str(r.get("effective_date",""))[:10] if r.get("effective_date") else "—",
                        "Expires":   str(r.get("expiry_date",""))[:10]    if r.get("expiry_date")    else "Never",
                        "Label": r.get("rate_label") or "",
                    } for r in rates])
                    st.dataframe(df_r, use_container_width=True, hide_index=True)
                    if st.button(f"\U0001f5d1\ufe0f Delete ALL rates for {view_prod}", type="secondary", key="del_prod_rates"):
                        resp = requests.delete(f"{API_BASE}/config/rates/product/{view_prod}", headers=hdr)
                        if resp.status_code == 200:
                            st.success(f"\u2705 Deleted {resp.json().get('rows_deleted',0)} rates")
                            st.rerun()
            except Exception as ex:
                st.error(f"Error loading rates: {ex}")

        st.divider()
        st.markdown("**Add Single Rate**")
        with st.form("add_rate_form"):
            r1, r2, r3 = st.columns(3)
            with r1:
                nr_prod = st.text_input("Product Code")
                nr_g    = st.selectbox("Gender",  ["MALE","FEMALE"])
                nr_tob  = st.selectbox("Tobacco", ["NON_TOBACCO","TOBACCO"])
            with r2:
                nr_amin = st.number_input("Age Min", 0, 99, 18)
                nr_amax = st.number_input("Age Max", 0, 99, 29)
                nr_term = st.number_input("Term Years (0=any)", 0, 50, 20)
            with r3:
                nr_rc   = st.selectbox("Risk Class", ["STANDARD","PREFERRED","PREFERRED_PLUS","STANDARD_PLUS","SUBSTANDARD"])
                nr_tbl  = st.selectbox("Table Rating", [0,2,4,6,8,10,12,14,16])
                nr_rate = st.number_input("Rate per $1K", 0.0, 200.0, 1.50, step=0.01, help="Annual premium per $1,000 of face amount. e.g. $1.50/K × $500K face = $750/yr base premium before table ratings or flat extras.")
                nr_fe   = st.number_input("Flat Extra ($/K)", 0.0, 20.0, 0.0, step=0.25, help="Additional flat extra surcharge per $1,000 face per year for this rate band. Added on top of the base rate for substandard risks.")
            nr_label = st.text_input("Label / Source", placeholder="e.g. 2026 Reinsurer Schedule")
            rd1, rd2 = st.columns(2)
            from datetime import date as _date
            nr_eff = rd1.date_input("Effective Date", value=_date.today(),
                help="Date this rate schedule becomes active")
            nr_exp = rd2.date_input("Expiry Date", value=None,
                help="Date this rate expires — leave blank for no expiry")
            if st.form_submit_button("\u2795 Add Rate", use_container_width=True):
                if not nr_prod.strip():
                    st.error("Product code required")
                else:
                    resp = requests.post(f"{API_BASE}/config/rates/add", headers=hdr, json={
                        "product_code":   nr_prod.strip().upper(),
                        "gender": nr_g, "tobacco_status": nr_tob,
                        "age_min": nr_amin, "age_max": nr_amax,
                        "term_years": nr_term if nr_term > 0 else None,
                        "risk_class": nr_rc, "table_rating": nr_tbl,
                        "rate_per_thou": nr_rate, "flat_extra_rate": nr_fe,
                        "rate_label":     nr_label,
                        "effective_date": str(nr_eff) if nr_eff else None,
                        "expiry_date":    str(nr_exp) if nr_exp else None,
                    })
                    if resp.status_code == 200:
                        st.success(f"\u2705 Rate added (ID: {resp.json().get('id','')})")
                        st.rerun()
                    else:
                        st.error(f"Error: {resp.text[:200]}")

    # ── Tab 4: CSV Upload ─────────────────────────────────────
    with tab_csv:
        st.caption("Bulk upload premium rates from a CSV file.")
        st.markdown("**Required CSV columns:** `gender, age_min, age_max, rate_per_thou`")
        st.markdown("**Optional columns:** `tobacco_status, term_years, risk_class, table_rating, flat_extra_rate, rate_label, effective_date, expiry_date`")

        template_csv = (
            "gender,tobacco_status,age_min,age_max,term_years,risk_class,table_rating,rate_per_thou,flat_extra_rate,rate_label,effective_date,expiry_date\n"
            "MALE,NON_TOBACCO,18,29,20,PREFERRED_PLUS,0,0.83,0,2026 Schedule,2026-01-01,\n"
            "MALE,NON_TOBACCO,18,29,20,PREFERRED,0,0.94,0,2026 Schedule,2026-01-01,\n"
            "MALE,NON_TOBACCO,18,29,20,STANDARD,0,1.10,0,2026 Schedule,2026-01-01,\n"
            "FEMALE,NON_TOBACCO,18,29,20,STANDARD,0,0.85,0,2026 Schedule,2026-01-01,\n"
        )
        st.download_button("\U0001f4e5 Download CSV Template", template_csv,
                           "rate_template.csv", "text/csv")
        st.divider()
        with st.form("csv_upload_form"):
            up_prod    = st.text_input("Product Code *", placeholder="e.g. IND-TERM-20")
            up_replace = st.checkbox("Replace existing rates for this product", value=True, help="If checked, all existing rates for this product are deleted before the new CSV is loaded. Uncheck to merge/append rates without removing existing ones.")
            from datetime import date as _date
            uc1, uc2 = st.columns(2)
            up_eff = uc1.date_input("Effective Date for all rows", value=_date.today(),
                help="Applied to all uploaded rows unless overridden by a column in the CSV")
            up_exp = uc2.date_input("Expiry Date for all rows", value=None,
                help="Applied to all uploaded rows unless overridden by a column in the CSV")
            up_file    = st.file_uploader("Upload CSV", type=["csv"])
            if st.form_submit_button("\U0001f4e4 Upload Rates", use_container_width=True, type="primary"):
                if not up_prod.strip():
                    st.error("Product code required")
                elif not up_file:
                    st.error("Please upload a CSV file")
                else:
                    resp = requests.post(
                        f"{API_BASE}/config/rates/upload-csv",
                        headers=hdr,
                        params={"product_code": up_prod.strip().upper(),
                                "replace_existing": up_replace,
                                "effective_date": str(up_eff) if up_eff else None,
                                "expiry_date":    str(up_exp) if up_exp else None},
                        files={"file": (up_file.name, up_file.getvalue(), "text/csv")}
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        st.success(f"\u2705 Uploaded {result['inserted']} rates for {result['product_code']}")
                        if result.get("errors"):
                            st.warning(f"Errors in {len(result['errors'])} rows:")
                            for e in result["errors"]:
                                st.caption(f"  \u26a0\ufe0f {e}")
                        st.rerun()
                    else:
                        st.error(f"Upload failed: {resp.text[:200]}")



    # ── Tab 5: Letter Templates ───────────────────────────────
    with tab_ltmpl:
        render_letter_templates()


    # ── Tab 6: API Keys ──────────────────────────────────────
    with tab_apikeys:
        render_api_keys_config()

    # ── Tab 7: Error Codes ────────────────────────────────────
    with tab_errcodes:
        render_error_codes()

    # ── Tab 8: State / Province Codes ────────────────────────
    with tab_states:
        import pandas as _pd_sc
        st.markdown("#### 🗺️ State / Province Codes")
        st.caption(
            "Configure which state/province codes are valid for underwriting. "
            "These appear in the Workbench dropdown and are validated in batch uploads "
            "(DQ008 errors mean the state code is not in this list)."
        )

        COUNTRY_PRESETS = {
            "IN — India": {
                "AP":"Andhra Pradesh","AR":"Arunachal Pradesh","AS":"Assam",
                "BR":"Bihar","CG":"Chhattisgarh","GA":"Goa","GJ":"Gujarat",
                "HR":"Haryana","HP":"Himachal Pradesh","JK":"Jammu & Kashmir",
                "JH":"Jharkhand","KA":"Karnataka","KL":"Kerala","MP":"Madhya Pradesh",
                "MH":"Maharashtra","MN":"Manipur","ML":"Meghalaya","MZ":"Mizoram",
                "NL":"Nagaland","OD":"Odisha","PB":"Punjab","RJ":"Rajasthan",
                "SK":"Sikkim","TN":"Tamil Nadu","TS":"Telangana","TR":"Tripura",
                "UP":"Uttar Pradesh","UK":"Uttarakhand","WB":"West Bengal",
                "AN":"Andaman & Nicobar","CH":"Chandigarh","DD":"Daman & Diu",
                "DL":"Delhi","LD":"Lakshadweep","PY":"Puducherry"
            },
            "US — United States": {
                c: c for c in [
                    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
                    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
                    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
                    "TX","UT","VT","VA","WA","WV","WI","WY"
                ]
            },
            "GB — United Kingdom": {
                "ENG":"England","SCT":"Scotland","WLS":"Wales","NIR":"Northern Ireland"
            },
            "AU — Australia": {
                "NSW":"New South Wales","VIC":"Victoria","QLD":"Queensland",
                "WA":"Western Australia","SA":"South Australia","TAS":"Tasmania",
                "ACT":"Australian Capital Territory","NT":"Northern Territory"
            },
            "CA — Canada": {
                "AB":"Alberta","BC":"British Columbia","MB":"Manitoba",
                "NB":"New Brunswick","NL":"Newfoundland","NS":"Nova Scotia",
                "ON":"Ontario","PE":"Prince Edward Island","QC":"Quebec",
                "SK":"Saskatchewan","YT":"Yukon","NT":"Northwest Territories","NU":"Nunavut"
            },
        }

        _sc_conn = _get_db_conn()
        if not _sc_conn:
            st.error("Database connection unavailable.")
        else:
            _sc_cur = _sc_conn.cursor()
            _sc_cur.execute("""
                SELECT country_code, state_code, state_name, is_active
                FROM state_codes ORDER BY country_code, state_code
            """)
            _sc_rows = _sc_cur.fetchall()
            _sc_cur.close(); _release_db_conn(_sc_conn)

            sc_h1, sc_h2, sc_h3 = st.columns([3,1,1])
            sc_h1.markdown(f"**{len(_sc_rows)} codes configured across all countries**")
            _countries = sorted(set(
                r["country_code"] if isinstance(r, dict) else r[0]
                for r in _sc_rows
            ))
            _filter_country = sc_h2.selectbox(
                "Filter by country", ["ALL"] + _countries,
                key="sc_country_filter"
            )
            if sc_h3.button("🔄 Refresh", key="sc_refresh"):
                st.session_state.pop("configured_state_codes", None)
                st.rerun()
            if _sc_rows:
                _filtered_rows = _sc_rows if _filter_country == "ALL" else [
                    r for r in _sc_rows
                    if (r["country_code"] if isinstance(r, dict) else r[0]) == _filter_country
                ]
                _sc_df = _pd_sc.DataFrame([
                    {
                        "Country": r["country_code"] if isinstance(r, dict) else r[0],
                        "Code":    r["state_code"]   if isinstance(r, dict) else r[1],
                        "Name":    r["state_name"]   if isinstance(r, dict) else r[2],
                        "Active":  r["is_active"]    if isinstance(r, dict) else r[3],
                    }
                    for r in _filtered_rows
                ])
                _sc_df["Active"] = _sc_df["Active"].map({True:"✅", False:"🔴"})
                st.dataframe(_sc_df, use_container_width=True, hide_index=True)
            else:
                st.info("No state codes yet — load a country preset below.")

            st.divider()
            st.markdown("**📥 Load Country Preset**")
            st.caption("Loads all standard state/province codes for the selected country. Safe to run multiple times.")
            _pc1, _pc2 = st.columns([3,1])
            _sel_preset = _pc1.selectbox("Select country", list(COUNTRY_PRESETS.keys()), key="sc_preset_sel")
            if _pc2.button("Load Preset", key="sc_load", use_container_width=True, type="primary"):
                _ckey = _sel_preset.split(" — ")[0]
                _conn2 = _get_db_conn()
                if _conn2:
                    _cur2 = _conn2.cursor()
                    for _code, _name in COUNTRY_PRESETS[_sel_preset].items():
                        _cur2.execute("""
                            INSERT INTO state_codes (country_code, state_code, state_name, is_active)
                            VALUES (%s,%s,%s,TRUE)
                            ON CONFLICT (country_code, state_code)
                            DO UPDATE SET state_name=EXCLUDED.state_name, is_active=TRUE
                        """, (_ckey, _code, _name))
                    _cur2.close()
                    _release_db_conn(_conn2)
                    st.session_state.pop("configured_state_codes", None)
                    st.session_state["sc_preset_success"] = f"✅ Loaded {len(COUNTRY_PRESETS[_sel_preset])} codes for {_sel_preset}"
                    st.rerun()

            if st.session_state.get("sc_preset_success"):
                st.success(st.session_state.pop("sc_preset_success"))
            st.divider()
            st.markdown("**➕ Add Single Code**")
            with st.form("add_state_form", clear_on_submit=True):
                _f1,_f2,_f3,_f4 = st.columns([1,1,2,1])
                _fc = _f1.text_input("Country *", placeholder="IN")
                _fs = _f2.text_input("Code *", placeholder="MH")
                _fn = _f3.text_input("Name", placeholder="Maharashtra")
                _fa = _f4.checkbox("Active", value=True)
                if st.form_submit_button("Add", use_container_width=True, type="primary"):
                    if _fc.strip() and _fs.strip():
                        _conn3 = _get_db_conn()
                        if _conn3:
                            _cur3 = _conn3.cursor()
                            _cur3.execute("""
                                INSERT INTO state_codes (country_code,state_code,state_name,is_active)
                                VALUES (%s,%s,%s,%s)
                                ON CONFLICT (country_code,state_code)
                                DO UPDATE SET state_name=EXCLUDED.state_name, is_active=EXCLUDED.is_active
                            """, (_fc.upper(), _fs.upper(), _fn.strip() or None, _fa))
                            _cur3.close(); _release_db_conn(_conn3)
                            st.session_state.pop("configured_state_codes", None)
                            st.success(f"✅ {_fs.upper()} saved")
                            st.rerun()

            st.info("💡 **DQ008 errors in batch?** Your file has state codes not in this list. "
                    "Load the correct country preset above (e.g. India for WB, MH, GJ, DL, TS, AP).")

    # ══════════════════════════════════════════════════════════════
    # TAB 9 — OUTPUT INTERFACE (moved to sidebar nav)
    # ══════════════════════════════════════════════════════════════
    with tab_oic:
        st.info(
            "📤 **Output Interface** has been moved to its own page in the sidebar navigation. "
            "Click **📤 Output Interface** in the left menu to access it."
        )
        if st.button("📤 Go to Output Interface", type="primary"):
            st.session_state["page"] = "Output Interface"
            st.rerun()

    # ── Tab 10: Notifications ─────────────────────────────────
    with tab_notif:
        st.markdown("#### 🔔 Notification Settings")
        st.caption(
            "Configure which platform events trigger email notifications, "
            "who receives them, and customise the subject and body. "
            "SMTP must be configured in the **API Keys** tab for notifications to send."
        )

        # SMTP status check
        _smtp_chk = _get_smtp_config()
        if _smtp_chk.get("host"):
            st.success(
                f"✅ SMTP configured: **{_smtp_chk.get('host')}** "
                f"from **{_smtp_chk.get('from_email')}**"
            )
        else:
            st.warning(
                "⚠️ SMTP not configured — notifications will not send. "
                "Go to **API Keys** tab to set up SMTP first."
            )

        st.markdown("---")

        # ── Reinsurance Email Setting ─────────────────────────────────────
        st.markdown("#### 🏦 Reinsurance Email Settings")
        _ri_auto = _get_ri_auto_email()
        with st.form("ri_email_global_form"):
            _ri_auto_new = st.toggle(
                "Auto-email reinsurer on cession submission",
                value=_ri_auto,
                help=(
                    "When ON: clicking 'Submit Cession' automatically emails the RI slip "
                    "to the reinsurer's contact email. "
                    "When OFF: submission is recorded but email must be sent manually. "
                    "This is the global default — can be overridden per slip."
                )
            )
            st.caption(
                "📧 The email is sent to the **contact email** configured in each reinsurer's "
                "profile (Reinsurance → Reinsurer Registry). Make sure SMTP is configured above."
            )
            if st.form_submit_button("💾 Save Reinsurance Email Setting",
                                     use_container_width=True, type="primary"):
                _set_ri_auto_email(_ri_auto_new)
                st.success(
                    f"✅ Reinsurance auto-email: **{'Enabled' if _ri_auto_new else 'Disabled'}**"
                )
                st.rerun()

        st.markdown("---")

        _notif_cfg = _get_notification_config()

        for _ev_key, _ev_label in _NOTIF_EVENTS.items():
            _ev_data = _notif_cfg.get(_ev_key, {})
            _ev_enabled  = _ev_data.get("enabled", True)
            _ev_recip    = _ev_data.get("recipients","")
            _ev_subj     = _ev_data.get("subject","") or _NOTIF_DEFAULT_SUBJECTS.get(_ev_key,"")
            _ev_body     = _ev_data.get("body","")    or _NOTIF_DEFAULT_BODIES.get(_ev_key,"")

            _status_dot = "🟢" if _ev_enabled else "⚫"
            with st.expander(
                f"{_status_dot} {_ev_label}  ({_ev_key})",
                expanded=False
            ):
                with st.form(f"notif_form_{_ev_key}"):
                    _en = st.checkbox(
                        "Enable this notification",
                        value=_ev_enabled,
                        help="When disabled, this event fires silently with no email sent."
                    )
                    _rec = st.text_input(
                        "Recipients (comma-separated emails)",
                        value=_ev_recip,
                        placeholder="manager@carrier.com, supervisor@carrier.com",
                        help=(
                            "Who gets this email. Separate multiple addresses with commas. "
                            "For CASE_ASSIGNED the assigned underwriter's own email is also "
                            "added automatically if it's on their user profile."
                        )
                    )
                    _subj = st.text_input(
                        "Subject template",
                        value=_ev_subj,
                        help=(
                            "Use {placeholders} for dynamic values. "
                            "Available: {case_number} {outcome} {applicant_ref} "
                            "{uw_name} {job_number} {total} {rule_name} {due_date}"
                        )
                    )
                    _body = st.text_area(
                        "Body template",
                        value=_ev_body,
                        height=160,
                        help=(
                            "Plain text email body. Same placeholders as subject. "
                            "Use {from_name} to insert your carrier name."
                        )
                    )
                    _sc1, _sc2 = st.columns(2)
                    if _sc1.form_submit_button(
                        "💾 Save", use_container_width=True, type="primary"
                    ):
                        _save_notification_event(
                            _ev_key, _en, _rec, _subj, _body
                        )
                        st.success(f"✅ {_ev_key} notification saved.")
                        st.rerun()
                    if _sc2.form_submit_button(
                        "↩️ Reset to default", use_container_width=True
                    ):
                        _save_notification_event(
                            _ev_key, True, _rec,
                            _NOTIF_DEFAULT_SUBJECTS.get(_ev_key,""),
                            _NOTIF_DEFAULT_BODIES.get(_ev_key,""),
                        )
                        st.success("Reset to default template.")
                        st.rerun()

        st.markdown("---")

        # Notification log
        with st.expander("📋 Notification Log (last 100)"):
            try:
                import pandas as _pd_nl
                _conn_nl = _get_db_conn()
                if _conn_nl:
                    _cur_nl = _conn_nl.cursor()
                    _conn_nl.commit()
                    _cur_nl.execute("""
                        SELECT event, recipient, subject, status,
                               error_msg, sent_at
                        FROM notification_log
                        ORDER BY sent_at DESC LIMIT 100
                    """)
                    _nl_rows = _cur_nl.fetchall()
                    _cur_nl.close(); _conn_nl.close()
                    if _nl_rows:
                        _nl_df = _pd_nl.DataFrame(
                            _nl_rows,
                            columns=["Event","Recipient","Subject",
                                     "Status","Error","Sent At"]
                        )
                        # Colour status
                        st.dataframe(
                            _nl_df,
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.caption(f"{len(_nl_rows)} entries shown")
                    else:
                        st.info("No notifications sent yet.")
            except Exception as _nle:
                st.warning(f"Log unavailable: {_nle}")


def render_rule_builder():
    """Rule Builder — full CRUD for custom rules + workflow + rule library."""
    import pandas as pd, json
    hdr = api_headers()
    st.markdown("## ⚙️ Rule Builder")
    st.caption("View the built-in medical impairment library and create custom JSON-based underwriting rules.")

    # ── helper: load rules ──────────────────────────────────────────────
    def _load_rules(force=False):
        if force or "rb_custom_data" not in st.session_state:
            rules = []
            for ep in ["/custom-rules", "/rules/custom", "/custom_rules"]:
                try:
                    r = requests.get(f"{API_BASE}{ep}", headers=hdr, timeout=6)
                    if r.status_code == 200:
                        data = r.json()
                        rules = data if isinstance(data, list) else data.get("rules", data.get("items", []))
                        if rules is not None:
                            st.session_state.rb_endpoint = ep
                            break
                except Exception as _exc:
                    logger.debug("[_load_rules] Suppressed exception", exc_info=_exc)
                    continue
            st.session_state.rb_custom_data = rules or []

    # ── helper: load/save custom rule fields ────────────────────────────
    _DEFAULT_FIELDS = [
        "age", "bmi", "gender", "state", "face_amount", "occupation_class",
        "tobacco_status", "dui_count", "major_violation_count", "systolic_bp",
        "diastolic_bp", "diabetes_type", "heart_condition", "cancer_status",
        "hiv_positive", "alcohol_use", "hazardous_activity", "cholesterol",
        "hdl", "ldl", "egfr", "a1c", "family_hx_cvd", "family_hx_stroke",
        "annual_income", "existing_coverage",
    ]

    def _load_custom_fields():
        """Load user-added fields from DB, fall back to session state."""
        if "rb_custom_fields" in st.session_state:
            return st.session_state["rb_custom_fields"]
        fields = []
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT field_name, label, data_type, description "
                    "FROM rule_custom_fields ORDER BY field_name"
                )
                rows = cur.fetchall()
                cur.close(); _release_db_conn(conn)
                fields = [{"field_name": r[0], "label": r[1] or r[0],
                           "data_type": r[2], "description": r[3] or ""}
                          for r in rows]
        except Exception as _exc:
            logger.warning("[_load_custom_fields] Suppressed exception", exc_info=_exc)
        st.session_state["rb_custom_fields"] = fields
        return fields

    def _save_custom_field(field_name, label, data_type, description):
        """Persist a new custom field to DB."""
        username = st.session_state.get("username", "admin")
        saved = False
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO rule_custom_fields
                        (field_name, label, data_type, description, added_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (field_name) DO UPDATE
                        SET label=EXCLUDED.label,
                            data_type=EXCLUDED.data_type,
                            description=EXCLUDED.description
                """, (field_name, label, data_type, description, username))
                cur.close(); _release_db_conn(conn)
                saved = True
        except Exception as _exc:
            logger.warning("[_save_custom_field] Suppressed exception", exc_info=_exc)
        # Always update session state so UI refreshes immediately
        existing = st.session_state.get("rb_custom_fields", [])
        existing = [f for f in existing if f["field_name"] != field_name]
        existing.append({"field_name": field_name, "label": label,
                         "data_type": data_type, "description": description})
        existing.sort(key=lambda f: f["field_name"])
        st.session_state["rb_custom_fields"] = existing
        return saved

    def _delete_custom_field(field_name):
        """Remove a custom field from DB and session state."""
        try:
            conn = _get_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    "DELETE FROM rule_custom_fields WHERE field_name = %s",
                    (field_name,)
                )
                cur.close(); _release_db_conn(conn)
        except Exception as _exc:
            logger.warning("[_delete_custom_field] Suppressed exception", exc_info=_exc)
        existing = st.session_state.get("rb_custom_fields", [])
        st.session_state["rb_custom_fields"] = [
            f for f in existing if f["field_name"] != field_name
        ]

    _load_rules()
    rules = st.session_state.get("rb_custom_data", [])
    ep    = st.session_state.get("rb_endpoint", "/custom-rules")

    # Build merged RULE_FIELDS = defaults + user-added custom fields
    _custom_fields_data = _load_custom_fields()
    _custom_field_names = [f["field_name"] for f in _custom_fields_data]
    RULE_FIELDS = sorted(set(_DEFAULT_FIELDS + _custom_field_names))

    STATUS_COLORS = {
        "DRAFT":     "#64748b", "IN_REVIEW": "#f59e0b",
        "APPROVED":  "#3b82f6", "DEPLOYED":  "#10b981",
        "ARCHIVED":  "#ef4444",
    }
    WORKFLOW = {
        "DRAFT":     ["IN_REVIEW"],
        "IN_REVIEW": ["APPROVED", "DRAFT"],
        "APPROVED":  ["DEPLOYED", "IN_REVIEW"],
        "DEPLOYED":  ["ARCHIVED"],
        "ARCHIVED":  [],
    }
    STATUS_EMOJI = {
        "DRAFT": "📝", "IN_REVIEW": "🔍", "APPROVED": "✅",
        "DEPLOYED": "🚀", "ARCHIVED": "📦",
    }

    tab_library, tab_list, tab_new, tab_assign, tab_fields = st.tabs([
        "📚 Rule Library", "⚡ Custom Rules", "➕ Create Rule",
        "🔗 Assign to Product", "🏷️ Manage Fields"
    ])

    # ══════════════════════════════════════════════════════════════
    #  TAB 1 — CUSTOM RULES LIST + EDIT/DELETE/WORKFLOW
    # ══════════════════════════════════════════════════════════════
    with tab_list:
        col_hd, col_ref = st.columns([5, 1])
        col_hd.caption("Custom underwriting rules — stored in DB, applied after core engine rules.")
        if col_ref.button("🔄 Refresh", key="rb_refresh"):
            _load_rules(force=True)
            st.rerun()

        if not rules:
            st.info("No custom rules yet. Use the **➕ Create New Rule** tab to add one.")
        else:
            # ── Metrics row ─────────────────────────────────────────────
            statuses = [r.get("status","DRAFT") for r in rules]
            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("Total",    len(rules))
            m2.metric("Draft",    statuses.count("DRAFT"))
            m3.metric("In Review",statuses.count("IN_REVIEW"))
            m4.metric("Deployed", statuses.count("DEPLOYED"))
            m5.metric("Archived", statuses.count("ARCHIVED"))
            st.divider()

            # ── Filter ──────────────────────────────────────────────────
            fc1, fc2 = st.columns(2)
            f_status = fc1.selectbox("Filter by status",
                ["All","DRAFT","IN_REVIEW","APPROVED","DEPLOYED","ARCHIVED"], key="rb_f_status")
            f_search = fc2.text_input("🔍 Search name/code", key="rb_f_search", placeholder="type to filter...")

            display = rules
            if f_status != "All":
                display = [r for r in display if r.get("status") == f_status]
            if f_search:
                q = f_search.lower()
                display = [r for r in display if
                           q in str(r.get("rule_name","")).lower() or
                           q in str(r.get("rule_code","")).lower()]

            st.caption(f"Showing {len(display)} of {len(rules)} rules")

            # ── Table ───────────────────────────────────────────────────
            df_cr = pd.DataFrame([{
                "Status":    STATUS_EMOJI.get(r.get("status","DRAFT"),"") + " " + r.get("status","—"),
                "Code":      r.get("rule_code") or r.get("code","—"),
                "Name":      r.get("rule_name") or r.get("name","—"),
                "Debits":    r.get("debit_points", r.get("action",{}).get("debit_points","—") if isinstance(r.get("action"),dict) else "—"),
                "Hard Stop": r.get("hard_stop", False),
                "Effective": str(r.get("effective_date","—"))[:10] if r.get("effective_date") else "Immediate",
                "Expires":   str(r.get("expire_date","—"))[:10]    if r.get("expire_date")    else "Never",
                "Version":   r.get("version","—"),
                "Created":   str(r.get("created_at","—"))[:10],
            } for r in display])
            st.dataframe(df_cr, use_container_width=True, hide_index=True)
            st.divider()

            # ── Rule Detail + Actions ────────────────────────────────────
            st.markdown("#### Manage Rule")
            rule_names = ["— select a rule —"] + [
                f"{STATUS_EMOJI.get(r.get('status',''),'')}{r.get('rule_code','?')}  —  {r.get('rule_name','?')}"
                for r in display
            ]
            sel_idx = st.selectbox("Select rule to manage", range(len(rule_names)),
                                   format_func=lambda i: rule_names[i], key="rb_sel_idx")

            if sel_idx > 0:
                rule = display[sel_idx - 1]
                rule_id = rule.get("id") or rule.get("rule_id") or rule.get("rule_code")
                status  = rule.get("status", "DRAFT")

                # Status badge
                col = STATUS_COLORS.get(status, "#64748b")
                st.markdown(
                    f"<span style='background:{col};color:white;padding:3px 12px;"
                    f"border-radius:12px;font-size:0.8rem;font-weight:600;'>"
                    f"{STATUS_EMOJI.get(status,'')} {status}</span>",
                    unsafe_allow_html=True
                )
                st.markdown(f"**{rule.get('rule_name','—')}** &nbsp;|&nbsp; Code: `{rule.get('rule_code','—')}` &nbsp;|&nbsp; v{rule.get('version','—')}")

                act1, act2, act3, act4 = st.columns(4)

                # ── Workflow transitions ──────────────────────────────
                next_statuses = WORKFLOW.get(status, [])
                if next_statuses:
                    with act1.expander("🔄 Change Status"):
                        new_s = st.selectbox("Transition to", next_statuses, key="rb_new_status")
                        reason = st.text_input("Reason *", key="rb_trans_reason", help="Mandatory reason for this workflow transition. Stored in the audit log for compliance — required for APPROVED→DEPLOYED and similar irreversible transitions.")
                        if st.button("Apply Transition", key="rb_do_trans"):
                            if not reason.strip():
                                st.error("Reason required")
                            else:
                                resp = requests.post(
                                    f"{API_BASE}{ep}/{rule_id}/workflow",
                                    headers=hdr,
                                    json={"new_status": new_s, "reason": reason}
                                )
                                if resp.status_code == 200:
                                    st.success(f"✅ Status → {new_s}")
                                    _load_rules(force=True)
                                    st.rerun()
                                else:
                                    st.error(f"Failed: {resp.text[:200]}")
                else:
                    act1.caption("No transitions available")

                # ── Edit rule ─────────────────────────────────────────
                with act2.expander("✏️ Edit Rule"):
                    if status in ("DRAFT", "IN_REVIEW"):
                        with st.form("rb_edit_form"):
                            e_name    = st.text_input("Rule Name", value=rule.get("rule_name",""))
                            e_desc    = st.text_area("Description", value=rule.get("description",""), height=60)
                            e_debits  = st.number_input("Debit Points", 0, 999,
                                int(rule.get("debit_points", 0) or 0))
                            e_hard    = st.checkbox("Hard Stop (instant decline)", value=bool(rule.get("hard_stop", False)), help="When enabled, this rule causes an immediate automatic decline regardless of the total debit score or thresholds. Used for absolute exclusions like HIV, active cancer, etc.")
                            from datetime import date as _date, datetime as _datetime
                            ed1, ed2 = st.columns(2)
                            def _parse_date(val):
                                if not val: return None
                                try: return _datetime.fromisoformat(str(val)[:10]).date()
                                except: return None
                            e_eff = ed1.date_input("Effective Date",
                                value=_parse_date(rule.get("effective_date")),
                                help="Date this rule starts evaluating applications")
                            e_exp = ed2.date_input("Expire Date",
                                value=_parse_date(rule.get("expire_date")),
                                help="Date this rule stops (leave blank = never expires)")
                            e_cond    = st.text_area("Conditions (JSON)",
                                value=json.dumps(rule.get("conditions", rule.get("condition_json", {})), indent=2),
                                height=120)
                            e_action  = st.text_area("Action (JSON)",
                                value=json.dumps(rule.get("action", rule.get("action_json",
                                    {"debit_points": rule.get("debit_points",0)})), indent=2),
                                height=80)
                            if st.form_submit_button("💾 Save Changes", use_container_width=True):
                                try:
                                    payload = {
                                        "rule_name":      e_name,
                                        "description":    e_desc,
                                        "debit_points":   e_debits,
                                        "hard_stop":      e_hard,
                                        "effective_date": str(e_eff) if e_eff else None,
                                        "expire_date":    str(e_exp) if e_exp else None,
                                        "conditions":     json.loads(e_cond),
                                        "action":         json.loads(e_action),
                                    }
                                    resp = requests.put(
                                        f"{API_BASE}{ep}/{rule_id}",
                                        headers=hdr, json=payload
                                    )
                                    if resp.status_code == 200:
                                        st.success("✅ Rule updated")
                                        _load_rules(force=True)
                                        st.rerun()
                                    else:
                                        st.error(f"Update failed: {resp.text[:200]}")
                                except json.JSONDecodeError as je:
                                    st.error(f"Invalid JSON: {je}")
                    else:
                        st.warning(f"Cannot edit rules in {status} status. Archive first to create a new version.")

                # ── Delete rule ───────────────────────────────────────
                with act3.expander("🗑️ Delete"):
                    if status in ("DRAFT", "ARCHIVED"):
                        st.warning(f"Permanently delete **{rule.get('rule_name')}**?")
                        if st.button("⚠️ Confirm Delete", key="rb_delete_confirm", type="primary"):
                            resp = requests.delete(f"{API_BASE}{ep}/{rule_id}", headers=hdr)
                            if resp.status_code in (200, 204):
                                st.success("✅ Deleted")
                                _load_rules(force=True)
                                st.rerun()
                            else:
                                st.error(f"Delete failed: {resp.text[:200]}")
                    else:
                        st.info(f"Only DRAFT or ARCHIVED rules can be deleted. Current: {status}")

                # ── Full JSON view ────────────────────────────────────
                with act4.expander("👁️ View JSON"):
                    st.json(rule)

    # ══════════════════════════════════════════════════════════════
    #  TAB 2 — CREATE NEW RULE
    # ══════════════════════════════════════════════════════════════
    with tab_new:
        st.markdown("#### ➕ Create Custom UW Rule")
        st.caption("Build a rule with conditions and actions. Rules run after the built-in library.")

        OPERATORS = [">", "<", ">=", "<=", "==", "!=", "in", "not_in"]
        CATEGORIES = ["CUSTOM", "BUILD", "MEDICAL", "FINANCIAL", "LIFESTYLE",
                      "OCCUPATION", "DRIVING", "PRODUCT", "STATE"]
        LOGIC_OPTS = ["AND", "OR"]
        OUTCOMES   = ["REFER", "DECLINE", "APPROVE", "FLAT_EXTRA", "TABLE_RATING", "DEBIT_ONLY"]


        # ── No st.form — plain widgets so Add/Remove buttons can call st.rerun() ──
        if "rb_n_cond" not in st.session_state:
            st.session_state["rb_n_cond"] = 1

        # ── Row 1: Rule ID | Rule Name | Version ─────────────────
        r1c1, r1c2, r1c3 = st.columns([2, 2, 1])
        new_rule_id   = r1c1.text_input("Rule ID *",   placeholder="e.g. CUST001",       key="crf_id")
        new_rule_name = r1c2.text_input("Rule Name *", placeholder="e.g. High BMI Refer", key="crf_name")
        new_version   = r1c3.text_input("Version",     value="1.0",                       key="crf_ver",
            help="Rule version — e.g. 1.0, 2.1")

        # ── Row 2: Category | Logic | Priority ───────────────────
        r2c1, r2c2, r2c3 = st.columns(3)
        new_category = r2c1.selectbox("Category",          CATEGORIES, index=0,  key="crf_cat")
        new_logic    = r2c2.selectbox("Condition Logic ⓘ", LOGIC_OPTS, index=0,  key="crf_logic",
            help="AND = all must match · OR = any must match")
        new_priority = r2c3.number_input("Priority ⓘ", min_value=1, max_value=9999,
            value=100, key="crf_pri",
            help="Lower = evaluated first. Default = 100.")

        # ── Row 3: Description | Product Code ────────────────────
        new_desc = st.text_input("Description (optional)", placeholder="", key="crf_desc")
        new_prod = st.text_input("Product Code (blank = all products)",
            placeholder="e.g. IND-TERM-20", key="crf_prod")

        st.divider()

        # ── Conditions header + Add/Remove inline ─────────────────
        _nc = st.session_state.get("rb_n_cond", 1)
        ch1, ch2, ch3 = st.columns([3, 1, 1])
        ch1.markdown(
            f"##### 📋 Conditions &nbsp;"
            f"<small style='color:grey;font-weight:normal'>({_nc} row(s) · max 10)</small>",
            unsafe_allow_html=True
        )
        if ch2.button("➕ Add Condition", key="rb_add_cond", use_container_width=True):
            if st.session_state["rb_n_cond"] < 10:
                st.session_state["rb_n_cond"] += 1
                st.rerun()
        if ch3.button("➖ Remove Last", key="rb_rem_cond", use_container_width=True,
                      disabled=_nc <= 1):
            st.session_state["rb_n_cond"] -= 1
            st.rerun()

        n = int(st.session_state.get("rb_n_cond", 1))
        conditions_list = []

        # Column headers (only show once)
        _hc1, _hc2, _hc3, _hc4 = st.columns([1.2, 2, 1.2, 1.5])
        _hc1.caption("🔍 Search field")
        _hc2.caption("Field")
        _hc3.caption("Operator")
        _hc4.caption("Value")

        for i in range(n):
            cc1, cc2, cc3, cc4 = st.columns([1.2, 2, 1.2, 1.5])

            # Search box — filters the field dropdown in real time
            search_q = cc1.text_input(
                f"_search_{i}",
                value=st.session_state.get(f"crf_search_{i}", ""),
                placeholder="type to filter…",
                label_visibility="collapsed",
                key=f"crf_search_{i}",
                help="Type part of a field name to narrow the list below — e.g. 'bp' shows systolic_bp and diastolic_bp"
            )

            # Filter RULE_FIELDS by search
            _filtered = [f for f in RULE_FIELDS
                         if search_q.lower() in f.lower()] if search_q else RULE_FIELDS

            if not _filtered:
                _filtered = RULE_FIELDS  # fallback — never show empty list
                cc1.caption("No match")

            # Preserve previously selected field across reruns
            _prev_field = st.session_state.get(f"crf_field_{i}", RULE_FIELDS[0])
            _fidx = _filtered.index(_prev_field) if _prev_field in _filtered else 0

            field = cc2.selectbox(
                f"Field {i+1}" if i > 0 else "Field",
                _filtered,
                index=_fidx,
                key=f"crf_field_{i}",
                label_visibility="collapsed"
            )
            op = cc3.selectbox(
                f"Operator {i+1}" if i > 0 else "Operator",
                OPERATORS,
                index=0,
                key=f"crf_op_{i}",
                label_visibility="collapsed"
            )
            val = cc4.text_input(
                f"Value {i+1}" if i > 0 else "Value",
                placeholder="e.g. 35",
                key=f"crf_val_{i}",
                label_visibility="collapsed"
            )
            conditions_list.append({"field": field, "operator": op, "value": val})

        st.divider()

        # ── Actions ───────────────────────────────────────────────
        st.markdown("##### ⚡ Actions")
        ac1, ac2, ac3 = st.columns(3)
        new_outcome   = ac1.selectbox("Outcome",           OUTCOMES,             index=0, key="crf_outcome")
        new_debits    = ac2.number_input("Debit Points",   min_value=0,  max_value=999,   value=0, key="crf_debits")
        new_flat      = ac3.number_input("Flat Extra ($/K/yr)", min_value=0.0, max_value=20.0, value=0.0, step=0.5, key="crf_flat")
        ac4, ac5, ac6 = st.columns(3)
        new_table_rat = ac4.selectbox("Table Rating",      [0,2,4,6,8,10,12,14,16], index=0, key="crf_table")
        new_hard      = ac5.checkbox("Hard Stop (instant decline)", key="crf_hard")
        new_aps       = ac6.checkbox("Requires APS",                key="crf_aps")
        new_reason    = st.text_input("Reason / Message",
            placeholder="e.g. BMI exceeds maximum threshold for STP", key="crf_reason")

        st.divider()

        # ── Validity Period ───────────────────────────────────────
        st.markdown("##### 📅 Validity Period")
        vd1, vd2 = st.columns(2)
        from datetime import date as _date
        new_eff_date = vd1.date_input("Effective Date", value=_date.today(), key="crf_eff",
            help="Date this rule starts evaluating applications.")
        new_exp_date = vd2.date_input("Expire Date", value=None, key="crf_exp",
            help="Date this rule stops. Leave blank = never expires.")

        st.divider()
        submitted = st.button("✅ Save Rule", use_container_width=True, type="primary", key="crf_submit")

        # ── Submit handler ────────────────────────────────────────
        if submitted:
            errs = []
            if not new_rule_id.strip():   errs.append("Rule ID is required")
            if not new_rule_name.strip(): errs.append("Rule Name is required")
            parsed_conds = []
            for i, c in enumerate(conditions_list):
                v = c["value"].strip()
                if not v:
                    errs.append(f"Condition {i+1}: Value is required")
                    continue
                try:    v = int(v)
                except ValueError:
                    try:    v = float(v)
                    except ValueError:
                        if "," in v:
                            v = [x.strip() for x in v.split(",")]
                parsed_conds.append({"field": c["field"], "operator": c["operator"], "value": v})

            if errs:
                for e in errs: st.error(f"❌ {e}")
            else:
                cond_json = (
                    {"logic": new_logic, "conditions": parsed_conds}
                    if len(parsed_conds) > 1
                    else (parsed_conds[0] if parsed_conds else {})
                )
                action_json = {
                    "outcome":      new_outcome,
                    "debit_points": new_debits,
                    "flat_extra":   new_flat if new_flat > 0 else None,
                    "table_rating": new_table_rat if new_table_rat > 0 else None,
                    "hard_stop":    new_hard,
                    "reason":       new_reason.strip() or None,
                }
                payload = {
                    "rule_id":         new_rule_id.strip().upper(),
                    "rule_name":       new_rule_name.strip(),
                    "rule_code":       new_rule_id.strip().upper(),
                    "version":         new_version.strip() or "1.0",
                    "category":        new_category,
                    "priority":        new_priority,
                    "description":     new_desc.strip() or None,
                    "product_code":    new_prod.strip() or None,
                    "condition_logic": new_logic,
                    "debit_points":    new_debits,
                    "hard_stop":       new_hard,
                    "requires_aps":    new_aps,
                    "effective_date":  str(new_eff_date) if new_eff_date else None,
                    "expire_date":     str(new_exp_date) if new_exp_date else None,
                    "conditions":      cond_json,
                    "action":          action_json,
                    "status":          "DRAFT",
                }
                resp = requests.post(f"{API_BASE}{ep}", headers=hdr, json=payload)
                if resp.status_code in (200, 201):
                    created = resp.json()
                    st.success(
                        f"✅ Rule **{created.get('rule_name', new_rule_name)}** saved as DRAFT! "
                        f"ID: `{created.get('rule_id', new_rule_id)}` — "
                        f"Go to **⚡ Custom Rules** tab to review and deploy."
                    )
                    _load_rules(force=True)
                else:
                    st.error(f"❌ Create failed ({resp.status_code}): {resp.text[:300]}")


    # ══════════════════════════════════════════════════════════════
    #  TAB 3 — BUILT-IN RULE LIBRARY
    # ══════════════════════════════════════════════════════════════
    with tab_library:
        try:
            import sys
            sys.path.insert(0, "/home/vsch/uw_platform")
            from rules.medical_impairment_library import MEDICAL_REGISTRY
            rules_lib = MEDICAL_REGISTRY.list_all()
            _total_lib = len(rules_lib)
            st.caption(
                f"Core medical impairment rules — **{_total_lib} rules** built into "
                f"the engine. Read-only reference."
            )
            c1,c2,c3 = st.columns(3)
            c1.metric("Total Rules",  _total_lib)
            c2.metric("Hard Stops",   sum(1 for r in rules_lib if r.hard_stop))
            c3.metric("APS Required", sum(1 for r in rules_lib if r.requires_aps))
            st.divider()
            s1, s2 = st.columns(2)
            search_lib = s1.text_input("🔍 Search", key="rb_lib_search",
                                       placeholder="name, ID, category...")
            cats = sorted(set(str(r.category).replace("RuleCategory.","")
                              for r in rules_lib))
            cat_f = s2.selectbox("Category", ["All"] + cats, key="rb_cat")
            c1f, c2f = st.columns(2)
            sev_f = c1f.selectbox(
                "Show",
                ["All","Hard stops","Debits only","Credits only","APS required"],
                key="rb_sev"
            )
            filtered = rules_lib
            if search_lib:
                q = search_lib.lower()
                filtered = [r for r in filtered if
                            q in r.rule_name.lower() or
                            q in r.rule_id.lower() or
                            q in str(r.category).lower()]
            if cat_f != "All":
                filtered = [r for r in filtered if
                            str(r.category).replace("RuleCategory.","") == cat_f]
            if sev_f == "Hard stops":     filtered = [r for r in filtered if r.hard_stop]
            elif sev_f == "Debits only":  filtered = [r for r in filtered if r.debit_points > 0 and not r.hard_stop]
            elif sev_f == "Credits only": filtered = [r for r in filtered if r.credit_points > 0]
            elif sev_f == "APS required": filtered = [r for r in filtered if r.requires_aps]
            st.caption(f"Showing {len(filtered)} of {_total_lib} rules")
            import pandas as pd
            df_lib = pd.DataFrame([{
                "Rule ID":   r.rule_id,
                "Rule Name": r.rule_name,
                "Category":  str(r.category).replace("RuleCategory.",""),
                "Debits":    r.debit_points,
                "Credits":   r.credit_points,
                "Flat Extra":f"${r.flat_extra}/K" if r.flat_extra else "—",
                "Hard Stop": "🔴" if r.hard_stop else "",
                "APS":       "📋" if r.requires_aps else "",
            } for r in filtered])
            st.dataframe(df_lib, use_container_width=True, hide_index=True)

            # ── Detail view with search-filter to prevent dropdown clipping ──
            if filtered:
                st.divider()
                st.markdown("**View Rule Detail**")
                _dl1, _dl2 = st.columns([1, 3])
                _lib_search = _dl1.text_input(
                    "Filter detail list",
                    placeholder="type ID or name…",
                    key="rb_lib_det_search",
                    help="Type part of a rule ID or name to narrow the detail dropdown"
                )
                _det_opts = [r for r in filtered if
                             not _lib_search or
                             _lib_search.lower() in r.rule_id.lower() or
                             _lib_search.lower() in r.rule_name.lower()
                            ] if _lib_search else filtered

                sel_lib = _dl2.selectbox(
                    "Select rule",
                    ["— select —"] + [r.rule_id for r in _det_opts],
                    format_func=lambda x: x if x == "— select —" else
                        next((f"[{r.rule_id}] {r.rule_name}"
                              for r in _det_opts if r.rule_id == x), x),
                    key="rb_lib_detail",
                    label_visibility="collapsed"
                )
                if sel_lib != "— select —":
                    rd = next((r for r in filtered if r.rule_id == sel_lib), None)
                    if rd:
                        with st.expander(
                            f"📋 {rd.rule_name} — Full Detail", expanded=True
                        ):
                            d1,d2,d3,d4 = st.columns(4)
                            d1.metric("Debit Points",  rd.debit_points)
                            d2.metric("Credit Points", rd.credit_points)
                            d3.metric("Flat Extra",
                                      f"${rd.flat_extra}/K" if rd.flat_extra else "—")
                            d4.metric("Hard Stop", "YES 🔴" if rd.hard_stop else "No")
                            if getattr(rd, "explanation_template", None):
                                st.info(f"📝 {rd.explanation_template}")
                            if getattr(rd, "clinical_basis", None):
                                st.caption(f"Clinical basis: {rd.clinical_basis}")
        except Exception as e:
            st.warning(f"Rule library not available: {e}")
            st.info(
                "The built-in rule library is embedded in the engine and "
                "active for every evaluation."
            )

    # ══════════════════════════════════════════════════════════════
    #  TAB 4 — ASSIGN RULES TO PRODUCT
    # ══════════════════════════════════════════════════════════════
    with tab_assign:
        st.markdown("#### 🔗 Assign Rules to Product")
        st.caption("Select a product and assign built-in or custom rules to it. "
                   "Assigned rules appear in Product Config → Rules & Overrides.")

        # Load products
        products_map = _get_products_from_api()
        if not products_map:
            st.error("Could not load products. Check API connection.")
        else:
            ap_col1, ap_col2 = st.columns([3, 1])
            sel_product = ap_col1.selectbox(
                "Select Product",
                list(products_map.keys()),
                format_func=lambda k: f"{k}  —  {products_map[k]}",
                key="rb_assign_product"
            )
            if ap_col2.button("🔄 Refresh", key="rb_assign_refresh"):
                st.session_state.pop("rb_assigned_rules", None)
                st.rerun()

            st.divider()

            # ── Currently assigned rules — try API then direct DB ────
            st.markdown("**Currently Assigned Rules**")
            assigned_list = []
            try:
                ar = requests.get(f"{API_BASE}/products/{sel_product}/rules", headers=hdr, timeout=5)
                if ar.status_code == 200:
                    assigned = ar.json()
                    assigned_list = assigned if isinstance(assigned, list) else assigned.get("rules", [])
            except Exception as _exc:
                logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)
            # If API returned nothing, fall back to direct DB read
            if not assigned_list:
                try:
                        conn = _get_db_conn()
                        if conn:
                            cur = conn.cursor()
                        cur.execute("""
                            SELECT rule_id, is_enabled, debit_points_override,
                                   debit_override_active, created_at
                            FROM product_rules
                            WHERE product_code = %s
                            ORDER BY rule_id
                        """, (sel_product,))
                        rows = cur.fetchall()
                        cur.close(); _release_db_conn(conn)
                        assigned_list = [
                            {"rule_id": r[0], "is_enabled": r[1],
                             "debit_points_override": r[2],
                             "debit_override_active": r[3],
                             "rule_name": r[0]}  # rule_name fallback to ID
                            for r in rows
                        ]
                except Exception as _exc:
                    logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)

            if assigned_list:
                df_assigned = pd.DataFrame([{
                    "Rule ID":   r.get("rule_id", "—"),
                    "Rule Name": r.get("rule_name", "—"),
                    "Debits":    r.get("debit_points", r.get("base_debit_points", 0)),
                    "Enabled":   "✅" if r.get("is_enabled", True) else "🔴",
                    "Hard Stop": "🔴" if r.get("hard_stop") else "",
                } for r in assigned_list])
                st.dataframe(df_assigned, use_container_width=True, hide_index=True)
                st.caption(f"{len(assigned_list)} rules assigned to **{sel_product}**")
            else:
                st.info(f"No rules assigned to **{sel_product}** yet.")

            st.divider()

            # ── Assign rules via SQL (direct DB insert into product_rules) ──
            st.markdown("**Assign Rules from Library**")
            st.caption("Enter comma-separated rule IDs from the Rule Library tab (e.g. R010, R020, R060)")

            with st.form("assign_rules_form"):
                rule_ids_input = st.text_input(
                    "Rule IDs to assign",
                    placeholder="e.g. R010, R020, R060, R070",
                    help="Find Rule IDs in the 📚 Rule Library tab above"
                )
                col_e1, col_e2 = st.columns(2)
                assign_enabled = col_e1.checkbox("Enable rules immediately", value=True, help="If checked, assigned rules start evaluating applications right away. Uncheck to assign but keep disabled until you're ready to activate.")
                assign_replace = col_e2.checkbox("Replace existing assignments", value=False, help="If checked, ALL previously assigned rules for this product are removed first, then the new rules are inserted. If unchecked, new rules are added alongside existing ones.")

                if st.form_submit_button("🔗 Assign Rules", use_container_width=True, type="primary"):
                    if not rule_ids_input.strip():
                        st.error("Please enter at least one Rule ID")
                    else:
                        rule_ids = [r.strip().upper() for r in rule_ids_input.split(",") if r.strip()]
                        success_count = 0
                        errors = []

                        # Try API endpoint first
                        payload = {
                            "product_code": sel_product,
                            "rule_ids":     rule_ids,
                            "is_enabled":   assign_enabled,
                            "replace":      assign_replace,
                        }
                        api_saved = False
                        for url in [
                            f"{API_BASE}/products/{sel_product}/rules",
                            f"{API_BASE}/product-rules/assign",
                            f"{API_BASE}/rules/assign",
                        ]:
                            try:
                                resp = requests.post(url, headers=hdr, json=payload, timeout=5)
                                if resp.status_code in (200, 201):
                                    api_saved = True
                                    success_count = len(rule_ids)
                                    break
                            except Exception as _exc:
                                logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)
                                continue

                        if not api_saved:
                            # Direct DB insertion via psycopg2
                            db_success = False
                            db_error = None
                            inserted = 0
                            try:
                                conn = _get_db_conn()
                                if conn:
                                    cur = conn.cursor()

                                # Step 2: fetch existing assigned rule IDs for this product
                                cur.execute(
                                    "SELECT rule_id FROM product_rules WHERE product_code = %s",
                                    (sel_product,)
                                )
                                existing_ids = [row[0] for row in cur.fetchall()]

                                # Step 3: optional replace
                                if assign_replace:
                                    cur.execute(
                                        "DELETE FROM product_rules WHERE product_code = %s",
                                        (sel_product,)
                                    )

                                # Step 4: insert each rule
                                for rid in rule_ids:
                                    cur.execute("""
                                        INSERT INTO product_rules
                                            (product_code, rule_id, is_enabled, created_at, updated_at)
                                        VALUES (%s, %s, %s, NOW(), NOW())
                                        ON CONFLICT (product_code, rule_id)
                                        DO UPDATE SET
                                            is_enabled = EXCLUDED.is_enabled,
                                            updated_at = NOW()
                                    """, (sel_product, rid, assign_enabled))
                                    inserted += 1

                                # Step 5: verify the insert actually worked
                                cur.execute(
                                    "SELECT rule_id, is_enabled FROM product_rules WHERE product_code = %s ORDER BY rule_id",
                                    (sel_product,)
                                )
                                verified = cur.fetchall()
                                cur.close()
                                _release_db_conn(conn)
                                db_success = True

                            except ImportError:
                                db_error = "psycopg2 not installed — run: pip install psycopg2-binary"
                            except Exception as _dbe:
                                db_error = str(_dbe)

                            if db_success:
                                st.success(f"✅ {inserted} rule(s) assigned to **{sel_product}** in database!")
                                if verified:
                                    vdf = pd.DataFrame(verified, columns=["Rule ID", "Enabled"])
                                    vdf["Enabled"] = vdf["Enabled"].map({True: "✅", False: "🔴"})
                                    st.markdown(f"**Confirmed in DB — {len(verified)} total rules for {sel_product}:**")
                                    st.dataframe(vdf, use_container_width=True, hide_index=True)
                                # Clear all related caches
                                for _ck in ["rb_assigned_rules", "pc_rules_data", "pc_rules_product"]:
                                    st.session_state.pop(_ck, None)
                                st.rerun()
                            else:
                                st.error(f"❌ DB insert failed: {db_error}")
                                st.warning("Run this SQL manually in psql as fallback:")
                                sql_lines = []
                                if assign_replace:
                                    sql_lines.append(f"DELETE FROM product_rules WHERE product_code = '{sel_product}';")
                                for rid in rule_ids:
                                    sql_lines.append(
                                        f"INSERT INTO product_rules (product_code, rule_id, is_enabled, created_at, updated_at) "
                                        f"VALUES ('{sel_product}', '{rid}', TRUE, NOW(), NOW()) "
                                        f"ON CONFLICT (product_code, rule_id) DO UPDATE SET is_enabled = TRUE, updated_at = NOW();"
                                    )
                                st.code("\n".join(sql_lines), language="sql")
                        else:
                            st.success(f"✅ {success_count} rules assigned to **{sel_product}** successfully!")
                            st.session_state.pop("rb_assigned_rules", None)
                            st.rerun()

    # ══════════════════════════════════════════════════════════════
    #  TAB 5 — MANAGE FIELDS
    # ══════════════════════════════════════════════════════════════
    with tab_fields:
        st.caption(
            "Add custom fields to the rule condition builder. "
            "New fields appear immediately in the **Field** dropdown when creating rules."
        )

        # ── Current field list ────────────────────────────────────────────────
        _cf_data = _load_custom_fields()
        _all_field_display = (
            [{"Field": f, "Source": "🔒 Built-in", "Type": "—", "Description": "—"}
             for f in sorted(_DEFAULT_FIELDS)] +
            [{"Field": f["field_name"], "Source": "✏️ Custom",
              "Type": f.get("data_type","—"),
              "Description": f.get("description","—")}
             for f in _cf_data]
        )
        st.markdown(
            f"**{len(_DEFAULT_FIELDS)} built-in fields · "
            f"{len(_cf_data)} custom fields · "
            f"{len(_DEFAULT_FIELDS) + len(_cf_data)} total**"
        )
        st.dataframe(
            pd.DataFrame(_all_field_display),
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        # ── Add new field ─────────────────────────────────────────────────────
        st.markdown("### ➕ Add Custom Field")
        st.caption(
            "The **field name** must exactly match the JSON key your underwriting "
            "engine sends — e.g. if the engine payload has `\"creatinine\": 1.2`, "
            "the field name is `creatinine`."
        )

        with st.form("add_custom_field_form"):
            _af1, _af2 = st.columns(2)
            _new_fname = _af1.text_input(
                "Field Name *",
                placeholder="e.g. creatinine",
                help=(
                    "The exact JSON key name from the underwriting engine payload. "
                    "Use lowercase with underscores — e.g. `creatinine`, "
                    "`egfr_stage`, `kidney_disease_years`. "
                    "This must match what the engine sends or the condition will "
                    "never fire."
                )
            )
            _new_label = _af2.text_input(
                "Display Label",
                placeholder="e.g. Creatinine Level",
                help=(
                    "Human-readable name shown in the field dropdown. "
                    "If left blank the field name is used."
                )
            )
            _af3, _af4 = st.columns(2)
            _new_dtype = _af3.selectbox(
                "Data Type",
                ["numeric", "text", "boolean", "enum"],
                help=(
                    "**numeric** — numbers (age, BMI, creatinine, etc.)\n"
                    "**text** — string values (state codes, occupation names)\n"
                    "**boolean** — true/false flags (hazardous_activity, hiv_positive)\n"
                    "**enum** — fixed set of values (gender: MALE/FEMALE, "
                    "diabetes_type: NONE/TYPE1/TYPE2)"
                )
            )
            _new_desc = _af4.text_input(
                "Description (optional)",
                placeholder="e.g. Serum creatinine in mg/dL",
                help="Brief description for other underwriters to understand what this field measures."
            )

            if st.form_submit_button("➕ Add Field", use_container_width=True,
                                     type="primary"):
                _fname_clean = _new_fname.strip().lower().replace(" ","_")
                if not _fname_clean:
                    st.error("Field Name is required")
                elif _fname_clean in _DEFAULT_FIELDS:
                    st.error(
                        f"**{_fname_clean}** is already a built-in field — "
                        f"no need to add it."
                    )
                elif _fname_clean in [f["field_name"] for f in _cf_data]:
                    st.error(f"**{_fname_clean}** already exists as a custom field.")
                elif not _fname_clean.replace("_","").isalnum():
                    st.error(
                        "Field name can only contain letters, numbers and underscores."
                    )
                else:
                    _label_clean = _new_label.strip() or _fname_clean
                    _saved = _save_custom_field(
                        _fname_clean, _label_clean, _new_dtype, _new_desc.strip()
                    )
                    if _saved:
                        st.success(
                            f"✅ Field **{_fname_clean}** saved to database — "
                            f"it now appears in the rule condition dropdown."
                        )
                    else:
                        st.warning(
                            f"⚠️ Database unavailable — field **{_fname_clean}** "
                            f"added for this session only. It will be lost on restart. "
                            f"Check your DB connection to persist it permanently."
                        )
                    st.rerun()

        st.divider()

        # ── Remove custom fields ──────────────────────────────────────────────
        if _cf_data:
            st.markdown("### 🗑️ Remove Custom Field")
            st.caption("Built-in fields cannot be removed. Only user-added fields can be deleted.")
            _del_opts = {f["field_name"]: f["field_name"] for f in _cf_data}
            _del_col1, _del_col2 = st.columns([3, 1])
            _to_delete = _del_col1.selectbox(
                "Select field to remove",
                list(_del_opts.keys()),
                help="This removes the field from the dropdown and from the database. "
                     "Existing rules that reference this field are NOT automatically updated."
            )
            if _del_col2.button("🗑️ Remove", type="secondary",
                                use_container_width=True,
                                key="del_custom_field_btn"):
                _delete_custom_field(_to_delete)
                st.success(f"✅ Field **{_to_delete}** removed.")
                st.rerun()

            st.warning(
                "⚠️ Removing a field does **not** update existing rules that "
                "use it. Those rules will continue to reference the old field name — "
                "edit or delete them manually in the Custom Rules tab."
            )
        else:
            st.info("No custom fields added yet. Use the form above to add your first one.")



# ══════════════════════════════════════════════════════════════
#  LOGIN GATE — must be logged in to see anything
# ══════════════════════════════════════════════════════════════
if not st.session_state.token:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("""
        <div style='text-align:center;padding:2rem 0 1.5rem 0;'>
          <span style='font-size:3rem;'>🛡️</span>
          <div style='font-size:1.4rem;font-weight:700;color:#e2e8f0;margin-top:0.5rem;'>UW Platform</div>
          <div style='font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;'>
            Enterprise Underwriting Engine
          </div>
        </div>""", unsafe_allow_html=True)

        # ── MFA step 2: OTP entry ─────────────────────────────────────────────
        if st.session_state.get("_mfa_pending"):
            _pending_email = st.session_state["_mfa_pending_email"]
            _pending_tok   = st.session_state["_mfa_pending_tok"]
            _pending_role  = st.session_state["_mfa_pending_role"]
            _uname_mfa     = _pending_email.split("@")[0] if "@" in _pending_email else _pending_email

            st.markdown("#### 🔐 Two-Factor Authentication")
            st.info(f"Password verified for **{_pending_email}**. Enter your authenticator code to continue.")

            with st.form("mfa_form"):
                _otp_input = st.text_input(
                    "6-digit code",
                    placeholder="000000",
                    max_chars=6,
                    help="Open your authenticator app (Google Authenticator, Authy, etc.) and enter the current 6-digit code."
                )
                _mfa_col1, _mfa_col2 = st.columns(2)
                _otp_submitted = _mfa_col1.form_submit_button(
                    "✅ Verify", use_container_width=True, type="primary")
                _use_backup    = _mfa_col2.form_submit_button(
                    "🔑 Use backup code", use_container_width=True)

            if _otp_submitted and _otp_input:
                _mfa_cfg = _mfa_get(_uname_mfa)
                if _mfa_cfg and _mfa_verify(_mfa_cfg["secret"], _otp_input):
                    # ✅ MFA passed
                    _mfa_mark_used(_uname_mfa)
                    st.session_state.token    = _pending_tok
                    st.session_state.username = _pending_email
                    st.session_state.role     = _pending_role
                    st.session_state.pop("_mfa_pending", None)
                    st.session_state.pop("_mfa_pending_email", None)
                    st.session_state.pop("_mfa_pending_tok", None)
                    st.session_state.pop("_mfa_pending_role", None)
                    _log_audit("AUTH", "MFA_LOGIN_SUCCESS",
                        entity_type="USER", entity_id=_uname_mfa,
                        actor_username=_uname_mfa, actor_role=_pending_role,
                        metadata={"method": "totp"})
                    st.rerun()
                else:
                    _log_audit("AUTH", "MFA_LOGIN_FAILED",
                        entity_type="USER", entity_id=_uname_mfa,
                        actor_username=_uname_mfa,
                        outcome="FAILURE",
                        failure_reason="Invalid TOTP code")
                    st.error("❌ Invalid code. Check your authenticator app — codes refresh every 30 seconds.")

            if _use_backup:
                st.session_state["_mfa_use_backup"] = True
                st.rerun()

            if st.session_state.get("_mfa_use_backup"):
                with st.form("backup_form"):
                    _bc_input = st.text_input(
                        "Backup code",
                        placeholder="XXXX-XXXX",
                        help="Enter one of the 8 backup codes you saved when you set up MFA."
                    )
                    if st.form_submit_button("✅ Verify backup code",
                                             use_container_width=True, type="primary"):
                        if _mfa_use_backup(_uname_mfa, _bc_input):
                            st.session_state.token    = _pending_tok
                            st.session_state.username = _pending_email
                            st.session_state.role     = _pending_role
                            st.session_state.pop("_mfa_pending", None)
                            st.session_state.pop("_mfa_pending_email", None)
                            st.session_state.pop("_mfa_pending_tok", None)
                            st.session_state.pop("_mfa_pending_role", None)
                            st.session_state.pop("_mfa_use_backup", None)
                            _log_audit("AUTH", "MFA_BACKUP_CODE_USED",
                                entity_type="USER", entity_id=_uname_mfa,
                                actor_username=_uname_mfa, actor_role=_pending_role,
                                metadata={"method": "backup_code"})
                            st.rerun()
                        else:
                            st.error("❌ Invalid backup code.")

            if st.button("← Back to login", key="mfa_back"):
                for k in ["_mfa_pending","_mfa_pending_email",
                          "_mfa_pending_tok","_mfa_pending_role","_mfa_use_backup"]:
                    st.session_state.pop(k, None)
                st.rerun()

        else:
            # ── Show Forgot Password flow if triggered ────────────────────────
            if st.session_state.get("_show_forgot"):
                _render_forgot_password()
                st.stop()

            # ── MFA step 1: Password ──────────────────────────────────────────
            with st.form("login_form"):
                st.markdown("#### Sign In")
                email    = st.text_input("Username or Email",
                    placeholder="e.g. vsch  or  vs.chakravarthi@yahoo.com",
                    help="Enter your username or registered email address.")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "🔐 Sign In", use_container_width=True, type="primary")

            # Forgot Password link — shown below the form
            if st.button("🔑 Forgot Password?", key="forgot_pw_btn",
                         help="Reset your password via email OTP or authenticator app"):
                st.session_state["_show_forgot"] = True
                st.session_state.pop("_fp", None)
                st.rerun()

            if submitted:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    _lr = login(email, password)
                    # login() may return: str (token), None, or (None, message)
                    if isinstance(_lr, tuple):
                        tok, _lock_msg = _lr
                    else:
                        tok, _lock_msg = _lr, ""
                    _uname_l = email.split("@")[0] if "@" in email else email

                    if tok:
                        _role = st.session_state.get("role","underwriter")
                        if _mfa_required(_uname_l):
                            st.session_state["_mfa_pending"]       = True
                            st.session_state["_mfa_pending_email"] = email
                            st.session_state["_mfa_pending_tok"]   = tok
                            st.session_state["_mfa_pending_role"]  = _role
                            _log_audit("AUTH","MFA_CHALLENGE_SENT",
                                entity_type="USER", entity_id=_uname_l,
                                actor_username=_uname_l,
                                metadata={"method":"totp"})
                            st.rerun()
                        else:
                            st.session_state.token    = tok
                            st.session_state.username = email
                            if not st.session_state.get("role"):
                                st.session_state.role = "underwriter"
                            _log_audit("AUTH","LOGIN_SUCCESS",
                                entity_type="USER", entity_id=_uname_l,
                                actor_username=_uname_l,
                                actor_role=st.session_state.get("role",""),
                                metadata={"email": email, "method": "password"})
                            st.rerun()
                    elif _lock_msg:
                        # Covers: brute-force lockout AND service-unavailable messages
                        st.error(f"🔒 {_lock_msg}")
                        _log_audit("AUTH","LOGIN_BLOCKED",
                            entity_type="USER", entity_id=_uname_l,
                            outcome="FAILURE", failure_reason=_lock_msg)
                    else:
                        _record_login_failure(_uname_l)
                        _log_audit("AUTH","LOGIN_FAILED",
                            entity_type="USER", entity_id=_uname_l,
                            actor_username=_uname_l,
                            outcome="FAILURE", failure_reason="Invalid credentials")
                        # Show remaining attempts without revealing account names
                        try:
                            conn = _get_db_conn()
                            if conn:
                                cur = conn.cursor()
                                cur.execute("SELECT failed_count FROM login_attempts WHERE username=%s",
                                            (_uname_l,))
                                row = cur.fetchone()
                                cur.close(); _release_db_conn(conn)
                                remaining = max(0, MAX_LOGIN_ATTEMPTS - (row[0] if row else 1))
                                if remaining > 0:
                                    st.error(f"❌ Invalid credentials. {remaining} attempt(s) remaining before lockout.")
                                else:
                                    st.error(f"❌ Account locked for {LOCKOUT_MINUTES} minutes.")
                        except Exception as _exc:
                            logger.warning("[_delete_custom_field] Suppressed exception", exc_info=_exc)
                            st.error("❌ Invalid credentials.")

    st.stop()

# ══════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style='display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0 0.4rem 0;'>
      <span style='font-size:1.1rem;'>🛡️</span>
      <span style='font-size:0.88rem;font-weight:700;color:#e2e8f0;'>UW Platform</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Top Sign Out button ──────────────────────────────────────────
    _top_col1, _top_col2 = st.columns([2,1])
    with _top_col1:
        st.markdown(f"<span style='font-size:0.75rem;color:#94a3b8;'>👤 {st.session_state.get('username','')}</span>", unsafe_allow_html=True)
    with _top_col2:
        if st.button('🚪 Logout', key='top_signout_btn', use_container_width=True):
            st.session_state.token = None
            st.session_state.last_result = None
            st.session_state.page = 'Underwriting Workbench'
            st.rerun()
    st.markdown('---')
    # ── Role-based page visibility ─────────────────────────────────────────
    _sidebar_role = st.session_state.get("role", "underwriter")
    _ROLE_PAGES = {
        "super_admin":        {"System Config","Product Config","Rule Builder",
                               "Underwriting Workbench","UW Queue","APS Abstraction",
                               "Batch Jobs","Member Data","Reinsurance","Audit Log","Dashboard","Getting Started","Tenants","User Management",
                               "Output Interface","Physician Registry","My Account"},
        "admin":              {"System Config","Product Config","Rule Builder",
                               "Underwriting Workbench","UW Queue","APS Abstraction",
                               "Batch Jobs","Member Data","Reinsurance","Audit Log","Dashboard","Getting Started","User Management",
                               "Output Interface","Physician Registry","My Account"},
        "senior_underwriter": {"Underwriting Workbench","UW Queue","APS Abstraction",
                               "Batch Jobs","Member Data","Reinsurance","Product Config","Audit Log","Dashboard","Getting Started",
                               "Output Interface","Physician Registry","My Account"},
        "underwriter":        {"Underwriting Workbench","UW Queue","APS Abstraction",
                               "Batch Jobs","Member Data","Dashboard","Getting Started","Physician Registry","My Account"},
        "case_manager":       {"Underwriting Workbench","UW Queue","APS Abstraction","My Account"},
        "viewer":             {"Underwriting Workbench","UW Queue","My Account"},
        "auditor":            {"Audit Log","Underwriting Workbench","UW Queue","My Account"},
    }
    _allowed_pages = _ROLE_PAGES.get(_sidebar_role,
                                     {"Underwriting Workbench","UW Queue","My Account"})

    NAV_GROUPS = [
        ("UNDERWRITING", [
            ("📝", "Underwriting Workbench"),
            ("📋", "UW Queue"),
            ("🧠", "APS Abstraction"),
            ("🩺", "Physician Registry"),
        ]),
        ("OPERATIONS", [
            ("📦", "Batch Jobs"),
            ("👤", "Member Data"),
            ("🏦", "Reinsurance"),
            ("📤", "Output Interface"),
        ]),
        ("ANALYTICS", [
            ("📊", "Dashboard"),
            ("🔍", "Audit Log"),
            ("🚀", "Getting Started"),
        ]),
        ("CONFIGURATION", [
            ("🔩", "System Config"),
            ("🔧", "Product Config"),
            ("⚙️",  "Rule Builder"),
        ]),
        ("ADMINISTRATION", [
            ("🏢", "Tenants"),
            ("👥", "User Management"),
        ]),
        ("ACCOUNT", [
            ("👤", "My Account"),
        ]),
    ]
    for group_label, items in NAV_GROUPS:
        visible = [i for i in items if i[1] in _allowed_pages]
        if not visible:
            continue
        st.markdown(
            f"<p style='font-size:0.6rem;text-transform:uppercase;letter-spacing:0.1em;"
            f"color:#475569;margin:6px 0 2px 2px;font-weight:600;'>{group_label}</p>",
            unsafe_allow_html=True
        )
        for icon, label in visible:
            active = st.session_state.page == label
            if st.button(f"{icon}  {label}", key=f"nav_{label}",
                         use_container_width=True,
                         type="primary" if active else "secondary"):
                st.session_state.page = label
                st.rerun()

    # Role badge
    _role_colors = {
        "super_admin":"#dc2626","admin":"#7c3aed",
        "senior_underwriter":"#0369a1","underwriter":"#059669",
        "case_manager":"#d97706","viewer":"#64748b","auditor":"#0891b2",
    }
    _rc = _role_colors.get(_sidebar_role, "#64748b")
    st.markdown(
        f"<div style='margin-top:8px;padding:4px 10px;border-radius:12px;"
        f"background:{_rc}22;border:1px solid {_rc}55;display:inline-block;'>"
        f"<span style='font-size:11px;color:{_rc};font-weight:600;'>"
        f"{_sidebar_role.replace('_',' ').title()}</span></div>",
        unsafe_allow_html=True
    )

    # Usage meter — cases this month
    try:
        _u = _get_usage_this_month()
        if _u["total"] > 0:
            st.markdown(
                f"<div style='margin:4px 0;padding:4px 8px;background:#1e2530;"
                f"border-radius:4px;font-size:0.68rem;color:#64748b;'>"
                f"📊 {_u['total']:,} decisions · {_u['month']}</div>",
                unsafe_allow_html=True
            )
    except Exception as _exc:
        logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)

    st.markdown("---")
    try:
        r = requests.get("http://localhost:8000/health", timeout=2)
        _api_ok = r.status_code == 200
        st.markdown(
            f"<span style='font-size:0.7rem;color:{'#10b981' if _api_ok else '#ef4444'};'>"
            f"{'🟢 API Online' if _api_ok else '🔴 API Offline'}</span>",
            unsafe_allow_html=True
        )
    except Exception as _exc:
        logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)
        st.markdown("<span style='font-size:0.7rem;color:#ef4444;'>🔴 API Offline</span>",
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] > div:first-child {
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        div[data-testid="stSidebarNav"] {
            flex: 1;
            overflow-y: auto;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    if st.button("🚪 Sign Out", key="signout_btn", use_container_width=True):
        _log_audit("AUTH","LOGOUT",
            entity_type="USER",
            entity_id=st.session_state.get("username",""),
            actor_username=st.session_state.get("username",""))
        st.session_state.token = None
        st.session_state.last_result = None
        st.session_state.page = "Underwriting Workbench"
        st.rerun()


# ══════════════════════════════════════════════════════════════
#  PAGE HEADER
# ══════════════════════════════════════════════════════════════
page = st.session_state.get("page", "Underwriting Workbench")

# ── Page-level access guard (defence-in-depth) ───────────────────────────────
_guard_role = st.session_state.get("role", "underwriter")
_GUARD_PAGES = {
    "super_admin":        {"System Config","Product Config","Rule Builder",
                           "Underwriting Workbench","UW Queue","APS Abstraction",
                           "Batch Jobs","Member Data","Reinsurance","Audit Log","Dashboard","Getting Started","Tenants","User Management",
                           "Output Interface","Physician Registry","My Account"},
    "admin":              {"System Config","Product Config","Rule Builder",
                           "Underwriting Workbench","UW Queue","APS Abstraction",
                           "Batch Jobs","Member Data","Reinsurance","Audit Log","Dashboard","Getting Started","User Management",
                           "Output Interface","Physician Registry","My Account"},
    "senior_underwriter": {"Underwriting Workbench","UW Queue","APS Abstraction",
                           "Batch Jobs","Member Data","Reinsurance","Product Config","Audit Log","Dashboard","Getting Started",
                           "Output Interface","Physician Registry","My Account"},
    "underwriter":        {"Underwriting Workbench","UW Queue","APS Abstraction",
                           "Batch Jobs","Member Data","Physician Registry","My Account"},
    "case_manager":       {"Underwriting Workbench","UW Queue","APS Abstraction","My Account"},
    "viewer":             {"Underwriting Workbench","UW Queue","My Account"},
    "auditor":            {"Audit Log","Underwriting Workbench","UW Queue","My Account"},
}
_guard_allowed = _GUARD_PAGES.get(_guard_role, {"Underwriting Workbench","UW Queue","My Account"})
if page not in _guard_allowed:
    st.error(
        f"🚫 **Access denied** — your role "
        f"(**{_guard_role.replace('_',' ').title()}**) "
        f"does not have permission to view **{page}**."
    )
    st.info("Contact your administrator if you need access to this page.")
    st.stop()

page_titles = {
    "Underwriting Workbench": ("📝", "Underwriting Workbench", "Individual & Group Life · Rules Engine v1.0.0"),
    "UW Queue":               ("📋", "UW Queue", "Cases assigned to underwriters · SLA tracking"),
    "APS Abstraction":        ("🧠", "APS Abstraction", "AI-powered APS document analysis · Claude extracts diagnoses, medications & debits"),
    "Batch Jobs":             ("📦", "Batch Jobs", "Scheduled & on-demand batch processing"),
    "Product Config":         ("🔧", "Product Config", "Product definitions · eligibility rules"),
    "Rule Builder":           ("⚙️",  "Rule Builder", "Custom underwriting rules · JSON engine"),
    "System Config":          ("🔩", "System Config", "Platform settings · currency · SLA · rate tables"),
    "Audit Log":              ("🔍", "Audit Log", "Full system event history"),
    "Tenants":                ("🏢", "Tenants", "Multi-tenant management"),
    "User Management":        ("👥", "User Management", "Users · roles · permissions"),
    "My Account":             ("👤", "My Account", "MFA setup · security · profile"),
    "Dashboard":              ("📊", "Dashboard", "Management reporting · KPIs · SLA · UW productivity"),
    "Reinsurance":            ("🏦", "Reinsurance", "RI cessions · slip generation · premium splits"),
    "Member Data":            ("👤", "Member Data", "Applicant master records · upload · search"),
    "Output Interface":       ("📤", "Output Interface", "PAS webhook push · CSV extract · field mapping"),
}
icon, title, subtitle = page_titles.get(page, ("🛡️", page, ""))
st.markdown(f"""
<div style='display:flex;align-items:center;gap:1rem;padding-bottom:1rem;
     border-bottom:1px solid #1e2530;margin-bottom:1.5rem;'>
  <span style='font-size:1.8rem;'>{icon}</span>
  <div>
    <div style='font-size:1.1rem;font-weight:600;color:#e2e8f0;'>{title}</div>
    <div style='font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;'>{subtitle}</div>
  </div>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
#  UNDERWRITING WORKBENCH PAGE
# ══════════════════════════════════════════════════════════════
if page == "Underwriting Workbench":
    tab1, tab2, tab3, tab4 = st.tabs(["⚡ Evaluate Application", "📋 Case History", "📊 Session Analytics", "📈 Platform Analytics"])

    # ══════════════════════════════════════════════════════════════
    #  TAB 1 — EVALUATE
    # ══════════════════════════════════════════════════════════════
    with tab1:
        # ── 3/2 column split: form (left) | decision card (right) ──────────
        form_col, card_col = st.columns([3, 2], gap="large")

        with form_col:

            st.markdown("##### Application Intake Form")
            # ── Product selectors OUTSIDE the form so banner updates live ──
            st.markdown("**📦 Product Selection**")
            _wb_products, _wb_categories = _load_all_products()

            # ── Refresh + Category row ──────────────────────────
            _wb_col1, _wb_col2 = st.columns([5, 1])
            with _wb_col1:
                category = st.selectbox(
                    "Product Category",
                    list(_wb_categories.keys()),
                    key="wb_category"
                )
            with _wb_col2:
                st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
                if st.button("🔄", key="wb_prod_refresh", help="Reload product list from DB"):
                    st.session_state.pop("all_products_merged", None)
                    st.session_state.pop("wb_prod_search", None)
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

            # ── Search filter to narrow the product list ─────────
            _all_in_cat = _wb_categories.get(category, [])
            _search_term = st.text_input(
                "🔍 Search product",
                key="wb_prod_search",
                placeholder="Type to filter...",
                label_visibility="collapsed"
            )
            if _search_term.strip():
                _q = _search_term.strip().lower()
                product_options = [
                    k for k in _all_in_cat
                    if _q in _wb_products.get(k, {}).get("name", k).lower()
                    or _q in k.lower()
                ]
                if not product_options:
                    st.caption("No products match your search.")
                    product_options = _all_in_cat  # fallback to all
            else:
                product_options = _all_in_cat

            selected_code = st.selectbox(
                "Product",
                product_options,
                format_func=lambda k: f"{k}  —  {_wb_products.get(k, {}).get('name', k)}",
                key="wb_product_select"
            )
            prod = _wb_products.get(selected_code, PRODUCTS.get(selected_code, {
                "name": selected_code, "category": category,
                "min_age": 18, "max_age": 70, "min_face": 0, "max_face": 0,
                "terms": [], "uw_method": "Full UW", "exam_note": "",
                "notes": "", "is_gi": False,
            }))

            terms_str = ", ".join(str(t) + "yr" for t in prod.get("terms",[])) if prod.get("terms") else "Permanent"
            _sym = get_currency_symbol()
            st.markdown(
                f'<div class="product-banner">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                f'<div>'
                f'<div class="product-name">{prod.get("name", selected_code)}</div>'
                f'<div class="product-meta">Ages {prod.get("min_age","?")}–{prod.get("max_age","?")} &nbsp;·&nbsp; '
                f'{_sym}{prod.get("min_face",0):,.0f}–{_sym}{prod.get("max_face",0):,.0f} &nbsp;·&nbsp; {terms_str}</div>'
                f'<div class="product-meta" style="color:#475569;margin-top:4px;">{prod.get("notes","")}</div>'
                f'</div>'
                f'<span class="product-pill">{prod.get("uw_method","Full UW")}</span>'
                f'</div></div>',
                unsafe_allow_html=True
            )

            with st.form("uw_form"):
                st.markdown(f"**Evaluating:** {prod['name']}")
                st.divider()

                # ── APPLICANT ──────────────────────────────────────
                st.markdown("**Applicant**")
                c1, c2, c3, c4 = st.columns(4)
                with c1: applicant_ref = st.text_input("Ref", "APP-001", help="Your internal reference number for this application. Appears on the decision report and in case history.")
                with c2: age    = st.number_input("Age", 1, 100, 40, help="Applicant age at last birthday. Each year-band has different mortality rates — a 40yr old pays less than a 41yr old.")
                with c3: gender = st.selectbox("Gender", ["MALE", "FEMALE"], help="Biological sex for mortality rating. Females have lower mortality at most ages and receive better rates.")
                _state_list = _get_state_codes()
                _state_default = min(43, len(_state_list)-1)
                with c4: state = st.selectbox("State", _state_list, index=_state_default,
                    help="State/province codes. Configure in System Config → State Codes.")

                # ── COVERAGE ───────────────────────────────────────
                st.markdown("**Coverage**")
                c1, c2 = st.columns(2)
                with c1:
                    face_amount = st.number_input(  # tooltip added below
                        "Face Amount ($)",
                        min_value=int(prod["min_face"]),
                        max_value=int(prod["max_face"]),
                        value=min(500_000, int(prod["max_face"])),
                        step=50_000
                    )
                with c2:
                    if prod["terms"]:
                        term_yrs = st.selectbox("Term (years)", prod["terms"])
                    else:
                        term_yrs = None
                        st.text_input("Coverage", "Permanent", disabled=True)

                from datetime import date as _date, timedelta as _td
                pc1, pc2 = st.columns(2)
                policy_eff = pc1.date_input(
                    "Policy Effective Date",
                    value=_date.today(),
                    help="Date coverage begins — used for rate lookups and rule evaluation")
                _default_exp = (
                    _date(policy_eff.year + term_yrs, policy_eff.month, policy_eff.day)
                    if prod["terms"] else None
                ) if prod.get("terms") else None
                policy_exp = pc2.date_input(
                    "Policy Expire Date",
                    value=_default_exp,
                    help="Date coverage ends — auto-calculated from term, editable for permanent products")

                st.markdown(f'<div class="exam-box">🔬 {prod["exam_note"]}</div>', unsafe_allow_html=True)
                st.divider()

                is_gi = prod["is_gi"]

                if not is_gi:
                    # ── BUILD ──────────────────────────────────────
                    st.markdown("**Build**")
                    use_build = st.checkbox("Enter height / weight", value=True, help="Enable to enter actual height and weight. The system calculates BMI and applies the product's Build Table to assign debit points. Disable if height/weight is unknown.")
                    height = weight = None
                    if use_build:
                        c1, c2 = st.columns(2)
                        with c1: height = st.number_input("Height (inches)", 54, 84, 70, help="Applicant height. Combined with weight to calculate BMI which the Build Table uses to assign debit points.")
                        with c2: weight = st.number_input("Weight (lbs)", 80, 400, 175, help="Applicant weight. BMI = weight(kg) / height(m)². Normal range 18.5–24.9. Higher BMI bands carry increasing debit points.")
                        if height and weight:
                            st.caption(f"Calculated BMI: **{round((weight / (height ** 2)) * 703, 1)}**")

                    # ── TOBACCO ────────────────────────────────────
                    st.markdown("**Tobacco**")
                    tobacco = st.selectbox("Status", ["NEVER","NON_SMOKER","SMOKER","CIGAR","CHEW","VAPE"], help="NEVER = never used. NON_SMOKER = quit >12 months ago. SMOKER/CIGAR/CHEW/VAPE = active users pay 2–3x higher mortality loading. Nicotine test may be required.")
                    tobacco_quit = None
                    if tobacco == "NON_SMOKER":
                        tobacco_quit = st.number_input("Years since quit", 0.0, 30.0, 2.0, step=0.5, help="Years since last tobacco use. Most products require 12–24 months tobacco-free for non-tobacco rates. Less than 12 months = tobacco rates apply.")

                    # ── BLOOD PRESSURE ─────────────────────────────
                    st.markdown("**Blood Pressure**")
                    use_bp = st.checkbox("Enter blood pressure", value=True, help="Enable to enter blood pressure readings. Used by the Hypertension rule (R020). Disable if BP reading is not available — rule will not fire.")
                    systolic = diastolic = bp_med = bp_med_cnt = None
                    if use_bp:
                        c1, c2, c3, c4 = st.columns(4)
                        with c1: systolic   = st.number_input("Systolic",  80, 220, 120, help="Top blood pressure number. Normal <120. Hypertension Stage 1 = 130–139. Stage 2 = 140+. Uncontrolled hypertension (160+) triggers higher debit points.")
                        with c2: diastolic  = st.number_input("Diastolic", 50, 140, 78, help="Bottom blood pressure number. Normal <80. Combined with systolic for hypertension rating. Diastolic 90+ = Stage 1, 100+ = Stage 2.")
                        with c3: bp_med     = st.checkbox("On BP meds", help="Whether applicant is on antihypertensive medication. Controlled hypertension on medication is rated more favourably than uncontrolled hypertension.")
                        with c4: bp_med_cnt = st.number_input("# meds", 0, 5, 0) if bp_med else 0

                    # ── DIABETES ───────────────────────────────────
                    st.markdown("**Diabetes**")
                    c1, c2, c3 = st.columns(3)
                    with c1: diabetes = st.selectbox("Type", ["NONE","PRE_DIABETIC","TYPE2","TYPE1"], help="NONE = no diagnosis. PRE_DIABETIC = elevated glucose, not yet diabetic. TYPE2 = adult-onset, often manageable. TYPE1 = juvenile, insulin-dependent, highest debit loading.")
                    with c2: dx_age   = st.number_input("Dx Age", 1, 100, 45, help="Age at diabetes diagnosis. Younger age at diagnosis = longer disease duration = more complications = higher debits.") if diabetes != "NONE" else None
                    with c3: a1c      = st.number_input("A1c %", 4.0, 15.0, 6.5, step=0.1, help="HbA1c measures average blood sugar over 3 months. <7% = well controlled. 7–9% = moderate. >9% = poorly controlled. Higher A1c = more debit points.") if diabetes != "NONE" else None

                    # ── CARDIAC ────────────────────────────────────
                    st.markdown("**Cardiac History**")
                    c1, c2 = st.columns(2)
                    with c1: heart     = st.selectbox("Condition", ["NONE","HYPERTENSION","HYPERTENSION_UNCONTROLLED","MI","ANGINA","CABG","STENT","ARRHYTHMIA"], help="MI = heart attack. CABG = bypass surgery. STENT = coronary stent placed. ARRHYTHMIA = irregular heartbeat. Each condition carries specific debit points based on severity and years since event.")
                    with c2: heart_yrs = st.number_input("Years ago", 0.0, 30.0, 2.0, step=0.5, help="Years since the cardiac event. More recent events carry higher debit points. Most products require 6–12 months post-event minimum before issuing.") if heart != "NONE" else None

                    # ── MEDICAL FLAGS ──────────────────────────────
                    st.markdown("**Medical Flags**")
                    c1, c2, c3, c4 = st.columns(4)
                    with c1: hiv       = st.checkbox("HIV+", help="HIV positive status. Hard stop (instant decline) on most individual life products. Some carriers offer HIV+ products — check product-specific rules.")
                    with c2: cirrhosis = st.checkbox("Cirrhosis", help="Liver cirrhosis. Hard stop on most products due to severe mortality impact.")
                    with c3: stroke    = st.checkbox("Stroke", help="History of stroke or TIA (mini-stroke). Significant debit loading. Date of event and residual deficits affect rating severity.")
                    with c4: kidney    = st.checkbox("Kidney disease", help="Chronic kidney disease. eGFR level determines severity — Stage 3 (eGFR 30–59) = rated, Stage 4–5 (<30) = typically decline.")
                    c1, c2, c3, c4 = st.columns(4)
                    with c1: depression = st.checkbox("Depression", help="History of depression. Single episode, well-controlled = mild debits. Recurrent or severe = higher rating. Hospitalisation significantly increases loading.")
                    with c2: dep_hosp   = st.checkbox("Dep. hospitalised", help="Whether applicant was hospitalised for depression/mental health. Inpatient psychiatric history carries substantially higher debit loading than outpatient treatment.")
                    with c3: epilepsy   = st.checkbox("Epilepsy", help="Seizure disorder. Well-controlled on medication = moderate debits. Uncontrolled seizures = possible decline. Type of seizures and medication compliance matter.")
                    with c4: copd       = st.checkbox("COPD", help="Chronic Obstructive Pulmonary Disease (emphysema/chronic bronchitis). FEV1 level determines severity. Mild COPD = rated. Severe = possible decline.")

                    # ── OCCUPATION ─────────────────────────────────
                    st.markdown("**Occupation**")
                    c1, c2 = st.columns(2)
                    with c1: occ_class = st.selectbox("Class", ["1","2","3","4","D"],
                        help="Occupation class 1 = professional/office (lowest risk). Class 2 = skilled. Class 3 = semi-skilled manual. Class 4 = heavy manual. D = declined occupations (mining, logging, offshore oil). Higher class = more debits.")
                    with c2: occ_title = st.text_input("Job Title", "Software Engineer", help="Applicant's specific job title. Combined with occupation class for more precise occupational hazard assessment.")

                    # ── DRIVING ────────────────────────────────────
                    st.markdown("**Driving Record**")
                    c1, c2 = st.columns(2)
                    with c1: dui_count = st.number_input("DUI / DWI (last 5yr)", 0, 5, 0, help="Drink-driving convictions in the past 5 years. 1 DUI = debit points. 2+ DUIs = typically decline. Indicates elevated accidental death risk.")
                    with c2: major_vio = st.number_input("Major violations (last 3yr)", 0, 5, 0, help="Reckless driving, excessive speeding (20mph+ over limit), hit-and-run in last 3 years. Multiple violations = elevated accidental death risk.")

                    # ── LIFESTYLE ──────────────────────────────────
                    st.markdown("**Lifestyle**")
                    c1, c2 = st.columns(2)
                    with c1: drinks = st.number_input("Alcohol drinks/week", 0, 100, 0, help="Standard drinks per week. 0–14 = low risk. 15–21 = moderate (debit points). 22+ = heavy use (significant debits). Self-reported; APS may be requested to verify.")
                    with c2: hazard = st.checkbox("Hazardous activity", help="Skydiving, scooter/motorcycle racing, private aviation, rock climbing, deep-sea diving etc. Triggers flat extra premium surcharge rather than debit points.")
                    hazard_types = []
                    if hazard:
                        hazard_types = st.multiselect("Activity type", [
                            "SKYDIVING","BASE_JUMPING","SCUBA_DEEP","MOTOR_RACING",
                            "MOTORCYCLES","MOUNTAINEERING","HANG_GLIDING","PRIVATE_PILOT"
                        ])

                    # ── LAB VALUES ─────────────────────────────────
                    st.markdown("**Lab Values** (optional)")
                    use_labs = st.checkbox("Enter lab results", help="Enable to enter lab values (cholesterol, eGFR). These feed the cardiovascular and kidney disease rules. Leave disabled if lab results are not yet available.")
                    total_chol = hdl = ldl = egfr_val = None
                    if use_labs:
                        c1, c2, c3, c4 = st.columns(4)
                        with c1: total_chol = st.number_input("Total Chol", 100, 400, 190, help="Total cholesterol in mg/dL. Desirable <200. Borderline 200–239. High 240+. Assessed alongside HDL ratio for cardiovascular risk.")
                        with c2: hdl        = st.number_input("HDL", 20, 150, 55, help="HDL (good) cholesterol in mg/dL. Low HDL <40 = increased cardiac risk. High HDL >60 = protective, may earn credit points.")
                        with c3: ldl        = st.number_input("LDL", 50, 300, 110, help="LDL (bad) cholesterol in mg/dL. Optimal <100. Near optimal 100–129. Borderline high 130–159. High 160+. Key cardiovascular risk factor.")
                        with c4: egfr_val   = st.number_input("eGFR", 5, 150, 75, help="Estimated Glomerular Filtration Rate — measures kidney function. Normal 90+. Stage 2 CKD = 60–89. Stage 3 = 30–59 (rated). Stage 4 = 15–29. Stage 5 <15 = decline.")

                    # ── FAMILY HISTORY ─────────────────────────────
                    st.markdown("**Family History**")
                    c1, c2 = st.columns(2)
                    with c1: fh_cardio = st.checkbox("CVD in parent/sibling before age 60", help="Family history of cardiovascular disease (heart attack, CABG, angina) in a first-degree relative before age 60. Indicates elevated hereditary cardiac risk — adds debit points.")
                    with c2: fh_stroke = st.checkbox("Stroke in parent/sibling before age 65", help="Family history of stroke in a first-degree relative before age 65. Combined with applicant's own BP/cholesterol profile for cerebrovascular risk assessment.")

                    # ── FINANCIAL ──────────────────────────────────
                    st.markdown("**Financial**")
                    c1, c2 = st.columns(2)
                    with c1: income       = st.number_input("Annual Income ($)", 0, 5_000_000, 100_000, step=10_000, help="Applicant annual income. Used for financial underwriting — face amount should not exceed 10–25x income (insurable interest). Very high face amounts relative to income may trigger financial UW review.")
                    with c2: existing_cov = st.number_input("Existing Life Coverage ($)", 0, 10_000_000, 0, step=50_000, help="Total existing life insurance already in force. New coverage + existing combined must be justifiable by income/net worth. Excess coverage is an underwriting red flag.")

                    # ── KEY PERSON extras ──────────────────────────
                    if selected_code == "IND-KEYMAN":
                        st.markdown("**Business Information**")
                        c1, c2 = st.columns(2)
                        with c1: st.number_input("Business Annual Revenue ($)", 0, 100_000_000, 1_000_000, step=100_000)
                        with c2: st.text_input("Key Person Role / Title", "CEO")

                else:
                    # Guaranteed Issue — no medical questions
                    st.info("✅ **Guaranteed Issue** — No individual medical underwriting required for this product.")
                    tobacco = "NEVER"; height = weight = None; use_build = False; use_bp = False
                    diabetes = "NONE"; heart = "NONE"; hiv = cirrhosis = stroke = kidney = False
                    depression = dep_hosp = epilepsy = copd = False
                    occ_class = "1"; occ_title = ""; dui_count = 0; major_vio = 0
                    drinks = 0; hazard = False; hazard_types = []
                    use_labs = False; total_chol = hdl = ldl = egfr_val = None
                    fh_cardio = fh_stroke = False; income = 50_000; existing_cov = 0
                    tobacco_quit = None; dx_age = a1c = heart_yrs = None
                    bp_med = False; bp_med_cnt = 0; systolic = diastolic = None

                submitted = st.form_submit_button("⚡ Run Underwriting Evaluation", use_container_width=True)

            # ── Submit ─────────────────────────────────────────────
            if submitted:
                # Run product validation first (error codes 1001–1008)
                _seed_product_error_codes()
                prod_errors = validate_product_for_submission(selected_code, age, face_amount)
                _hard_errors = [e for e in prod_errors if e["severity"] == "ERROR"]
                _warnings    = [e for e in prod_errors if e["severity"] == "WARNING"]

                for w in _warnings:
                    st.warning(f"⚠️ [{w['error_code']}] {w['message']}")

                if _hard_errors:
                    for e in _hard_errors:
                        st.error(
                            f"🚫 [{e['error_code']}] {e['message']} "
                            f"| Resolution: {e['resolution']}"
                        )
                else:
                    # Legacy eligibility check
                    elig_errors = check_eligibility(age, face_amount, selected_code)
                    if elig_errors:
                        for e in elig_errors:
                            st.error(e)
                if not _hard_errors and not check_eligibility(age, face_amount, selected_code):
                    pass
                if _hard_errors or check_eligibility(age, face_amount, selected_code):
                    pass
                elif True:
                    payload = {
                        "applicant_ref":      applicant_ref,
                        "age":                age,
                        "gender":             gender,
                        "state":              state,
                        "product_type":       "INDIVIDUAL_TERM",
                        "product_code":       selected_code,
                        "face_amount":        face_amount,
                        "coverage_term_yrs":  term_yrs or 20,
                        "policy_effective_date": str(policy_eff) if policy_eff else None,
                        "policy_expire_date":    str(policy_exp) if policy_exp else None,
                        "tobacco_status":     tobacco if not is_gi else "NEVER",
                        "tobacco_quit_years": tobacco_quit,
                        "heart_condition":    heart if not is_gi else "NONE",
                        "heart_event_years_ago": heart_yrs,
                        "diabetes_type":      diabetes if not is_gi else "NONE",
                        "diabetes_dx_age":    int(dx_age) if dx_age and not is_gi else None,
                        "a1c":                float(a1c) if a1c and not is_gi else None,
                        "hiv_positive":       hiv if not is_gi else False,
                        "cirrhosis":          cirrhosis if not is_gi else False,
                        "stroke_history":     stroke if not is_gi else False,
                        "kidney_disease":     kidney if not is_gi else False,
                        "depression_history":      depression if not is_gi else False,
                        "depression_hospitalized": dep_hosp if not is_gi else False,
                        "epilepsy":           epilepsy if not is_gi else False,
                        "copd":               copd if not is_gi else False,
                        "occupation_class":   occ_class,
                        "occupation_title":   occ_title,
                        "alcohol_drinks_week": drinks,
                        "hazardous_activity":  hazard,
                        "hazard_types":        hazard_types,
                        "financial": {
                            "annual_income":          income,
                            "existing_life_coverage": existing_cov,
                        },
                        "family_history": {
                            "cardiovascular_before_60": fh_cardio if not is_gi else False,
                            "stroke_before_65":         fh_stroke if not is_gi else False,
                            "cancer_history":   False,
                            "diabetes_history": False,
                        },
                        "driving_record": {
                            "dui_dwi_count_5yr":      dui_count,
                            "major_violations_3yr":   major_vio,
                            "minor_violations_3yr":   0,
                            "at_fault_accidents_3yr": 0,
                            "license_suspended":      False,
                        },
                    }
                    if not is_gi and use_build and height and weight:
                        payload["build"] = {"height_inches": height, "weight_lbs": weight}
                    if not is_gi and use_bp and systolic:
                        payload["blood_pressure"] = {
                            "systolic":        systolic,
                            "diastolic":       diastolic,
                            "on_medication":   bp_med or False,
                            "medication_count": int(bp_med_cnt or 0),
                        }
                    if not is_gi and use_labs and total_chol:
                        payload["labs"] = {
                            "total_cholesterol": total_chol,
                            "hdl_cholesterol":   hdl,
                            "ldl_cholesterol":   ldl,
                            "egfr":              egfr_val,
                        }

                    with st.spinner("Evaluating..."):
                        start = time.time()
                        result, status_code = evaluate(payload)
                        elapsed = round((time.time() - start) * 1000)

                    if status_code == 201:
                        st.session_state.last_result  = result
                        st.session_state.last_payload  = payload
                        st.session_state.last_product = prod
                        st.session_state.case_history.append({
                            "Ref":     applicant_ref,
                            "Product": prod["name"][:30],
                            "Age":     age,
                            "Outcome": result["outcome"],
                            "Pathway": result["pathway"],
                            "Debits":  result["net_debit_points"],
                            "ms":      elapsed,
                            "Time":    datetime.now().strftime("%H:%M:%S"),
                        })
                    else:
                        st.error(f"API Error {status_code}: {result}")


        with card_col:
            st.markdown("##### Decision Output")
            if st.session_state.last_result:
                r       = st.session_state.last_result
                prod    = st.session_state.last_product or {}
                outcome = r["outcome"]

                if "APPROVED" in outcome:   css, icon = "decision-approved", "✅"
                elif "DECLINE" in outcome:  css, icon = "decision-decline",  "🚫"
                elif "POSTPONE" in outcome: css, icon = "decision-postpone", "⏸️"
                else:                       css, icon = "decision-refer",    "👤"

                table_html = ""
                if r.get("table_rating"):
                    table_html += (
                        f"<div style='font-size:0.75rem;color:#f59e0b;margin-top:4px;'>"
                        f"Table {r['table_rating']}</div>"
                    )
                if r.get("flat_extra_per_thou"):
                    table_html += (
                        f"<div style='font-size:0.75rem;color:#fb923c;margin-top:4px;'>"
                        f"Flat Extra ${r['flat_extra_per_thou']}/K</div>"
                    )

                pathway_raw = r.get("pathway", "REFERRED")
                if r.get("is_stp") and "DECLINE" not in outcome:
                    pathway_label = "STRAIGHT THROUGH"
                elif "DECLINE" in outcome and pathway_raw == "INSTANT_DECLINE":
                    pathway_label = "INSTANT DECLINE"
                else:
                    pathway_label = pathway_raw.replace("_", " ")

                prod_name    = prod.get("name", "Decision")
                risk_class   = r.get("risk_class") or "—"
                net_debits   = r.get("net_debit_points", 0)
                outcome_text = outcome.replace("_", " ")

                card_html = (
                    f'<div class="{css}">'
                    f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                    f'<div>'
                    f'<div style="font-size:0.7rem;color:#94a3b8;text-transform:uppercase;'
                    f'letter-spacing:0.1em;margin-bottom:4px;">{prod_name}</div>'
                    f'<div class="outcome-badge">{icon} {outcome_text}</div>'
                    f'<div style="margin-top:6px;background:rgba(0,0,0,0.3);display:inline-block;'
                    f'padding:2px 10px;border-radius:20px;font-size:0.72rem;font-weight:600;">'
                    f'{pathway_label}</div>'
                    f'</div>'
                    f'<div style="text-align:right;">'
                    f'<div style="font-size:0.7rem;color:#94a3b8;">Risk Class</div>'
                    f'<div style="font-family:monospace;font-size:1rem;color:#e2e8f0;">'
                    f'{risk_class}</div>'
                    f'{table_html}'
                    f'</div>'
                    f'</div>'
                    f'</div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)

                # Key metrics row
                metrics = [
                    (f"{net_debits:+.0f}",        "Net Debits"),
                    (f"${r.get('approved_premium', 0):,.2f}" if r.get('approved_premium') else "—", "Annual Premium"),
                    (r.get("reinsurance_required") and "Yes" or "No",  "Reinsurance"),
                ]
                m_cols = st.columns(len(metrics))
                for mc, (val, label) in zip(m_cols, metrics):
                    mc.markdown(
                        f"<div class='metric-card'><div class='metric-value'>{val}</div>"
                        f"<div class='metric-label'>{label}</div></div>",
                        unsafe_allow_html=True
                    )

                # Policy dates row
                _eff_show = r.get("policy_effective_date") or (str(policy_eff) if "policy_eff" in dir() and policy_eff else "—")
                _exp_show = r.get("policy_expire_date")    or (str(policy_exp) if "policy_exp" in dir() and policy_exp else "—")
                st.caption(
                    f"📅 Policy Effective: **{str(_eff_show)[:10]}**"
                    f"  →  Expires: **{str(_exp_show)[:10]}**"
                )

                if r.get("adverse_action_text"):
                    st.markdown(
                        f"<div style='margin-top:0.75rem;padding:0.5rem 0.75rem;"
                        f"background:#2d1b1b;border-left:3px solid #ef4444;"
                        f"border-radius:4px;font-size:0.78rem;color:#fca5a5;'>"
                        f"⚠️ {r['adverse_action_text']}</div>",
                        unsafe_allow_html=True
                    )
            else:
                st.markdown("""
                <div style='text-align:center;padding:4rem 2rem;color:#4a5568;
                     border:1px dashed #1e2530;border-radius:12px;'>
                  <div style='font-size:2.5rem;margin-bottom:1rem;'>⚡</div>
                  <div style='font-size:0.9rem;'>
                    Select a product and fill in the form<br>
                    <strong style='color:#64748b;'>Run Underwriting Evaluation</strong>
                  </div>
                  <div style='font-size:0.75rem;margin-top:1rem;color:#374151;'>
                    Individual &amp; Group Life · Decisions in &lt;500ms
                  </div>
                </div>""", unsafe_allow_html=True)

        # ── FULL WIDTH DETAIL — below both columns ──────────────────────────
        if st.session_state.last_result:
            r    = st.session_state.last_result
            prod = st.session_state.last_product or {}
            st.divider()

            detail_col1, detail_col2 = st.columns([3, 2])

            with detail_col1:
                # Rules fired
                if r["rules_fired"]:
                    st.markdown("**Rules Fired**")
                    for f in r["rules_fired"]:
                        if f["hard_stop"]:
                            css2, pts = "rule-hardstop", "⛔ HARD STOP"
                        elif f.get("category") == "PRODUCT":
                            css2, pts = "rule-product", "📦 PRODUCT RULE"
                        elif f["debit_points"] > 0:
                            css2, pts = "rule-fired", f"+{f['debit_points']} db"
                        elif f["credit_points"] > 0:
                            css2, pts = "rule-credit", f"−{f['credit_points']} cr"
                        elif f["flat_extra"] > 0:
                            css2, pts = "rule-fired", f"FE ${f['flat_extra']}/K"
                        else:
                            css2, pts = "rule-fired", "refer"
                        expl  = f["explanation"]
                        short = expl[:120] + ("..." if len(expl) > 120 else "")
                        st.markdown(f"""
                        <div class="{css2}">
                          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.75rem;color:#64748b;">
                            [{f['rule_id']}]
                          </span>
                          <span style="color:#e2e8f0;margin:0 0.5rem;">{f['rule_name']}</span>
                          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;
                               color:#f59e0b;float:right;">{pts}</span>
                          <br>
                          <span style="color:#94a3b8;font-size:0.78rem;">→ {short}</span>
                        </div>""", unsafe_allow_html=True)

            with detail_col2:
                # Debit waterfall chart
                fired_pts = [f for f in r["rules_fired"] if f["debit_points"] > 0 or f["credit_points"] > 0]
                if fired_pts:
                    st.markdown("**Debit Breakdown**")
                    names  = [f["rule_name"] for f in fired_pts]   # full names, no truncation
                    values = [f["debit_points"] - f["credit_points"] for f in fired_pts]
                    colors = ["#ef4444" if v > 0 else "#10b981" for v in values]
                    # Point labels inside the bar so they never overflow
                    text_labels = [f"+{v} debits" if v > 0 else f"{v} credits" for v in values]
                    fig = go.Figure(go.Bar(
                        x=values, y=names, orientation="h",
                        marker_color=colors,
                        text=text_labels,
                        textposition="inside",
                        insidetextanchor="middle",
                        textfont=dict(color="white", size=12, family="monospace"),
                    ))
                    # Calculate left margin based on longest rule name
                    max_label_len = max(len(n) for n in names) if names else 20
                    left_margin = min(max_label_len * 7, 280)  # ~7px per char, cap at 280
                    fig.update_layout(
                        height=max(220, len(fired_pts) * 48),
                        margin=dict(l=left_margin, r=60, t=10, b=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#94a3b8", size=12),
                        xaxis=dict(
                            gridcolor="#1e2530", zerolinecolor="#475569",
                            tickfont=dict(size=11),
                            title="Points (debits = positive, credits = negative)",
                            title_font=dict(size=10, color="#64748b"),
                        ),
                        yaxis=dict(
                            gridcolor="rgba(0,0,0,0)",
                            tickfont=dict(size=12),
                            automargin=True,   # key: auto-expand margin for long labels
                        ),
                        showlegend=False,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # Adverse action + audit trail
                if r.get("adverse_action_text", "").strip():
                    with st.expander("📋 Adverse Action Notice (Regulatory)"):
                        st.markdown(
                            f'<div class="adverse-action">{r["adverse_action_text"]}</div>',
                            unsafe_allow_html=True
                        )
                with st.expander("🔍 Audit Trail"):
                    st.code(
                        f"Application ID : {r['application_id']}\n"
                        f"Case ID        : {r['case_id']}\n"
                        f"Decision ID    : {r['decision_id']}\n"
                        f"Rules Version  : {r['rules_version']}\n"
                        f"Policy Eff.    : {r.get('policy_effective_date','—')}\n"
                        f"Policy Exp.    : {r.get('policy_expire_date','—')}\n"
                        f"Evaluated At   : {r['evaluated_at']}",
                        language="text"
                    )

                # ── PDF / HTML Decision Report Download ────────────
                st.markdown("---")
                outcome_check = r.get("outcome", "")
                is_open_case  = r.get("status") in (
                    "OPEN", "IN_PROGRESS", "PENDING_REVIEW",
                    "PENDING_DATA", "PENDING_REQUIREMENTS"
                ) or r.get("pathway") in ("REFERRED", "PENDING_REQUIREMENTS")

                if is_open_case:
                    st.info(
                        "📋 **Open Case** — Decision report available once case is closed. "
                        "Download is disabled for cases still under review."
                    )
                else:
                    try:
                        file_bytes, filename = get_pdf_download_data(
                            r, st.session_state.last_product or {}
                        )
                        is_pdf = filename.endswith(".pdf")
                        st.download_button(
                            label     = "📄 Download Decision Report (PDF)" if is_pdf
                                        else "📄 Download Decision Report (HTML)",
                            data      = file_bytes,
                            file_name = filename,
                            mime      = "application/pdf" if is_pdf else "text/html",
                            use_container_width = True,
                            type      = "primary",
                            help      = "Download full underwriting decision report with rules fired, "
                                        "debit breakdown, audit IDs and adverse action notice"
                        )
                        if not is_pdf:
                            st.caption(
                                "💡 Install `weasyprint` for true PDF output: "
                                "`pip install weasyprint`"
                            )
                    except Exception as e:
                        st.error(f"Report generation failed: {e}")

                # ── AI Risk Scoring Panel ──────────────────────
                try:
                    from ai_engine.ai_scoring_panel import render_ai_scoring_panel
                    render_ai_scoring_panel(
                        evaluation_result=st.session_state.last_result or {},
                        applicant_data=st.session_state.get("last_payload", {})
                    )
                except Exception as _ai_err:
                    st.warning(f"AI scoring panel error: {_ai_err}")

    # ══════════════════════════════════════════════════════════════
    #  TAB 2 — CASE HISTORY
    # ══════════════════════════════════════════════════════════════
    with tab2:
        st.markdown("##### Case History")
        col_r, col_f = st.columns([1,3])
        if col_r.button("🔄 Refresh from database", use_container_width=True):
            st.session_state._db_cases = get_cases()

        # Auto-load on first visit
        if "_db_cases" not in st.session_state:
            st.session_state._db_cases = get_cases()

        db_cases = st.session_state._db_cases or []

        if db_cases:
            # Summary metrics
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total Cases", len(db_cases))
            m2.metric("Approved",  sum(1 for c in db_cases if c.get("status") == "APPROVED" or "APPROV" in (c.get("outcome") or "").upper()))
            m3.metric("Declined",  sum(1 for c in db_cases if c.get("status") == "DECLINED" or "DECLIN" in (c.get("outcome") or "").upper()))
            m4.metric("Referred",  sum(1 for c in db_cases if c.get("status") in ("OPEN","IN_PROGRESS","PENDING_REVIEW","PENDING_DATA","PENDING_REQUIREMENTS")))
            st.divider()

            rows = []
            for c in db_cases:
                status     = c.get("status", "—")
                outcome    = c.get("outcome") or ""
                risk_class = c.get("risk_class") or "—"
                net_debits = c.get("net_debit_points")
                ref        = c.get("applicant_ref") or c.get("ref") or "—"
                pathway    = c.get("pathway") or c.get("decision_pathway") or "—"
                # Determine emoji from status first, then outcome
                if status == "APPROVED" or "APPROV" in outcome:
                    emoji = "✅"
                elif status == "DECLINED" or "DECLIN" in outcome:
                    emoji = "🚫"
                elif "POSTPON" in outcome:
                    emoji = "⏸️"
                else:
                    emoji = "👤"
                rows.append({
                    "":          emoji,
                    "Case #":    c.get("case_number", ""),
                    "Ref":       ref,
                    "Status":    status,
                    "Outcome":   outcome if outcome and outcome not in (status, "—") else ("Pending" if status in ("OPEN","IN_PROGRESS","PENDING_REVIEW","PENDING_DATA","PENDING_REQUIREMENTS") else outcome),
                    "Risk Class": risk_class,
                    "Net Debits": net_debits if net_debits is not None else "—",
                    "Pathway":   pathway,
                    "Policy Eff":  str(c.get("policy_effective_date",""))[:10] if c.get("policy_effective_date") else "—",
                    "Policy Exp":  str(c.get("policy_expire_date",""))[:10]    if c.get("policy_expire_date")    else "—",
                    "Created":   str(c.get("created_at", ""))[:16].replace("T", " "),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                         height=min(600, 40 + len(rows)*38))
        elif st.session_state.case_history:
            st.caption("Showing session history (DB unavailable)")
            st.dataframe(pd.DataFrame(st.session_state.case_history),
                         use_container_width=True, hide_index=True)
        else:
            st.info("No cases yet. Submit an evaluation to see results here.")


    # ══════════════════════════════════════════════════════════════
    #  TAB 3 — ANALYTICS
    # ══════════════════════════════════════════════════════════════
    with tab3:
        st.markdown("##### Session Analytics")
        history = st.session_state.case_history
        # If no session history, fall back to DB cases for analytics
        if not history:
            db_c = st.session_state.get("_db_cases") or []
            if db_c:
                history = [
                    {
                        "Ref":     c.get("applicant_ref") or c.get("ref") or c.get("case_number","—"),
                        "Outcome": c.get("outcome") or c.get("status","—"),
                        "Pathway": c.get("pathway") or c.get("decision_pathway","—"),
                        "Debits":  c.get("net_debit_points", 0) or 0,
                        "Product": c.get("product_code","—"),
                    }
                    for c in db_c
                ]
        if not history:
            st.info("Submit evaluations to see analytics, or visit Case History tab to load from database.")
        else:
            df = pd.DataFrame(history)
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Total Evaluated", len(df))
            with c2: st.metric("Approved", int(df["Outcome"].str.contains("APPROVED").sum()))
            with c3: st.metric("Declined", int(df["Outcome"].str.contains("DECLINE").sum()))
            with c4:
                stp = df["Pathway"].str.contains("STRAIGHT_THROUGH|INSTANT", na=False).sum()
                st.metric("STP Rate", f"{int(stp / len(df) * 100)}%")

            c1, c2 = st.columns(2)
            with c1:
                oc = df["Outcome"].value_counts().reset_index()
                oc.columns = ["Outcome", "Count"]
                fig = px.pie(oc, values="Count", names="Outcome",
                             title="Decision Outcomes",
                             color_discrete_sequence=["#10b981","#ef4444","#f59e0b","#818cf8","#64748b"])
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#94a3b8")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                fig2 = px.bar(df, x="Ref", y="Debits", color="Product",
                              title="Net Debit Points by Application")
                fig2.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#94a3b8"
                )
                st.plotly_chart(fig2, use_container_width=True)

            if "ms" in df.columns:
                st.caption(f"Average decision time this session: **{df['ms'].mean():.0f}ms**")


    # ══════════════════════════════════════════════════════════════
    #  TAB 4 — PLATFORM ANALYTICS
    # ══════════════════════════════════════════════════════════════
    with tab4:
        st.markdown("##### 📈 Platform Analytics Dashboard")

        col_a, col_b, col_c = st.columns([1, 1, 1])
        with col_a:
            date_from_input = st.date_input("From", value=(datetime.now() - timedelta(days=30)).date())
        with col_b:
            date_to_input = st.date_input("To", value=datetime.now().date())
        with col_c:
            st.markdown("<br>", unsafe_allow_html=True)
            refresh_btn = st.button("🔄 Load Analytics", key="load_analytics")

        if refresh_btn or "analytics_data" not in st.session_state:
            try:
                r = requests.get(
                    f"http://localhost:8000/api/v1/analytics/summary",
                    headers=api_headers(),
                    params={"date_from": str(date_from_input), "date_to": str(date_to_input)},
                    timeout=10,
                )
                if r.status_code == 200:
                    st.session_state.analytics_data = r.json()
                else:
                    st.error(f"API error {r.status_code}: {r.text[:200]}")
                    st.session_state.analytics_data = None
            except Exception as e:
                st.error(f"Could not reach API: {e}")
                st.session_state.analytics_data = None

        adata = st.session_state.get("analytics_data")
        if adata:
            period = adata.get("period", {})
            st.caption(f"Period: {period.get('from')} → {period.get('to')}")

            # ── KPI Row ──────────────────────────────────────────────────────────
            outcomes = adata.get("outcomes", [])
            total    = sum(o["count"] for o in outcomes)
            approved = sum(o["count"] for o in outcomes if str(o.get("outcome","")).startswith("APPROVED"))
            declined = sum(o["count"] for o in outcomes if str(o.get("outcome","")).startswith("DECLIN"))
            stp_count= sum(o["count"] for o in outcomes if o.get("uw_pathway") in ("STRAIGHT_THROUGH","INSTANT_DECLINE"))
            stp_rate = f"{int(stp_count/total*100)}%" if total else "—"
            avg_ms   = sum((o.get("avg_ms") or 0)*o["count"] for o in outcomes) / total if total else 0

            k1,k2,k3,k4,k5 = st.columns(5)
            k1.metric("Total Cases", total)
            k2.metric("Approved", approved)
            k3.metric("Declined", declined)
            k4.metric("STP Rate", stp_rate)
            k5.metric("Avg Decision", f"{avg_ms:.0f}ms")

            st.markdown("---")

            # ── Charts row 1 ─────────────────────────────────────────────────────
            c1, c2 = st.columns(2)

            with c1:
                st.markdown("###### Decision Outcomes")
                if outcomes:
                    df_out = pd.DataFrame(outcomes)
                    fig = px.pie(df_out, values="count", names="outcome",
                                 color_discrete_sequence=["#10b981","#ef4444","#f59e0b","#818cf8","#64748b","#06b6d4"])
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#94a3b8", showlegend=True,
                                      margin=dict(t=10,b=10,l=10,r=10))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No outcome data")

            with c2:
                st.markdown("###### Daily Volume Trend")
                trend = adata.get("trend", [])
                if trend:
                    df_trend = pd.DataFrame(trend)
                    fig2 = go.Figure()
                    fig2.add_trace(go.Bar(x=df_trend["day"], y=df_trend["total"],
                                          name="Total", marker_color="#818cf8"))
                    fig2.add_trace(go.Scatter(x=df_trend["day"], y=df_trend["approved"],
                                              name="Approved", line=dict(color="#10b981", width=2)))
                    fig2.add_trace(go.Scatter(x=df_trend["day"], y=df_trend["declined"],
                                              name="Declined", line=dict(color="#ef4444", width=2)))
                    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                       font_color="#94a3b8", margin=dict(t=10,b=10,l=10,r=10),
                                       legend=dict(orientation="h", y=1.1))
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("No trend data")

            # ── Charts row 2 ─────────────────────────────────────────────────────
            c3, c4 = st.columns(2)

            with c3:
                st.markdown("###### Risk Class Distribution")
                risk_classes = adata.get("risk_classes", [])
                if risk_classes:
                    df_risk = pd.DataFrame(risk_classes)
                    fig3 = px.bar(df_risk, x="risk_class", y="count",
                                  color="count", color_continuous_scale="Blues")
                    fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                       font_color="#94a3b8", margin=dict(t=10,b=10,l=10,r=10),
                                       showlegend=False, coloraxis_showscale=False)
                    st.plotly_chart(fig3, use_container_width=True)
                else:
                    st.info("No risk class data")

            with c4:
                st.markdown("###### Top Fired Rules")
                top_rules = adata.get("top_rules", [])
                if top_rules:
                    df_rules = pd.DataFrame(top_rules).head(10)
                    fig4 = px.bar(df_rules, x="fire_count", y="rule_code", orientation="h",
                                  color="fire_count", color_continuous_scale="Oranges")
                    fig4.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                       font_color="#94a3b8", margin=dict(t=10,b=10,l=10,r=10),
                                       yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
                    st.plotly_chart(fig4, use_container_width=True)
                else:
                    st.info("No rule firing data for this period")

            # ── SLA & Batch ───────────────────────────────────────────────────────
            c5, c6 = st.columns(2)

            with c5:
                st.markdown("###### SLA Performance")
                sla = adata.get("sla", {})
                s1, s2, s3 = st.columns(3)
                s1.metric("Open Cases", sla.get("open_cases", 0))
                s2.metric("SLA Breached", sla.get("breached", 0),
                          delta=None if not sla.get("breached") else f"-{sla['breached']}",
                          delta_color="inverse")
                s3.metric("Avg SLA Hours", f"{sla.get('avg_sla_hours', 0):.1f}h")

            with c6:
                st.markdown("###### Batch Job Stats")
                batch = adata.get("batch", {})
                if "error" in batch:
                    st.warning(f"Batch stats unavailable: {batch['error']}")
                else:
                    b1, b2, b3 = st.columns(3)
                    b1.metric("Total Jobs", batch.get("total_jobs", 0))
                    b2.metric("Records", batch.get("total_records", 0))
                    b3.metric("Processed", batch.get("total_processed", 0))
        elif adata is None:
            st.info("Click **Load Analytics** to fetch platform data.")


    # ══════════════════════════════════════════════════════════════
    #  UW QUEUE PAGE
# ══════════════════════════════════════════════════════════════
elif page == "UW Queue":
    render_uw_queue()

elif page == "Batch Jobs":
    render_batch_jobs()

elif page == "Member Data":
    render_member_data()

elif page == "Audit Log":
    render_audit_log()

elif page == "My Account":
    render_my_account()

elif page == "Getting Started":
    render_onboarding()

elif page == "Reinsurance":
    render_reinsurance()

elif page == "Dashboard":
    render_management_dashboard()

elif page == "Tenants":
    render_tenant_management()

elif page == "User Management":
    render_user_management()

elif page == "Product Config":
    render_product_config()

elif page == "Rule Builder":
    render_rule_builder()
elif page == "APS Abstraction":
    st.markdown("## 🧠 APS AI Abstraction")
    st.caption("Upload Attending Physician Statements — Claude extracts diagnoses, medications, labs and suggests debit points.")
    render_aps_abstraction()

elif page == "System Config":
    render_system_config()

elif page == "Output Interface":
    import json as _oic_json_pg
    st.markdown("## 📤 Output Interface")
    st.caption(
        "Configure how underwriting decisions are pushed to your policy "
        "administration system — via webhook API push or file extract."
    )

    _oic_cfg = _get_output_interface_config()

    # ── Summary metrics ───────────────────────────────────────────────────────
    try:
        _conn_m = _get_db_conn()
        if _conn_m:
            _ensure_policy_admin_queue()
            _cur_m = _conn_m.cursor()
            _cur_m.execute("""
                SELECT
                    COUNT(*) FILTER(WHERE push_status='PUSHED')       AS pushed,
                    COUNT(*) FILTER(WHERE push_status='PUSH_FAILED')  AS failed,
                    COUNT(*) FILTER(WHERE push_status='PENDING')      AS pending,
                    COUNT(*) FILTER(WHERE status='UNPROCESSED')       AS unprocessed,
                    COUNT(*)                                           AS total
                FROM policy_admin_queue
            """)
            _ms = _cur_m.fetchone()
            _cur_m.close(); _conn_m.close()
            if _ms:
                _om1,_om2,_om3,_om4,_om5 = st.columns(5)
                _om1.metric("Total records",     f"{_ms[4]:,}")
                _om2.metric("Pushed to PAS",     f"{_ms[0]:,}")
                _om3.metric("Pending push",      f"{_ms[2]:,}",
                            delta=f"-{_ms[2]}" if _ms[2] else None,
                            delta_color="inverse")
                _om4.metric("Push failed",       f"{_ms[1]:,}",
                            delta=f"-{_ms[1]}" if _ms[1] else None,
                            delta_color="inverse")
                _om5.metric("Unextracted (CSV)", f"{_ms[3]:,}")
    except Exception as _exc:
        logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)

    st.divider()

    # ══════════════════════════════════════════════════════════════
    # BLOCK 1 — WEBHOOK PUSH CONFIG
    # ══════════════════════════════════════════════════════════════
    st.markdown("### 🌐 Block 1 — Webhook Push Configuration")
    st.caption(
        "Configure the PAS API endpoint. Once set, every new approved decision "
        "is pushed automatically. Use Block 3 to push existing backlog records."
    )

    with st.form("oic_webhook_form"):
        _wh1, _wh2 = st.columns([3, 1])
        _wc_url = _wh1.text_input(
            "PAS Webhook URL *",
            value=_oic_cfg.get("webhook_url", ""),
            placeholder="https://your-pas.example.com/api/v1/decisions",
            help="Full HTTPS URL of your policy admin system's inbound API endpoint."
        )
        _wc_method = _wh2.selectbox(
            "Method",
            ["POST", "PUT"],
            index=0 if _oic_cfg.get("webhook_method","POST") == "POST" else 1,
            help="HTTP method to use when calling the PAS endpoint."
        )

        _wa1, _wa2 = st.columns(2)
        _wc_auth = _wa1.selectbox(
            "Authentication",
            ["NONE", "BEARER", "API_KEY", "BASIC"],
            index=["NONE","BEARER","API_KEY","BASIC"].index(
                _oic_cfg.get("webhook_auth_type","NONE"))
            if _oic_cfg.get("webhook_auth_type","NONE")
               in ["NONE","BEARER","API_KEY","BASIC"] else 0,
            help="Authentication method for the PAS endpoint."
        )
        _wc_token = _wa2.text_input(
            "Token / Key / user:password",
            value=_oic_cfg.get("webhook_auth_value",""),
            type="password",
            help="Bearer token, API key value, or user:password for Basic auth."
        )

        _wb1, _wb2, _wb3 = st.columns(3)
        _wc_keyheader = _wb1.text_input(
            "API Key header name",
            value=_oic_cfg.get("webhook_api_key_header","X-API-Key"),
            help="Header name for API_KEY auth, e.g. X-API-Key or Authorization.",
        )
        _wc_timeout = _wb2.number_input(
            "Timeout (seconds)",
            min_value=5, max_value=120, value=int(_oic_cfg.get("webhook_timeout",15)),
            help="How long to wait for a response before failing."
        )
        _wc_retries = _wb3.number_input(
            "Max retries",
            min_value=1, max_value=10, value=int(_oic_cfg.get("webhook_max_retries",3)),
            help="How many times to retry a failed push before marking it PUSH_FAILED."
        )

        _wc_envelope = st.text_input(
            "Envelope key (optional)",
            value=_oic_cfg.get("webhook_envelope_key",""),
            placeholder='e.g. "decision" wraps payload as {"decision": {...}}',
            help="If your PAS expects the payload wrapped in a key, enter it here. Leave blank to POST the record directly."
        )
        _wc_custom_hdrs = st.text_area(
            "Custom headers (JSON object, optional)",
            value=_oic_cfg.get("webhook_custom_headers",""),
            placeholder='{"X-Client-ID": "UW-PLATFORM", "X-Version": "2"}',
            height=70,
            help="Additional headers to include in every webhook request, as a JSON object."
        )
        _wc_auto = st.checkbox(
            "Auto-push on every new decision",
            value=_oic_cfg.get("webhook_auto_push","1") == "1",
            help="When checked, every new decision is pushed to the PAS immediately as it is recorded."
        )

        if st.form_submit_button("💾 Save Webhook Config",
                                 use_container_width=True, type="primary"):
            _save_output_interface_config({
                **_oic_cfg,
                "webhook_url":         _wc_url.strip(),
                "webhook_method":      _wc_method,
                "webhook_auth_type":   _wc_auth,
                "webhook_auth_value":  _wc_token.strip(),
                "webhook_api_key_header": _wc_keyheader.strip() or "X-API-Key",
                "webhook_timeout":     str(_wc_timeout),
                "webhook_max_retries": str(_wc_retries),
                "webhook_envelope_key": _wc_envelope.strip(),
                "webhook_custom_headers": _wc_custom_hdrs.strip(),
                "webhook_auto_push":   "1" if _wc_auto else "0",
            })
            st.success("✅ Webhook configuration saved.")
            st.rerun()

    # Status badge
    _wurl = _oic_cfg.get("webhook_url","").strip()
    if _wurl:
        _auth_label = _oic_cfg.get("webhook_auth_type","NONE")
        _auto_label = "Auto-push ON" if _oic_cfg.get("webhook_auto_push","0")=="1" else "Manual push only"
        st.markdown(
            f"<div style='background:#0f2d1f;border:1px solid #10b981;border-radius:6px;"
            f"padding:6px 14px;font-size:0.8rem;color:#6ee7b7;display:inline-block;margin-top:4px;'>"
            f"🌐 {_wurl[:60]}{'…' if len(_wurl)>60 else ''} &nbsp;|&nbsp; "
            f"{_oic_cfg.get('webhook_method','POST')} &nbsp;|&nbsp; "
            f"Auth: {_auth_label} &nbsp;|&nbsp; {_auto_label}"
            f"</div>",
            unsafe_allow_html=True
        )

        # Test button
        if st.button("🧪 Test webhook with sample payload",
                     help="Send a test payload to verify connectivity and auth before going live."):
            _test_rec = {
                "applicant_ref": "TEST-001", "applicant_name": "Test Applicant",
                "product_code": "IND-TERM-20", "face_amount": 1000000,
                "outcome": "APPROVED", "risk_class": "STANDARD",
                "approved_premium": 12000.0, "decision_date": "2026-01-01",
                "source": "TEST", "_test": True
            }
            with st.spinner("Sending test payload..."):
                _tok, _hc, _terr = _push_to_pas(_test_rec, _get_output_interface_config())
            if _tok:
                st.success(f"✅ Test succeeded — HTTP {_hc}. Webhook is working correctly.")
            else:
                st.error(f"❌ Test failed: {_terr}")
    else:
        st.warning("⚠️ No webhook URL configured yet.")

    st.divider()

    # ══════════════════════════════════════════════════════════════
    # BLOCK 2 — FIELD MAPPING
    # ══════════════════════════════════════════════════════════════
    st.markdown("### 🗂️ Block 2 — Field Mapping")
    st.caption(
        "Map internal field names to the field names your PAS expects. "
        "Leave blank to use the internal name. Also controls which fields "
        "are included in CSV exports."
    )

    _AVAILABLE_COLS_PG = {
        "applicant_ref":     "Applicant reference",
        "applicant_name":    "Applicant name",
        "applicant_email":   "Applicant email",
        "case_id":           "Case ID",
        "job_id":            "Batch job ID",
        "product_code":      "Product code",
        "face_amount":       "Face amount",
        "age":               "Age",
        "gender":            "Gender",
        "state":             "State",
        "outcome":           "Outcome",
        "risk_class":        "Risk class",
        "net_debit_points":  "Net debit points",
        "approved_premium":  "Approved premium",
        "effective_date":    "Policy effective date",
        "expire_date":       "Policy expiry date",
        "decision_date":     "Decision date",
        "reason":            "Decision reason",
        "source":            "Source (ONLINE/BATCH)",
        "created_at":        "Record created at",
    }

    try:
        _saved_cols_pg = _oic_json_pg.loads(_oic_cfg.get("columns","[]"))
    except Exception as _exc:
        logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)
        _saved_cols_pg = []
    _default_cols_pg = _saved_cols_pg if _saved_cols_pg else list(_AVAILABLE_COLS_PG.keys())

    try:
        _field_map_saved = _oic_json_pg.loads(_oic_cfg.get("webhook_field_map","{}") or "{}")
    except Exception as _exc:
        logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)
        _field_map_saved = {}

    with st.form("oic_fieldmap_form"):
        st.markdown("**Select fields and optionally rename them for your PAS:**")
        _col_checks_pg = {}
        _col_renames   = {}
        for _ckey, _clabel in _AVAILABLE_COLS_PG.items():
            _fc1, _fc2, _fc3 = st.columns([1, 2, 2])
            _col_checks_pg[_ckey] = _fc1.checkbox(
                "", value=(_ckey in _default_cols_pg),
                key=f"oic_col_{_ckey}")
            _fc2.markdown(
                f"<div style='padding-top:6px;font-size:0.83rem;'>"
                f"<code>{_ckey}</code> — {_clabel}</div>",
                unsafe_allow_html=True)
            _col_renames[_ckey] = _fc3.text_input(
                "PAS field name",
                value=_field_map_saved.get(_ckey, ""),
                placeholder=_ckey,
                key=f"oic_rename_{_ckey}",
                label_visibility="collapsed")

        if st.form_submit_button("💾 Save Field Mapping",
                                 use_container_width=True, type="primary"):
            _sel = [k for k, v in _col_checks_pg.items() if v]
            _fmap = {k: v.strip() for k, v in _col_renames.items()
                     if v.strip() and v.strip() != k}
            if not _sel:
                st.error("Select at least one field.")
            else:
                _save_output_interface_config({
                    **_get_output_interface_config(),
                    "columns":            _oic_json_pg.dumps(_sel),
                    "webhook_field_map":  _oic_json_pg.dumps(_fmap),
                })
                st.success(f"✅ Field mapping saved — {len(_sel)} fields, {len(_fmap)} renamed.")
                st.rerun()

    st.divider()

    # ══════════════════════════════════════════════════════════════
    # BLOCK 3 — PUSH QUEUE
    # ══════════════════════════════════════════════════════════════
    st.markdown("### 🚀 Block 3 — Webhook Push Queue")
    st.caption(
        "Push pending records to the PAS webhook. Retry failed records. "
        "Every push is logged to the audit trail."
    )

    # Queue stats
    try:
        _conn_q = _get_db_conn()
        if _conn_q:
            _ensure_policy_admin_queue()
            _cur_q = _conn_q.cursor()
            _cur_q.execute("""
                SELECT push_status, COUNT(*),
                       MIN(created_at), MAX(created_at)
                FROM policy_admin_queue
                GROUP BY push_status
            """)
            _q_stats = {r[0]: r for r in _cur_q.fetchall()}
            _cur_q.close(); _conn_q.close()

            _pend = _q_stats.get("PENDING",   (None,0))[1]
            _fail = _q_stats.get("PUSH_FAILED",(None,0))[1]
            _ok   = _q_stats.get("PUSHED",    (None,0))[1]

            _bs1, _bs2, _bs3 = st.columns(3)
            _bs1.metric("Pending push",  f"{_pend:,}",
                        delta=f"-{_pend}" if _pend else None, delta_color="inverse")
            _bs2.metric("Push failed",   f"{_fail:,}",
                        delta=f"-{_fail}" if _fail else None, delta_color="inverse")
            _bs3.metric("Pushed OK",     f"{_ok:,}")
    except Exception as _qe:
        st.warning(f"Could not load push stats: {_qe}")

    _pb1, _pb2, _pb3 = st.columns([2,1,1])

    if _pb1.button("🚀 Push all pending to PAS",
                   type="primary", use_container_width=True,
                   key="run_push_btn",
                   help="Push all PENDING and PUSH_FAILED records to the PAS webhook."):
        if not _oic_cfg.get("webhook_url","").strip():
            st.error("❌ Configure webhook URL in Block 1 first.")
        else:
            with st.spinner("Pushing records to PAS..."):
                _res = _run_webhook_push()
            if _res.get("skipped") == -1:
                st.error("❌ No webhook URL configured.")
            else:
                if _res["pushed"]:
                    st.success(f"✅ Pushed {_res['pushed']} record(s) to PAS.")
                if _res["failed"]:
                    st.error(f"❌ {_res['failed']} record(s) failed — will retry on next push.")
                if not _res["pushed"] and not _res["failed"]:
                    st.info("No pending records to push.")
            if _res.get("details"):
                with st.expander(f"Push details ({_res['pushed']} pushed, {_res['failed']} failed)"):
                    for _d in _res["details"]:
                        st.caption(_d)
            st.rerun()

    if _pb2.button("🔁 Retry failed only",
                   use_container_width=True, key="retry_failed_btn",
                   help="Re-attempt only PUSH_FAILED records."):
        if not _oic_cfg.get("webhook_url","").strip():
            st.error("❌ Configure webhook URL in Block 1 first.")
        else:
            with st.spinner("Retrying failed records..."):
                _res2 = _run_webhook_push(limit=50)
            st.success(f"✅ {_res2['pushed']} pushed, {_res2['failed']} still failing.")
            st.rerun()

    if _pb3.button("🔄 Refresh", use_container_width=True, key="refresh_push"):
        st.rerun()

    # Failed records detail
    try:
        import pandas as _pd_oic
        _conn_f = _get_db_conn()
        if _conn_f:
            _cur_f = _conn_f.cursor()
            _cur_f.execute("""
                SELECT id, applicant_ref, applicant_name, outcome,
                       push_attempts, push_last_error, push_last_at, created_at
                FROM policy_admin_queue
                WHERE push_status = 'PUSH_FAILED'
                ORDER BY push_last_at DESC NULLS LAST
                LIMIT 30
            """)
            _fail_rows = _cur_f.fetchall()
            _cur_f.close(); _conn_f.close()
            if _fail_rows:
                st.markdown("##### Failed records")
                _df_f = _pd_oic.DataFrame(_fail_rows, columns=[
                    "ID","Applicant ref","Name","Outcome",
                    "Attempts","Last error","Last tried","Queued at"
                ])
                _df_f["Last tried"] = _df_f["Last tried"].astype(str).str[:16]
                _df_f["Queued at"]  = _df_f["Queued at"].astype(str).str[:16]
                st.dataframe(_df_f, use_container_width=True, hide_index=True)

                # Manual re-push single record
                _sel_id = st.selectbox(
                    "Re-push single record",
                    options=["—"] + [str(r[0]) for r in _fail_rows],
                    format_func=lambda x: "Select..." if x=="—" else
                        next((f"{r[1]} — {r[3]}" for r in _fail_rows
                              if str(r[0])==x), x),
                    key="repush_sel",
                    help="Select a specific failed record to re-push immediately."
                )
                if _sel_id != "—":
                    if st.button("🔁 Push this record now",
                                 key="repush_single", type="primary"):
                        try:
                            _conn_rp = _get_db_conn()
                            if _conn_rp:
                                _cur_rp = _conn_rp.cursor()
                                _cur_rp.execute("""
                                    SELECT applicant_ref, applicant_name, applicant_email,
                                           case_id, job_id, product_code, face_amount,
                                           age, gender, state, outcome, risk_class,
                                           net_debit_points, approved_premium,
                                           effective_date, expire_date,
                                           decision_date, reason, source
                                    FROM policy_admin_queue WHERE id=%s
                                """, (int(_sel_id),))
                                _single = _cur_rp.fetchone()
                                if _single:
                                    _srec = dict(zip([
                                        "applicant_ref","applicant_name","applicant_email",
                                        "case_id","job_id","product_code","face_amount",
                                        "age","gender","state","outcome","risk_class",
                                        "net_debit_points","approved_premium",
                                        "effective_date","expire_date",
                                        "decision_date","reason","source"
                                    ], _single))
                                    _sok, _shc, _serr = _push_to_pas(
                                        _srec, _get_output_interface_config())
                                    if _sok:
                                        _cur_rp.execute("""
                                            UPDATE policy_admin_queue SET
                                                push_status='PUSHED',
                                                push_attempts=push_attempts+1,
                                                push_last_at=NOW(),
                                                push_last_error=NULL,
                                                status='PROCESSED',
                                                processed_at=NOW()
                                            WHERE id=%s
                                        """, (int(_sel_id),))
                                        _conn_rp.commit()
                                        st.success(f"✅ Pushed — HTTP {_shc}")
                                    else:
                                        _cur_rp.execute("""
                                            UPDATE policy_admin_queue SET
                                                push_status='PUSH_FAILED',
                                                push_attempts=push_attempts+1,
                                                push_last_at=NOW(),
                                                push_last_error=%s
                                            WHERE id=%s
                                        """, (_serr[:500], int(_sel_id)))
                                        _conn_rp.commit()
                                        st.error(f"❌ Still failing: {_serr}")
                                _cur_rp.close(); _conn_rp.close()
                                st.rerun()
                        except Exception as _rpe:
                            st.error(f"Re-push error: {_rpe}")
    except Exception as _exc:
        logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)

    st.divider()

    # ══════════════════════════════════════════════════════════════
    # BLOCK 4 — CSV FILE EXTRACT (fallback)
    # ══════════════════════════════════════════════════════════════
    st.markdown("### 📁 Block 4 — CSV / Excel File Extract")
    st.caption(
        "Manual fallback extract — downloads a file for systems that cannot "
        "accept a webhook push. Records already pushed via webhook are excluded."
    )

    with st.form("oic_file_form"):
        _fb1, _fb2 = st.columns(2)
        oic_format = _fb1.selectbox(
            "File format",
            ["csv","excel"],
            index=0 if _oic_cfg.get("file_format","csv")=="csv" else 1,
            format_func=lambda x: "CSV" if x=="csv" else "Excel (.xlsx)",
            help="CSV is recommended for PAS integrations. Excel for human review."
        )
        oic_delim = _fb2.selectbox(
            "CSV delimiter",
            [",","|",";","\t"],
            index=[",","|",";","\t"].index(_oic_cfg.get("delimiter",","))
                  if _oic_cfg.get("delimiter",",") in [",","|",";","\t"] else 0,
            format_func=lambda x: {",":",(comma)","|":"| (pipe)",
                                    ";":"; (semi)","\t":"tab"}.get(x,x),
            disabled=(oic_format=="excel"),
            help="Delimiter for CSV output."
        )
        oic_prefix = st.text_input(
            "Filename prefix",
            value=_oic_cfg.get("filename_prefix","policy_admin"),
            help="Files named: {prefix}_{YYYYMMDD_HHMMSS}.csv"
        )
        if st.form_submit_button("💾 Save file settings",
                                 use_container_width=True):
            _save_output_interface_config({
                **_oic_cfg,
                "file_format": oic_format,
                "delimiter":   oic_delim,
                "filename_prefix": oic_prefix.strip() or "policy_admin",
            })
            st.success("✅ File settings saved.")
            st.rerun()

    if st.button("🚀 Run CSV Extract Now",
                 type="primary", use_container_width=True,
                 key="run_extract_btn"):
        with st.spinner("Extracting records..."):
            _ok_e, _fpath_e, _cnt_e, _msg_e = _run_policy_admin_extract()
        if _ok_e and _cnt_e > 0:
            st.success(f"✅ {_msg_e}")
            if _fpath_e:
                try:
                    with open(_fpath_e, "rb") as _ef:
                        st.download_button(
                            "📥 Download extract file",
                            data=_ef.read(),
                            file_name=_fpath_e.split("/")[-1],
                            mime=("application/vnd.openxmlformats-officedocument"
                                  ".spreadsheetml.sheet"
                                  if _fpath_e.endswith(".xlsx") else "text/csv"),
                            use_container_width=True,
                            type="primary",
                            key="dl_extract",
                        )
                except Exception as _exc:
                    logger.debug("[_delete_custom_field] Suppressed exception", exc_info=_exc)
        elif _ok_e and _cnt_e == 0:
            st.info("No unprocessed records — nothing to extract.")
        else:
            st.error(f"Extract failed: {_msg_e}")

    with st.expander("🔍 Preview unprocessed records (max 50)"):
        try:
            import pandas as _pd_prev
            _conn_pv = _get_db_conn()
            if _conn_pv:
                _cur_pv = _conn_pv.cursor()
                _cur_pv.execute("""
                    SELECT applicant_ref, applicant_name, product_code,
                           outcome, decision_date, push_status, source, created_at
                    FROM policy_admin_queue
                    WHERE status = 'UNPROCESSED'
                    ORDER BY created_at DESC LIMIT 50
                """)
                _pv_rows = _cur_pv.fetchall()
                _cur_pv.close(); _conn_pv.close()
                if _pv_rows:
                    st.dataframe(
                        _pd_prev.DataFrame(_pv_rows, columns=[
                            "Applicant ref","Name","Product","Outcome",
                            "Decision date","Push status","Source","Queued at"
                        ]),
                        use_container_width=True, hide_index=True
                    )
                else:
                    st.info("No unprocessed records.")
        except Exception as _pve:
            st.warning(f"Preview unavailable: {_pve}")


elif page == "Physician Registry":
    import pandas as _pd_phy
    from datetime import date as _date_phy
    st.markdown("## 🩺 Physician Registry")
    st.caption(
        "Manage the list of registered physicians for APS requests. "
        "Physicians here appear as a dropdown in the APS form — name, email "
        "and phone pre-fill automatically when selected."
    )
    _ensure_physician_table()
    st.session_state.pop("_physicians_cache", None)  # always fresh on this page

    # Show success/error messages that survived a rerun
    if st.session_state.get("_phy_msg_success"):
        st.success(st.session_state.pop("_phy_msg_success"))
    if st.session_state.get("_phy_msg_error"):
        st.error(st.session_state.pop("_phy_msg_error"))

    tab_list_phy, tab_add_phy = st.tabs(["📋 All Physicians", "➕ Add Physician"])

    # ── TAB 1: All Physicians ─────────────────────────────────────────────────
    with tab_list_phy:
        _phy_all = _load_physicians(active_only=False)
        if not _phy_all:
            st.info("No physicians registered yet. Use the **Add Physician** tab.")
        else:
            _phy_search = st.text_input(
                "🔍 Search", placeholder="name, clinic, city, specialisation…",
                key="phy_search"
            )
            if _phy_search:
                _q = _phy_search.lower()
                _phy_all = [p for p in _phy_all if
                            _q in p["physician_name"].lower() or
                            _q in p.get("clinic_name","").lower() or
                            _q in p.get("city","").lower() or
                            _q in p.get("specialisation","").lower() or
                            _q in p.get("registration_no","").lower()]

            st.caption(f"{len(_phy_all)} physician(s) found")

            # Table with data
            _phy_df = _pd_phy.DataFrame([{
                "Name":           p["physician_name"],
                "Reg No.":        p.get("registration_no","—") or "—",
                "Specialisation": p.get("specialisation","—") or "—",
                "Clinic":         p.get("clinic_name","—") or "—",
                "Email":          p.get("email","—") or "—",
                "Phone":          p.get("phone","—") or "—",
                "City":           p.get("city","—") or "—",
                "Effective":      str(p["effective_date"])[:10] if p.get("effective_date") else "—",
                "Expires":        str(p["expire_date"])[:10]    if p.get("expire_date")    else "—",
                "Status":         "✅ Active" if p.get("is_active") else "🔴 Inactive",
            } for p in _phy_all])
            st.dataframe(_phy_df, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("**Edit or Delete a Physician**")

            _phy_edit_opts = ["— select —"] + [
                f"{p['physician_name']}"
                + (f" | {p['registration_no']}" if p.get("registration_no") else "")
                + (f" | {p['city']}" if p.get("city") else "")
                for p in _phy_all
            ]
            _phy_edit_sel = st.selectbox(
                "Select physician",
                range(len(_phy_edit_opts)),
                format_func=lambda i: _phy_edit_opts[i],
                key="phy_edit_sel"
            )
            if _phy_edit_sel > 0:
                _ep = _phy_all[_phy_edit_sel - 1]

                with st.form("phy_edit_form"):
                    _ec1, _ec2 = st.columns(2)
                    _en  = _ec1.text_input("Name *",       value=_ep["physician_name"])
                    _ere = _ec2.text_input("Reg No.",       value=_ep.get("registration_no",""),
                                           help="Must be unique across all physicians.")
                    _es1, _es2 = st.columns(2)
                    _esp = _es1.text_input("Specialisation",value=_ep.get("specialisation",""))
                    _ecl = _es2.text_input("Clinic Name",   value=_ep.get("clinic_name",""))
                    _ee1, _ee2 = st.columns(2)
                    _eem = _ee1.text_input("Email *",       value=_ep.get("email",""),
                                           help="APS request letters sent here.")
                    _eph = _ee2.text_input("Phone",         value=_ep.get("phone",""))
                    _ead = st.text_input("Address",         value=_ep.get("address_line1",""))
                    _ef1, _ef2, _ef3 = st.columns(3)
                    _ect = _ef1.text_input("City",          value=_ep.get("city",""))
                    _est = _ef2.text_input("State",         value=_ep.get("state",""))
                    _epn = _ef3.text_input("Pincode",       value=_ep.get("pincode","") if "pincode" in _ep else "")
                    # Effective / Expire dates
                    _ed1, _ed2 = st.columns(2)
                    _eeff = _ed1.date_input(
                        "Effective Date",
                        value=_ep["effective_date"] if _ep.get("effective_date") else None,
                        help="Date from which this physician is available for APS requests."
                    )
                    _eexp = _ed2.date_input(
                        "Expire Date",
                        value=_ep["expire_date"] if _ep.get("expire_date") else None,
                        help="Date after which this physician should no longer be used. Leave blank = no expiry."
                    )
                    _eac = st.checkbox("Active", value=_ep.get("is_active", True))

                    _btn_s, _btn_d = st.columns(2)
                    _do_save = _btn_s.form_submit_button(
                        "💾 Save Changes", use_container_width=True, type="primary")
                    _do_del  = _btn_d.form_submit_button(
                        "🗑️ Delete Physician", use_container_width=True)

                if _do_save:
                    # Check unique reg no (exclude self)
                    if _ere.strip():
                        try:
                            _conn_chk = _get_db_conn()
                            if _conn_chk:
                                _cur_chk = _conn_chk.cursor()
                                _cur_chk.execute(
                                    "SELECT COUNT(*) FROM physicians "
                                    "WHERE registration_no=%s AND id!=%s",
                                    (_ere.strip(), _ep["id"])
                                )
                                if _cur_chk.fetchone()[0] > 0:
                                    st.error(f"Registration No. **{_ere.strip()}** is already used by another physician.")
                                    _cur_chk.close(); _conn_chk.close()
                        except Exception as _exc:
                            logger.warning("[_delete_custom_field] Suppressed exception", exc_info=_exc)
                    try:
                        _conn_e = _get_db_conn()
                        if _conn_e:
                            _cur_e = _conn_e.cursor()
                            _cur_e.execute("""
                                UPDATE physicians SET
                                    physician_name=%s, registration_no=%s,
                                    specialisation=%s, clinic_name=%s,
                                    email=%s, phone=%s, address_line1=%s,
                                    city=%s, state=%s, is_active=%s,
                                    effective_date=%s, expire_date=%s
                                WHERE id=%s
                            """, (_en, _ere.strip() or None, _esp, _ecl,
                                  _eem, _eph, _ead, _ect, _est, _eac,
                                  _eeff if _eeff else None,
                                  _eexp if _eexp else None,
                                  _ep["id"]))
                            _conn_e.commit(); _cur_e.close(); _conn_e.close()
                            st.session_state.pop("_physicians_cache", None)
                            st.session_state["_phy_msg_success"] = f"✅ Dr. {_en} updated successfully."
                            st.rerun()
                    except Exception as _ee:
                        st.error(f"Save failed: {_ee}")

                if _do_del:
                    try:
                        _conn_d = _get_db_conn()
                        if _conn_d:
                            _cur_d = _conn_d.cursor()
                            _cur_d.execute("DELETE FROM physicians WHERE id=%s", (_ep["id"],))
                            _conn_d.commit(); _cur_d.close(); _conn_d.close()
                            st.session_state.pop("_physicians_cache", None)
                            st.session_state["_phy_msg_success"] = (
                                f"✅ Dr. {_ep['physician_name']} deleted from registry."
                            )
                            st.rerun()
                    except Exception as _de:
                        st.error(f"Delete failed: {_de}")

    # ── TAB 2: Add Physician ──────────────────────────────────────────────────
    with tab_add_phy:
        st.markdown("#### Register New Physician")
        with st.form("phy_add_form"):
            _nc1, _nc2 = st.columns(2)
            _nn  = _nc1.text_input("Physician Name *", placeholder="Dr. Ramesh Kumar")
            _nre = _nc2.text_input("Registration No.", placeholder="MCI-123456",
                                    help="Medical council registration number. Must be unique.")
            _ns1, _ns2 = st.columns(2)
            _nsp = _ns1.text_input("Specialisation",   placeholder="Cardiologist")
            _ncl = _ns2.text_input("Clinic / Hospital", placeholder="Apollo Hospitals")
            _ne1, _ne2 = st.columns(2)
            _nem = _ne1.text_input("Email *",          placeholder="doctor@clinic.com",
                                    help="APS request letters will be emailed here.")
            _nph = _ne2.text_input("Phone",            placeholder="+91 98765 43210")
            _nad = st.text_input("Address",            placeholder="12 MG Road")
            _nf1, _nf2, _nf3 = st.columns(3)
            _nct = _nf1.text_input("City",             placeholder="Bengaluru")
            _nst = _nf2.text_input("State",            placeholder="KA")
            _npc = _nf3.text_input("Pincode",          placeholder="560001")
            # Effective / Expire dates
            _nd1, _nd2 = st.columns(2)
            _neff = _nd1.date_input(
                "Effective Date", value=None,
                help="Date from which this physician is active for APS requests. Leave blank = active immediately."
            )
            _nexp = _nd2.date_input(
                "Expire Date", value=None,
                help="Date after which this physician is no longer valid. Leave blank = no expiry."
            )

            if st.form_submit_button("➕ Register Physician",
                                      use_container_width=True, type="primary"):
                if not _nn.strip():
                    st.error("Physician Name is required.")
                elif not _nem.strip():
                    st.error("Email is required.")
                else:
                    try:
                        _conn_a = _get_db_conn()
                        if _conn_a:
                            _cur_a = _conn_a.cursor()
                            # Unique check on registration number
                            if _nre.strip():
                                _cur_a.execute(
                                    "SELECT COUNT(*) FROM physicians WHERE registration_no=%s",
                                    (_nre.strip(),)
                                )
                                if _cur_a.fetchone()[0] > 0:
                                    st.error(
                                        f"❌ Registration No. **{_nre.strip()}** already exists. "
                                        "Each physician must have a unique registration number."
                                    )
                                    _cur_a.close(); _conn_a.close()
                                    st.stop()
                            _cur_a.execute("""
                                INSERT INTO physicians
                                    (physician_name, registration_no, specialisation,
                                     clinic_name, email, phone, address_line1,
                                     city, state, pincode,
                                     effective_date, expire_date, is_active)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                            """, (_nn.strip(), _nre.strip() or None, _nsp.strip(),
                                  _ncl.strip(), _nem.strip(), _nph.strip(), _nad.strip(),
                                  _nct.strip(), _nst.strip(), _npc.strip(),
                                  _neff if _neff else None,
                                  _nexp if _nexp else None))
                            _conn_a.commit(); _cur_a.close(); _conn_a.close()
                            st.session_state.pop("_physicians_cache", None)
                            st.session_state["_phy_msg_success"] = (
                                f"✅ Dr. {_nn.strip()} registered successfully."
                            )
                            st.rerun()
                    except Exception as _ae:
                        st.error(f"Registration failed: {_ae}")

        # Success message rendered outside form — survives rerun
        if st.session_state.get("_phy_add_success"):
            st.success(st.session_state.pop("_phy_add_success"))
        if st.session_state.get("_phy_msg_success"):
            st.success(st.session_state.pop("_phy_msg_success"))
