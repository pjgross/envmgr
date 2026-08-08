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
    # REQUIRED SINCE 2026-08-08, and it is worth knowing why it wasn't.
    # Defaulted `False` from the day it shipped and set by NO construction
    # site, this field answered "no conflicts" for every booking on every
    # endpoint that returns this type. Nothing rendered it — the conflict
    # indicators all read `BookingResponse` — so it was dead weight rather than
    # a visible lie, and it stayed that way because a default cannot fail.
    # It is now populated from `conflict_service.bookings_with_unacknowledged_conflicts`,
    # batched once per response, and required so a new site cannot repeat this.
    has_unacknowledged_conflicts: bool
    # A3's usage-agreement warning — see BookingResponse for what it means.
    #
    # REQUIRED, NOT DEFAULTED, deliberately unlike the optional fields above:
    # EnvBookingSummary is constructed by keyword at six sites across two
    # routers, and a default would let a missed one render a booking as "no
    # gap" while `GET /bookings` reports the same booking as in gap. A2 left
    # this exact type self-contradictory that way. Pydantic raises on a missing
    # required field, so a new construction site cannot forget — though note
    # that guards only OMISSION: passing a constant satisfies it just as well,
    # which is why every site has a named test.
    agreement_gap: Optional[str]
    has_unacknowledged_agreement_gap: bool
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
    # `booking_id -> message` for the bookings JUST CREATED that no live usage
    # agreement covers. Keyed by booking id, not environment id (unlike
    # detected_conflicts, whose key is the environment being contended for),
    # because the gap is a property of one booking and a group booking may hold
    # several bookings against the same environment over different dates.
    #
    # Absent keys mean "no gap"; an empty map is the ordinary case and is what
    # keeps this a warning rather than a banner. The same text is on each
    # booking's own summary — this map exists so the caller does not have to
    # walk `request.bookings` to find out whether to say anything at all.
    agreement_gaps: dict[int, str] = {}


class PreviewConflictsRequest(BaseModel):
    environment_ids: list[int]
    start_date: datetime
    end_date: datetime


class PreviewConflictsResponse(BaseModel):
    conflicts: dict[int, list[EnvBookingSummary]]
