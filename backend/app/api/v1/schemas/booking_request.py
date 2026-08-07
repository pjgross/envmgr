from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class EnvBookingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    environment_name: Optional[str] = None
    project_name: Optional[str] = None
    start_date: datetime
    end_date: datetime
    status: str
    has_unacknowledged_conflicts: bool = False
    # Provenance, not a live link — see Booking.environment_group_id. Null for
    # a hand-picked environment; set for one that arrived via a group.
    environment_group_id: Optional[int] = None
    environment_group_name: Optional[str] = None


class BookingRequestCreate(BaseModel):
    project_name: str
    # The project this booking belongs to. Distinct from `project_name`, which
    # is free text the UI now labels "Purpose" — see the spec.
    project_id: Optional[int] = None
    booking_type_id: int
    start_date: datetime
    end_date: datetime
    # May be empty when environment_group_ids supplies at least one group —
    # the combined "at least one environment" rule is enforced by the
    # service, not by Pydantic, because it spans both fields.
    environment_ids: list[int] = Field(default_factory=list)
    environment_group_ids: list[int] = Field(default_factory=list)
    notes: Optional[str] = None
    context_tag: str = "none"
    exclusive_use_requested: bool = False
    custom_fields: Optional[dict[str, Any]] = None
    delegate_user_ids: Optional[list[int]] = None


class BookingRequestUpdate(BaseModel):
    project_name: Optional[str] = None
    # The project this booking belongs to. Distinct from `project_name`, which
    # is free text the UI now labels "Purpose" — see the spec.
    project_id: Optional[int] = None
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
    project_id: Optional[int] = None
    project_name_link: Optional[str] = None  # the Project's name, if linked
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
