from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class AuditTrail(BaseModel):
    """Immutable audit log — DB trigger prevents UPDATE/DELETE."""
    id: Optional[int] = None
    event_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    event_category: str
    event_type: str
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    actor_ip: Optional[str] = None
    tenant_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    entity_ref: Optional[str] = None
    before_state: Optional[Any] = None
    after_state: Optional[Any] = None
    event_metadata: Optional[Any] = None
    outcome: str = "SUCCESS"
    failure_reason: Optional[str] = None
    source: str = "API"


class AuditEvent(BaseModel):
    id: str
    tenant_id: str
    event_id: str
    event_type: str
    event_category: str
    entity_type: str
    entity_id: str
    actor_type: str
    actor_id: str
    actor_ip: Optional[str] = None
    before_state: Optional[Any] = None
    after_state: Optional[Any] = None
    event_metadata: Optional[Any] = None
    occurred_at: Optional[datetime] = None
    recorded_at: Optional[datetime] = None


class NotificationLog(BaseModel):
    id: Optional[int] = None
    event: Optional[str] = None
    recipient: Optional[str] = None
    subject: Optional[str] = None
    status: Optional[str] = None
    error_msg: Optional[str] = None
    sent_at: Optional[datetime] = None
    error_code: Optional[str] = None
    applicant_ref: Optional[str] = None
    batch_job_name: Optional[str] = None
