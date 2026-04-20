# backend/app/api/v1/schemas/release_gate.py
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.schemas.gate_criterion import GateCriterionRead


class ReleaseGateCreate(BaseModel):
    name: str = Field(..., max_length=150)
    test_phase_id: Optional[int] = None


class ReleaseGateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    test_phase_id: Optional[int] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    test_phase_id: Optional[int]
    name: str
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
    criteria: List[GateCriterionRead] = []
    overdue_criterion_count: int = 0
