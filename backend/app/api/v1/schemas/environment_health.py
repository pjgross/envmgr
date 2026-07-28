from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

HEALTH_STATUSES = {"up", "down", "issue"}


class HealthSampleCreate(BaseModel):
    status: str
    source: str
    detail: Optional[str] = None
    recorded_at: Optional[datetime] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in HEALTH_STATUSES:
            raise ValueError(f"status must be one of {sorted(HEALTH_STATUSES)}")
        return v


class HealthSample(BaseModel):
    id: int
    environment_id: int
    status: str
    recorded_at: datetime
    source: str
    detail: Optional[str]
    model_config = ConfigDict(from_attributes=True)


class ActiveBookingSummary(BaseModel):
    project_name: str
    start_date: datetime
    end_date: datetime


class EnvironmentHealthOverviewRow(BaseModel):
    environment_id: int
    environment_name: str
    current_status: str                    # up | down | issue | unknown
    last_recorded_at: Optional[datetime]
    active_booking: bool
    active_booking_summary: Optional[ActiveBookingSummary]
    planned_outage: bool
    alert: bool
