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
from sqlalchemy import and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """
    if escalation.decided_at is not None:
        return STATE_ANSWERED
    if _utc(escalation.respond_by) < now:
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


async def _assert_in_conflict(
    db: AsyncSession, lower: int, higher: int, tenant_id: int
) -> None:
    """The pair must really be in contention — asked of `conflict_service`.

    THE OVERLAP IS NEVER RE-DERIVED HERE. `conflicts_with` is the single
    definition of what a clash is (same tenant, same environment, neither
    soft-deleted, neither terminal, half-open `[start, end)` overlap) and a
    second copy is precisely the "two mechanisms enforcing one outcome" shape
    that has cost this codebase repeated defects.

    WHY THE 404 CHECK LIVES INSIDE THE 400. `list_conflicts` is itself
    tenant-scoped, so another tenant's booking comes back as "no conflicts" —
    and answering "these two bookings do not overlap" about a pair the caller
    cannot see would be both a claim about invisible rows and, quite often,
    false. So an empty result is refined: not ours is 404, ours-and-disjoint is
    400.
    """
    conflicts, _total = await conflict_service.list_conflicts(db, lower, tenant_id)
    if higher in {row.booking.id for row in conflicts}:
        return
    await _assert_bookings_visible(db, (lower, higher), tenant_id)
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
    asking again.

    `respond_by` is NOT required to be in the future. A deadline already passed
    is a legitimate thing to record — it reads as `expired` immediately, which
    is exactly what an escalation raised about a clash that is already upon
    someone should say — and refusing it here would put a clock-dependent
    validation in the service where the API schema is the honest place for one.
    """
    lower, higher = normalise_pair(booking_id, other_booking_id)
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

    existing = await get_escalation(db, lower, higher, tenant_id)
    if existing is not None:
        return existing

    # A concurrent escalation of the same clash may land between the read above
    # and this insert; `uq_contention_pair` then refuses ours. `insert_or_reread`
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
    """
    escalation = (await db.execute(
        select(ContentionEscalation).where(
            ContentionEscalation.id == escalation_id,
            ContentionEscalation.tenant_id == tenant_id,
            ContentionEscalation.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if escalation is None:
        # Another tenant's escalation is 404, NEVER 403 — a 403 confirms the
        # record exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found"
        )

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
