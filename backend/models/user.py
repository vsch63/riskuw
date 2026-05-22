"""
backend/models/user.py
Pydantic row models for user-related tables.
Used for type-safe parsing of psycopg2 RealDictCursor rows.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class UwUser(BaseModel):
    id: str
    username: str
    email: str
    hashed_password: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    tenant_id: str
    last_login_at: Optional[datetime] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    created_at: Optional[datetime] = None
    is_deleted: bool = False

    model_config = {"from_attributes": True}


class MfaConfig(BaseModel):
    username: str
    totp_secret: str
    is_enabled: bool = False
    is_verified: bool = False
    backup_codes: Optional[list[str]] = None
    enabled_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class LoginAttempts(BaseModel):
    username: str
    failed_count: int = 0
    last_failed_at: Optional[datetime] = None
    locked_until: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserAuthorityLimits(BaseModel):
    id: Optional[int] = None
    username: str
    min_face_amount: float = 0
    max_face_amount: Optional[float] = None
    product_codes: Optional[list[str]] = None
    notes: Optional[str] = None
    is_active: bool = True
    set_by: Optional[str] = None
    is_medical_officer: bool = False
    medical_specialisations: Optional[list[str]] = None
    can_assess_medical: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
