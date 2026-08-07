-- ════════════════════════════════════════════════════════════════════════════
-- V020__ai_decision_log.sql
-- AI Audit Trail — logs every AI-assist call (XGBoost/Claude/Ollama) for
-- explainability and regulatory review. Captures input, output, who requested
-- it, and (later) whether the human underwriter's final decision matched the
-- AI recommendation.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_decision_log (
    id               INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    case_ref_id      INTEGER,             -- policy_admin_queue.id, nullable (batch rows may not have one)
    job_id           VARCHAR(40),         -- batch_jobs.id, nullable (single-evaluate calls)
    applicant_ref    VARCHAR(100),
    product_code     VARCHAR(40),
    source           VARCHAR(20) NOT NULL DEFAULT 'EVALUATE',
        -- EVALUATE | BATCH | WORKBENCH
    ai_engine        VARCHAR(20) NOT NULL,
        -- xgboost | claude | ollama
    ai_model         VARCHAR(60),         -- e.g. llava-llama3:latest, claude-sonnet-4-...
    input_payload    JSONB,
    risk_tier        VARCHAR(20),
    risk_score       NUMERIC(5,1),
    confidence       NUMERIC(4,2),
    recommendation   VARCHAR(20),
    primary_concerns JSONB,
    positive_factors JSONB,
    narrative        TEXT,
    loading_suggestion TEXT,
    rules_outcome    VARCHAR(40),         -- rules engine outcome at time of AI call, for comparison
    rules_ndp        INTEGER,
    human_decision   VARCHAR(40),         -- filled when underwriter records final decision
    human_decided_by VARCHAR(100),
    human_decided_at TIMESTAMPTZ,
    matches_ai       BOOLEAN,             -- true if human_decision aligns with AI recommendation
    requested_by     VARCHAR(100),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_log_case_ref     ON ai_decision_log(case_ref_id);
CREATE INDEX IF NOT EXISTS idx_ai_log_applicant    ON ai_decision_log(applicant_ref);
CREATE INDEX IF NOT EXISTS idx_ai_log_job          ON ai_decision_log(job_id);
CREATE INDEX IF NOT EXISTS idx_ai_log_engine       ON ai_decision_log(ai_engine);
CREATE INDEX IF NOT EXISTS idx_ai_log_created      ON ai_decision_log(created_at);
