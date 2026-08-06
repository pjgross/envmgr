from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentRequestCreate(BaseModel):
    # M4: no `custom_fields` here — no tenant can define a custom-field
    # vocabulary for this entity (VALID_ENTITY_TYPES in
    # api/v1/schemas/custom_field.py has no `environment_request` entry), so
    # this was the only entity in the app accepting an arbitrary, unvalidated
    # JSON blob. Removed rather than left dead: dead-but-accepted input
    # surface is still surface.
    kind: str = Field(pattern="^(access|new_environment)$")
    justification: str = Field(min_length=1)
    needed_by: Optional[datetime] = None
    # kind='access'
    environment_id: Optional[int] = None
    # kind='new_environment'
    proposed_name: Optional[str] = Field(default=None, max_length=200)
    tier_id: Optional[int] = None
    expires_at: Optional[datetime] = None


class EnvironmentRequestUpdate(BaseModel):
    # M3: extra="forbid" — {"status": ..., "created_environment_id": ...}
    # used to return 200 and silently ignore both keys rather than refuse
    # them, which is the same "looks like it worked" hazard M4 removes for
    # custom_fields and the earlier `kind` test pins for the same reason.
    model_config = ConfigDict(extra="forbid")

    justification: Optional[str] = Field(default=None, min_length=1)
    needed_by: Optional[datetime] = None
    environment_id: Optional[int] = None
    proposed_name: Optional[str] = Field(default=None, max_length=200)
    tier_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    # Set by the approving Admin on a new-environment request; becomes the
    # created environment's operating team.
    operations_group_id: Optional[int] = None


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
    # M4: no `custom_fields` — see EnvironmentRequestCreate's docstring. The
    # underlying model column is left in place (dead, always null) rather
    # than migrated away, matching this repo's existing precedent for an
    # unused-but-undropped column (InfrastructureComponentSource.TERRAFORM).
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
            created_at=r.created_at, updated_at=r.updated_at,
        )


NOT_PROVIDED = "Not provided"


class WelcomePackResponse(BaseModel):
    """Rendered live from the environment; stored nowhere.

    Every free-text field falls back to "Not provided" rather than null or an
    empty string. A blank "How to connect" section reads as "there is nothing
    to do", which is the absent-versus-checked-and-empty confusion this
    codebase has been burned by before.
    """

    environment: dict
    access: dict
    support: dict
    caveats: dict
    offboarding: dict
    context: dict
