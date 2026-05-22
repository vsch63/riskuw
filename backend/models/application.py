from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel


class Application(BaseModel):
    id: str
    application_number: str
    product_type: str
    product_code: Optional[str] = None
    channel: str
    applicant_ref: str
    age: int
    gender: str
    state: str
    citizenship: str = "IN"
    face_amount: float
    coverage_term_yrs: Optional[int] = None
    is_replacement: bool = False
    status: str = "DRAFT"
    submitted_at: Optional[datetime] = None
    raw_payload: Optional[Any] = None
    tenant_id: str
    created_at: Optional[datetime] = None
    is_deleted: bool = False

    model_config = {"from_attributes": True}


class ApplicantMaster(BaseModel):
    id: Optional[int] = None
    applicant_ref: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: str = "India"
    source: str = "UPLOAD"
    uploaded_by: Optional[str] = None
    created_at: Optional[datetime] = None
