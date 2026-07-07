"""
backend/services/notification.py
──────────────────────────────────
Email notifications for decision letters, APS requests, and batch completion.
Reads SMTP config from smtp_config table (mirrors Streamlit's approach).
Falls back to .env SMTP_* vars if table is empty.
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("uw_platform")

# ── Notification error codes (error_codes table, 5001-5008) ──────────────────
NOTIF_SMTP_NOT_CONFIGURED = "NOTIF_SMTP_NOT_CONFIGURED"   # 5001
NOTIF_SMTP_AUTH_FAILED    = "NOTIF_SMTP_AUTH_FAILED"      # 5002
NOTIF_RECIPIENT_MISSING   = "NOTIF_RECIPIENT_MISSING"     # 5003
NOTIF_SEND_TIMEOUT        = "NOTIF_SEND_TIMEOUT"          # 5004
NOTIF_SEND_FAILED         = "NOTIF_SEND_FAILED"           # 5005
NOTIF_RI_EMAIL_FAILED     = "NOTIF_RI_EMAIL_FAILED"       # 5006
NOTIF_APS_EMAIL_FAILED    = "NOTIF_APS_EMAIL_FAILED"      # 5007
NOTIF_TEMPLATE_NOT_FOUND  = "NOTIF_TEMPLATE_NOT_FOUND"    # 5008


def _classify_smtp_error(exc: Exception) -> str:
    """Map an SMTP exception to the appropriate error code."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return NOTIF_SMTP_AUTH_FAILED
    if isinstance(exc, smtplib.SMTPConnectError):
        return NOTIF_SEND_FAILED
    if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
        return NOTIF_SEND_TIMEOUT
    return NOTIF_SEND_FAILED


def _get_smtp_config(conn) -> dict:
    """Load SMTP settings from DB smtp_config table, fall back to env vars."""
    cfg: dict = {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM smtp_config")
        rows = cur.fetchall()
        cur.close()
        for r in rows:
            k, v = (r[0], r[1]) if isinstance(r, tuple) else (r["key"], r["value"])
            cfg[k] = v
    except Exception as exc:
        logger.warning("Could not load smtp_config from DB", exc_info=exc)

    # Fall back to env vars
    return {
        "host":     cfg.get("smtp_host")     or os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port":     int(cfg.get("smtp_port") or os.environ.get("SMTP_PORT", "587")),
        "user":     cfg.get("smtp_user")     or os.environ.get("SMTP_USER", ""),
        "password": cfg.get("smtp_password") or os.environ.get("SMTP_PASSWORD", ""),
        "from":     cfg.get("smtp_from")     or os.environ.get("SMTP_FROM", "noreply@riskuw.online"),
        "tls":      str(cfg.get("smtp_tls", "true")).lower() == "true",
    }


def _log_notification(conn, event: str, recipient: str, subject: str,
                       status: str, error_msg: Optional[str] = None,
                       applicant_ref: Optional[str] = None,
                       batch_job_name: Optional[str] = None,
                       error_code: Optional[str] = None) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO notification_log
                (event, recipient, subject, status, error_msg, error_code,
                 applicant_ref, batch_job_name, sent_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
            """,
            (event, recipient, subject, status, error_msg, error_code,
             applicant_ref, batch_job_name),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.warning("notification_log insert failed", exc_info=exc)


def _already_sent(conn, event: str, applicant_ref: str, window_seconds: int = 60) -> bool:
    """Deduplication — True if same event+ref was sent recently."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM notification_log
            WHERE event=%s AND applicant_ref=%s AND status='SENT'
              AND sent_at > now() - (%s || ' seconds')::interval
            LIMIT 1
        """, (event, applicant_ref, str(window_seconds)))
        found = cur.fetchone() is not None
        cur.close()
        return found
    except Exception:
        return False


def is_auto_email_enabled(conn, event: str = "AUTO_EMAIL_ENABLED") -> bool:
    """Check notification_config global + per-event switch."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT enabled FROM notification_config WHERE event='AUTO_EMAIL_ENABLED'")
        row = cur.fetchone()
        if row:
            g = (dict(row) if hasattr(row,"keys") else {"enabled":row[0]}).get("enabled", True)
            if not g:
                cur.close()
                return False
        if event != "AUTO_EMAIL_ENABLED":
            cur.execute("SELECT enabled FROM notification_config WHERE event=%s", (event,))
            er = cur.fetchone()
            if er:
                e = (dict(er) if hasattr(er,"keys") else {"enabled":er[0]}).get("enabled", True)
                if not e:
                    cur.close()
                    return False
        cur.close()
        return True
    except Exception:
        return True


def get_policy_number(conn, applicant_ref: str) -> str | None:
    """Look up issued policy number for an applicant."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT policy_number FROM policy
            WHERE applicant_ref=%s
            ORDER BY issue_date DESC NULLS LAST LIMIT 1
        """, (applicant_ref,))
        row = cur.fetchone()
        cur.close()
        if row:
            return (dict(row) if hasattr(row,"keys") else {"policy_number":row[0]}).get("policy_number")
    except Exception:
        pass
    return None


