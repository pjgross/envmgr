"""Which project outranks the other, and — far more often — why neither does.

A4 ADVISES; IT NEVER ACTS. Nothing here transitions, rejects or reschedules a
booking. `test_a_contention_changes_no_booking_behaviour` is the guard on that
promise; if it fails, A4 has started acting.

THE VERDICT IS COMPUTED, NEVER STORED. It depends on two bookings AND two
project ranks, so four separate edits could falsify a cached one — a worse
invalidation surface than A3's gap, which is computed for the same reason.
Changing a rank or setting a project on a project-less request therefore takes
effect immediately, with nothing to invalidate.

THREE OF THE FOUR OUTCOMES ARE "NO WINNER", each reported with its reason
rather than a fabricated ordering. On today's data almost every pair is
`no_project` — A1 shipped `project_id` nullable with no backfill — so the
honest answer is exactly what makes the unranked estate visible instead of
hiding it behind a spurious winner. Same rule as the drift report's absence
categories, which return null with a reason and never `[]`.

FOUR OUTCOMES, FIVE REASONS: `no_project` carries two, because "the request
names no project" and "the request names a project this tenant cannot resolve"
look identical to the verdict and completely different to the person reading the
screen. See the constants below.
"""
from datetime import datetime, timezone
from typing import Iterable, NamedTuple, Optional

from fastapi import HTTPException, status
from sqlalchemy import Exists, and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.core.upsert import insert_or_reread
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.contention_escalation import ContentionEscalation
from app.db.models.project import Project
from app.db.models.user import User
from app.services import conflict_service

OUTCOME_RANKED = "ranked"
OUTCOME_NO_PROJECT = "no_project"
OUTCOME_UNRANKED = "unranked"
OUTCOME_EQUAL_RANK = "equal_rank"

# The two `no_project` reasons. ONE OUTCOME, TWO REASONS — deliberately not a
# fifth outcome, because "the link cannot be resolved" is not a different KIND
# of answer, it is another way of saying priority cannot separate these. Only
# the reason tells them apart, and it has to, because the second one is the case
# where the UI CONTRADICTS the verdict on screen: `get_project_names`
# deliberately does not filter `deleted_at`, so a row whose request names an
# archived project renders that project's NAME right beside the verdict line. A
# user told "not linked to a project" while looking at the project's name reads
# it as a bug in the register. Naming the real problem — the link is archived,
# or points outside this tenant — points them at the thing that is actually
# wrong, which is the same call the deviation in `_ranks_for` made.
REASON_NO_PROJECT = "at least one booking is not linked to a project"
REASON_PROJECT_UNRESOLVABLE = (
    "at least one booking's project is archived or belongs to another tenant"
)


class ContentionVerdict(NamedTuple):
    outcome: str
    winner_booking_id: Optional[int]
    reason: str


