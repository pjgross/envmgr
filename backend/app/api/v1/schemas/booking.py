from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.booking import ContextTag


class BookingRequestSummary(BaseModel):
    """Parent BookingRequest summary embedded in booking responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_name: str
    booking_type_id: int
    booked_by: int
    booked_by_username: Optional[str] = None
    context_tag: ContextTag
    exclusive_use_requested: bool
    start_date: datetime
    end_date: datetime
    notes: Optional[str] = None
    delegate_user_ids: Optional[list[int]] = None
    custom_fields: Optional[dict] = None


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
    environment_name: Optional[str] = None  # populated manually in endpoint
    # Fields sourced from the parent booking_request (populated manually in endpoint)
    project_name: Optional[str] = None
    # The project this booking's parent request links to — id plus a batch-resolved
    # display name (project_service.get_project_names, deliberately not filtering
    # deleted_at so an archived project's name still renders). Distinct from
    # project_name above, which is the free-text "Purpose" field on the same
    # booking_request; do not conflate them.
    project_id: Optional[int] = None
    project_name_link: Optional[str] = None
    booked_by: Optional[int] = None
    booked_by_username: Optional[str] = None  # populated manually in endpoint
    booking_type_id: Optional[int] = None
    exclusive_use: Optional[bool] = None
    notes: Optional[str] = None
    context_tag: Optional[ContextTag] = None
    custom_fields: Optional[dict] = None
    # Per-env override fields (on Booking directly)
    start_date: datetime
    end_date: datetime
    status: str
    recurrence_rule: Optional[str] = None
    recurrence_parent_id: Optional[int] = None
    release_id: Optional[int] = None
    test_phase_id: Optional[int] = None
    custom_field_permissions: Optional[dict[str, dict]] = None
    standard_field_permissions: Optional[dict[str, dict]] = None
    tenant_id: int
    created_at: datetime
    updated_at: datetime
    booking_request_id: Optional[int] = None
    request: Optional[BookingRequestSummary] = None
    has_unacknowledged_conflicts: bool = False
    # A3's usage-agreement warning: the message, and whether anyone has accepted
    # it. Computed from `usage_agreement`, never stored — adding the missing
    # agreement clears both with nothing to invalidate. A3 WARNS: neither field
    # refuses or alters anything.
    #
    # Defaulted here ONLY because BookingResponse is built by
    # `model_validate(booking)` and a Booking has no such attribute; the guard
    # against a missed call site is `bookings.py::_to_response`'s
    # required-positional `gap` argument, which turns an unconverted site into a
    # TypeError. `has_unacknowledged_conflicts` above is the counter-example — a
    # defaulted field set at two of its six builders and silently False at the
    # rest.
    agreement_gap: Optional[str] = None
    has_unacknowledged_agreement_gap: bool = False
    # Provenance, not a live link — see Booking.environment_group_id. Null for
    # a hand-picked environment; set for one that arrived via a group.
    environment_group_id: Optional[int] = None
    environment_group_name: Optional[str] = None


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
