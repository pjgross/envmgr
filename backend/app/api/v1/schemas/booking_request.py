from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class EnvBookingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    environment_name: Optional[str] = None
    start_date: datetime
    end_date: datetime
    status: str
    has_unacknowledged_conflicts: bool = False


class BookingRequestCreate(BaseModel):
    project_name: str
    booking_type_id: int
    start_date: datetime
    end_date: datetime
    environment_ids: list[int] = Field(..., min_length=1)
    notes: Optional[str] = None
    context_tag: str = "none"
    exclusive_use_requested: bool = False
    custom_fields: Optional[dict[str, Any]] = None
    delegate_user_ids: Optional[list[int]] = None


class BookingRequestUpdate(BaseModel):
    project_name: Optional[str] = None
    booking_type_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    notes: Optional[str] = None
    context_tag: Optional[str] = None
    exclusive_use_requested: Optional[bool] = None
    delegate_user_ids: Optional[list[int]] = None


class BookingRequestCustomFieldsUpdate(BaseModel):
    values: dict[str, Any]


class AddEnvironmentRequest(BaseModel):
    environment_id: int
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class BookingRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_name: str
    booking_type_id: int
    start_date: datetime
    end_date: datetime
    notes: Optional[str]
    context_tag: str
    exclusive_use_requested: bool
    custom_fields: Optional[dict[str, Any]]
    booked_by: int
    delegate_user_ids: Optional[list[int]]
    rollup_status: str
    bookings: list[EnvBookingSummary]


class BookingRequestCreateResponse(BaseModel):
    request: BookingRequestResponse
    detected_conflicts: dict[int, list[EnvBookingSummary]]


class PreviewConflictsRequest(BaseModel):
    environment_ids: list[int]
    start_date: datetime
    end_date: datetime


class PreviewConflictsResponse(BaseModel):
    conflicts: dict[int, list[EnvBookingSummary]]
