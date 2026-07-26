from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import Role

_VALID_ROLES = {
    Role.ADMIN, Role.RELEASE_MANAGER, Role.TEST_MANAGER, Role.DEVELOPER, Role.VIEWER,
}


class GateCriterionCreate(BaseModel):
    title: str = Field(..., max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None
    assigned_role: Optional[str] = Field(None, max_length=50)

    @field_validator("assigned_role")
    @classmethod
    def _valid_role(cls, v):
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"assigned_role must be one of {sorted(_VALID_ROLES)}")
        return v

    @model_validator(mode="after")
    def _one_assignee(self):
        if self.assigned_role is not None and self.assigned_to_user_id is not None:
            raise ValueError("A criterion cannot be assigned to both a user and a role")
        return self


class GateCriterionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None
    assigned_role: Optional[str] = Field(None, max_length=50)

    @field_validator("assigned_role")
    @classmethod
    def _valid_role(cls, v):
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"assigned_role must be one of {sorted(_VALID_ROLES)}")
        return v

    @model_validator(mode="after")
    def _one_assignee(self):
        if self.assigned_role is not None and self.assigned_to_user_id is not None:
            raise ValueError("A criterion cannot be assigned to both a user and a role")
        return self


class GateCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str] = None
    assigned_role: Optional[str] = None
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
