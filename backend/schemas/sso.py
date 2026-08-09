"""
backend/schemas/sso.py
────────────────────────
Pydantic request / response models for SSO provider configuration and
the OIDC authorize flow.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator

ALLOWED_ROLES = {
    "super_admin", "admin", "senior_underwriter", "underwriter",
    "api_client", "readonly", "agent", "broker",
}
PROVIDER_TYPES = {"OIDC", "LDAP"}


def _validate_role(v: str) -> str:
    if v not in ALLOWED_ROLES:
        raise ValueError(f"role must be one of {sorted(ALLOWED_ROLES)}")
    return v


class SsoProviderCreate(BaseModel):
    provider_code: str
    provider_type: str
    display_name: str
    is_active: bool = True

    # OIDC
    issuer_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    jwks_url: str | None = None
    scope: str = "openid email profile"
    oidc_username_claim: str = "preferred_username"

    # LDAP
    ldap_server_uri: str | None = None
    ldap_base_dn: str | None = None
    ldap_bind_dn: str | None = None
    ldap_bind_password: str | None = None
    ldap_user_filter: str | None = None
    ldap_username_attr: str = "sAMAccountName"

    # Mapping / provisioning
    default_role: str = "viewer"
    default_tenant_id: str | None = None
    claim_role_attr: str | None = None
    auto_provision: bool = False

    @field_validator("provider_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in PROVIDER_TYPES:
            raise ValueError(f"provider_type must be one of {sorted(PROVIDER_TYPES)}")
        return v.upper()

    @field_validator("default_role")
    @classmethod
    def _role(cls, v: str) -> str:
        return _validate_role(v)


class SsoProviderUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None

    issuer_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    jwks_url: str | None = None
    scope: str | None = None
    oidc_username_claim: str | None = None

    ldap_server_uri: str | None = None
    ldap_base_dn: str | None = None
    ldap_bind_dn: str | None = None
    ldap_bind_password: str | None = None
    ldap_user_filter: str | None = None
    ldap_username_attr: str | None = None

    default_role: str | None = None
    default_tenant_id: str | None = None
    claim_role_attr: str | None = None
    auto_provision: bool | None = None

    @field_validator("default_role")
    @classmethod
    def _role(cls, v):  # noqa: ANN001
        return _validate_role(v) if v is not None else v


class SsoProviderOut(BaseModel):
    provider_code: str
    provider_type: str
    display_name: str
    is_active: bool
    client_secret_set: bool = False
    ldap_bind_password_set: bool = False

    issuer_url: str | None = None
    client_id: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    jwks_url: str | None = None
    scope: str | None = None
    oidc_username_claim: str | None = None

    ldap_server_uri: str | None = None
    ldap_base_dn: str | None = None
    ldap_bind_dn: str | None = None
    ldap_user_filter: str | None = None
    ldap_username_attr: str | None = None

    default_role: str
    default_tenant_id: str | None = None
    claim_role_attr: str | None = None
    auto_provision: bool


class SsoProviderBrief(BaseModel):
    """Public login-page view — never exposes secrets."""
    provider_code: str
    provider_type: str
    display_name: str


class SsoAuthorizeOut(BaseModel):
    authorize_url: str
