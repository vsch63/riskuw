
# ── Policy Schedule Letter (PDF) ─────────────────────────────────────────────
@router.get("/{policy_id}/letter")
def generate_policy_letter(policy_id: str, current: CurrentUser = None):
    """Generate a professional PDF policy schedule letter."""
    if current and current.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Underwriters only")

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Load policy details
        cur.execute("""
            SELECT p.*, am.full_name, am.email, am.mobile, am.phone,
                   am.address_line1, am.address_line2, am.city, am.state,
                   am.pincode, am.country, am.nominee_name, am.nominee_relation,
                   am.nominee_dob, am.pan_number
            FROM policy p
            LEFT JOIN applicant_master am ON am.applicant_ref = p.applicant_ref
            WHERE p.id = %s AND p.tenant_id = %s::uuid
        """, (policy_id, current.tenant_id if current else "00000000-0000-0000-0000-000000000001"))
        pol = cur.fetchone()
        if not pol:
            raise HTTPException(404, "Policy not found")

        # Load multi-benefit data if available
        cur.execute("""
            SELECT pb.benefit_type, pb.product_code, pb.face_amount,
                   pb.outcome, pb.risk_class, pb.annual_premium, pb.exclusions,
                   pr.product_name
            FROM proposal_benefit pb
            JOIN proposal prop ON prop.id = pb.proposal_id
            LEFT JOIN products pr ON pr.product_code = pb.product_code
            WHERE prop.applicant_ref = %s
            ORDER BY pb.benefit_type
        """, (pol["applicant_ref"],))
        benefits = cur.fetchall()

        # Load premium history
        cur.execute("""
            SELECT due_date, paid_date, amount, mode, receipt_number, status
            FROM policy_premium_history
            WHERE policy_id = %s
            ORDER BY due_date DESC LIMIT 5
        """, (policy_id,))
        premiums = cur.fetchall()

        # Load letter template
        cur.execute("""
            SELECT header_company_name, header_tagline, contact_email,
                   contact_phone, footer_text
            FROM letter_templates
            WHERE outcome = 'APPROVED' AND is_active = true
            LIMIT 1
        """)
        tpl = cur.fetchone() or {}
        cur.close()

        # Build PDF
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
        from fastapi.responses import StreamingResponse

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=15*mm, bottomMargin=20*mm)

        # Colours
        TEAL    = colors.HexColor("#006B5E")
        DARK    = colors.HexColor("#1A1A2E")
        LGRAY   = colors.HexColor("#F0F4F4")
        MGRAY   = colors.HexColor("#888888")
        WHITE   = colors.white
        RED     = colors.HexColor("#DC2626")
        AMBER   = colors.HexColor("#D97706")

        styles = getSampleStyleSheet()
        def S(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        H1    = S("H1", fontSize=18, textColor=TEAL, fontName="Helvetica-Bold", spaceAfter=2)
        H2    = S("H2", fontSize=11, textColor=DARK, fontName="Helvetica-Bold", spaceAfter=4)
        BODY  = S("BODY", fontSize=9, textColor=DARK, leading=14, spaceAfter=4)
        SMALL = S("SMALL", fontSize=8, textColor=MGRAY, leading=12)
        CENTER= S("CENTER", fontSize=9, textColor=DARK, alignment=TA_CENTER)
        MONO  = S("MONO", fontSize=9, textColor=TEAL, fontName="Courier-Bold")

        company = tpl.get("header_company_name") or "RiskUW Insurance"
        tagline = tpl.get("header_tagline") or "AI-Enabled Life Insurance Underwriting"
        contact_email = tpl.get("contact_email") or "uw@riskuw.online"
        contact_phone = tpl.get("contact_phone") or "+91 1800 123 4567"
        footer_text   = tpl.get("footer_text") or (
            "This document is computer-generated and does not require a signature. "
            "Any misrepresentation may result in cancellation of this policy.")

        story = []

        # ── HEADER ────────────────────────────────────────────────────────────
        header_data = [[
            Paragraph(f"<b>{company}</b>", S("CH", fontSize=16, textColor=TEAL, fontName="Helvetica-Bold")),
            Paragraph(f"<b>POLICY SCHEDULE</b>", S("CR", fontSize=13, textColor=DARK, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        header_tbl = Table(header_data, colWidths=[100*mm, 70*mm])
        header_tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("BACKGROUND", (0,0), (-1,-1), DARK),
            ("LEFTPADDING", (0,0), (0,0), 6*mm),
            ("RIGHTPADDING", (-1,0), (-1,0), 6*mm),
            ("TOPPADDING", (0,0), (-1,-1), 4*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm),
        ]))
        story.append(header_tbl)

        # Tagline bar
        tl_data = [[Paragraph(tagline, S("TL", fontSize=8, textColor=colors.HexColor("#00D4AA"), alignment=TA_CENTER))]]
        tl_tbl = Table(tl_data, colWidths=[170*mm])
        tl_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#0A1628")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
        ]))
        story.append(tl_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICY NUMBER BANNER ──────────────────────────────────────────────
        status_color = TEAL if pol["status"] == "IN_FORCE" else AMBER if pol["status"] == "PENDING_ACCEPTANCE" else RED
        pn_data = [[
            Paragraph(f"Policy Number: <b>{pol['policy_number']}</b>",
                S("PN", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold")),
            Paragraph(f"Status: <b>{pol['status'].replace('_',' ')}</b>",
                S("PS", fontSize=10, textColor=status_color, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        pn_tbl = Table(pn_data, colWidths=[100*mm, 70*mm])
        pn_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1E3A5F")),
            ("LEFTPADDING", (0,0), (0,0), 4*mm),
            ("RIGHTPADDING", (-1,0), (-1,0), 4*mm),
            ("TOPPADDING", (0,0), (-1,-1), 3*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3*mm),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(pn_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICYHOLDER DETAILS ──────────────────────────────────────────────
        story.append(Paragraph("POLICYHOLDER DETAILS", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        name = pol.get("full_name") or pol.get("applicant_name") or pol.get("applicant_ref","—")
        addr_parts = [pol.get("address_line1"), pol.get("city"),
                      pol.get("state"), pol.get("pincode"), pol.get("country")]
        address = ", ".join(p for p in addr_parts if p) or "—"

        ph_data = [
            ["Full Name", name, "PAN Number", pol.get("pan_number") or "—"],
            ["Email", pol.get("email") or "—", "Mobile", pol.get("mobile") or pol.get("phone") or "—"],
            ["Address", address, "", ""],
            ["Nominee", pol.get("nominee_name") or "—", "Relationship", pol.get("nominee_relation") or "—"],
        ]
        ph_tbl = Table(ph_data, colWidths=[35*mm, 55*mm, 35*mm, 45*mm])
        ph_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0,0), (0,-1), DARK),
            ("TEXTCOLOR", (2,0), (2,-1), DARK),
            ("BACKGROUND", (0,0), (-1,-1), LGRAY),
            ("BACKGROUND", (1,0), (1,-1), WHITE),
            ("BACKGROUND", (3,0), (3,-1), WHITE),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
            ("SPAN", (1,2), (3,2)),
        ]))
        story.append(ph_tbl)
        story.append(Spacer(1, 5*mm))

        # ── POLICY DETAILS ────────────────────────────────────────────────────
        story.append(Paragraph("POLICY DETAILS", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        def fmt_date(d):
            if not d: return "—"
            return str(d)[:10]
        def fmt_amt(v):
            if not v: return "—"
            try: return f"\u20b9{float(v):,.2f}"
            except: return str(v)

        pol_data = [
            ["Product Code", pol.get("product_code") or "—",
             "Risk Class", pol.get("risk_class") or "—"],
            ["Sum Assured", fmt_amt(pol.get("sum_assured") or pol.get("face_amount")),
             "Coverage Term", f"{pol.get('coverage_term_yrs') or '—'} years"],
            ["Issue Date", fmt_date(pol.get("issue_date")),
             "Commencement Date", fmt_date(pol.get("commencement_date"))],
            ["Maturity Date", fmt_date(pol.get("maturity_date")),
             "Next Premium Due", fmt_date(pol.get("next_premium_due"))],
            ["Premium Mode", (pol.get("premium_mode") or "ANNUAL").replace("_"," ").title(),
             "Modal Premium", fmt_amt(pol.get("modal_premium") or pol.get("annual_premium"))],
            ["Grace Period End", fmt_date(pol.get("grace_period_end")),
             "Total Premiums Paid", fmt_amt(pol.get("total_premiums_paid"))],
        ]
        pol_tbl = Table(pol_data, colWidths=[40*mm, 50*mm, 40*mm, 40*mm])
        pol_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
            ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,-1), LGRAY),
            ("BACKGROUND", (1,0), (1,-1), WHITE),
            ("BACKGROUND", (3,0), (3,-1), WHITE),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
        ]))
        story.append(pol_tbl)
        story.append(Spacer(1, 5*mm))

        # ── BENEFIT SCHEDULE ──────────────────────────────────────────────────
        story.append(Paragraph("BENEFIT SCHEDULE", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))

        if benefits:
            ben_header = [
                Paragraph("<b>Benefit</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Product</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Sum Assured</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph("<b>Status</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>Annual Premium</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                Paragraph("<b>Exclusions</b>", S("BH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
            ]
            ben_rows = [ben_header]
            total_prem = 0
            for b in benefits:
                b_outcome = b.get("outcome","—")
                b_color = TEAL if "APPROVED" in (b_outcome or "") else RED
                excl = ""
                if b.get("exclusions"):
                    import json as _json
                    try:
                        excl_list = b["exclusions"] if isinstance(b["exclusions"], list) else _json.loads(b["exclusions"])
                        excl = "; ".join(e.get("condition","") for e in excl_list if isinstance(e, dict))
                    except: excl = str(b["exclusions"])[:40]
                prem = b.get("annual_premium")
                if prem: total_prem += float(prem)
                ben_rows.append([
                    Paragraph(b.get("benefit_type","").replace("RIDER_","") + (" (Base)" if b.get("benefit_type") == "BASE" else " Rider"),
                        S("BC", fontSize=8, textColor=DARK)),
                    Paragraph(b.get("product_code","—"), S("BC", fontSize=8, textColor=DARK, fontName="Courier")),
                    Paragraph(fmt_amt(b.get("face_amount")), S("BC", fontSize=8, textColor=DARK, alignment=TA_RIGHT)),
                    Paragraph(b_outcome.replace("_"," "), S("BC", fontSize=8, textColor=b_color)),
                    Paragraph(fmt_amt(prem) if prem else "—", S("BC", fontSize=8, textColor=DARK, alignment=TA_RIGHT)),
                    Paragraph(excl or "None", S("BC", fontSize=7, textColor=AMBER if excl else MGRAY)),
                ])
            # Total row
            ben_rows.append([
                Paragraph("<b>TOTAL</b>", S("BT", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                "", "", "",
                Paragraph(f"<b>{fmt_amt(total_prem)}</b>",
                    S("BT", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                "",
            ])
            ben_tbl = Table(ben_rows, colWidths=[30*mm, 32*mm, 28*mm, 28*mm, 28*mm, 24*mm])
            nrows = len(ben_rows)
            ben_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("BACKGROUND", (0,nrows-1), (-1,nrows-1), colors.HexColor("#1E3A5F")),
                ("BACKGROUND", (0,1), (-1,nrows-2), WHITE),
                ("ROWBACKGROUNDS", (0,1), (-1,nrows-2), [WHITE, LGRAY]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("SPAN", (0,nrows-1), (3,nrows-1)),
                ("SPAN", (5,nrows-1), (5,nrows-1)),
            ]))
            story.append(ben_tbl)
        else:
            # Single benefit — show base product only
            sb_data = [
                [Paragraph("<b>Cover</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                 Paragraph("<b>Sum Assured</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                 Paragraph("<b>Annual Premium</b>", S("SH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
                [Paragraph(pol.get("product_code") or "Life Insurance", BODY),
                 Paragraph(fmt_amt(pol.get("sum_assured") or pol.get("face_amount")), S("SA", fontSize=9, alignment=TA_RIGHT)),
                 Paragraph(fmt_amt(pol.get("annual_premium")), S("AP", fontSize=9, alignment=TA_RIGHT))],
            ]
            sb_tbl = Table(sb_data, colWidths=[80*mm, 45*mm, 45*mm])
            sb_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("BACKGROUND", (0,1), (-1,1), LGRAY),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
            ]))
            story.append(sb_tbl)

        story.append(Spacer(1, 5*mm))

        # ── PREMIUM HISTORY ───────────────────────────────────────────────────
        if premiums:
            story.append(Paragraph("PREMIUM PAYMENT HISTORY", H2))
            story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))
            pr_header = ["Due Date", "Paid Date", "Amount", "Mode", "Receipt No.", "Status"]
            pr_rows = [pr_header]
            for pr in premiums:
                pr_rows.append([
                    fmt_date(pr.get("due_date")),
                    fmt_date(pr.get("paid_date")),
                    fmt_amt(pr.get("amount")),
                    (pr.get("mode") or "—").replace("_"," ").title(),
                    pr.get("receipt_number") or "—",
                    pr.get("status") or "—",
                ])
            pr_tbl = Table(pr_rows, colWidths=[28*mm, 28*mm, 30*mm, 28*mm, 32*mm, 24*mm])
            pr_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("TEXTCOLOR", (0,0), (-1,0), WHITE),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LGRAY]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
                ("TOPPADDING", (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
            ]))
            story.append(pr_tbl)
            story.append(Spacer(1, 5*mm))

        # ── IMPORTANT NOTES ───────────────────────────────────────────────────
        story.append(Paragraph("IMPORTANT INFORMATION", H2))
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=3*mm))
        notes = [
            "This policy schedule is subject to the terms and conditions of the policy contract.",
            "The free-look period is 15 days from the date of receipt of this policy document.",
            "Please preserve this document safely as it is required for claims processing.",
            f"For queries: {contact_email}  |  {contact_phone}",
        ]
        for note in notes:
            story.append(Paragraph(f"• {note}", SMALL))
        story.append(Spacer(1, 5*mm))

        # ── FOOTER ────────────────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=1, color=TEAL))
        story.append(Spacer(1, 2*mm))
        gen_date = datetime.now().strftime("%d %B %Y at %H:%M")
        story.append(Paragraph(
            f"{footer_text}<br/>"
            f"<font color='#888888' size='7'>Generated: {gen_date}  |  "
            f"Policy: {pol['policy_number']}  |  Powered by RiskUW</font>",
            S("FT", fontSize=7, textColor=MGRAY, leading=10, alignment=TA_CENTER)
        ))

        doc.build(story)
        buf.seek(0)

        from fastapi.responses import StreamingResponse
        filename = f"PolicySchedule_{pol['policy_number']}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(500, f"PDF generation failed: {e}\n{traceback.format_exc()[:300]}")
    finally:
        release(conn)
