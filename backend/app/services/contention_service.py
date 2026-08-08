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