def log_missing_email_warning(conn, applicant_ref: str, outcome: str) -> None:
    """Log warning when approved case has no email address."""
    _log_notification(
        conn,
        event="DECISION_EMAIL",
        recipient="",
        subject=f"Email not sent — no email for {applicant_ref}",
        status="SKIPPED",
        error_msg=(f"Applicant {applicant_ref} approved ({outcome}) but has no email in "
                   f"applicant_master. Add email via Evaluate form."),
        applicant_ref=applicant_ref,
        error_code=NOTIF_RECIPIENT_MISSING,
    )
    logger.warning(
        f"[{NOTIF_RECIPIENT_MISSING}] No email for approved applicant "
        f"{applicant_ref} (outcome={outcome}) — decision email skipped"
    )


def send_email(conn, to_email: str, subject: str, html_body: str,
               event: str = "GENERIC",
               applicant_ref: Optional[str] = None,
               batch_job_name: Optional[str] = None) -> tuple[bool, str]:
    """
    Send a single email. Returns (success: bool, message: str).
    On failure, logs structured error code to notification_log for audit trail.
    """
    if not to_email or "@" not in to_email:
        msg = f"Invalid or missing recipient email: '{to_email}'"
        logger.warning(msg)
        _log_notification(conn, event, to_email or "", subject, "SKIPPED",
                          msg, applicant_ref, batch_job_name,
                          error_code=NOTIF_RECIPIENT_MISSING)
        return False, msg

    cfg = _get_smtp_config(conn)
    if not cfg["user"] or not cfg["password"]:
        msg = "SMTP not configured — set smtp_user and smtp_password in System Config → SMTP/Email"
        logger.warning(f"[{NOTIF_SMTP_NOT_CONFIGURED}] {msg}")
        _log_notification(conn, event, to_email, subject, "SKIPPED", msg,
                          applicant_ref, batch_job_name,
                          error_code=NOTIF_SMTP_NOT_CONFIGURED)
        return False, msg

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["from"]
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        port = int(cfg["port"])
        if port == 465:
            # Port 465 uses SSL directly
            import ssl
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], port, context=ctx, timeout=15) as server:
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from"], [to_email], msg.as_string())
        else:
            # Port 587 uses STARTTLS
            with smtplib.SMTP(cfg["host"], port, timeout=15) as server:
                if cfg["tls"]:
                    server.starttls()
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from"], [to_email], msg.as_string())

        _log_notification(conn, event, to_email, subject, "SENT",
                          applicant_ref=applicant_ref,
                          batch_job_name=batch_job_name)
        logger.info(f"Email sent: event={event} to={to_email} ref={applicant_ref}")
        return True, "sent"

    except smtplib.SMTPAuthenticationError as exc:
        err_code = NOTIF_SMTP_AUTH_FAILED
        err = f"[{err_code}] SMTP authentication failed — check smtp_user and smtp_password in System Config"
        logger.error(err)
        _log_notification(conn, event, to_email, subject, "FAILED", err,
                          applicant_ref, batch_job_name, error_code=err_code)
        return False, err

    except (TimeoutError, smtplib.SMTPConnectError) as exc:
        err_code = NOTIF_SEND_TIMEOUT
        err = f"[{err_code}] SMTP connection timed out — check smtp_host ({cfg['host']}) and smtp_port ({cfg['port']})"
        logger.error(err)
        _log_notification(conn, event, to_email, subject, "FAILED", err,
                          applicant_ref, batch_job_name, error_code=err_code)
        return False, err

    except Exception as exc:
        err_code = _classify_smtp_error(exc)
        err = f"[{err_code}] {str(exc)[:180]}"
        logger.error(f"send_email failed: {err}", exc_info=exc)
        _log_notification(conn, event, to_email, subject, "FAILED", err,
                          applicant_ref, batch_job_name, error_code=err_code)
        return False, err


