-- ── Policy number sequence (atomic, no collisions) ──────────────────────────────
CREATE SEQUENCE IF NOT EXISTS policy_number_seq START 1;

-- ── Main policy table ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policy (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_number           VARCHAR(30) UNIQUE NOT NULL,
    application_id          UUID NOT NULL REFERENCES application(id),
    case_id                 UUID REFERENCES uw_case(id),
    decision_id             UUID REFERENCES uw_decision(id),

    product_code            VARCHAR(20) NOT NULL,
    applicant_ref           VARCHAR(100) NOT NULL,
    applicant_name          VARCHAR(200),

    sum_assured             NUMERIC(15,2) NOT NULL,
    annual_premium          NUMERIC(12,2) NOT NULL,
    premium_mode            VARCHAR(20) DEFAULT 'ANNUAL',
    modal_premium           NUMERIC(12,2),

    risk_class              VARCHAR(30),
    coverage_term_yrs       INT,

    status                  VARCHAR(30) NOT NULL DEFAULT 'PENDING_ACCEPTANCE',
    issue_date              DATE,
    commencement_date       DATE,
    maturity_date           DATE,

    next_premium_due        DATE,
    grace_period_end        DATE,
    last_premium_paid_date  DATE,
    total_premiums_paid     NUMERIC(15,2) DEFAULT 0,

    lapsed_at               TIMESTAMPTZ,
    revived_at              TIMESTAMPTZ,
    surrendered_at          TIMESTAMPTZ,
    surrender_value         NUMERIC(15,2),

    nominee_name            VARCHAR(200),
    nominee_relation        VARCHAR(50),

    tenant_id               UUID NOT NULL,
    created_by              VARCHAR(100) NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT chk_policy_status CHECK (status IN (
        'PENDING_ACCEPTANCE', 'PENDING_FIRST_PREMIUM', 'IN_FORCE',
        'LAPSED', 'REVIVED', 'SURRENDERED', 'MATURED', 'CLAIMED'
    ))
);

CREATE INDEX IF NOT EXISTS idx_policy_status ON policy(status);
CREATE INDEX IF NOT EXISTS idx_policy_tenant ON policy(tenant_id);
CREATE INDEX IF NOT EXISTS idx_policy_applicant_ref ON policy(applicant_ref);
CREATE INDEX IF NOT EXISTS idx_policy_next_premium ON policy(next_premium_due) WHERE status = 'IN_FORCE';

-- ── Premium payment history ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policy_premium_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policy(id) ON DELETE CASCADE,
    due_date        DATE NOT NULL,
    amount_due      NUMERIC(12,2) NOT NULL,
    amount_paid     NUMERIC(12,2),
    paid_date       DATE,
    status          VARCHAR(20) DEFAULT 'DUE',
    payment_mode    VARCHAR(30),
    receipt_number  VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT chk_premium_status CHECK (status IN ('DUE', 'PAID', 'OVERDUE', 'WAIVED'))
);

CREATE INDEX IF NOT EXISTS idx_premium_history_policy ON policy_premium_history(policy_id);
CREATE INDEX IF NOT EXISTS idx_premium_history_due ON policy_premium_history(due_date) WHERE status = 'DUE';

-- ── Status change audit trail ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policy_status_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policy(id) ON DELETE CASCADE,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30) NOT NULL,
    reason          TEXT,
    changed_by      VARCHAR(100),
    changed_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_status_history_policy ON policy_status_history(policy_id);
