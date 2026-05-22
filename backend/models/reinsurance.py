from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class RiReinsurer(BaseModel):
    id: Optional[int] = None
    tenant_id: Optional[str] = None
    reinsurer_name: str
    reinsurer_code: Optional[str] = None
    treaty_type: Optional[str] = None     # QUOTA_SHARE, SURPLUS, FAC
    retention_limit: Optional[float] = None
    is_active: bool = True
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    treaty_effective_date: Optional[date] = None
    treaty_expiry_date: Optional[date] = None


class RiCession(BaseModel):
    id: Optional[int] = None
    case_id: str
    reinsurer_id: int
    cession_type: str = "AUTOMATIC"       # AUTOMATIC, MANUAL, FACULTATIVE
    face_amount: float
    cession_amount: float
    risk_class: Optional[str] = None
    treaty_reference: Optional[str] = None
    status: str = "PENDING"              # PENDING, ACCEPTED, REJECTED, SETTLED
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
