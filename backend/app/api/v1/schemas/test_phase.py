# backend/app/api/v1/schemas/test_phase.py
from typing import Literal, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, field_validator


class TestPhaseCreate(BaseModel):
    name: str = Field(..., max_length=100)
    order: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: str = "pending"
    kind: Literal["test", "hypercare"] = "test"


class TestPhaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    order: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None
    kind: Optional[Literal["test", "hypercare"]] = None


class TestPhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    name: str
    order: int
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    status: str
    kind: str

    # SQLite strips tzinfo on readback (PostgreSQL doesn't); every datetime
    # this app stores is UTC, so a naive value read off the row is UTC, not
    # "unknown". Same pattern as app/core/day_boundaries.py's `_utc`. Without
    # this, `start_date`/`end_date` serialize with no offset on SQLite and an
    # offset on PostgreSQL for byte-identical underlying data.
    @field_validator("start_date", "end_date", mode="after")
    @classmethod
    def _assume_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
