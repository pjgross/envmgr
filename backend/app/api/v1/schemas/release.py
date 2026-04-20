# backend/app/api/v1/schemas/release.py
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field, ConfigDict


class ReleaseCreate(BaseModel):
    name: str = Field(..., max_length=250)
    description: Optional[str] = None
    release_type: str = Field(..., max_length=50)
    release_kind: str = Field(default="project", max_length=20)
    template_id: Optional[int] = None
    lifecycle_template_id: Optional[int] = None  # service falls back to tenant default
    target_date: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=250)
    description: Optional[str] = None
    release_type: Optional[str] = Field(None, max_length=50)
    target_date: Optional[datetime] = None
    actual_date: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    release_type: str
    release_kind: str
    parent_release_id: Optional[int]
    template_id: Optional[int]
    lifecycle_template_id: int
    status: str
    target_date: Optional[datetime]
    actual_date: Optional[datetime]
    custom_fields: Optional[dict[str, Any]] = None
    raised_by: int
    created_at: datetime
    updated_at: datetime


class ReleaseTransition(BaseModel):
    to_state: str
    notes: Optional[str] = None


class ReleaseStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    release_id: int
    from_state: Optional[str]
    to_state: str
    changed_by: int
    changed_at: datetime
    notes: Optional[str]


class ReleaseListItemRead(ReleaseRead):
    """Extended read schema for list endpoints — includes summary counts."""
    phase_count: int = 0
    scope_count: int = 0
    blocker_count: int = 0
    overdue_criterion_count: int = 0