async def _ranks_for(
    db: AsyncSession, booking_ids: set[int], tenant_id: int
) -> dict[int, tuple[Optional[int], Optional[int], Optional[int]]]:
    """booking id -> (requested_project_id, resolved_project_id, priority_rank).

    THREE VALUES, NOT TWO, AND THE FIRST TWO ARE NOT THE SAME QUESTION.
    `requested` is what the REQUEST names (`BookingRequest.project_id`, raw and
    unfiltered); `resolved` is what this tenant can actually SEE (`Project.id`
    through the filtered LEFT join). They differ exactly when a request names a
    project that is archived or belongs to another tenant — and that difference
    is the only thing that can tell the two `no_project` reasons apart, so it is
    computed here and must NOT be discarded on the way out. An earlier version
    returned only the last two and `_decide` reported every unresolvable link as
    "not linked to a project", directly beside the archived project's name.

    The Project join is LEFT and tenant-filtered on BOTH sides: a booking whose
    request points at another tenant's project must read as project-less here,
    not as ranked. `Project.deleted_at` is filtered because an archived project
    should not win an argument — unlike `get_project_names`, which deliberately
    does not filter it, because rendering an archived name and letting it decide
    a contention are different questions.

    THE PROJECT ID IS `Project.id` FROM THAT JOIN, NOT `BookingRequest.project_id`,
    and the difference is the whole reason the first two tests written against
    this function failed. Reading the id off the REQUEST reports a booking
    pointing at a cross-tenant or archived project as "has a project, and it is
    unranked" — because only the rank comes back null — so the verdict tells an
    admin to go and rank a project whose rank this join then refuses to read.
    They would set a rank and watch nothing change. Taking the id from the join
    makes both sides of the pair answer the same question ("is there a project
    HERE, live, in this tenant?") and puts such a booking in `no_project`, which
    is what the paragraph above says it does. The alternative considered and
    declined was a fifth outcome for "project not resolvable": the four are
    fixed by tasks 3 and 4, and a malformed or archived link is not a different
    KIND of answer — it is still "priority cannot separate these, and here is
    why".

    Two things it deliberately does NOT filter, so neither reads as an
    oversight. `BookingRequest.tenant_id` is unqualified, matching the join
    `booking_service.list_bookings` and `agreement_gap_service.gaps_for_bookings`
    both use — tenant scoping that can change an answer lives on
    `Booking.tenant_id` below and inside the Project join, so an unqualified
    request join can leak nothing. And `Booking.deleted_at` is the CALLER's
    question, exactly as it is in `gaps_for_bookings`: the caller's query
    decides which bookings it is asking about, and a verdict about a booking
    nobody renders changes nothing.

    A booking id that resolves to nothing — another tenant's, or stale — is
    simply absent from the result, and `verdicts_for_pairs` reads that absence
    as project-less rather than raising. This feeds a warning, not a permission
    decision.
    """
    rows = (await db.execute(
        select(Booking.id, BookingRequest.project_id, Project.id, Project.priority_rank)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
        .join(
            Project,
            (Project.id == BookingRequest.project_id)
            & (Project.tenant_id == tenant_id)
            & (Project.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Booking.id.in_(booking_ids), Booking.tenant_id == tenant_id)
    )).all()
    return {bid: (requested, pid, rank) for bid, requested, pid, rank in rows}


def _decide(
    a_id: int, a: tuple[Optional[int], Optional[int], Optional[int]],
    b_id: int, b: tuple[Optional[int], Optional[int], Optional[int]],
) -> ContentionVerdict:
    """The whole decision, in branch order — and the order is load-bearing.

    A booking with no project has no rank either, so `no_project` must be asked
    FIRST or every project-less pair would report as `unranked` and invite
    someone to fix it by ranking a project that is not there.
    """
    a_requested, a_project, a_rank = a
    b_requested, b_project, b_rank = b
    if a_project is None or b_project is None:
        # ONE OUTCOME, TWO REASONS. A request that NAMES a project we cannot
        # resolve is a different thing to tell a user from one that names none:
        # the first shows the project's name on the same row (see the constants
        # above), so it is reported whenever EITHER side is in that state, even
        # if the other side genuinely has no project — the contradiction on
        # screen is what needs explaining, and "not linked to a project" does
        # not explain it.
        unresolvable = (a_requested is not None and a_project is None) or (
            b_requested is not None and b_project is None
        )
        return ContentionVerdict(
            OUTCOME_NO_PROJECT, None,
            REASON_PROJECT_UNRESOLVABLE if unresolvable else REASON_NO_PROJECT,
        )
    if a_rank is None or b_rank is None:
        # A RANKED PROJECT DOES NOT BEAT AN UNRANKED ONE. See the module note.
        return ContentionVerdict(
            OUTCOME_UNRANKED, None,
            "at least one project has no priority rank",
        )
    if a_rank == b_rank:
        return ContentionVerdict(
            OUTCOME_EQUAL_RANK, None,
            "both projects have the same priority rank",
        )
    winner = a_id if a_rank < b_rank else b_id  # LOWER WINS
    return ContentionVerdict(OUTCOME_RANKED, winner, "the higher-priority project wins")


async def verdicts_for_pairs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]], tenant_id: int
) -> dict[tuple[int, int], ContentionVerdict]:
    """One query for a page of conflict pairs. Keyed by the pair AS GIVEN."""
    pairs = list(pairs)
    if not pairs:
        return {}
    ids = {b for pair in pairs for b in pair}
    ranks = await _ranks_for(db, ids, tenant_id)
    # A booking id that resolved to nothing requested nothing either, as far as
    # this tenant can tell — so it takes the plain `no_project` reason, not the
    # "archived or another tenant's" one, which is a claim about a project.
    missing = (None, None, None)
    return {
        (a, b): _decide(a, ranks.get(a, missing), b, ranks.get(b, missing))
        for a, b in pairs
    }


async def verdict_for_pair(
    db: AsyncSession, booking_id: int, other_booking_id: int, tenant_id: int
) -> ContentionVerdict:
    """The single-pair form. DERIVED FROM THE BATCH, not a second implementation
    — two mechanisms answering one question means one test cannot guard both."""
    return (await verdicts_for_pairs(db, [(booking_id, other_booking_id)], tenant_id))[
        (booking_id, other_booking_id)
    ]


# ===========================================================================
# The escalation record — THE ONE THING A4 STORES.
#
# The verdict above is computed; so is the escalation's STATE. What is stored
# is the asking (who, of whom, by when) and the answer (which booking should
# give way, on whose say-so, when, and why). Nothing else, and in particular no
# status column: `open`, `answered` and `expired` follow from `respond_by` and
# `decided_at`, which is why A4 ships no scheduler and nothing to invalidate.
#
# A4 STILL NEVER ACTS. `record_decision` writes four columns on the escalation
# and touches neither booking — not status, not dates, not lifecycle.
# `test_recording_a_decision_changes_nothing_on_either_booking` is the guard.
#
# It lives in this module rather than a second one for the same reason
# `agreement_gap_service` holds both the gap and its acknowledgement: one
# subject, one file. A reader asking "what does A4 do about this pair" finds
# the verdict and the escalation together.
# ===========================================================================

