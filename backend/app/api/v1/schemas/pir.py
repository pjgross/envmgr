from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

from app.api.v1.schemas.pir_finding import PirFindingResponse

PIR_STATUSES = {"draft", "complete"}


class PIRCreate(BaseModel):
    incident_id: Optional[int] = None
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    what_went_well: Optional[str] = None
    what_went_wrong: Optional[str] = None
    action_plan: Optional[str] = None
    status: Optional[str] = "draft"

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in PIR_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIR_STATUSES)}")
        return v


class PIRUpdate(BaseModel):
    incident_id: Optional[int] = None
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    what_went_well: Optional[str] = None
    what_went_wrong: Optional[str] = None
    action_plan: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in PIR_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIR_STATUSES)}")
        return v


class PIRResponse(BaseModel):
    id: int
    release_id: int
    incident_id: Optional[int]
    summary: Optional[str]
    root_cause: Optional[str]
    what_went_well: Optional[str]
    what_went_wrong: Optional[str]
    action_plan: Optional[str]
    status: str
    completed_at: Optional[datetime]
    findings: list[PirFindingResponse] = []
    model_config = ConfigDict(from_attributes=True)
