from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentRequestCreate(BaseModel):
    kind: str = Field(pattern="^(access|new_environment)$")
    justification: str = Field(min_length=1)
    needed_by: Optional[datetime] = None
    # kind='access'
    environment_id: Optional[int] = None
    # kind='new_environment'
    proposed_name: Optional[str] = Field(default=None, max_length=200)
    tier_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    custom_fields: Optional[dict] = None


class EnvironmentRequestUpdate(BaseModel):
    justification: Optional[str] = Field(default=None, min_length=1)
    needed_by: Optional[datetime] = None
    environment_id: Optional[int] = None
    proposed_name: Optional[str] = Field(default=None, max_length=200)
    tier_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    # Set by the approving Admin on a new-environment request; becomes the
    # created environment's operating team.
    operations_group_id: Optional[int] = None
    custom_fields: Optional[dict] = None


class EnvironmentRequestTransition(BaseModel):
    """No `notes` field: there is no history table for this entity, so any
    text sent here would be accepted and silently discarded rather than
    persisted anywhere an approver's rejection reason could be read back.
    Removed rather than wired up — adding a history table is out of scope
    for this task; reconsider if/when one exists."""

    to_state: str


class EnvironmentRequestResponse(BaseModel):
    """Display names travel with the row.

    Resolving them in the browser against separately-fetched collections is the
    failure docs/pagination.md documents: those collections are capped, so a
    `.find()` miss renders the entity as '—' and loses information no
    truncation banner can recover.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    kind: str
    status: str
    lifecycle_id: int
    requested_by: int
    requester_username: Optional[str] = None
    justification: str
    needed_by: Optional[datetime] = None
    environment_id: Optional[int] = None
    environment_name: Optional[str] = None
    proposed_name: Optional[str] = None
    tier_id: Optional[int] = None
    tier_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    operations_group_id: Optional[int] = None
    operations_group_name: Optional[str] = None
    created_environment_id: Optional[int] = None
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "EnvironmentRequestResponse":
        r = view.request
        return cls(
            id=r.id, tenant_id=r.tenant_id, kind=r.kind, status=r.status,
            lifecycle_id=r.lifecycle_id, requested_by=r.requested_by,
            requester_username=view.requester_username,
            justification=r.justification, needed_by=r.needed_by,
            environment_id=r.environment_id,
            environment_name=view.environment_name,
            proposed_name=r.proposed_name, tier_id=r.tier_id,
            tier_name=view.tier_name, expires_at=r.expires_at,
            operations_group_id=r.operations_group_id,
            operations_group_name=view.operations_group_name,
            created_environment_id=r.created_environment_id,
            custom_fields=r.custom_fields,
            created_at=r.created_at, updated_at=r.updated_at,
        )