STATE_OPEN = "open"
STATE_ANSWERED = "answered"
STATE_EXPIRED = "expired"


def normalise_pair(a: int, b: int) -> tuple[int, int]:
    """(min, max). A conflict is symmetric; the record is not."""
    return (a, b) if a < b else (b, a)


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes for `DateTime(timezone=True)` columns
    while PostgreSQL hands back aware ones. Comparing the two raises, so
    normalise before any Python-side arithmetic — the stored values are UTC on
    both engines.

    A copy of `agreement_gap_service._utc`, which is itself one of four in this
    package (environment_health_service, environment_utilization_service and
    release_metrics_service carry the others). Copied rather than imported
    because reaching into another service's private helper couples two modules
    that share nothing else; the repo has settled on the copy.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def escalation_state(escalation: ContentionEscalation, now: datetime) -> str:
    """COMPUTED, never stored — which is why A4 needs no scheduler.

    Answering LATE is still `answered`: the decision arrived, and rewriting it
    as expired would lose the fact that someone did decide — and would invite a
    second escalation of a contention that already has an answer. The branch
    ORDER is the rule, and `test_answering_late_is_still_answered` is what pins
    it.

    BOTH SIDES OF THE COMPARISON ARE NORMALISED, not just the stored one. `now`
    comes from the caller, and a caller that reaches for `datetime.utcnow()` —
    naive, and the historically easy mistake in this package — would otherwise
    raise `TypeError: can't compare offset-naive and offset-aware datetimes`
    from a READ path, on both engines, with the traceback nowhere near the call
    site that chose the wrong clock. `_utc` on both sides removes the class
    rather than relying on every future call site to get it right.
    """
    if escalation.decided_at is not None:
        return STATE_ANSWERED
    if _utc(escalation.respond_by) < _utc(now):
        return STATE_EXPIRED
    return STATE_OPEN


async def get_escalation(
    db: AsyncSession, booking_id: int, other_booking_id: int, tenant_id: int
) -> Optional[ContentionEscalation]:
    """The escalation for this contention, asked in EITHER direction.

    Normalises the pair itself, so a caller holding (B,A) is not told there is
    no escalation while looking at the clash it was raised for. Filters
    `deleted_at`: a withdrawn escalation is gone, and tenant scoping is here
    rather than left to the caller because the pair columns are globally unique
    ids — without it another tenant's record answers this question.
    """
    lower, higher = normalise_pair(booking_id, other_booking_id)
    return (await db.execute(
        select(ContentionEscalation).where(
            ContentionEscalation.booking_id == lower,
            ContentionEscalation.other_booking_id == higher,
            ContentionEscalation.tenant_id == tenant_id,
            ContentionEscalation.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def escalations_for_pairs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]], tenant_id: int
) -> dict[tuple[int, int], ContentionEscalation]:
    """One query for a page of conflict pairs. Keyed by the pair AS GIVEN.

    The same contract as `verdicts_for_pairs`, deliberately: a caller walking a
    conflicts page holds one tuple per pair and looks up the verdict and the
    escalation with it. Keying by the NORMALISED pair instead would silently
    answer nothing for every pair the caller happened to hold the other way
    round — while the lookup itself still has to normalise, because the row is
    stored that way.

    A pair with no escalation is simply ABSENT, so a caller may `.get()` its way
    to `escalation: None` without a second question — the same shape as
    `agreement_gap_service.gaps_for_bookings`.
    """
    pairs = list(pairs)
    if not pairs:
        return {}
    wanted = {pair: normalise_pair(*pair) for pair in pairs}
    rows = (await db.execute(
        select(ContentionEscalation).where(
            ContentionEscalation.tenant_id == tenant_id,
            ContentionEscalation.deleted_at.is_(None),
            # An OR of equality pairs rather than `tuple_(...).in_(...)`:
            # row-value IN is not portable across both engines this suite runs
            # on. Same call as `agreement_gap_service._windows_for_pairs`.
            or_(*[
                and_(
                    ContentionEscalation.booking_id == lower,
                    ContentionEscalation.other_booking_id == higher,
                )
                for lower, higher in set(wanted.values())
            ]),
        )
    )).scalars().all()
    by_normalised = {(row.booking_id, row.other_booking_id): row for row in rows}
    return {
        pair: by_normalised[normalised]
        for pair, normalised in wanted.items()
        if normalised in by_normalised
    }


