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
    model_config = ConfigDict(from_attributes=True)


class PirActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    detail: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[datetime] = None
    status: str = "open"
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


PirFindingResponse.model_rebuild()
