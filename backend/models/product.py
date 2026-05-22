from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class Product(BaseModel):
    id: str
    tenant_id: str
    product_code: str
    product_name: str
    category: Optional[str] = None
    sub_type: Optional[str] = None
    uw_method: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    min_face: Optional[float] = None
    max_face: Optional[float] = None
    is_active: bool = True
    is_gi: bool = False
    effective_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None


class ProductRules(BaseModel):
    id: Optional[int] = None
    product_code: str
    rule_id: str
    is_enabled: bool = True
    debit_points_override: Optional[int] = None
    flat_extra_override: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProductDecisionThresholds(BaseModel):
    id: str
    tenant_id: str
    product_code: str
    refer_threshold: int = 150
    decline_threshold: int = 200
    stp_threshold: int = 75
    max_table_rating: int = 8
    max_flat_extra: float = 25.0
    allow_permanent_flat_extra: bool = False
    allow_exclusion_riders: bool = True
    max_income_multiple: int = 20
    max_net_worth_multiple: float = 5.0
    large_face_threshold: float = 10_000_000
    version: int = 1
    created_at: Optional[datetime] = None


class ProductBuildTable(BaseModel):
    id: Optional[int] = None
    product_code: str
    bmi_min: float
    bmi_max: float
    debit_points: int = 0
    is_decline: bool = False
    band_label: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None