async def bookings_live(
    db: AsyncSession, escalations: Iterable[ContentionEscalation], tenant_id: int
) -> dict[int, bool]:
    """`escalation id -> is this pair still a live contention?`

    COMPUTED, NEVER STORED, and an escalation OUTLIVES ITS BOOKINGS on purpose:
    the record is the audit trail of an argument, so soft-deleting or closing a
    booking must not delete the ask or the answer. It must make the pair read as
    no longer live, so a UI can say the contention has gone away instead of
    dropping the row and the decision with it.

    "Live" is `conflict_service.TERMINAL_STATES` ({rejected, closed}) plus
    `deleted_at`, NOT `booking_states.INACTIVE_BOOKING_STATUSES` — that set
    counts a draft as inactive, and conflict_service deliberately counts drafts
    AS conflicts. An escalation is about a conflict, so it must read live
    exactly while `list_conflicts` would still report the pair; using the other
    set would mark a contention dead that the conflicts page still shows.

    Tenant-scoped like everything else here: asked as a tenant that cannot see
    the bookings, the answer is False rather than a confirmation that they
    exist.
    """
    escalations = list(escalations)
    if not escalations:
        return {}
    ids = {
        booking_id
        for escalation in escalations
        for booking_id in (escalation.booking_id, escalation.other_booking_id)
    }
    live_ids = set((await db.execute(
        select(Booking.id).where(
            Booking.id.in_(ids),
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(conflict_service.TERMINAL_STATES)),
        )
    )).scalars().all())
    return {
        escalation.id: escalation.booking_id in live_ids
        and escalation.other_booking_id in live_ids
        for escalation in escalations
    }


async def _assert_bookings_visible(
    db: AsyncSession, booking_ids: tuple[int, ...], tenant_id: int
) -> None:
    """Both ids must be live bookings of THIS tenant — 404 otherwise, never 403.

    A cross-tenant id must not be confirmed to exist, and both positions are
    checked: validating the subject alone would let the record name a
    counterparty from a tenant the reader cannot open.
    """
    found = set((await db.execute(
        select(Booking.id).where(
            Booking.id.in_(set(booking_ids)),
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
        )
    )).scalars().all())
    if not set(booking_ids) <= found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )


def _pair_conflict_exists(higher: int, tenant_id: int) -> Exists:
    """EXISTS(the other member of this pair, clashing with the correlated Booking).

    THE OVERLAP IS NEVER RE-DERIVED HERE. `conflict_service.conflicts_with` is
    the single definition of what a clash is (same tenant, a different booking,
    same environment, neither soft-deleted, neither terminal, half-open
    `[start, end)` overlap), composed into an EXISTS exactly as
    `conflict_service._unacknowledged_conflict_exists` does. A second copy of
    those rules is precisely the "two mechanisms enforcing one outcome" shape
    that has cost this codebase repeated defects.

    Composed rather than asked of `list_conflicts` because this is a MEMBERSHIP
    question — "is `higher` among them?" — and `list_conflicts` answers it by
    building a `ConflictingBooking` (two outer joins, project and environment
    labels) for every clash on that environment, on a per-escalation write path,
    only to throw all but one row away.
    """
    other = aliased(Booking)
    return (
        select(other.id)
        .where(
            *conflict_service.conflicts_with(
                other,
                subject_id=Booking.id,
                environment_id=Booking.environment_id,
                start_date=Booking.start_date,
                end_date=Booking.end_date,
                tenant_id=tenant_id,
            ),
            other.id == higher,
        )
        .correlate(Booking)
        .exists()
    )


async def _assert_in_conflict(
    db: AsyncSession, lower: int, higher: int, tenant_id: int
) -> None:
    """The pair must really be in contention.

    VISIBILITY IS CHECKED FIRST, UNCONDITIONALLY, and that ordering is the
    fix for a real defect rather than a tidy-up. The overlap question is asked
    of ONE booking about the other, so the two positions are not symmetric:
    `conflicts_with` filters the counterparty's `deleted_at`, while the subject
    side has to be filtered separately. When the visibility check hung off the
    empty branch only, a soft-deleted booking was invisible in one position and
    not the other — so the SAME pair was accepted or refused depending on which
    of the two happened to hold the lower id, and the accepting direction
    created an escalation against a deleted booking that no withdraw path can
    remove. Asking `_assert_bookings_visible` up front costs one query and makes
    both orderings answer the same way.

    WHY A 404 STILL SITS AHEAD OF THE 400. Everything below is tenant-scoped, so
    another tenant's booking would otherwise come back as "no conflict" — and
    answering "these two bookings do not overlap" about a pair the caller cannot
    see would be both a claim about invisible rows and, quite often, false. Not
    ours is 404; ours-and-disjoint is 400.

    THE SUBJECT'S `deleted_at` IS DELIBERATELY NOT FILTERED BELOW. The check
    above already guarantees it, and a second copy would mean two mechanisms
    enforcing one outcome — so a mutation that moved the visibility check back
    where it was would still pass, and the test guarding this would guard
    nothing. `tenant_id` is repeated because the repo's rule is that every query
    on a tenant-scoped table carries it, which is a rule about queries, not
    about this call site.

    The subject's TERMINAL filter has no such backstop and is load-bearing:
    `list_conflicts` returns nothing at all for a terminal subject, and
    `conflicts_with` only filters the counterparty's status.
    """
    await _assert_bookings_visible(db, (lower, higher), tenant_id)
    found = (await db.execute(
        select(Booking.id).where(
            Booking.id == lower,
            Booking.tenant_id == tenant_id,
            not_(Booking.status.in_(conflict_service.TERMINAL_STATES)),
            _pair_conflict_exists(higher, tenant_id),
        )
    )).first()
    if found is not None:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "These two bookings are not in conflict, so there is nothing to "
            "escalate"
        ),
    )


