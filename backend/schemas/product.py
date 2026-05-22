from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Product ───────────────────────────────────────────────────────────────────

class ProductOut(BaseModel):
    product_code: str
    product_name: str
    name: Optional[str] = None          # alias for frontend
    category: Optional[str] = None
    sub_type: Optional[str] = None
    uw_method: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    min_face: Optional[float] = None
    max_face: Optional[float] = None
    min_face_amount: Optional[float] = None  # alias
    max_face_amount: Optional[float] = None  # alias
    is_active: bool = True
    is_gi: bool = False
    terms: list[int] = []
    notes: Optional[str] = None
    exam_note: Optional[str] = None

    model_config = {"from_attributes": True}


class ProductRuleOut(BaseModel):
    product_code: str
    rule_id: str
    is_enabled: bool = True
    debit_points_override: Optional[int] = None
    flat_extra_override: Optional[float] = None
    created_at: Optional[datetime] = None
