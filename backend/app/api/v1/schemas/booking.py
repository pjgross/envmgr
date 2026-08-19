from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.agreement_gap import AgreementGapAckRead
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
    protection_level: Optional[str] = None


class BookingCreate(BaseModel):
    environment_id: int
    project_name: str
    start_date: datetime
    end_date: datetime
    booking_type_id: int
    exclusive_use: bool = False
    # None means "inherit the booking type's default". A caller who is not an
    # Admin or Release Manager may send the inherited value but may not choose
    # a different one — see booking_request_service.assert_may_set_protection.
    protection_level: Optional[Literal["soft", "hard"]] = None
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
    # B4 — how hard the parent request's claim is (app/core/protection_levels.py).
    # Lives on booking_request, not on Booking, so Booking has no such
    # attribute; `model_validate(booking)` cannot populate this and it must be
    # set explicitly in `_to_response`, the same way `exclusive_use` is.
    protection_level: Optional[str] = None
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
    # WHO accepted the gap, and WHEN — populated by `GET /bookings/{id}` ALONE,
    # the same way `request`, `custom_field_permissions` and
    # `standard_field_permissions` above are. Deliberately not on the list: it
    # is detail-page information, and a paginated list would need a batch
    # lookup per page for something no list row renders. Nor on
    # `EnvBookingSummary`, nor on the create envelope (nothing has been
    # acknowledged one millisecond after a booking is created).
    #
    # Without it "who and when" survived only inside the browser session that
    # made the ack — after a reload the page could say no more than "this has
    # been acknowledged". Follows `ConflictItem.ack`, the same mechanism A3
    # mirrors everywhere else.
    #
    # NOT suppressed when the gap has since closed: the field reports the ack
    # row, and gating its presence on the computed gap would make one field's
    # presence depend on two mechanisms. Consumers key on `agreement_gap`.
    agreement_gap_ack: Optional[AgreementGapAckRead] = None
    # Provenance, not a live link — see Booking.environment_group_id. Null for
    # a hand-picked environment; set for one that arrived via a group.
    environment_group_id: Optional[int] = None
    environment_group_name: Optional[str] = None
    # B6 Task 4 — the folded forward-contention state
    # (contention_forecast_service.STATE_UNOWNED / STATE_OWNED / STATE_DECIDED),
    # or None when this booking has no contention. Never a "none" state: an
    # uncontended booking carries null, and the grid cell (Task 6) must render
    # nothing for it rather than an empty chip. Computed, not stored —
    # `model_validate(booking)` cannot populate it, since Booking has no such
    # attribute; set explicitly in `_to_response`, batch-resolved for the whole
    # page via `contention_forecast_service.contention_states_for_bookings`.
    contention_state: Optional[str] = None


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
