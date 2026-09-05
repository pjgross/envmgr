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
