from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GateCriterionCreate(BaseModel):
    title: str = Field(..., max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str] = None
    status: str
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class GateCriterionWithGate(GateCriterionRead):
    """List-item variant used by /releases/{id}/overdue-criteria.

    `gate_name` and `gate_due_date` are hydrated by the endpoint from the
    parent ReleaseGate — criteria no longer carry their own due date."""
    gate_name: str
    gate_due_date: datetime