async def create_escalation(
    db: AsyncSession,
    *,
    booking_id: int,
    other_booking_id: int,
    owner_user_id: int,
    respond_by: datetime,
    current_user: User,
    tenant_id: int,
) -> ContentionEscalation:
    """Ask a named person to decide this contention by a named date.

    ONE ESCALATION PER CONTENTION, keyed on the unordered pair. Escalating
    (B,A) after (A,B) returns the EXISTING record, unchanged — deliberately
    unlike the two acknowledgement upserts, where the later answer wins. An
    acknowledgement is one person's answer about their own booking; an
    escalation names SOMEONE ELSE as the decider and starts a clock against
    them, so letting the second escalator silently reassign the owner and reset
    the deadline would let either party restart the other's clock at will, and
    would quietly re-open a contention that already has an answer. Changing an
    owner or a deadline is therefore an explicit edit, not a side effect of
    asking again. Returning it is also the FIRST thing this function does, so
    "escalate again" keeps answering the same way after the pair stops
    overlapping — see the comment on the ordering below.

    `respond_by` is NOT required to be in the future. A deadline already passed
    is a legitimate thing to record — it reads as `expired` immediately, which
    is exactly what an escalation raised about a clash that is already upon
    someone should say — and refusing it here would put a clock-dependent
    validation in the service where the API schema is the honest place for one.
    """
    lower, higher = normalise_pair(booking_id, other_booking_id)

    # THE EXISTING RECORD IS LOOKED FOR FIRST, BEFORE THE CONFLICT CHECK, so
    # that re-asking stays idempotent for the whole life of the escalation.
    # Nothing re-checks overlap after creation and the dates are editable, so a
    # pair can stop clashing while its escalation is still open and unanswered;
    # with the conflict check in front, the second call would then 400 with
    # "these two bookings are not in conflict" about a contention the caller can
    # see on screen, and a UI that re-posts on a double click would show it. The
    # check still guards every NEW record below — a resolved clash cannot be
    # escalated afresh — which is the half of it that was ever doing work.
    #
    # This is safe to answer before any booking is validated because
    # `get_escalation` is tenant-scoped: a record found here belongs to this
    # tenant, and therefore so do both its bookings.
    #
    # `owner_user_id` IS DELIBERATELY NOT VALIDATED ON THIS PATH. The early
    # return below hands back the record that already exists, unchanged (see
    # the docstring above), so a caller-supplied owner — even a nonexistent or
    # cross-tenant one — is simply ignored rather than checked: there is
    # nothing to leak, since the response carries the TRUE owner, not the one
    # just supplied. Pinned by
    # `test_re_asking_with_a_cross_tenant_owner_returns_the_existing_record_unchanged`.
    existing = await get_escalation(db, lower, higher, tenant_id)
    if existing is not None:
        return existing

    await _assert_in_conflict(db, lower, higher, tenant_id)

    # `owner_user_id` is a client-supplied foreign key, so it is checked against
    # the CALLER'S ACTIVE TENANT — the IDOR-class gap the 2026-07-16 isolation
    # audit found four of. Deliberately no `is_active` check, matching
    # `environment_service._validate_client_foreign_keys`: a deactivated account
    # is a different retirement state, and a contention already assigned to
    # someone who has since left still names them.
    found = (await db.execute(
        select(User.id).where(User.id == owner_user_id, User.tenant_id == tenant_id)
    )).first()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Owner not found"
        )

    # A concurrent escalation of the same clash may land between the `existing`
    # read above and this insert; `uq_contention_pair` then refuses ours. That
    # constraint is the backstop, and `test_uq_contention_pair_refuses_a_second_row_for_the_same_pair`
    # guards the constraint itself so that deleting the race test cannot silently
    # unguard it. `insert_or_reread`
    # hands back the row that won — the second escalator gets the first one's
    # record, which is what they would have got had the two calls not
    # overlapped. See app/core/upsert.py for why this needs a savepoint.
    escalation, _inserted = await insert_or_reread(
        db,
        ContentionEscalation(
            tenant_id=tenant_id,
            booking_id=lower,
            other_booking_id=higher,
            escalated_by=current_user.id,
            owner_user_id=owner_user_id,
            respond_by=respond_by,
        ),
        lambda: get_escalation(db, lower, higher, tenant_id),
    )
    await db.flush()
    return escalation


