from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.pir_finding import ACTION_STATUSES, FINDING_KINDS


class PirFindingCreate(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=500)
    detail: Optional[str] = None
    root_cause: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in FINDING_KINDS:
            raise ValueError(f"kind must be one of {sorted(FINDING_KINDS)}")
        return v


class PirFindingUpdate(BaseModel):
    # `kind` is accepted so an attempt to change it earns an explicit 422 naming
    # the field, rather than `extra="forbid"`'s generic "extra inputs are not
    # permitted" — the reader needs to know it is immutable, not misspelled.
    kind: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    detail: Optional[str] = None
    root_cause: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class PirFindingResponse(BaseModel):
    id: int
    kind: str
    seq: int
    title: str
    detail: Optional[str]
    root_cause: Optional[str]
    created_at: datetime
    actions: list["PirActionResponse"] = []
    # The incidents this finding cites as evidence. Defaulted so `model_validate`
    # can build straight off the ORM row (which has no such attribute) before the
    # route layer fills it in — no caller is meant to see the default itself.
    incidents: list["PirCitationResponse"] = []
    model_config = ConfigDict(from_attributes=True)


class PirActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    detail: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[datetime] = None
    status: str = "open"
    # An action may be created ALREADY CLOSED — "we did this during the
    # incident" is an ordinary thing for a review to record — and `status` is
    # settable here, so the note explaining the closure has to be settable too.
    # Without it the create form's own Closure note field is a 422 (found in the
    # browser: every action created from the UI failed, because the dialog sends
    # this key on every save).
    closure_note: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ACTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(ACTION_STATUSES)}")
        return v


class PirActionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    detail: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None
    closure_note: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in ACTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(ACTION_STATUSES)}")
        return v


class PirActionResponse(BaseModel):
    id: int
    finding_id: int
    seq: int
    title: str
    detail: Optional[str]
    owner_id: Optional[int]
    # Resolved server-side and travelling WITH the row. Never `#N`, and never
    # looked up client-side against a capped collection. Both fields default here
    # only so `model_validate` can build straight off the ORM row (which has
    # neither attribute) before the route layer overwrites them with the real,
    # computed values — no caller of this schema is ever meant to see the
    # defaults themselves.
    owner_username: Optional[str] = None
    due_date: Optional[datetime]
    status: str
    closed_at: Optional[datetime]
    closure_note: Optional[str]
    is_overdue: bool = False
    model_config = ConfigDict(from_attributes=True)


class PirCitationCreate(BaseModel):
    incident_id: int
    note: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class PirCitationResponse(BaseModel):
    """A cited incident rendered for the finding it is evidence for.

    The incident's title, severity and status travel WITH the citation: a chip
    reading `#41` identifies nothing, and resolving the id client-side against a
    capped collection loses the incident rather than merely shortening a list.
    """

    incident_id: int
    incident_title: str
    severity: str
    status: str
    note: Optional[str]


PirFindingResponse.model_rebuild()


class PirActionRow(BaseModel):
    """One worklist row. Every name travels WITH the row — a worklist is a list of
    things the reader has never seen, so an id identifies nothing."""

    id: int
    finding_id: int
    finding_title: str
    release_id: int
    release_name: str
    pir_status: str
    title: str
    detail: Optional[str]
    owner_id: Optional[int]
    owner_username: Optional[str]
    due_date: Optional[datetime]
    status: str
    closed_at: Optional[datetime]
    closure_note: Optional[str]
    is_overdue: bool
