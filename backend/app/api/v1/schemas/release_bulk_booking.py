from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ReleaseBulkBookingRequest(BaseModel):
    environment_ids: list[int] = Field(..., min_length=1)
    phase_id: Optional[int] = None
    start: datetime
    end: datetime
    booking_type_id: int
    project_name: Optional[str] = None
    notes: Optional[str] = None
    exclusive_use: bool = False

    @field_validator("environment_ids")
    @classmethod
    def _dedupe(cls, v):
        seen: set[int] = set()
        out: list[int] = []
        for x in v:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out


class BulkBookCreated(BaseModel):
    environment_id: int
    booking_id: int
    warnings: list[int]


class BulkBookSkipped(BaseModel):
    environment_id: int
    conflicts: list[int]


class BulkBookResult(BaseModel):
    created: list[BulkBookCreated]
    skipped: list[BulkBookSkipped]
