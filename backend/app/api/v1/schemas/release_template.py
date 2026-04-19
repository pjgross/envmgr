# backend/app/api/v1/schemas/release_template.py
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ReleaseTemplatePhase(BaseModel):
    name: str = Field(..., max_length=100)
    order: int = 0
    default_duration_days: int = 5
    activities: list[str] = []


class ReleaseTemplateGate(BaseModel):
    name: str = Field(..., max_length=150)
    phase_name: Optional[str] = None  # None = release-level gate
    acceptance_criteria: Optional[str] = None


class ReleaseTemplateCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    release_type: str = Field(..., max_length=50)
    default_lifecycle_template_id: Optional[int] = None
    phases: list[ReleaseTemplatePhase] = []
    gates: list[ReleaseTemplateGate] = []


class ReleaseTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    release_type: Optional[str] = Field(None, max_length=50)
    default_lifecycle_template_id: Optional[int] = None
    phases: Optional[list[ReleaseTemplatePhase]] = None
    gates: Optional[list[ReleaseTemplateGate]] = None


class ReleaseTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    release_type: str
    default_lifecycle_template_id: Optional[int]
    phases: list[Any]
    gates: list[Any]
    version: int
    created_at: datetime
    updated_at: datetime


class ReleaseTemplateInstantiate(BaseModel):
    name: str = Field(..., max_length=250)
    target_date: datetime
    description: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
