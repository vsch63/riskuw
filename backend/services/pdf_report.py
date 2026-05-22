"""
backend/services/pdf_report.py
────────────────────────────────
Generates a professional UW decision report as PDF.
Uses weasyprint (HTML → PDF).  Falls back to raw HTML bytes if weasyprint
is not installed (so the endpoint doesn't crash in dev).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("uw_platform")


def generate_decision_pdf(
    result: dict,
    product: dict,
    template: Optional[dict] = None,
) -> bytes:
    """
    Build and return PDF bytes for a UW decision.
    result   — UWDecisionResponse dict
    product  — Product dict (name, code, etc.)
    template — Optional letter_template dict for branding
    """
    html = _build_html(result, product, template or {})
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except ImportError:
        logger.warning("weasyprint not installed — returning HTML bytes")
        return html.encode("utf-8")
    except Exception as exc:
        logger.error("PDF generation failed", exc_info=exc)
        return html.encode("utf-8")


def _build_html(result: dict, product: dict, tmpl: dict) -> str:
    company     = tmpl.get("header_company_name") or "🛡️ RiskUW"
    tagline     = tmpl.get("header_tagline")      or "Automated Underwriting Decision Report"
    contact_em  = tmpl.get("contact_email")       or ""
    footer_text = tmpl.get("footer_text")         or (
        "This document is generated automatically by the RiskUW underwriting engine. "
        "All decisions are subject to underwriter review where required."
    )

    outcome     = result.get("outcome", "—")
    risk_class  = result.get("risk_class", "—")
    debits      = result.get("net_debit_points", 0)
    app_id      = result.get("application_id", "—")
    eval_at     = str(result.get("evaluated_at", "—"))[:19].replace("T", " ")
    prod_name   = product.get("name") or product.get("product_name") or "Life Insurance"
    premium     = result.get("approved_premium")
    adverse     = result.get("adverse_action_text", "")
    rules_fired = result.get("rules_fired") or []
    is_stp      = result.get("is_stp", False)

    if "APPROVED" in outcome:
        color, badge = "#065f46", "#10b981"
    elif "DECLIN" in outcome:
        color, badge = "#7f1d1d", "#ef4444"
    elif "POSTPON" in outcome:
        color, badge = "#1e1b4b", "#818cf8"
    else:
        color, badge = "#1c1917", "#f59e0b"

    rules_rows = ""
    for r in rules_fired[:20]:
        pts = r.get("debit_points", 0)
        rules_rows += (
            f"<tr>"
            f"<td>{r.get('rule_id','')}</td>"
            f"<td>{r.get('rule_name','')}</td>"
            f"<td>{r.get('category','')}</td>"
            f"<td style='text-align:right;font-weight:700;color:{'#ef4444' if pts>50 else '#f59e0b' if pts>0 else '#22c55e'}'>"
            f"{'+'if pts>0 else ''}{pts}</td>"
            f"</tr>"
        )

    premium_row = ""
    if premium and float(premium) > 0:
        premium_row = f"<tr><td>Approved Premium</td><td><strong>₹{float(premium):,.2f}</strong></td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 13px; color: #1e293b; margin: 0; padding: 0; }}
  .header {{ background: #0a1628; color: white; padding: 28px 36px; }}
  .header h1 {{ margin: 0; font-size: 22px; color: #00d4aa; }}
  .header p  {{ margin: 4px 0 0; color: #94a3b8; font-size: 13px; }}
  .outcome-box {{ background: {color}; border-left: 6px solid {badge};
                  padding: 20px 36px; margin: 0; }}
  .outcome-box h2 {{ color: {badge}; font-size: 28px; margin: 0; letter-spacing: 1px; }}
  .outcome-box small {{ color: #cbd5e1; }}
  .content {{ padding: 28px 36px; }}
  table.meta {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  table.meta td {{ padding: 7px 10px; border-bottom: 1px solid #e2e8f0; }}
  table.meta td:first-child {{ color: #64748b; width: 40%; }}
  table.rules {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  table.rules th {{ background: #f1f5f9; padding: 8px 10px; text-align: left;
                    border-bottom: 2px solid #e2e8f0; font-weight: 700; }}
  table.rules td {{ padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }}
  .adverse {{ background: #fef2f2; border-left: 4px solid #ef4444;
              padding: 12px 16px; border-radius: 4px; margin: 16px 0;
              color: #7f1d1d; font-size: 12px; }}
  .footer {{ background: #f8fafc; padding: 16px 36px; font-size: 11px;
             color: #94a3b8; border-top: 1px solid #e2e8f0; }}
  h3 {{ color: #0f172a; margin: 20px 0 10px; font-size: 14px; }}
</style>
</head>
<body>

<div class="header">
  <h1>{company}</h1>
  <p>{tagline}</p>
</div>

<div class="outcome-box">
  <h2>{outcome.replace('_',' ')}</h2>
  <small>{'⚡ Straight-Through Processed' if is_stp else '👤 Referred to Underwriter'}</small>
</div>

<div class="content">
  <h3>Decision Summary</h3>
  <table class="meta">
    <tr><td>Application Reference</td><td><strong>{app_id}</strong></td></tr>
    <tr><td>Product</td><td>{prod_name}</td></tr>
    <tr><td>Risk Class</td><td><strong>{risk_class}</strong></td></tr>
    <tr><td>Net Debit Points</td><td><strong>{debits}</strong></td></tr>
    {premium_row}
    <tr><td>Evaluated At</td><td>{eval_at}</td></tr>
    <tr><td>Rules Version</td><td>{result.get('rules_version','—')}</td></tr>
  </table>

  {'<div class="adverse"><strong>Adverse Action:</strong> ' + adverse + '</div>' if adverse else ''}

  {'<h3>Rules Fired (' + str(len(rules_fired)) + ')</h3><table class="rules"><thead><tr><th>Rule ID</th><th>Rule Name</th><th>Category</th><th style="text-align:right">Points</th></tr></thead><tbody>' + rules_rows + '</tbody></table>' if rules_fired else ''}
</div>

<div class="footer">
  {footer_text}
  {f'<br>Contact: {contact_em}' if contact_em else ''}
  <br>Generated: {datetime.now().strftime('%d %b %Y %H:%M')}
</div>

</body>
</html>"""
