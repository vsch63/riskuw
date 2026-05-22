from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel


# ── Batch ─────────────────────────────────────────────────────────────────────

class BatchJob(BaseModel):
    id: str
    job_number: str
    job_name: Optional[str] = None
    status: str = "QUEUED"
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


class BatchJobRecord(BaseModel):
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


class BatchRecurringSchedule(BaseModel):
    id: Optional[int] = None
    schedule_name: Optional[str] = None
    cron_expression: Optional[str] = None
    status: str = "ACTIVE"
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
