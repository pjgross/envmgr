"""Unified environment schedule schemas (Phase 2 Step 4).

The schedule response groups bookings and change requests so a single
timeline view can render them together. A `deployments` field is reserved
for Phase 4; it is always an empty list today.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ScheduleBooking(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    project_name: str
    start_date: datetime
    end_date: datetime
    status: str


class ScheduleChangeRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    subsystem_id: int
    title: str
    change_type: str
    status: str
    scheduled_start: datetime
    scheduled_end: datetime
    has_outage: bool
    outage_start: Optional[datetime]
    outage_end: Optional[datetime]


class EnvironmentScheduleResponse(BaseModel):
    environment_id: int
    start_date: datetime
    end_date: datetime
    bookings: list[ScheduleBooking]
    change_requests: list[ScheduleChangeRequest]
    # Reserved for Phase 4 — always empty today. Consumers must accept a
    # present-but-empty array so clients don't need a version negotiation
    # once Phase 4 starts populating it.
    deployments: list[dict] = []