async def record_decision(
    db: AsyncSession,
    escalation_id: int,
    *,
    yields_booking_id: int,
    notes: Optional[str],
    current_user: User,
    tenant_id: int,
) -> ContentionEscalation:
    """Record which booking a human said should give way. AND NOTHING ELSE.

    A4 ADVISES; IT NEVER ACTS: neither booking's status, dates nor lifecycle is
    touched here, and nothing is published. Acting on the decision is the owning
    team's job, through the ordinary transition path — which for an A2 group
    booking moves the whole group atomically, something this service must never
    reach inside.

    A second decision overwrites the first, author and timestamp included, the
    same way the two acknowledgement upserts record the later answer: the row
    answers "who decided this, and when" about the decision that stands. What it
    must never do is drift back to `open` — `escalation_state` keys on
    `decided_at`, which is only ever set here.

    THAT INCLUDES THE NOTES, AND `None` IS AN ANSWER, NOT AN OMISSION. A second
    decision passing `notes=None` clears the first one's stated reason. DECIDED,
    NOT OVERLOOKED: this row holds the decision that stands, and a reason
    carried over from a superseded decision would be attributed to the new one —
    which is worse than no reason at all on a record whose purpose is an audit
    trail. Keeping both would mean an append-only history table, which nobody
    has asked for and which the ack precedent does not have either. If a history
    is ever wanted, it is a new table, not a `COALESCE` here.
    """
    # Tenant-filtered, and another tenant's escalation is 404, NEVER 403 — a 403
    # confirms the record exists. ONE SPELLING of that lookup, shared with the
    # API's decision gate: two copies of a tenant filter on one path means a
    # test cannot tell which of them it is guarding.
    escalation = await get_escalation_by_id(db, escalation_id, tenant_id)

    if yields_booking_id not in (escalation.booking_id, escalation.other_booking_id):
        # BOTH members, because the pair is stored normalised: a check written
        # against `booking_id` alone would refuse whichever booking happened to
        # take the higher id.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The yielding booking must be one of the two in contention",
        )

    escalation.decision_yields_booking_id = yields_booking_id
    escalation.decision_notes = notes
    escalation.decided_by = current_user.id
    escalation.decided_at = datetime.now(timezone.utc)
    await db.flush()
    return escalation


# ===========================================================================
# The API's half: the worklist query, the batch view, and the TWO PERMISSION
# GATES.
#
# `create_escalation` and `record_decision` above carry no authorization —
# they are write primitives. Every rule about WHO may ask and WHO may answer
# lives below, and is asserted through HTTP in
# tests/integration/test_contention_api.py.
# ===========================================================================


ESCALATION_SORTS = {
    "respond_by": ContentionEscalation.respond_by,
    "created_at": ContentionEscalation.created_at,
    "decided_at": ContentionEscalation.decided_at,
}


def state_predicate(state: str, now: datetime):
    """The three states as SQL, over the same two columns `escalation_state`
    reads — and nothing else.

    IN SQL, NEVER IN PYTHON. A worklist filtered after the page was fetched
    would window the unfiltered set first: the rows returned would be whatever
    the page happened to hold, and `X-Total-Count` would describe the unfiltered
    total. `X-Total-Count` is the only evidence available from outside that this
    ran in the query, which is why every filtered test asserts it.

    THE BRANCH ORDER OF `escalation_state` IS REPRODUCED HERE, not approximated:
    `answered` is `decided_at IS NOT NULL` with no reference to the deadline, so
    a late answer is `answered` in the filter exactly as it is on the row. The
    two are separate mechanisms answering one question, so every state test
    asserts the filtered row's own computed `state` as well as its id.

    `now` is the CALLER'S clock, passed in rather than taken here, so the page's
    filter and the page's rendered states are computed from one instant. Taken
    twice, a row whose deadline falls between the two reads would be selected as
    open and rendered as expired.
    """
    if state == STATE_ANSWERED:
        return ContentionEscalation.decided_at.is_not(None)
    if state == STATE_EXPIRED:
        return and_(
            ContentionEscalation.decided_at.is_(None),
            ContentionEscalation.respond_by < now,
        )
    if state == STATE_OPEN:
        return and_(
            ContentionEscalation.decided_at.is_(None),
            ContentionEscalation.respond_by >= now,
        )
    raise ValueError(f"unknown escalation state {state!r}")


