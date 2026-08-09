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

    # WHICH ARGUMENT THIS IS, in the only terms a human recognises. A worklist
    # is a list of things the reader has never seen, so `booking_id` /
    # `other_booking_id` identify nothing on their own, and `Booking #12` is
    # exactly the `#N` fallback this codebase does not render. Resolved
    # server-side and batched by `contention_service.booking_labels`, for the
    # same reason the usernames above are.
    #
    # `booking_*` is `booking_id` and `other_booking_*` is `other_booking_id` —
    # the LOWER and HIGHER id, because the pair is stored normalised. Neither
    # side is "mine": a worklist reader is often party to neither booking.
    #
    # All four nullable, and each null is a REAL STATE: a booking need not link
    # to a project, and a booking this tenant cannot resolve has no names at all.
    booking_environment_name: Optional[str]
    booking_project_name: Optional[str]
    other_booking_environment_name: Optional[str]
    other_booking_project_name: Optional[str]

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
            booking_environment_name=view.booking_label.environment_name,
            booking_project_name=view.booking_label.project_name,
            other_booking_environment_name=view.other_booking_label.environment_name,
            other_booking_project_name=view.other_booking_label.project_name,
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

    # THE TWO PROJECTS BY NAME, because `winner_booking_id` alone cannot be
    # rendered. A4's design says the line should read "Mortgage Replatform
    # outranks Payments Rebuild"; nothing on this response could say that while
    # it carried only ids, and the caller cannot fill the gap either —
    # `EnvBookingSummary.project_name` on the same item is
    # `BookingRequest.project_name`, the free text the UI labels "Purpose", not
    # the linked project. Resolving the counterparty's project per row would be
    # the N+1 this endpoint has had undone three times.
    #
    # `booking_project_name` is the SUBJECT of the request — the booking whose
    # conflicts page this is — and `other_project_name` is the row's own
    # booking. Deliberately NOT the normalised (lower, higher) order the
    # escalation uses: a verdict is read from one side, so the pair is keyed
    # here AS GIVEN, matching `verdicts_for_pairs`' own contract.
    #
    # Both nullable, and null is a real state: `no_project` is the commonest
    # outcome in today's data.
    booking_project_name: Optional[str]
    other_project_name: Optional[str]

    @classmethod
    def from_verdict(
        cls, verdict, view, booking_project_name, other_project_name
    ) -> "ContentionRead":
        """`verdict` is a `ContentionVerdict`; `view` an `EscalationView` or None.

        Taking the verdict OBJECT rather than three loose fields is what stops a
        call site quietly composing an outcome from one pair and a winner from
        another — the shape a batch lookup keyed on the wrong tuple produces.

        EVERY PARAMETER IS REQUIRED-POSITIONAL, `view` included — it used to
        default to None. A1 shipped a response field that rendered `null` at
        four of five construction sites with the suite green, because Pydantic
        silently defaults a missing value rather than raising; the fix there was
        to make the helper take it required-positional, turning an omission into
        a `TypeError`. The same applies here twice over, since a project name
        omitted at the one construction site would render every verdict as
        project-less on a page where the projects are the entire subject.
        """
        return cls(
            outcome=verdict.outcome,
            winner_booking_id=verdict.winner_booking_id,
            reason=verdict.reason,
            escalation=EscalationRead.from_view(view) if view is not None else None,
            booking_project_name=booking_project_name,
            other_project_name=other_project_name,
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
