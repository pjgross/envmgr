from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

from app.api.v1.schemas.pir_finding import PirFindingResponse

PIR_STATUSES = {"draft", "complete"}


class PIRCreate(BaseModel):
    summary: Optional[str] = None
    status: Optional[str] = "draft"
    # `extra="forbid"` so a client still sending `what_went_wrong` is told the
    # field is gone rather than watching it be silently dropped — the
    # `POST /tenant/lifecycle-templates` failure shape.
    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in PIR_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIR_STATUSES)}")
        return v


class PIRUpdate(BaseModel):
    summary: Optional[str] = None
    status: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in PIR_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIR_STATUSES)}")
        return v


class PIRResponse(BaseModel):
    id: int
    release_id: int
    summary: Optional[str]
    status: str
    completed_at: Optional[datetime]
    findings: list[PirFindingResponse] = []
    model_config = ConfigDict(from_attributes=True)
