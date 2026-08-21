"""Phase 9 C4 Task 2 — wire schemas for the per-component rollback plan."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Reversibility = Literal["reversible", "lossy", "irreversible"]
RehearsalOutcome = Literal["passed", "failed", "partial"]


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
