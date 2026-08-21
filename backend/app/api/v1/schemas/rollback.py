"""Phase 9 C4 Tasks 2 and 4 — wire schemas for the per-component rollback plan
and the per-system rollback rehearsal."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Reversibility = Literal["reversible", "lossy", "irreversible"]
RehearsalOutcome = Literal["passed", "failed", "partial"]
RehearsalState = Literal["current", "stale"]


class RollbackPlanCreate(BaseModel):
    # extra="forbid" so a typo'd key is a 422 rather than a silent drop — the
    # POST /projects dropping priority_rank class of bug.
    model_config = ConfigDict(extra="forbid")

    system_id: int
    steps: str = Field(..., min_length=1)
    reversibility: Reversibility
    estimated_minutes: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None


class RollbackPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    release_id: int
    system_id: int
    system_name: Optional[str] = None
    steps: str
    reversibility: str
    estimated_minutes: Optional[int]
    notes: Optional[str]
    agreed_by_user_id: Optional[int]
    agreed_by_username: Optional[str] = None
    agreed_at: Optional[datetime]


class RehearsalCreate(BaseModel):
    # extra="forbid" — same reason as RollbackPlanCreate: a typo'd key must be
    # a 422, never a silent drop.
    model_config = ConfigDict(extra="forbid")

    rehearsed_at: datetime
    outcome: RehearsalOutcome
    notes: Optional[str] = None


class RehearsalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    system_id: int
    rehearsed_at: datetime
    rehearsed_by_user_id: int
    rehearsed_by_username: Optional[str] = None
    outcome: str
    notes: Optional[str]
    # COMPUTED on every read, never stored — see rollback_rehearsal_service.
    # rehearsal_state. A `failed` rehearsal still renders here faithfully;
    # whether it counts as "current" for readiness purposes is Task 5's call,
    # not this schema's.
    state: RehearsalState
