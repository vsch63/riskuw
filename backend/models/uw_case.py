from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel


class UwCase(BaseModel):
    id: str
    case_number: str
    application_id: str
    product_type: str
    product_code: Optional[str] = None
    status: str
    decision_pathway: Optional[str] = None
    assigned_uw_id: Optional[str] = None
    assigned_at: Optional[datetime] = None
    sla_due_at: Optional[datetime] = None
    sla_breached: bool = False
    priority_score: Optional[int] = None
    complexity_score: Optional[int] = None
    auto_decision_at: Optional[datetime] = None
    final_decision_at: Optional[datetime] = None
    reinsurance_required: bool = False
    applicant_age: Optional[int] = None
    face_amount: Optional[float] = None
    uw_notes: Optional[str] = None
    tenant_id: str
    created_at: Optional[datetime] = None
    is_deleted: bool = False


class UwDecision(BaseModel):
    id: str
    case_id: str
    application_id: str
    decision_sequence: int = 1
    is_final: bool = True
    outcome: str
    risk_class: Optional[str] = None
    table_rating: Optional[int] = None
    flat_extra_per_thou: Optional[float] = None
    flat_extra_years: Optional[int] = None
    total_debit_points: int = 0
    total_credit_points: int = 0
    net_debit_points: int = 0
    approved_face_amount: Optional[float] = None
    approved_premium: Optional[float] = None
    decline_reason_code: Optional[str] = None
    adverse_action_text: Optional[str] = None
    findings_json: Optional[Any] = None
    is_override: bool = False
    decided_by_type: str = "AUTOMATED"
    decided_at: Optional[datetime] = None
    decision_rules_ver: Optional[str] = None
    primary_reason: Optional[str] = None
    tenant_id: str
    created_at: Optional[datetime] = None
    is_deleted: bool = False


class PolicyAdminQueue(BaseModel):
    id: Optional[int] = None
    applicant_ref: Optional[str] = None
    applicant_name: Optional[str] = None
    applicant_email: Optional[str] = None
    case_id: Optional[str] = None
    product_code: Optional[str] = None
    face_amount: Optional[float] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    state: Optional[str] = None
    outcome: Optional[str] = None
    risk_class: Optional[str] = None
    net_debit_points: Optional[int] = None
    approved_premium: Optional[float] = None
    effective_date: Optional[date] = None
    decision_date: Optional[datetime] = None
    source: str = "ONLINE"
    status: str = "UNPROCESSED"
    push_status: str = "PENDING"
    created_at: Optional[datetime] = None
