from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class QueueCaseOut(BaseModel):
    id: str
    applicant_ref: Optional[str] = None
    applicant_name: Optional[str] = None
    product_code: Optional[str] = None
    face_amount: Optional[float] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    outcome: Optional[str] = None
    risk_class: Optional[str] = None
    net_debit_points: Optional[int] = None
    approved_premium: Optional[float] = None
    status: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AssignRequest(BaseModel):
    case_id: str
    assigned_to: str


class DecideRequest(BaseModel):
    case_id: str
    outcome: str
    risk_class: Optional[str] = None
    notes: Optional[str] = None
    table_rating: Optional[int] = None
    flat_extra: Optional[float] = None
    adverse_action_text: Optional[str] = None


class APSCreateRequest(BaseModel):
    case_id: str
    physician_name: Optional[str] = None
    physician_address: Optional[str] = None
    physician_phone: Optional[str] = None
    notes: Optional[str] = None
    rule_name: Optional[str] = None


class APSUpdateRequest(BaseModel):
    aps_id: str
    status: str
    notes: Optional[str] = None
    document_ref: Optional[str] = None
