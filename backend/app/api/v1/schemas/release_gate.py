# backend/app/api/v1/schemas/release_gate.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ReleaseGateCreate(BaseModel):
    name: str = Field(..., max_length=150)
    test_phase_id: Optional[int] = None
    acceptance_criteria: Optional[str] = None


class ReleaseGateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    test_phase_id: Optional[int] = None
    acceptance_criteria: Optional[str] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    test_phase_id: Optional[int]
    name: str
    acceptance_criteria: Optional[str]
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
