"""The contention verdict and its escalation, as the API renders them.

NOTHING HERE IS STORED EXCEPT THE ESCALATION'S OWN COLUMNS. The verdict is
computed per pair, the escalation's `state` from two columns and a clock, and
`bookings_live` from the two bookings — so a response carries no field a
background job has to keep true.

USERNAMES TRAVEL WITH THE ROW, resolved server-side by
`contention_service.usernames_for`. The browser must not look them up in the
capped tenant-users collection: a name past the cap is information LOST, not
merely hidden, and renders the person as '—' (docs/pagination.md).

Both write schemas set `extra="forbid"`, so a misspelled key is a 422 rather
than a silently dropped field — the failure shape where a caller believes they
set a deadline that was never stored.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EscalationRead(BaseModel):
    """One escalation record, plus the three things about it that are computed.

    `state` and `bookings_live` are REQUIRED and have no default. A defaulted
    field is what left `has_unacknowledged_conflicts` dead at every construction
    site since it shipped: the type system is satisfied, and every reader is
    told the wrong thing. Build one through `from_view`, which takes an
    `EscalationView` and therefore cannot be handed a constant by accident.
    """

    id: int
    booking_id: int
    other_booking_id: int
    owner_user_id: int
    owner_username: Optional[str]
    # Who ASKED, beside who must answer. An escalation is an audit trail of an
    # argument, and "raised by" with no name is exactly the `#N` rendering this
    # codebase does not do.
    escalated_by: int
    escalated_by_username: Optional[str]
    respond_by: datetime
    state: str
    bookings_live: bool

    decision_yields_booking_id: Optional[int]
    decision_notes: Optional[str]
    decided_by: Optional[int]
    decided_by_username: Optional[str]
    decided_at: Optional[datetime]

    @classmethod
    def from_view(cls, view) -> "EscalationRead":
        """The ONE construction site, taking `contention_service.EscalationView`.

        Every call site therefore passes a value that was computed, never a
        literal — the mirror of `ProjectResponse.from_view` and
        `UsageAgreementResponse.from_row`.
        """
        escalation = view.escalation
        return cls(
            id=escalation.id,
            booking_id=escalation.booking_id,
            other_booking_id=escalation.other_booking_id,
            owner_user_id=escalation.owner_user_id,
            owner_username=view.owner_username,
            escalated_by=escalation.escalated_by,
            escalated_by_username=view.escalated_by_username,
            respond_by=escalation.respond_by,
            state=view.state,
            bookings_live=view.bookings_live,
            decision_yields_booking_id=escalation.decision_yields_booking_id,
            decision_notes=escalation.decision_notes,
            decided_by=escalation.decided_by,
            decided_by_username=view.decided_by_username,
            decided_at=escalation.decided_at,
        )


class ContentionRead(BaseModel):
    """What A4 has to say about one pair of conflicting bookings.

    THREE OF THE FOUR OUTCOMES CARRY NO WINNER, each with its own reason, so
    `reason` is required and `winner_booking_id` is nullable — never the other
    way round. A consumer that reads only `winner_booking_id` sees "no winner"
    and must go to `reason` to find out which of the three it is.
    """

    outcome: str
    winner_booking_id: Optional[int]
    reason: str
    # No default: a construction site must decide whether this pair has been
    # escalated, rather than inheriting None from the schema.
    escalation: Optional[EscalationRead]

    @classmethod
    def from_verdict(cls, verdict, view=None) -> "ContentionRead":
        """`verdict` is a `ContentionVerdict`; `view` an `EscalationView` or None.

        Taking the verdict OBJECT rather than three loose fields is what stops a
        call site quietly composing an outcome from one pair and a winner from
        another — the shape a batch lookup keyed on the wrong tuple produces.
        """
        return cls(
            outcome=verdict.outcome,
            winner_booking_id=verdict.winner_booking_id,
            reason=verdict.reason,
            escalation=EscalationRead.from_view(view) if view is not None else None,
        )


class EscalationCreate(BaseModel):
    """Ask a named person to decide, by a named date.

    `respond_by` is NOT required to be in the future: a deadline already passed
    is a legitimate thing to record — it reads as `expired` immediately, which
    is exactly what an escalation raised about a clash already upon someone
    should say.
    """

    model_config = ConfigDict(extra="forbid")

    owner_user_id: int
    respond_by: datetime


class EscalationDecision(BaseModel):
    """Which booking a human said should give way, and why.

    A4 NEVER MOVES IT. `yields_booking_id` is recorded; acting on it is the
    owning team's job, through the ordinary transition path — which for an A2
    group booking moves the whole group atomically.

    `notes` defaults to None, and passing None on a SECOND decision CLEARS the
    first one's stated reason: the row holds the decision that stands, and a
    reason carried over from a superseded decision would be attributed to the
    new one.
    """

    model_config = ConfigDict(extra="forbid")

    yields_booking_id: int
    notes: Optional[str] = None