async def list_escalations(
    db: AsyncSession,
    tenant_id: int,
    *,
    now: datetime,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    state: Optional[str] = None,
) -> tuple[list[ContentionEscalation], int]:
    """The worklist: every escalation this tenant can see, plus the unwindowed
    total.

    AN ESCALATION OUTLIVES ITS BOOKINGS, so nothing here joins them or filters
    on their state — a contention that has gone away keeps its record, and
    `bookings_live` says so. Filtering the worklist by liveness would delete the
    audit trail from the only screen that shows it.

    `deleted_at` IS filtered: a withdrawn escalation is gone, matching
    `get_escalation`.
    """
    query = select(ContentionEscalation).where(
        ContentionEscalation.tenant_id == tenant_id,
        ContentionEscalation.deleted_at.is_(None),
    )
    if state is not None:
        query = query.where(state_predicate(state, now))
    # The tiebreaker is chained AFTER apply_sort, never instead of it: none of
    # the sortable columns is unique (two escalations may share a deadline, and
    # `decided_at` is null on every open one), and LIMIT/OFFSET over a partial
    # order duplicates and drops rows across pages.
    query = apply_sort(query, sort).order_by(ContentionEscalation.id)
    return await fetch_page(db, query, page)


async def usernames_for(db: AsyncSession, user_ids: Iterable[int]) -> dict[int, str]:
    """`user id -> username`, for rendering names on escalation rows.

    DELIBERATELY NOT TENANT-QUALIFIED, and this is the trap in the whole field —
    the rule `agreement_gap_service.ack_author_username` carries, in batch form.
    Under master-admin impersonation `current_user.id` and
    `current_user.active_tenant_id` belong to different tenants, so
    `record_decision` legitimately writes a `decided_by` that sits OUTSIDE the
    escalation's own `tenant_id`. A `User.tenant_id == tenant_id` join renders
    that decider as nobody — the governance trail losing exactly the name it
    exists to hold, and only under impersonation.
    `test_the_deciders_name_resolves_from_outside_the_escalations_tenant` fails
    with that join added. **Do not "harden" this into a tenant-qualified join.**

    Not a leak: the caller's authority to see these escalations was already
    settled by the tenant-filtered query that produced them, and a username is
    the same thing the record's own author column already discloses.

    Nor does it filter `is_active` or `deleted_at`: A1's rule is that write
    validation filters retirement while read RENDERING does not — an archived
    user still renders their name on the row they wrote.

    Resolved SERVER-SIDE and carried with the row. The browser must not look
    these up in the capped tenant-users collection, where a name past the cap is
    information lost, not merely hidden (docs/pagination.md).
    """
    user_ids = {uid for uid in user_ids if uid is not None}
    if not user_ids:
        return {}
    rows = (await db.execute(
        select(User.id, User.username).where(User.id.in_(user_ids))
    )).all()
    return {uid: username for uid, username in rows}


class EscalationView(NamedTuple):
    """An escalation plus everything a response needs that is not a column.

    Every field is COMPUTED — the state from two columns and a clock, liveness
    from the two bookings, the names from the user table — which is why the
    record needs no status column and A4 needs no scheduler.
    """

    escalation: ContentionEscalation
    state: str
    bookings_live: bool
    owner_username: Optional[str]
    escalated_by_username: Optional[str]
    decided_by_username: Optional[str]


async def escalation_views(
    db: AsyncSession,
    escalations: Iterable[ContentionEscalation],
    tenant_id: int,
    now: datetime,
) -> dict[int, EscalationView]:
    """`escalation id -> EscalationView`, for a whole page in two queries.

    BATCH, NEVER PER ROW. Three sub-projects have now added a field to the
    conflicts endpoint and every per-row form has had to be undone; a per-row
    liveness or username lookup here would cost ~3N queries per page for
    something every row needs.
    """
    escalations = list(escalations)
    if not escalations:
        return {}
    live = await bookings_live(db, escalations, tenant_id)
    names = await usernames_for(
        db,
        [
            uid
            for escalation in escalations
            for uid in (
                escalation.owner_user_id,
                escalation.escalated_by,
                escalation.decided_by,
            )
        ],
    )
    return {
        escalation.id: EscalationView(
            escalation=escalation,
            state=escalation_state(escalation, now),
            bookings_live=live[escalation.id],
            owner_username=names.get(escalation.owner_user_id),
            escalated_by_username=names.get(escalation.escalated_by),
            decided_by_username=names.get(escalation.decided_by),
        )
        for escalation in escalations
    }


