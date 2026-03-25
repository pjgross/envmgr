from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.booking import ContextTag


class BookingCreate(BaseModel):
    environment_id: int
    project_name: str
    start_date: datetime
    end_date: datetime
    booking_type_id: int
    exclusive_use: bool = False
    notes: Optional[str] = None
    recurrence_rule: Optional[str] = None  # RRULE string e.g. "FREQ=WEEKLY;COUNT=4"
    release_id: Optional[int] = None
    test_phase_id: Optional[int] = None
    context_tag: Optional[ContextTag] = ContextTag.NONE
    custom_fields: Optional[dict] = None


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    environment_name: Optional[str] = None  # populated manually in service
    project_name: str
    booked_by: int
    booked_by_username: Optional[str] = None  # populated manually in service
    start_date: datetime
    end_date: datetime
    booking_type_id: int
    exclusive_use: bool
    status: str
    notes: Optional[str] = None
    recurrence_rule: Optional[str] = None
    recurrence_parent_id: Optional[int] = None
    release_id: Optional[int] = None
    test_phase_id: Optional[int] = None
    context_tag: ContextTag
    custom_fields: Optional[dict] = None
    tenant_id: int
    created_at: datetime
    updated_at: datetime


class BookingCreateResponse(BaseModel):
    booking: BookingResponse
    overlap_warnings: list[int] = []  # IDs of bookings that share the time slot


class BookingTransitionRequest(BaseModel):
    to_state: str
    notes: Optional[str] = None


class BookingStatusHistoryResponse(BaseModel):
    id: int
    from_state: Optional[str]
    to_state: str
    changed_by: int
    changed_at: datetime
    notes: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class AllowedTransitionResponse(BaseModel):
    from_state: str
    to_state: str
    label: str
