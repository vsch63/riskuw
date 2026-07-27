

def send_proposal_decision_email(
    conn,
    to_email: str,
    applicant_name: str,
    applicant_ref: str,
    proposal_ref: str,
    overall_status: str,
    benefit_decisions: list[dict],
) -> tuple[bool, str]:
    """
    Send a single consolidated email for a multi-benefit proposal.
    Shows ALL benefit decisions in one table — base plan + all riders.

    benefit_decisions: list of dicts with keys:
        product_code, benefit_label, outcome, risk_class,
        annual_premium, face_amount, coverage_term_yrs, linked_decline
    """
    if not to_email or "@" not in to_email:
        log_missing_email_warning(conn, applicant_ref, overall_status)
        return False, "missing_email"

    if not is_auto_email_enabled(conn, "STP_APPROVAL_EMAIL"):
        logger.info(f"Auto email disabled — skipping proposal email for {applicant_ref}")
        return False, "auto_email_disabled"

    if _already_sent(conn, "PROPOSAL_EMAIL", applicant_ref, window_seconds=120):
        logger.info(f"Proposal email skipped (duplicate) for {applicant_ref}")
        return True, "skipped_duplicate"

    # Overall outcome badge colour
    STATUS_COLOR = {
        "ALL_APPROVED":    "#22c55e",
        "PARTIAL_APPROVAL":"#f59e0b",
        "ALL_DECLINED":    "#ef4444",
        "ALL_REFERRED":    "#f59e0b",
    }
    OUTCOME_COLOR = {
        "APPROVED_STP":    "#22c55e",
        "APPROVED_RATED":  "#16a34a",
        "REFERRED":        "#f59e0b",
        "DECLINED":        "#ef4444",
        "ERROR":           "#94a3b8",
    }

    status_color = STATUS_COLOR.get(overall_status, "#94a3b8")
    status_label = overall_status.replace("_", " ")

    # Policy number lookup
    policy_number = get_policy_number(conn, applicant_ref)
    policy_block = ""
    if policy_number:
        policy_block = (
            "<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;"
            "padding:14px 16px;margin:14px 0'>"
            "<strong style='color:#166534'>Policy Number:</strong> "
            "<span style='font-family:monospace;font-size:16px;color:#15803d;font-weight:bold'>"
            + policy_number +
            "</span><br>"
            "<small style='color:#555'>Quote this number in all future correspondence.</small>"
            "</div>"
        )

    # Build benefits table rows
    benefit_rows = ""
    total_premium = 0.0
    approved_count = 0
    for d in benefit_decisions:
        outcome   = d.get("outcome", "")
        label     = d.get("benefit_label") or d.get("product_code", "")
        rc        = d.get("risk_class") or "—"
        premium   = d.get("annual_premium")
        face      = d.get("face_amount", 0)
        linked    = d.get("linked_decline", False)
        outcome_color = OUTCOME_COLOR.get(outcome, "#94a3b8")
        is_approved = outcome in ("APPROVED_STP", "APPROVED_RATED", "APPROVED_EXCLUDED")

        if is_approved and premium:
            total_premium += float(premium)
            approved_count += 1

        premium_str = (f"&#8377; {float(premium):,.2f}" if premium else "—")
        face_str    = (f"&#8377; {float(face):,.0f}" if face else "—")
        linked_note = (" <small style='color:#94a3b8'>(auto-declined)</small>"
                       if linked else "")

        benefit_rows += (
            f"<tr>"
            f"<td style='padding:10px 12px;border:1px solid #e2e8f0;font-size:13px;"
            f"font-weight:bold;color:#1e3a5f'>{label}</td>"
            f"<td style='padding:10px 12px;border:1px solid #e2e8f0;font-size:13px'>{face_str}</td>"
            f"<td style='padding:10px 12px;border:1px solid #e2e8f0;text-align:center'>"
            f"<span style='background:{outcome_color}18;color:{outcome_color};"
            f"font-weight:bold;font-size:12px;padding:3px 8px;border-radius:4px;"
            f"border:1px solid {outcome_color}44'>"
            f"{outcome.replace('_',' ')}{linked_note}</span></td>"
            f"<td style='padding:10px 12px;border:1px solid #e2e8f0;font-size:13px'>{rc}</td>"
            f"<td style='padding:10px 12px;border:1px solid #e2e8f0;font-size:13px;"
            f"text-align:right;font-weight:{'bold' if is_approved else 'normal'};"
            f"color:{'#166534' if is_approved else '#374141'}'>{premium_str}</td>"
            f"</tr>"
        )

    # Total premium row
    if approved_count > 0:
        benefit_rows += (
            f"<tr style='background:#f0fdf4'>"
            f"<td colspan='4' style='padding:10px 12px;border:1px solid #e2e8f0;"
            f"font-weight:bold;font-size:13px;color:#166534'>Total Annual Premium</td>"
            f"<td style='padding:10px 12px;border:1px solid #e2e8f0;font-weight:bold;"
            f"font-size:14px;color:#166534;text-align:right'>"
            f"&#8377; {total_premium:,.2f}</td>"
            f"</tr>"
        )

    # Summary sentence
    total = len(benefit_decisions)
    declined = sum(1 for d in benefit_decisions if d.get("outcome") == "DECLINED")
    referred = sum(1 for d in benefit_decisions if d.get("outcome") == "REFERRED")

    summary_parts = []
    if approved_count:
        summary_parts.append(f"<strong style='color:#166534'>{approved_count} benefit(s) approved</strong>")
    if referred:
        summary_parts.append(f"<strong style='color:#f59e0b'>{referred} referred for review</strong>")
    if declined:
        summary_parts.append(f"<strong style='color:#ef4444'>{declined} declined</strong>")
    summary_sentence = ", ".join(summary_parts) + "." if summary_parts else ""

    subject = (
        f"Proposal Decision — {proposal_ref} — {status_label}"
    )

    html = (
        "<div style='font-family:Arial,sans-serif;max-width:680px;margin:auto'>"

        # Header
        "<div style='background:#0a1628;padding:24px;border-radius:8px 8px 0 0'>"
        "<h2 style='color:#00d4aa;margin:0'>🛡️ RiskUW — Proposal Decision</h2>"
        "</div>"

        # Body
        "<div style='background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;"
        "border:1px solid #e2e8f0'>"
        f"<p>Dear {applicant_name or 'Applicant'},</p>"
        f"<p>Your proposal <strong>{proposal_ref}</strong> (Ref: {applicant_ref}) "
        "has been reviewed by our underwriting team. "
        "The decisions for each benefit selected are detailed below.</p>"

        # Overall status badge
        f"<div style='background:{status_color}18;border-left:4px solid {status_color};"
        f"padding:14px 16px;margin:16px 0;border-radius:4px'>"
        f"<strong style='color:{status_color};font-size:18px'>{status_label}</strong><br>"
        f"<span style='color:#374151;font-size:13px;margin-top:4px;display:block'>"
        f"{summary_sentence}</span>"
        "</div>"

        + policy_block +

        # Benefits table
        "<table style='width:100%;border-collapse:collapse;margin:16px 0'>"
        "<thead><tr style='background:#1e3a5f'>"
        "<th style='padding:10px 12px;border:1px solid #2d4a7a;color:#fff;"
        "font-size:12px;text-align:left'>Benefit</th>"
        "<th style='padding:10px 12px;border:1px solid #2d4a7a;color:#fff;"
        "font-size:12px;text-align:left'>Sum Assured</th>"
        "<th style='padding:10px 12px;border:1px solid #2d4a7a;color:#fff;"
        "font-size:12px;text-align:center'>Decision</th>"
        "<th style='padding:10px 12px;border:1px solid #2d4a7a;color:#fff;"
        "font-size:12px;text-align:left'>Risk Class</th>"
        "<th style='padding:10px 12px;border:1px solid #2d4a7a;color:#fff;"
        "font-size:12px;text-align:right'>Annual Premium</th>"
        "</tr></thead>"
        f"<tbody>{benefit_rows}</tbody>"
        "</table>"

        # Next steps
        "<div style='margin:16px 0;padding:14px 16px;background:#eff6ff;"
        "border-radius:6px;border:1px solid #bfdbfe'>"
        "<strong style='color:#1e40af'>Next Steps:</strong>"
        "<ol style='margin:8px 0;padding-left:20px;color:#374151;font-size:13px'>"
        "<li>Review the policy documents for each approved benefit carefully.</li>"
        "<li>Sign and return the acceptance form within 30 days.</li>"
        "<li>Ensure the first premium of "
        + (f"&#8377; {total_premium:,.2f}" if total_premium else "the quoted amount") +
        " is paid before the policy effective date.</li>"
        "<li>Contact your agent or our customer service team for any queries.</li>"
        "</ol></div>"

        "<hr style='margin:16px 0;border-color:#e2e8f0'>"
        "<small style='color:#94a3b8'>This is an automated notification from RiskUW. "
        f"Proposal Ref: {proposal_ref}. "
        "For queries, contact your underwriting team.</small>"
        "</div></div>"
    )

    ok, msg = send_email(
        conn, to_email, subject, html,
        event="PROPOSAL_EMAIL",
        applicant_ref=applicant_ref,
    )
    if not ok:
        logger.warning(f"Proposal decision email failed for {applicant_ref}: {msg}")
    return ok, msg
