-- Migration: Add password_reset_tokens table
-- No FK constraint on username since uw_user PK is on id not username

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token        TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    mfa_verified BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at   TIMESTAMPTZ NOT NULL,
    used_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prt_username ON password_reset_tokens(username);
CREATE INDEX IF NOT EXISTS idx_prt_expires  ON password_reset_tokens(expires_at);

-- Ensure uw_user has an email column (should already exist)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='uw_user' AND column_name='email'
  ) THEN
    ALTER TABLE uw_user ADD COLUMN email TEXT;
  END IF;
END$$;
