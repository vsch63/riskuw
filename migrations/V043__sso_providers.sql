-- ============================================================
-- V043__sso_providers.sql
--
-- SSO infrastructure (finishes Tier1): corporate-directory login
-- via OIDC authorization-code + PKCE and LDAP bind.
--
--   * sso_provider  — per-provider configuration (protocol fields,
--     role/tenant mapping, auto-provisioning flag). Tenant-level
--     infrastructure (like smtp_config), deliberately NOT tenant-
--     scoped — it is the thing other tenants' SSO would share.
--   * sso_flow      — short-lived OIDC state/code-verifier/nonce
--     scratch (single-use, mirrors password_reset_tokens).
--   * uw_user       — sso_provider_code + sso_subject linkage
--     (partial unique index; hashed_password is already nullable,
--     so SSO-only users can never password-login).
--
-- provider_type reserves 'SAML' for a later milestone (needs an
-- xmlsec system dependency); OIDC + LDAP are implemented today.
-- All statements are idempotent (IF NOT EXISTS). Matches the
-- V040–V042 pattern.
-- ============================================================

-- ── sso_provider ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sso_provider (
    provider_code        VARCHAR(50)  PRIMARY KEY,
    provider_type        VARCHAR(20)  NOT NULL
        CHECK (provider_type IN ('OIDC','LDAP','SAML')),
    display_name         VARCHAR(200) NOT NULL,
    is_active            BOOLEAN      NOT NULL DEFAULT true,

    -- OIDC (authorization-code + PKCE)
    issuer_url           VARCHAR(500),
    client_id            VARCHAR(500),
    client_secret        VARCHAR(1000),
    authorize_url        VARCHAR(500),
    token_url            VARCHAR(500),
    jwks_url             VARCHAR(500),
    scope                VARCHAR(500) NOT NULL DEFAULT 'openid email profile',
    oidc_username_claim  VARCHAR(100) NOT NULL DEFAULT 'preferred_username',

    -- LDAP (bind + search)
    ldap_server_uri      VARCHAR(500),
    ldap_base_dn         VARCHAR(500),
    ldap_bind_dn         VARCHAR(500),
    ldap_bind_password   VARCHAR(1000),
    ldap_user_filter     VARCHAR(500),
    ldap_username_attr   VARCHAR(100) NOT NULL DEFAULT 'sAMAccountName',

    -- Role / tenant mapping + JIT provisioning
    default_role         VARCHAR(30)  NOT NULL DEFAULT 'viewer',
    default_tenant_id    uuid,
    claim_role_attr      VARCHAR(100),
    auto_provision       BOOLEAN      NOT NULL DEFAULT false,

    created_by  VARCHAR(100),
    updated_by  VARCHAR(100),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Comments ─────────────────────────────────────────────────────────────────
COMMENT ON COLUMN public.sso_provider.client_secret IS
    'OIDC client secret — stored plaintext today, encrypted at rest once Vault lands (Tier1); never returned by the API.';
COMMENT ON COLUMN public.sso_provider.ldap_bind_password IS
    'LDAP service-account password — stored plaintext today, encrypted at rest once Vault lands (Tier1); never returned by the API.';

-- ── sso_flow ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sso_flow (
    state          VARCHAR(100) PRIMARY KEY,
    provider_code  VARCHAR(50)  NOT NULL,
    code_verifier  VARCHAR(200),
    nonce          VARCHAR(100),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ  NOT NULL
);

-- ── uw_user SSO linkage ──────────────────────────────────────────────────────
ALTER TABLE public.uw_user
    ADD COLUMN IF NOT EXISTS sso_provider_code VARCHAR(50);
ALTER TABLE public.uw_user
    ADD COLUMN IF NOT EXISTS sso_subject VARCHAR(500);

-- One SSO identity per provider per user; password-only users (both
-- NULL) are excluded so they are unaffected by the unique constraint.
CREATE UNIQUE INDEX IF NOT EXISTS uq_uw_user_sso
    ON public.uw_user (sso_provider_code, sso_subject)
    WHERE sso_provider_code IS NOT NULL AND sso_subject IS NOT NULL;

COMMENT ON COLUMN public.uw_user.sso_provider_code IS
    'Which sso_provider this account authenticates through (NULL = local password login).';
COMMENT ON COLUMN public.uw_user.sso_subject IS
    'Stable subject/identifier at the SSO provider (OIDC sub, LDAP username attr).';
