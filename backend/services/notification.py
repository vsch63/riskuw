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
                       batch_job_name: Optional[str] = None) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO notification_log
                (event, recipient, subject, status, error_msg,
                 applicant_ref, batch_job_name, sent_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now())
            """,
            (event, recipient, subject, status, error_msg,
             applicant_ref, batch_job_name),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.warning("notification_log insert failed", exc_info=exc)


def send_email(conn, to_email: str, subject: str, html_body: str,
               event: str = "GENERIC",
               applicant_ref: Optional[str] = None,
               batch_job_name: Optional[str] = None) -> tuple[bool, str]:
    """
    Send a single email. Returns (success: bool, message: str).
    """
    cfg = _get_smtp_config(conn)
    if not cfg["user"] or not cfg["password"]:
        msg = "SMTP not configured — set smtp_user and smtp_password in smtp_config table or .env"
        logger.warning(msg)
        _log_notification(conn, event, to_email, subject, "SKIPPED", msg,
                          applicant_ref, batch_job_name)
        return False, msg

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["from"]
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            if cfg["tls"]:
                server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], [to_email], msg.as_string())

        _log_notification(conn, event, to_email, subject, "SENT",
                          applicant_ref=applicant_ref,
                          batch_job_name=batch_job_name)
        return True, "sent"

    except smtplib.SMTPAuthenticationError:
        err = "SMTP authentication failed — check credentials"
        logger.error(err)
        _log_notification(conn, event, to_email, subject, "FAILED", err,
                          applicant_ref, batch_job_name)
        return False, err
    except Exception as exc:
        err = str(exc)[:200]
        logger.error("send_email failed", exc_info=exc)
        _log_notification(conn, event, to_email, subject, "FAILED", err,
                          applicant_ref, batch_job_name)
        return False, err


def send_decision_email(
    conn,
    to_email: str,
    applicant_name: str,
    outcome: str,
    applicant_ref: str,
    product_name: str = "Life Insurance",
    premium: Optional[float] = None,
    risk_class: Optional[str] = None,
) -> tuple[bool, str]:
    """Convenience wrapper for decision notification emails."""
    subject = f"Underwriting Decision — {applicant_ref} — {outcome}"
    color = {
        "APPROVED_STP": "#22c55e", "APPROVED_RATED": "#22c55e",
        "DECLINED": "#ef4444", "REFERRED": "#f59e0b", "POSTPONED": "#c084fc",
    }.get(outcome, "#94a3b8")

    premium_line = ""
    if premium and premium > 0:
        premium_line = f"<p><strong>Approved Premium:</strong> ₹{premium:,.2f}</p>"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#0a1628;padding:24px;border-radius:8px 8px 0 0">
        <h2 style="color:#00d4aa;margin:0">🛡️ RiskUW — Underwriting Decision</h2>
      </div>
      <div style="background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0">
        <p>Dear {applicant_name or 'Applicant'},</p>
        <p>We have completed the underwriting review for application <strong>{applicant_ref}</strong>.</p>
        <div style="background:{color}18;border-left:4px solid {color};padding:16px;margin:16px 0;border-radius:4px">
          <strong style="color:{color};font-size:20px">{outcome.replace("_", " ")}</strong>
          {'<br><small>Straight-through processed</small>' if 'STP' in outcome else ''}
        </div>
        <p><strong>Product:</strong> {product_name}</p>
        <p><strong>Risk Class:</strong> {risk_class or '—'}</p>
        {premium_line}
        <hr style="margin:16px 0;border-color:#e2e8f0">
        <small style="color:#94a3b8">This is an automated notification from RiskUW.
        For queries, contact your underwriting team.</small>
      </div>
    </div>
    """
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
    return send_email(conn, physician_email, subject, html,
                      event="APS_REQUEST", applicant_ref=applicant_ref)