def _already_sent(conn, event: str, applicant_ref: str, window_seconds: int = 60) -> bool:
    """Deduplication check — returns True if same event+ref was sent recently."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM notification_log
            WHERE event=%s AND applicant_ref=%s AND status='SENT'
              AND sent_at > now() - (%s || ' seconds')::interval
            LIMIT 1
        """, (event, applicant_ref, str(window_seconds)))
        found = cur.fetchone() is not None
        cur.close()
        return found
    except Exception:
        return False


def _get_letter_template(conn, outcome: str) -> dict | None:
    """Look up letter template for a given outcome from letter_templates."""
    try:
        cur = conn.cursor()
        tpl_outcome = "APPROVED" if "APPROVED" in outcome else outcome
        cur.execute("""
            SELECT template_name, body_text, next_steps,
                   header_company_name, contact_email, contact_phone, footer_text
            FROM letter_templates
            WHERE outcome = %s AND is_active = true
            LIMIT 1
        """, (tpl_outcome,))
        row = cur.fetchone()
        cur.close()
        if row:
            return dict(row) if hasattr(row,"keys") else {
                "template_name": row[0], "body_text": row[1], "next_steps": row[2],
                "header_company_name": row[3], "contact_email": row[4],
                "contact_phone": row[5], "footer_text": row[6],
            }
    except Exception as e:
        logger.warning(f"Template lookup failed: {e}")
    return None


def _render_template(template, variables: dict) -> str:
    if not template:
        return ""
    result = template
    for key, val in variables.items():
        result = result.replace("{" + key + "}", str(val) if val else "\u2014")
    return result


def _format_next_steps(next_steps_raw) -> str:
    if not next_steps_raw:
        return ""
    steps = [s.strip() for s in next_steps_raw.replace("\\n", "\n").split("\n") if s.strip()]
    if not steps:
        return ""
    items = "".join("<li style='margin-bottom:6px'>" + s + "</li>" for s in steps)
    return "<ol style='margin:0;padding-left:20px'>" + items + "</ol>"