async def get_escalation_by_id(
    db: AsyncSession, escalation_id: int, tenant_id: int
) -> ContentionEscalation:
    """One escalation by id, or 404.

    Another tenant's escalation is 404, NEVER 403 — a 403 confirms the record
    exists. The API's decision gate reads the row through this, so the tenant
    filter is settled before the owner-or-Admin question is ever asked.
    """
    escalation = (await db.execute(
        select(ContentionEscalation).where(
            ContentionEscalation.id == escalation_id,
            ContentionEscalation.tenant_id == tenant_id,
            ContentionEscalation.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if escalation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found"
        )
    return escalation


def _is_admin(user: User) -> bool:
    """Admin, or a master admin acting in this tenant.

    Both, everywhere: the rest of the app treats `is_master_admin` as satisfying
    an Admin bypass, and the two places that forgot (B3b's transition gate and
    `assert_may_edit_handover`) showed a master admin a button that 403'd on
    click.
    """
    return user.role == "Admin" or bool(user.is_master_admin)


async def assert_may_escalate(
    db: AsyncSession,
    booking_id: int,
    other_booking_id: int,
    tenant_id: int,
    current_user: User,
) -> None:
    """The owner or a delegate of EITHER contending booking, or an Admin.

    `conflict_service._authorize_ack` is the precedent, widened to the pair: an
    acknowledgement is one person's answer about their own booking, while a
    contention belongs to both sides of it — and either party may legitimately
    be the one who wants a decision. A gate written against the subject id alone
    would refuse whichever party happened to open the other booking's drawer,
    for a record that is symmetric by construction.

    DELIBERATELY NARROWER THAN A3'S ACK, which any tenant member may record.
    Escalating names SOMEONE ELSE as the decider and starts a clock against
    them, so a bystander must not be able to do it to two bookings they have no
    part in.

    VISIBILITY IS SETTLED BEFORE THE 403 IS EVER RAISED, and that is what makes
    a cross-tenant pair 404 rather than 403: without the check above, a
    bystander naming two of another tenant's bookings falls through the loop
    below and is refused with "you are not the owner of these" — a 403 where the
    contract says 404. `test_a_bystander_escalating_another_tenants_bookings_gets_404_not_403`
    fails with the line removed, and asserts the 404's DETAIL so it cannot be
    satisfied by an unrouted URL.

    The query below now carries its own `tenant_id` as well. That is defence in
    depth, not the mechanism: it changes no answer while this call site runs the
    visibility check first, and it exists so a future second caller cannot
    inherit a cross-tenant `BookingRequest` read. The check above remains
    load-bearing for the STATUS CODE, which the tenant filter does not fix.

    Its position relative to the Admin BYPASS is, measuredly, immaterial: an
    Admin who skipped it still hits `create_escalation`'s own check and still
    gets a 404. It sits at the top because that is where the question belongs,
    not because moving it changes an answer — a mutation that moved it below the
    bypass left all 27 tests green, and this note exists so a later reader does
    not mistake the ordering for a guarded rule.

    It lives here rather than in `create_escalation` for the same reason
    `record_decision` carries no authorization: those two are the service's
    write primitives and are called by tests and, one day, by other services
    with their own rules. The API is where a user's authority is decided.
    """
    await _assert_bookings_visible(db, (booking_id, other_booking_id), tenant_id)
    if _is_admin(current_user):
        return
    requests = (await db.execute(
        select(BookingRequest)
        .join(Booking, Booking.booking_request_id == BookingRequest.id)
        .where(
            Booking.id.in_({booking_id, other_booking_id}),
            # DEFENCE IN DEPTH, and free: the ids were just proved to be this
            # tenant's, so this changes no answer today. It is here because
            # `assert_may_escalate` is module-level and public — a second caller
            # that reached it without the visibility check above would otherwise
            # inherit a cross-tenant `BookingRequest` read, and the repo's rule
            # is that EVERY query on a tenant-scoped table carries `tenant_id`.
            # `conflict_service._authorize_ack` has the same shape and the same
            # exception; this removes ours rather than propagating it.
            BookingRequest.tenant_id == tenant_id,
        )
    )).scalars().all()
    for request in requests:
        if current_user.id == request.booked_by:
            return
        if request.delegate_user_ids and current_user.id in request.delegate_user_ids:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Only the owner or a delegate of one of these bookings, or an "
            "admin, may escalate this contention"
        ),
    )


def assert_may_decide(escalation: ContentionEscalation, current_user: User) -> None:
    """The NAMED OWNER, or an Admin. 403 otherwise.

    THE ADMIN PATH IS NOT A CONVENIENCE. A4 ships no edit and no withdraw path,
    so an escalation naming the wrong owner — or one whose owner has since left
    — has exactly one way out: someone with authority answers it. B3b
    established the failure mode by shipping the opposite: gating solely on one
    person left a workflow permanently stuck, and produced two unrecoverable
    states.

    Nobody else, though. The decision is the record of who said what should give
    way, and a decider chosen at random by whoever clicked first is not an audit
    trail. Note the caller need not be the owner for the record to name them:
    `record_decision` writes `decided_by = current_user.id`, so an Admin
    answering on someone else's behalf is visible as exactly that.

    The escalation is loaded by `get_escalation_by_id`, which is tenant-filtered
    and 404s — so a cross-tenant record never reaches this function to be
    refused with a 403 that would confirm it exists.
    """
    if current_user.id == escalation.owner_user_id or _is_admin(current_user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the named owner, or an admin, may decide this contention",
    )
