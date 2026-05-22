from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class BatchJobCreate(BaseModel):
    job_name: Optional[str] = None
    dry_run: bool = False
    skip_product_errors: bool = False
    policy_effective_date: Optional[str] = None
    policy_expire_date: Optional[str] = None


class BatchJobOut(BaseModel):
    id: str
    job_number: str
    job_name: Optional[str] = None
    status: str
    total_records: int = 0
    processed_count: int = 0
    approved_count: int = 0
    declined_count: int = 0
    referred_count: int = 0
    errored_count: int = 0
    dry_run: bool = False
    input_filename: Optional[str] = None
    error_message: Optional[str] = None
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BatchRecordOut(BaseModel):
    id: Optional[int] = None
    job_id: str
    row_number: Optional[int] = None
    applicant_ref: Optional[str] = None
    product_code: Optional[str] = None
    status: Optional[str] = None
    outcome: Optional[str] = None
    risk_class: Optional[str] = None
    net_debit_points: Optional[int] = None
    primary_reason: Optional[str] = None
    error_codes: Optional[str] = None
    processing_ms: Optional[int] = None
    created_at: Optional[datetime] = None
