from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel


class RuleFiredOut(BaseModel):
    rule_id: Optional[str] = None
    rule_code: Optional[str] = None
    rule_name: Optional[str] = None
    debit_points: int = 0
    credit_points: int = 0
    severity: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    requires_aps: bool = False
    aps_reason: Optional[str] = None


class UWDecisionResponse(BaseModel):
    outcome: str
    risk_class: Optional[str] = None
    net_debit_points: int = 0
    total_debits: Optional[int] = None
    total_credits: Optional[int] = None
    approved_premium: Optional[float] = None
    table_rating: Optional[int] = None
    flat_extra_per_thou: Optional[float] = None
    adverse_action_text: Optional[str] = None
    rules_fired: list[RuleFiredOut] = []
    pathway: Optional[str] = None
    is_stp: bool = False
    application_id: Optional[str] = None
    case_id: Optional[str] = None
    decision_id: Optional[str] = None
    rules_version: Optional[str] = None
    evaluated_at: Optional[str] = None
    applicant_name: Optional[str] = None
    policy_effective_date: Optional[str] = None
    policy_expire_date: Optional[str] = None
    error_codes: Optional[list[str]] = None
    error: Optional[str] = None
    detail: Optional[str] = None
