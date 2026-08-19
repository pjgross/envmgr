"""B5 Task 5 — initiating a decommission.

`DecommissionRead.state` is REQUIRED and has no default, the same reason A4's
`EscalationRead.state` is required: `EnvironmentDecommission` has no `state`
column (it stores facts only — see the service module docstring), so the
value can never come from `model_validate(row)`. It is set explicitly in the
response builder, computed by `environment_decommission_service.
decommission_state` from one clock taken once per request — the same call B4
made for `BookingResponse.protection_level`.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DecommissionCreate(BaseModel):
    """The WRITE model. `extra='forbid'` so a misspelled key is a 422, not a
    silently dropped field."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    # Optional: the initiator may push the teardown date LATER than the
    # tenant's notice period, never earlier. Omitted, it defaults to
    # warned_at + policy.decommission_notice_days.
    scheduled_teardown_at: Optional[datetime] = None


class ExtensionRequest(BaseModel):
    """The WRITE model for `POST .../extension` — the owner asking for more
    time. `extra='forbid'` for the same reason as `DecommissionCreate`."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    until: datetime


class ExtensionDecision(BaseModel):
    """The WRITE model for `POST .../extension/decision` — the operating
    team's answer. No message field: the decision is binary, and a refusal's
    reasoning belongs in conversation, not a stored column nothing renders."""

    model_config = ConfigDict(extra="forbid")

    granted: bool


class AttestationCreate(BaseModel):
    """The WRITE model for `POST .../attestations` — a human confirming one
    checklist step happened. `extra='forbid'` for the same reason as every
    other write model here."""

    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1)
    # Snapshot id, ticket, runbook link — free text, not parsed.
    reference: Optional[str] = None
    notes: Optional[str] = None


class AttestationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decommission_id: int
    step_key: str
    signed_by: int
    signed_at: datetime
    reference: Optional[str]
    notes: Optional[str]
    # Resolved ONLY when this is built by
    # `environment_decommission_service.list_attestations` (a JOIN to
    # `User`), which is what feeds `DecommissionRead.attestations` below. The
    # bare `POST .../attestations` response still validates straight off the
    # ORM row via `from_attributes=True`, which has no such column — this
    # defaults to None there rather than 422ing on a field the row cannot
    # supply. Deliberately NOT tenant-qualified in that join (see
    # `_usernames_for`'s own docstring): under master-admin impersonation the
    # signer may legitimately sit outside the decommission's own tenant, and
    # a tenant-qualified join would render them as nobody.
    signed_by_username: Optional[str] = None


class CancelRequest(BaseModel):
    """The WRITE model for `POST .../cancel` — the escape hatch. A reason is
    required for the same audit-record reason `DecommissionCreate.reason`
    is."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class DecommissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    reason: str
    warned_at: datetime
    scheduled_teardown_at: datetime
    initiated_by: int

    extension_requested_at: Optional[datetime]
    extension_reason: Optional[str]
    extension_until: Optional[datetime]
    extension_decided_at: Optional[datetime]
    extension_granted: Optional[bool]

    torn_down_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]

    # REQUIRED, computed — never model_validate'd. See the module docstring.
    state: str

    # Populated ONLY on the single-decommission reads — GET
    # /environments/{id}/decommission and every action response (initiate,
    # extension request/decision, sign, teardown, cancel), all through
    # `_to_read`'s own single JOIN query
    # (`environment_decommission_service.list_attestations`). REQUIRED, not
    # defaulted, is what forces `DecommissionWorklistRow.from_view` below to
    # answer explicitly rather than silently inheriting whatever this
    # defaulted to — see its own comment for why that answer is an empty
    # list, not a query.
    attestations: list[AttestationRead]


class DecommissionWorklistRow(DecommissionRead):
    """One row of `GET /decommissions` — `DecommissionRead` plus the three
    names a worklist reader has never resolved themselves.

    THE NAMES TRAVEL WITH THE ROW
    (`environment_decommission_service.decommission_views`), the same call
    `EscalationRead` makes on A4's worklist: the browser must not look them up
    in a capped picker collection, where a name past the cap is information
    LOST, not merely hidden (docs/pagination.md). Built only through
    `from_view`, which takes a `DecommissionView` and therefore cannot be
    handed a constant by accident — the same shape `EscalationRead.from_view`
    and `ProjectResponse.from_view` use.
    """

    environment_name: Optional[str]
    initiated_by_username: Optional[str]
    owner_username: Optional[str]

    @classmethod
    def from_view(cls, view) -> "DecommissionWorklistRow":
        row = view.decommission
        return cls(
            id=row.id,
            environment_id=row.environment_id,
            reason=row.reason,
            warned_at=row.warned_at,
            scheduled_teardown_at=row.scheduled_teardown_at,
            initiated_by=row.initiated_by,
            extension_requested_at=row.extension_requested_at,
            extension_reason=row.extension_reason,
            extension_until=row.extension_until,
            extension_decided_at=row.extension_decided_at,
            extension_granted=row.extension_granted,
            torn_down_at=row.torn_down_at,
            cancelled_at=row.cancelled_at,
            cancel_reason=row.cancel_reason,
            state=view.state,
            environment_name=view.environment_name,
            initiated_by_username=view.initiated_by_username,
            owner_username=view.owner_username,
            # DELIBERATELY EMPTY, NEVER FETCHED — A3's ack precedent: the
            # attestation detail lives on ONE entity's read
            # (GET .../decommission), not on every worklist row. Populating
            # this from `view` would need a per-row query the worklist's own
            # batch-view builder does not run, turning one page into an
            # N+1 — see `list_attestations`' own docstring. If a future
            # change makes this non-empty, it has broken that rule.
            attestations=[],
        )


class RemainingBookingSummary(BaseModel):
    """One booking teardown did NOT touch. SURFACES, never touches — the
    response names these; nothing about them changes. Deliberately thin: this
    is a disclosure, not a booking detail view."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    start_date: datetime
    end_date: datetime
    status: str


class TeardownRead(DecommissionRead):
    """`POST .../teardown`'s response — `DecommissionRead` plus the bookings
    still on the calendar for this environment. Reporting them is the point;
    the guard test in Task 15 proves teardown changed none of their rows."""

    remaining_bookings: list[RemainingBookingSummary]
