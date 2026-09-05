"""Schemas for Phase 9 C3 — recording a Go/No-Go decision.

`GoNoGoDecisionCreate` deliberately carries no snapshot fields: the frozen
readiness snapshot is captured SERVER-SIDE, by
`go_no_go_service.record_decision` calling `release_readiness_service.
evaluate`, never accepted from the request. A client-supplied snapshot would
be a client-supplied audit record.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.go_no_go import OUTCOME_VALUES


class GoNoGoSignoffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    perspective_id: int
    user_id: int
    verdict: str
    dissent_note: Optional[str] = None

    @field_validator("verdict")
    @classmethod
    def _known_verdict(cls, v: str) -> str:
        if v not in OUTCOME_VALUES:
            raise ValueError(f"verdict must be one of {OUTCOME_VALUES}")
        return v


class GoNoGoConditionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    owner_user_id: Optional[int] = None
    due_date: Optional[date] = None


class GoNoGoDecisionCreate(BaseModel):
    # extra="forbid" is not optional here: POST /tenant/lifecycle-templates
    # silently DROPPED required_fields for months because it was missing, and
    # A4's POST /projects silently discarded priority_rank the same way.
    model_config = ConfigDict(extra="forbid")

    outcome: str
    rationale: str = Field(min_length=1)
    decided_at: datetime
    attendees: list[int] = Field(default_factory=list)
    signoffs: list[GoNoGoSignoffCreate] = Field(default_factory=list)
    conditions: list[GoNoGoConditionCreate] = Field(default_factory=list)

    @field_validator("outcome")
    @classmethod
    def _known_outcome(cls, v: str) -> str:
        if v not in OUTCOME_VALUES:
            raise ValueError(f"outcome must be one of {OUTCOME_VALUES}")
        return v


class GoNoGoSignoffRead(BaseModel):
    id: int
    decision_id: int
    perspective_id: int
    user_id: int
    # Resolved server-side and travelling WITH the row — never `#N`. Defaulted
    # only so `model_validate` can build straight off the ORM row (which has
    # no such attribute) before the route layer overwrites it with the real,
    # `go_no_go_service.usernames_for`-resolved value.
    username: Optional[str] = None
    verdict: str
    dissent_note: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class GoNoGoConditionRead(BaseModel):
    id: int
    decision_id: int
    text: str
    owner_user_id: Optional[int]
    owner_username: Optional[str] = None
    due_date: Optional[date]
    met_at: Optional[datetime]
    met_by_user_id: Optional[int]
    met_by_username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class GoNoGoConditionClose(BaseModel):
    """PATCH body for `/go-no-go-conditions/{id}`. `met=False` reopens a
    condition marked met in error — the same clear-the-fields shape
    `go_no_go_service.close_condition` implements."""

    model_config = ConfigDict(extra="forbid")

    met: bool


class GoNoGoPerspectiveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class GoNoGoPerspectiveUpdate(BaseModel):
    # Optional fields + exclude_unset in the service: an omitted key means
    # "leave alone", same rule EnvironmentUpdate/GateTypeUpdate follow.
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class GoNoGoPerspectiveRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    sort_order: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class GoNoGoDecisionRead(BaseModel):
    """An append-only decision, read back with its children and resolved
    names. `unmet_condition_count` is computed by
    `go_no_go_service.reads_for_decisions` from `conditions` (a condition
    with `met_at is None`) rather than stored — the count moves the moment a
    condition closes, with no cache to invalidate. Every field defaulted
    below has no equivalent ORM attribute, so `model_validate` can build
    straight off the bare `GoNoGoDecision` row before `reads_for_decisions`
    overwrites them with the real, batched values — the same reason
    `GoNoGoSignoffRead.username` and `GoNoGoConditionRead.owner_username`
    default to `None`.
    """

    id: int
    tenant_id: int
    release_id: int
    outcome: str
    rationale: str
    decided_at: datetime
    chaired_by_user_id: int
    chaired_by_username: Optional[str] = None
    attendees: list[int]
    snapshot_ok: bool
    snapshot_blockers: list[dict]
    snapshot_warnings: list[dict]
    snapshot_reversibility: Optional[str]
    snapshot_rehearsal_state: Optional[str]
    signoffs: list[GoNoGoSignoffRead] = Field(default_factory=list)
    conditions: list[GoNoGoConditionRead] = Field(default_factory=list)
    unmet_condition_count: int = 0

    model_config = ConfigDict(from_attributes=True)