def send_decision_email(
    conn,
    to_email: str,
    applicant_name: str,
    outcome: str,
    applicant_ref: str,
    product_name: str = "Life Insurance",
    premium: Optional[float] = None,
    risk_class: Optional[str] = None,
    premium_detail: dict | None = None,
) -> tuple[bool, str]:
    """Send decision notification email using letter_templates if available."""
    subject = "Underwriting Decision \u2014 " + applicant_ref + " \u2014 " + outcome.replace("_"," ")

    color = {
        "APPROVED_STP": "#22c55e", "APPROVED": "#22c55e", "APPROVED_RATED": "#22c55e",
        "DECLINED": "#ef4444", "REFERRED": "#f59e0b", "POSTPONED": "#c084fc",
    }.get(outcome, "#94a3b8")

    policy_number = get_policy_number(conn, applicant_ref)
    next_due = None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT policy_number, next_premium_due, annual_premium, modal_premium
            FROM policy WHERE applicant_ref=%s
            ORDER BY issue_date DESC NULLS LAST LIMIT 1
        """, (applicant_ref,))
        prow = cur.fetchone()
        cur.close()
        if prow:
            pd = dict(prow) if hasattr(prow,"keys") else {
                "policy_number":prow[0], "next_premium_due":prow[1],
                "annual_premium":prow[2], "modal_premium":prow[3]
            }
            policy_number = policy_number or pd.get("policy_number")
            next_due = pd.get("next_premium_due")
            # If next_premium_due is NULL, calculate from issue_date + 1 year
            if not next_due:
                try:
                    cur2 = conn.cursor()
                    cur2.execute("""
                        SELECT issue_date, commencement_date, premium_mode FROM policy
                        WHERE applicant_ref=%s
                        ORDER BY issue_date DESC NULLS LAST LIMIT 1
                    """, (applicant_ref,))
                    irow = cur2.fetchone()
                    cur2.close()
                    if irow:
                        idict = dict(irow) if hasattr(irow,"keys") else {"issue_date":irow[0],"commencement_date":irow[1],"premium_mode":irow[2]}
                        if True:  # Always calculate next due
                            from datetime import date as _date
                            # Use commencement date as base (not issue date)
                            from datetime import date as _date2
                            base = (idict.get("commencement_date") 
                                   or idict.get("issue_date") 
                                   or _date2.today())
                            mode = idict.get("premium_mode","ANNUAL")
                            months = {"ANNUAL":12,"HALF_YEARLY":6,"QUARTERLY":3,"MONTHLY":1}.get(mode,12)
                            m = base.month - 1 + months
                            yr = base.year + m // 12
                            mo = m % 12 + 1
                            next_due = _date(yr, mo, min(base.day, 28))
                except Exception:
                    pass
            if not premium and pd.get("modal_premium"):
                premium = float(pd["modal_premium"])
    except Exception as pe:
        logger.warning(f"Policy lookup in email failed: {pe}")

    # Get premium_mode from policy_admin_queue and calculate modal premium
    premium_mode = "ANNUAL"
    try:
        _cur = conn.cursor()
        _cur.execute("""
            SELECT premium_mode, approved_premium FROM policy_admin_queue
            WHERE applicant_ref=%s ORDER BY decision_date DESC LIMIT 1
        """, (applicant_ref,))
        _qrow = _cur.fetchone()
        _cur.close()
        if _qrow:
            _qd = dict(_qrow) if hasattr(_qrow,"keys") else {"premium_mode":_qrow[0],"approved_premium":_qrow[1]}
            premium_mode = _qd.get("premium_mode") or "ANNUAL"
            if _qd.get("approved_premium"):
                # Use premium_detail.all_modes for accurate modal premium (includes loading/GST)
                _mode_key = {"ANNUAL":"ANNUAL","HALF_YEARLY":"HALF_YEARLY",
                             "QUARTERLY":"QUARTERLY","MONTHLY":"MONTHLY"}.get(premium_mode,"ANNUAL")
                _modal = (premium_detail or {}).get("all_modes",{}).get(_mode_key,{}).get("modal_premium")
                if _modal:
                    premium = float(_modal)
                else:
                    # Fallback: simple division
                    _annual = float(_qd["approved_premium"])
                    _divisor = {"ANNUAL":1,"HALF_YEARLY":2,"QUARTERLY":4,"MONTHLY":12}.get(premium_mode,1)
                    premium = round(_annual / _divisor, 2)
    except Exception as _pm_err:
        logger.warning(f"premium_mode lookup failed: {_pm_err}")

    mode_labels = {"ANNUAL":"Annual","HALF_YEARLY":"Half-Yearly","QUARTERLY":"Quarterly","MONTHLY":"Monthly"}
    premium_label = mode_labels.get(premium_mode, "Annual") + " Premium"

    variables = {
        "applicant_name": applicant_name or "Applicant",
        "applicant_ref":  applicant_ref,
        "outcome":        outcome.replace("_", " "),
        "product_name":   product_name,
        "risk_class":     risk_class or "Standard",
        "premium":        ("%.2f" % premium) if premium else "\u2014",
        "premium_label":  premium_label,
        "premium_mode":   premium_mode,
        "policy_number":  policy_number or "\u2014",
        "next_due_date":  str(next_due) if next_due else "\u2014",
    }

    tpl = _get_letter_template(conn, outcome)

    if tpl:
        body_html = _render_template(tpl.get("body_text",""), variables)
        next_steps_html = _format_next_steps(tpl.get("next_steps"))
        company = tpl.get("header_company_name") or "RiskUW Underwriting"
        footer  = _render_template(tpl.get("footer_text",""), variables)
        contact_email = tpl.get("contact_email","") or ""
        contact_phone = tpl.get("contact_phone","") or ""
        contact_line = ""
        if contact_email or contact_phone:
            contact_line = "<p style='color:#555;font-size:13px'>Contact: " + contact_email + " " + contact_phone + "</p>"

        policy_block = ""
        if policy_number and policy_number != "\u2014":
            policy_block = ("<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;"
                "padding:14px 16px;margin:14px 0'><strong style='color:#166534'>Policy Number:</strong> "
                "<span style='font-family:monospace;font-size:16px;color:#15803d;font-weight:bold'> "
                + policy_number + "</span><br><small style='color:#555'>Quote this number in all future correspondence.</small></div>")

        premium_row = ""
        if premium:
            premium_row = ("<tr style='background:#f0f4f4'><td style='padding:8px 12px;border:1px solid #e2e8f0;"
                "font-weight:bold;font-size:13px'>" + premium_label + "</td><td style='padding:8px 12px;border:1px solid #e2e8f0;"
                "font-size:13px'><strong>" + ("%.2f" % premium) + "</strong></td></tr>")

        due_row = ""
        if next_due:
            due_row = ("<tr><td style='padding:8px 12px;border:1px solid #e2e8f0;font-weight:bold;font-size:13px'>"
                "Next Premium Due</td><td style='padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;color:#dc2626'>"
                "<strong>" + str(next_due) + "</strong></td></tr>")

        steps_block = ""
        if next_steps_html:
            steps_block = ("<div style='margin:16px 0'><strong style='color:#374151'>Next Steps:</strong>"
                "<div style='margin-top:8px'>" + next_steps_html + "</div></div>")

        html = ("<div style=\"font-family:Arial,sans-serif;max-width:600px;margin:auto\">"
          "<div style=\"background:#0a1628;padding:24px;border-radius:8px 8px 0 0\">"
          "<h2 style=\"color:#00d4aa;margin:0\">\U0001F6E1\uFE0F " + company + "</h2></div>"
          "<div style=\"background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0\">"
          "<p>Dear " + (applicant_name or "Applicant") + ",</p>"
          "<div style=\"background:" + color + "18;border-left:4px solid " + color + ";"
          "padding:14px 16px;margin:16px 0;border-radius:4px\">"
          "<strong style=\"color:" + color + ";font-size:18px\">" + outcome.replace("_"," ") + "</strong></div>"
          "<p style=\"color:#374151;line-height:1.7\">" + body_html + "</p>"
          + policy_block +
          "<table style=\"width:100%;border-collapse:collapse;margin:16px 0\">"
          "<tr style=\"background:#f0f4f4\"><td style=\"padding:8px 12px;border:1px solid #e2e8f0;"
          "font-weight:bold;font-size:13px\">Product</td><td style=\"padding:8px 12px;border:1px solid #e2e8f0;"
          "font-size:13px\">" + product_name + "</td></tr>"
          "<tr><td style=\"padding:8px 12px;border:1px solid #e2e8f0;font-weight:bold;font-size:13px\">Risk Class</td>"
          "<td style=\"padding:8px 12px;border:1px solid #e2e8f0;font-size:13px\">" + (risk_class or "Standard") + "</td></tr>"
          + premium_row + due_row +
          "</table>" + steps_block + contact_line +
          "<hr style=\"margin:16px 0;border-color:#e2e8f0\">"
          "<small style=\"color:#94a3b8\">" + (footer or "This is an automated notification. For queries, contact your underwriting team.") + "</small>"
          "</div></div>")
    else:
        policy_line = ""
        if policy_number and policy_number != "\u2014":
            policy_line = ("<p><strong>Policy Number:</strong> <span style='font-family:monospace;color:#15803d;"
                "font-weight:bold'>" + policy_number + "</span></p>")
        due_line = ""
        if next_due:
            due_line = "<p><strong>Next Premium Due:</strong> <span style='color:#dc2626'>" + str(next_due) + "</span></p>"
        premium_line = ""
        if premium:
            premium_line = "<p><strong>Premium:</strong> " + ("%.2f" % premium) + "</p>"

        html = ("<div style=\"font-family:Arial,sans-serif;max-width:600px;margin:auto\">"
          "<div style=\"background:#0a1628;padding:24px;border-radius:8px 8px 0 0\">"
          "<h2 style=\"color:#00d4aa;margin:0\">\U0001F6E1\uFE0F RiskUW \u2014 Underwriting Decision</h2></div>"
          "<div style=\"background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0\">"
          "<p>Dear " + (applicant_name or "Applicant") + ",</p>"
          "<p>Your application <strong>" + applicant_ref + "</strong> has been reviewed.</p>"
          "<div style=\"background:" + color + "18;border-left:4px solid " + color + ";padding:14px;margin:16px 0;"
          "border-radius:4px\"><strong style=\"color:" + color + ";font-size:18px\">" + outcome.replace("_"," ") + "</strong></div>"
          "<p><strong>Product:</strong> " + product_name + " | <strong>Risk Class:</strong> " + (risk_class or "\u2014") + "</p>"
          + premium_line + policy_line + due_line +
          "<hr style=\"margin:16px 0;border-color:#e2e8f0\">"
          "<small style=\"color:#94a3b8\">Automated notification from RiskUW. Contact your underwriting team for queries.</small>"
          "</div></div>")

    if not is_auto_email_enabled(conn, "STP_APPROVAL_EMAIL"):
        logger.info("Auto email disabled \u2014 skipping decision email for " + applicant_ref)
        return False, "auto_email_disabled"

    if _already_sent(conn, "DECISION_EMAIL", applicant_ref, window_seconds=60):
        logger.info("Decision email skipped (duplicate) for " + applicant_ref)
        return True, "skipped_duplicate"

    return send_email(conn, to_email, subject, html,
                      event="DECISION_EMAIL", applicant_ref=applicant_ref)


def send_aps_request_email(
    conn,
    physician_email: str,
    physician_name: str,
    applicant_name: str,
    applicant_ref: str,
    requested_items: list[str] | None = None,
) -> tuple[bool, str]:
    """Send APS request letter to a physician."""
    subject = f"Request for Attending Physician Statement — {applicant_ref}"
    items_html = ""
    if requested_items:
        items_html = "<ul>" + "".join(f"<li>{i}</li>" for i in requested_items) + "</ul>"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#0a1628;padding:24px;border-radius:8px 8px 0 0">
        <h2 style="color:#00d4aa;margin:0">🛡️ RiskUW — APS Request</h2>
      </div>
      <div style="background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0">
        <p>Dear Dr. {physician_name},</p>
        <p>We are writing to request an Attending Physician Statement for:</p>
        <p><strong>Patient Reference:</strong> {applicant_ref}<br>
           <strong>Patient Name:</strong> {applicant_name or 'As known to you'}</p>
        <p>Please provide the following information:</p>
        {items_html or '<ul><li>Complete medical history</li><li>Current medications</li><li>Latest clinical findings</li></ul>'}
        <p>Kindly respond at your earliest convenience. Your cooperation is greatly appreciated.</p>
        <hr style="margin:16px 0;border-color:#e2e8f0">
        <small style="color:#94a3b8">RiskUW Automated Underwriting Platform</small>
      </div>
    </div>
    """
    ok, msg = send_email(conn, physician_email, subject, html,
                      event="APS_REQUEST", applicant_ref=applicant_ref)
    if not ok:
        logger.warning(f"[{NOTIF_APS_EMAIL_FAILED}] APS email failed for {applicant_ref}: {msg}")
    return ok, msg


