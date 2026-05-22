"""
backend/schemas/auth.py
────────────────────────
Pydantic request / response models for authentication.
"""
from __future__ import annotations
from pydantic import BaseModel, EmailStr, field_validator
import re


class LoginRequest(BaseModel):
    username: str
    password: str


class MFAVerifyRequest(BaseModel):
    totp_code: str
    username: str
    session_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    mfa_required: bool = False
    mfa_session_token: str | None = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str = "viewer"
    tenant_id: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {
            "super_admin", "admin", "senior_underwriter",
            "underwriter", "api_client", "readonly",
        }
        if v not in allowed:
            raise ValueError(f"role must be one of {sorted(allowed)}")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UserOut(BaseModel):
    username: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    tenant_id: str

    model_config = {"from_attributes": True}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class PasswordReset(BaseModel):
    """Admin-initiated reset — no current password needed."""
    new_password: str
    actor_username: str  # who is doing the reset (for audit_trail)
