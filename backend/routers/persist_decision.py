def _persist_decision(body: "EvaluateRequest", result: dict, current) -> str | None:
    """
    Persist an evaluation to application -> uw_case -> uw_decision.
    Returns the case_number, or None if persistence failed (non-fatal).
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        outcome = (result.get("outcome") or "REFERRED").upper()
        username = current.username
        tenant_id = current.tenant_id

        # ── Map outcome -> case status + decision pathway ──────────────────────
        if "APPROVED_STP" in outcome or "INSTANT" in outcome and "DECLINE" not in outcome:
            status, pathway, by_type = "APPROVED", "STRAIGHT_THROUGH", "AUTOMATED"
        elif "APPROVED" in outcome:
            status, pathway, by_type = "APPROVED", "ACCELERATED", "AUTOMATED"
        elif "DECLINED" in outcome:
            status, pathway, by_type = "DECLINED", "INSTANT_DECLINE", "AUTOMATED"
        elif "REFERRED" in outcome:
            status, pathway, by_type = "PENDING_REVIEW", "REFERRED", "AUTOMATED"
        else:
            status, pathway, by_type = "OPEN", "REFERRED", "AUTOMATED"

        app_id = str(_uuid.uuid4())
        case_id = str(_uuid.uuid4())
        dec_id = str(_uuid.uuid4())

        # ── application_number / case_number ────────────────────────────────────
        ts = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S%f")[:14]
        app_number = f"APP-{ts}"
        case_number = f"CASE-{ts}"

        # ── 1. application ───────────────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO application (
                id, application_number, product_type, product_code, channel,
                applicant_ref, age, gender, state, citizenship,
                face_amount, coverage_term_yrs, is_replacement, status,
                submitted_at, raw_payload,
                created_by, updated_by, version, is_deleted, tenant_id
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                now(), %s,
                %s, %s, 1, false, %s
            )
            """,
            (
                app_id, app_number, "INDIVIDUAL", body.product_code, "DIRECT",
                body.applicant_ref, body.age, body.gender, body.state, "IN",
                body.face_amount, getattr(body, "coverage_term_yrs", None) or getattr(body, "term_yrs", None),
                False, status,
                __import__("json").dumps(body.model_dump(), default=str),
                username, username, tenant_id,
            ),
        )

        # ── 2. uw_case ────────────────────────────────────────────────────────────
        sla_hours = 48
        cur.execute(
            """
            INSERT INTO uw_case (
                id, case_number, application_id, product_type, status,
                decision_pathway, sla_due_at, sla_breached,
                auto_decision_at, final_decision_at,
                reinsurance_required,
                created_by, updated_by, version, is_deleted, tenant_id,
                product_code, applicant_age, face_amount
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, now() + interval '%s hours', false,
                now(), CASE WHEN %s THEN now() ELSE NULL END,
                false,
                %s, %s, 1, false, %s,
                %s, %s, %s
            )
            """,
            (
                case_id, case_number, app_id, "INDIVIDUAL", status,
                pathway, sla_hours,
                status in ("APPROVED", "DECLINED"),
                username, username, tenant_id,
                body.product_code, body.age, body.face_amount,
            ),
        )

        # ── 3. uw_decision ────────────────────────────────────────────────────────
        findings = {
            "rules_fired": result.get("rules_fired", []),
            "error_codes": result.get("error_codes", []),
            "raw_result": {k: v for k, v in result.items()
                            if k not in ("rules_fired", "error_codes")},
        }

        cur.execute(
            """
            INSERT INTO uw_decision (
                id, case_id, application_id, decision_sequence, is_final,
                outcome, risk_class,
                total_debit_points, total_credit_points, net_debit_points,
                approved_face_amount, approved_premium,
                decline_reason_code, adverse_action_text,
                findings_json, is_override,
                decided_by_type, decided_by_id, decided_at,
                primary_reason,
                created_by, updated_by, version, is_deleted, tenant_id
            ) VALUES (
                %s, %s, %s, 1, true,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, false,
                %s, NULL, now(),
                %s,
                %s, %s, 1, false, %s
            )
            """,
            (
                dec_id, case_id, app_id,
                outcome, result.get("risk_class"),
                result.get("total_debit_points", result.get("net_debit_points", 0)) or 0,
                result.get("total_credit_points", 0) or 0,
                result.get("net_debit_points", 0) or 0,
                body.face_amount if status == "APPROVED" else None,
                result.get("approved_premium") or result.get("premium"),
                result.get("decline_reason_code"),
                result.get("adverse_action_text") or result.get("primary_reason"),
                __import__("json").dumps(findings, default=str),
                by_type,
                result.get("primary_reason"),
                username, username, tenant_id,
            ),
        )

        conn.commit()
        cur.close()
        return case_number

    except Exception as e:
        conn.rollback()
        logger.warning(f"Could not persist decision for {body.applicant_ref}: {e}")
        return None
    finally:
        release(conn)