def send_ri_notification(
    conn,
    reinsurer_email: str,
    reinsurer_name: str,
    cession_ref: str,
    applicant_ref: str,
    product_code: str,
    face_amount: float,
    ceded_amount: float,
    ri_premium: float,
    currency_symbol: str = "₹",
) -> tuple[bool, str]:
    """Send reinsurance cession notification to the reinsurer."""
    subject = f"New Reinsurance Cession — {cession_ref} — {applicant_ref}"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#0a1628;padding:24px;border-radius:8px 8px 0 0">
        <h2 style="color:#00d4aa;margin:0">🛡️ RiskUW — Reinsurance Cession Notice</h2>
      </div>
      <div style="background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0">
        <p>Dear {reinsurer_name} Treaty Team,</p>
        <p>A new facultative reinsurance cession has been registered on the RiskUW platform.</p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0">
          <tr style="background:#f0f4f4">
            <td style="padding:10px;border:1px solid #e2e8f0;font-weight:bold">Cession Reference</td>
            <td style="padding:10px;border:1px solid #e2e8f0;font-family:monospace">{cession_ref}</td>
          </tr>
          <tr>
            <td style="padding:10px;border:1px solid #e2e8f0;font-weight:bold">Applicant Reference</td>
            <td style="padding:10px;border:1px solid #e2e8f0">{applicant_ref}</td>
          </tr>
          <tr style="background:#f0f4f4">
            <td style="padding:10px;border:1px solid #e2e8f0;font-weight:bold">Product</td>
            <td style="padding:10px;border:1px solid #e2e8f0">{product_code}</td>
          </tr>
          <tr>
            <td style="padding:10px;border:1px solid #e2e8f0;font-weight:bold">Gross Sum Assured</td>
            <td style="padding:10px;border:1px solid #e2e8f0">{currency_symbol}{face_amount:,.0f}</td>
          </tr>
          <tr style="background:#f0f4f4">
            <td style="padding:10px;border:1px solid #e2e8f0;font-weight:bold">Ceded Amount</td>
            <td style="padding:10px;border:1px solid #e2e8f0"><strong>{currency_symbol}{ceded_amount:,.0f}</strong></td>
          </tr>
          <tr>
            <td style="padding:10px;border:1px solid #e2e8f0;font-weight:bold">RI Premium</td>
            <td style="padding:10px;border:1px solid #e2e8f0">{currency_symbol}{ri_premium:,.0f}</td>
          </tr>
        </table>
        <p>The RI slip will be generated and sent separately. Please acknowledge receipt of this cession notice.</p>
        <hr style="margin:16px 0;border-color:#e2e8f0">
        <small style="color:#94a3b8">RiskUW Automated Underwriting Platform — riskuw.online</small>
      </div>
    </div>
    """
    ok, msg = send_email(conn, reinsurer_email, subject, html,
                         event="RI_CESSION", applicant_ref=applicant_ref)
    if not ok:
        logger.warning(f"[{NOTIF_RI_EMAIL_FAILED}] RI email failed for {cession_ref}: {msg}")
    return ok, msg

