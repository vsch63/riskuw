from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel


class Tenant(BaseModel):
    id: str
    tenant_code: str
    tenant_name: str
    status: str = "ACTIVE"
    plan_tier: str = "STANDARD"
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    company_type: Optional[str] = None
    state_of_domicile: Optional[str] = None
    max_users: int = 50
    max_decisions_per_month: int = 10000
    decisions_this_month: int = 0
    api_enabled: bool = True
    timezone: str = "Asia/Kolkata"
    date_format: str = "DD-MMM-YYYY"
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    created_at: Optional[datetime] = None


class SystemConfig(BaseModel):
    id: str
    tenant_id: str
    config_key: str
    config_value: str
    config_type: str = "string"
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class TenantRuleConfig(BaseModel):
    id: str
    tenant_id: str
    rule_id: str
    rule_name: Optional[str] = None
    category: Optional[str] = None
    is_enabled: bool = True
    points_override: Optional[int] = None
    notes: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class TenantUsage(BaseModel):
    id: str
    tenant_id: str
    metric_date: date
    decisions_made: int = 0
    batch_jobs_run: int = 0
    api_calls: int = 0
    active_users: int = 0
