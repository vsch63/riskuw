from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class ApsRequest(BaseModel):
    id: Optional[str] = None
    tenant_id: Optional[str] = None
    case_id: str
    application_id: Optional[str] = None
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    physician_name: Optional[str] = None
    physician_address: Optional[str] = None
    physician_phone: Optional[str] = None
    requested_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    status: str = "PENDING"
    notes: Optional[str] = None
    document_ref: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class ApsLetterTemplate(BaseModel):
    id: str
    template_name: str
    is_active: bool = False
    subject: str
    body_text: str
    footer_text: Optional[str] = None
    created_at: Optional[datetime] = None


class LetterTemplate(BaseModel):
    id: str
    template_name: str
    outcome: str
    is_active: bool = False
    version: int = 1
    header_company_name: Optional[str] = None
    header_tagline: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    body_text: Optional[str] = None
    next_steps: Optional[str] = None
    footer_text: Optional[str] = None
    created_at: Optional[datetime] = None


class Physician(BaseModel):
    id: Optional[int] = None
    physician_name: str
    registration_no: Optional[str] = None
    specialisation: Optional[str] = None
    clinic_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    is_active: bool = True
    effective_date: Optional[date] = None
    expire_date: Optional[date] = None
    created_at: Optional[datetime] = None
