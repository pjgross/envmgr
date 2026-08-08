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
"""
from typing import Iterable, NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.project import Project

OUTCOME_RANKED = "ranked"
OUTCOME_NO_PROJECT = "no_project"
OUTCOME_UNRANKED = "unranked"
OUTCOME_EQUAL_RANK = "equal_rank"


class ContentionVerdict(NamedTuple):
    outcome: str
    winner_booking_id: Optional[int]
    reason: str


async def _ranks_for(
    db: AsyncSession, booking_ids: set[int], tenant_id: int
) -> dict[int, tuple[Optional[int], Optional[int]]]:
    """booking id -> (project_id, priority_rank), for bookings in this tenant.

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
        select(Booking.id, Project.id, Project.priority_rank)
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
    return {bid: (pid, rank) for bid, pid, rank in rows}


def _decide(
    a_id: int, a: tuple[Optional[int], Optional[int]],
    b_id: int, b: tuple[Optional[int], Optional[int]],
) -> ContentionVerdict:
    """The whole decision, in branch order — and the order is load-bearing.

    A booking with no project has no rank either, so `no_project` must be asked
    FIRST or every project-less pair would report as `unranked` and invite
    someone to fix it by ranking a project that is not there.
    """
    a_project, a_rank = a
    b_project, b_rank = b
    if a_project is None or b_project is None:
        return ContentionVerdict(
            OUTCOME_NO_PROJECT, None,
            "at least one booking is not linked to a project",
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
    missing = (None, None)
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
