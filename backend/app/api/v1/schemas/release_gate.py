# backend/app/api/v1/schemas/release_gate.py
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.schemas.gate_criterion import GateCriterionRead


class ReleaseGateCreate(BaseModel):
    # extra="forbid" so a typo'd key (e.g. gateTypeId) is a 422 rather than a
    # silent drop — the POST /projects class of bug, and the exact shape of
    # the hole this schema is being extended to close.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=150)
    due_date: datetime
    gate_type_id: Optional[int] = None
    test_phase_id: Optional[int] = None


class ReleaseGateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=150)
    due_date: Optional[datetime] = None
    # Both keyed on model_fields_set by the service: an OMITTED key means
    # "leave alone", only an explicit null clears it. See update_gate.
    gate_type_id: Optional[int] = None
    test_phase_id: Optional[int] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None
    # The three fields below only apply to override_gate (a waiver); pass_gate
    # and fail_gate ignore them. expires_at=None means a permanent waiver —
    # a legitimate state, never confused with an expired one.
    expires_at: Optional[datetime] = None
    remediation: Optional[str] = None
    approved_by_user_id: Optional[int] = None


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    name: str
    due_date: datetime
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
    gate_type_id: Optional[int] = None
    test_phase_id: Optional[int] = None
    criteria: List[GateCriterionRead] = []
    overdue_criterion_count: int = 0
