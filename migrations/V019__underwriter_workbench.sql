-- ════════════════════════════════════════════════════════════════════════════
-- V019__underwriter_workbench.sql
-- Adds tables to support the Underwriter Workbench:
--   - case_assignments : tracks workbench status, assignment, SLA, final decision
--   - case_notes       : free-text notes/comments timeline per case
--   - case_requirements: tracks requested items (medical test, financial doc, APS)
--
-- Scope: policy_admin_queue.id is the case reference (single-evaluate flow).
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS case_assignments (
    id                INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    case_ref_id       INTEGER NOT NULL REFERENCES policy_admin_queue(id) ON DELETE CASCADE,
    assigned_to       VARCHAR(100),
    assigned_by       VARCHAR(100),
    workbench_status  VARCHAR(30) NOT NULL DEFAULT 'OPEN',
        -- OPEN | IN_PROGRESS | PENDING_REQUIREMENTS | READY_FOR_DECISION
        -- | APPROVED | DECLINED | CLOSED
    priority          VARCHAR(10) NOT NULL DEFAULT 'NORMAL',
        -- LOW | NORMAL | HIGH | URGENT
    sla_hours         INTEGER NOT NULL DEFAULT 48,
    sla_due_at        TIMESTAMPTZ,
    final_outcome     VARCHAR(40),
    final_reason      TEXT,
    decided_by        VARCHAR(100),
    decided_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_case_assignments_case UNIQUE (case_ref_id)
);

CREATE TABLE IF NOT EXISTS case_notes (
    id           INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    case_ref_id  INTEGER NOT NULL REFERENCES policy_admin_queue(id) ON DELETE CASCADE,
    author       VARCHAR(100) NOT NULL,
    note         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS case_requirements (
    id                INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    case_ref_id       INTEGER NOT NULL REFERENCES policy_admin_queue(id) ON DELETE CASCADE,
    requirement_type  VARCHAR(50) NOT NULL,
        -- MEDICAL_TEST | APS | FINANCIAL_DOC | ID_PROOF | OTHER
    description       TEXT,
    status            VARCHAR(20) NOT NULL DEFAULT 'REQUESTED',
        -- REQUESTED | RECEIVED | WAIVED
    requested_by      VARCHAR(100),
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_at       TIMESTAMPTZ,
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_case_assignments_status      ON case_assignments(workbench_status);
CREATE INDEX IF NOT EXISTS idx_case_assignments_assigned_to ON case_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_case_assignments_sla_due     ON case_assignments(sla_due_at);
CREATE INDEX IF NOT EXISTS idx_case_notes_case              ON case_notes(case_ref_id);
CREATE INDEX IF NOT EXISTS idx_case_requirements_case       ON case_requirements(case_ref_id);
CREATE INDEX IF NOT EXISTS idx_case_requirements_status     ON case_requirements(status);
