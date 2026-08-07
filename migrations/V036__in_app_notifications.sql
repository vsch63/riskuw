-- ════════════════════════════════════════════════════════════════════════════
-- V036__in_app_notifications.sql
-- In-app notification feed for the Underwriter Workbench (Phase 3d).
--
-- Event triggers across the workbench (assignment, requirements, notes,
-- decisions, SLA breaches) write rows here; the frontend header bell polls
-- them. Recipients are uw_user.usernames, scoped by tenant.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS uw_notification (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     UUID,
    recipient     VARCHAR(100) NOT NULL,          -- uw_user.username
    event_type    VARCHAR(30)  NOT NULL,
        -- ASSIGNMENT | REQUIREMENT | NOTE | DECISION | SLA_BREACH
    title         VARCHAR(160) NOT NULL,
    body          TEXT,
    case_ref_id   INTEGER REFERENCES policy_admin_queue(id) ON DELETE CASCADE,
    is_read       BOOLEAN      NOT NULL DEFAULT false,
    read_at       TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uw_notification_recipient
    ON uw_notification (recipient, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_uw_notification_case
    ON uw_notification (case_ref_id);
CREATE INDEX IF NOT EXISTS idx_uw_notification_event
    ON uw_notification (event_type, is_read);
