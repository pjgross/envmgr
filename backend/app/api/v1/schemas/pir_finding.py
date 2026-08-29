from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.pir_finding import FINDING_KINDS


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
    model_config = ConfigDict(from_attributes=True)
