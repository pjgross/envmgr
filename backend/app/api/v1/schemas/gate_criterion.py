from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


class GateCriterionCreate(BaseModel):
    title: str = Field(..., max_length=250)
    notes: Optional[str] = None
    due_date: Optional[datetime] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = None
    due_date: Optional[datetime] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    due_date: Optional[datetime]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str] = None
    status: str
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    @computed_field  # exposed as `is_overdue` in JSON
    @property
    def is_overdue(self) -> bool:
        if self.status != "open" or self.due_date is None:
            return False
        return self.due_date < datetime.now(timezone.utc)


class GateCriterionWithGate(GateCriterionRead):
    """List-item variant used by /releases/{id}/overdue-criteria."""
    gate_name: str
