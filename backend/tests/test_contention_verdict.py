"""The contention verdict (A4, task 2): which project outranks the other, and why.

A4 ADVISES; IT NEVER ACTS. Nothing here transitions, rejects or reschedules a
booking, and nothing in this file asserts that it does — task 4 carries the
named guard on that promise.

THREE OF THE FOUR OUTCOMES ARE "NO WINNER". Each is asserted by name, with its
reason, rather than through a "there is no winner" catch-all: `no_project`,
`unranked` and `equal_rank` are three different things to tell a user, and a
test that only checked `winner_booking_id is None` would stay green while the
service told everyone the wrong one.

The last test asserts the batch form and the single form AGAINST EACH OTHER over
a population containing all four outcomes, not separately — A1 shipped a count
and a list, written three tasks apart, that disagreed two ways.
"""
from datetime import datetime, timezone

import pytest

from app.services import contention_service
from app.services.contention_service import (
    OUTCOME_EQUAL_RANK,
    OUTCOME_NO_PROJECT,
    OUTCOME_RANKED,
    OUTCOME_UNRANKED,
    REASON_NO_PROJECT,
    REASON_PROJECT_UNRESOLVABLE,
)
from tests.factories import ensure_environment, ensure_project, make_booking

START = datetime(2026, 3, 1, tzinfo=timezone.utc)
END = datetime(2026, 3, 5, tzinfo=timezone.utc)


class _NoDatabase:
    """A stand-in that fails loudly if anything touches it.

    Used by the empty-pair test: "asks the database nothing" is a claim about a
    code path, and the only way to assert it without inspecting emitted SQL is
    to hand the function something that cannot answer a query.
    """

    def __getattr__(self, name):  # pragma: no cover - only reached on failure
        raise AssertionError(
            f"the empty-pair path must not touch the database (asked for .{name})"
        )


async def _project(db, tenant_id, name, rank=None, deleted_at=None, is_active=True):
    """A project with a priority rank. `ensure_project` is idempotent per
    (tenant, name), so every caller here passes a distinct name."""
    project = await ensure_project(db, tenant_id, name=name)
    project.priority_rank = rank
    project.deleted_at = deleted_at
    project.is_active = is_active
    await db.flush()
    return project


async def _booking(db, tenant_id, user_id, *, project_id=None, slot=1):
    """A booking in `tenant_id` whose request names `project_id` (or nothing).

    `booking_request.project_id` is what the verdict reads; the booking itself
    has no project column.
    """
    env = await ensure_environment(db, tenant_id, slot=slot)
    return await make_booking(
        db,
        tenant_id,
        booked_by=user_id,
        environment=env,
        project_id=project_id,
        start=START,
        end=END,
    )


# ---------------------------------------------------------------------------
# The one outcome that names a winner.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_lower_rank_wins(db_session, test_tenant, test_user):
    """LOWER WINS: rank 1 outranks rank 5.

    Asserted on the WINNER'S IDENTITY, not merely on the outcome — a comparison
    written the wrong way round still returns `ranked`, and would hand every
    argument to the lowest-priority project on the estate.
    """
    high = await _project(db_session, test_tenant.id, "High priority", rank=1)
    low = await _project(db_session, test_tenant.id, "Low priority", rank=5)
    winner = await _booking(db_session, test_tenant.id, test_user.id, project_id=high.id)
    loser = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=low.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, winner.id, loser.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_RANKED
    assert verdict.winner_booking_id == winner.id
    assert verdict.reason


@pytest.mark.asyncio
async def test_the_lower_rank_still_wins_when_it_is_the_second_booking(
    db_session, test_tenant, test_user
):
    """The same pair asked the other way round names the same winner.

    The verdict is about the two projects, not about the order the caller
    happened to hand them over.
    """
    high = await _project(db_session, test_tenant.id, "High priority", rank=1)
    low = await _project(db_session, test_tenant.id, "Low priority", rank=5)
    winner = await _booking(db_session, test_tenant.id, test_user.id, project_id=high.id)
    loser = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=low.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, loser.id, winner.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_RANKED
    assert verdict.winner_booking_id == winner.id


# ---------------------------------------------------------------------------
# The three that decline to name one.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_booking_with_no_project_is_no_project(
    db_session, test_tenant, test_user
):
    """On today's data this is almost every pair — `project_id` is nullable
    with no backfill — so it must read as its own answer, not as a loss."""
    a = await _booking(db_session, test_tenant.id, test_user.id)
    b = await _booking(db_session, test_tenant.id, test_user.id, slot=2)

    verdict = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_NO_PROJECT
    assert verdict.winner_booking_id is None


@pytest.mark.asyncio
async def test_a_ranked_project_does_not_beat_a_booking_with_no_project(
    db_session, test_tenant, test_user
):
    """A ranked project does NOT win against a project-less booking.

    Pins the branch ORDER as well as the branch: a pair where one side has no
    project at all is `no_project`, never `unranked` and never a win for the
    only side that has a rank. Asserted with the ranked booking FIRST and
    SECOND, so neither half of the `or` can be dropped unnoticed.
    """
    ranked = await _project(db_session, test_tenant.id, "Ranked", rank=1)
    with_project = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=ranked.id
    )
    without = await _booking(db_session, test_tenant.id, test_user.id, slot=2)

    first = await contention_service.verdict_for_pair(
        db_session, with_project.id, without.id, test_tenant.id
    )
    second = await contention_service.verdict_for_pair(
        db_session, without.id, with_project.id, test_tenant.id
    )
    assert first.outcome == OUTCOME_NO_PROJECT
    assert first.winner_booking_id is None
    assert second.outcome == OUTCOME_NO_PROJECT
    assert second.winner_booking_id is None


@pytest.mark.asyncio
async def test_a_ranked_project_does_not_beat_an_unranked_one(
    db_session, test_tenant, test_user
):
    """THE RULE THAT PROTECTS THE EXISTING ESTATE.

    No project has a rank on first deploy. Treating unranked as lowest would
    declare every existing project the loser the day this ships, so a ranked
    project meeting an unranked one is `unranked` — no winner — and is asserted
    with the ranked side in both positions.
    """
    ranked = await _project(db_session, test_tenant.id, "Ranked", rank=1)
    unranked = await _project(db_session, test_tenant.id, "Unranked", rank=None)
    a = await _booking(db_session, test_tenant.id, test_user.id, project_id=ranked.id)
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=unranked.id, slot=2
    )

    first = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    second = await contention_service.verdict_for_pair(
        db_session, b.id, a.id, test_tenant.id
    )
    assert first.outcome == OUTCOME_UNRANKED
    assert first.winner_booking_id is None
    assert second.outcome == OUTCOME_UNRANKED
    assert second.winner_booking_id is None


@pytest.mark.asyncio
async def test_two_unranked_projects_are_unranked_not_equal(
    db_session, test_tenant, test_user
):
    """Two projects with no rank are NOT "the same rank".

    Both answers decline to name a winner, so only the outcome name separates
    them — and they say different things to a user: one asks for a rank, the
    other says ranks were set and did not separate these.
    """
    first_project = await _project(db_session, test_tenant.id, "One", rank=None)
    second_project = await _project(db_session, test_tenant.id, "Two", rank=None)
    a = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=first_project.id
    )
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=second_project.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_UNRANKED
    assert verdict.winner_booking_id is None


@pytest.mark.asyncio
async def test_two_projects_with_the_same_rank_are_equal_rank(
    db_session, test_tenant, test_user
):
    """Ranks are set and they do not separate these two — a real answer, and a
    different one from "nobody has ranked these"."""
    first_project = await _project(db_session, test_tenant.id, "One", rank=3)
    second_project = await _project(db_session, test_tenant.id, "Two", rank=3)
    a = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=first_project.id
    )
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=second_project.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_EQUAL_RANK
    assert verdict.winner_booking_id is None


@pytest.mark.asyncio
async def test_two_bookings_of_the_same_project_are_equal_rank(
    db_session, test_tenant, test_user
):
    """A project cannot outrank itself. The commonest real contention — one
    project double-booking an environment — must never name a winner."""
    project = await _project(db_session, test_tenant.id, "Only", rank=2)
    a = await _booking(db_session, test_tenant.id, test_user.id, project_id=project.id)
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=project.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_EQUAL_RANK
    assert verdict.winner_booking_id is None


@pytest.mark.asyncio
async def test_every_no_winner_outcome_carries_its_own_reason(
    db_session, test_tenant, test_user
):
    """Three refusals to name a winner, three distinct non-empty reasons.

    A shared "no winner" string would be indistinguishable to a reader, which
    is the whole point of reporting the reason instead of a fabricated
    ordering.
    """
    ranked = await _project(db_session, test_tenant.id, "Ranked", rank=1)
    unranked = await _project(db_session, test_tenant.id, "Unranked", rank=None)
    same_a = await _project(db_session, test_tenant.id, "Same A", rank=4)
    same_b = await _project(db_session, test_tenant.id, "Same B", rank=4)

    none_booking = await _booking(db_session, test_tenant.id, test_user.id)
    ranked_booking = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=ranked.id, slot=2
    )
    unranked_booking = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=unranked.id, slot=3
    )
    same_a_booking = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=same_a.id, slot=4
    )
    same_b_booking = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=same_b.id, slot=5
    )

    no_project = await contention_service.verdict_for_pair(
        db_session, none_booking.id, ranked_booking.id, test_tenant.id
    )
    unranked_verdict = await contention_service.verdict_for_pair(
        db_session, ranked_booking.id, unranked_booking.id, test_tenant.id
    )
    equal = await contention_service.verdict_for_pair(
        db_session, same_a_booking.id, same_b_booking.id, test_tenant.id
    )

    reasons = [no_project.reason, unranked_verdict.reason, equal.reason]
    assert all(reason.strip() for reason in reasons)
    assert len(set(reasons)) == 3


# ---------------------------------------------------------------------------
# Tenant scoping. Assume every tenant filter is unguarded until a named test
# fails without it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_tenants_project_rank_never_decides_our_verdict(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """A booking of ours whose request points at ANOTHER tenant's project reads
    as project-less here — never as ranked.

    The other tenant's project is ranked 1 and ours is ranked 5, so a missing
    `Project.tenant_id` filter would not merely leak a number: it would decide
    the argument, and decide it for the wrong side.
    """
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await _project(db_session, other_tenant.id, "Theirs", rank=1)
    ours = await _project(db_session, test_tenant.id, "Ours", rank=5)

    cross = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=theirs.id
    )
    mine = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=ours.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, cross.id, mine.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_NO_PROJECT
    assert verdict.winner_booking_id is None
    # The REQUEST names a project; this tenant cannot resolve it. Telling the
    # user "not linked to a project" would be a lie they can see is a lie.
    assert verdict.reason == REASON_PROJECT_UNRESOLVABLE


@pytest.mark.asyncio
async def test_another_tenants_booking_is_not_resolved_even_against_our_project(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """A booking that is not ours contributes no rank, whatever its request
    points at.

    The malformed row here is another tenant's booking whose request names OUR
    ranked project — the only shape in which dropping `Booking.tenant_id` from
    the lookup changes an answer, because the Project join is filtered to our
    tenant either way. Without that filter this pair becomes `ranked` and hands
    the win to a booking in a tenant the caller cannot even see.
    """
    other_tenant, other_admin = await second_tenant_factory()
    high = await _project(db_session, test_tenant.id, "High", rank=1)
    low = await _project(db_session, test_tenant.id, "Low", rank=5)

    theirs = await _booking(
        db_session, other_tenant.id, other_admin.id, project_id=high.id
    )
    mine = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=low.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, theirs.id, mine.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_NO_PROJECT
    assert verdict.winner_booking_id is None


@pytest.mark.asyncio
async def test_a_soft_deleted_project_never_wins_an_argument(
    db_session, test_tenant, test_user
):
    """An archived project reads as project-less to the verdict.

    Deliberately NOT the rule `get_project_names` follows — it renders an
    archived project's name on the rows that reference it, because rendering a
    name and deciding a contention are different questions. The archived
    project here holds rank 1 against a live rank 5, so keeping it would let a
    project nobody runs any more win.
    """
    archived = await _project(
        db_session,
        test_tenant.id,
        "Archived",
        rank=1,
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    live = await _project(db_session, test_tenant.id, "Live", rank=5)
    a = await _booking(db_session, test_tenant.id, test_user.id, project_id=archived.id)
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=live.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_NO_PROJECT
    assert verdict.winner_booking_id is None
    # THE CASE THAT SHOWS ITS OWN CONTRADICTION. Task 4 renders the project name
    # from `get_project_names`, which deliberately does not filter `deleted_at`,
    # so "Archived" appears on the row. The reason has to name the archiving.
    assert verdict.reason == REASON_PROJECT_UNRESOLVABLE


@pytest.mark.asyncio
async def test_the_two_no_project_reasons_are_not_interchangeable(
    db_session, test_tenant, test_user
):
    """One outcome, two reasons, and neither may be served for the other's case.

    Pinned by the CHOICE between the two exported constants rather than word by
    word — copy edits to either string flow through, but swapping which case
    gets which, or collapsing them back into one string, fails here. The two
    substring assertions are the minimum that stops "distinct" being satisfied
    by two strings that say the same thing.
    """
    archived = await _project(
        db_session,
        test_tenant.id,
        "Archived",
        rank=1,
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ranked = await _project(db_session, test_tenant.id, "Ranked", rank=5)

    on_archived = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=archived.id
    )
    on_ranked = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=ranked.id, slot=2
    )
    without = await _booking(db_session, test_tenant.id, test_user.id, slot=3)

    unresolvable = await contention_service.verdict_for_pair(
        db_session, on_archived.id, on_ranked.id, test_tenant.id
    )
    genuinely_none = await contention_service.verdict_for_pair(
        db_session, without.id, on_ranked.id, test_tenant.id
    )

    # Same outcome — no fifth outcome was invented — different reason.
    assert unresolvable.outcome == genuinely_none.outcome == OUTCOME_NO_PROJECT
    assert unresolvable.reason != genuinely_none.reason
    assert unresolvable.reason == REASON_PROJECT_UNRESOLVABLE
    assert genuinely_none.reason == REASON_NO_PROJECT
    # Each names its own case rather than the other's.
    assert "archived" in unresolvable.reason.lower()
    assert "archived" not in genuinely_none.reason.lower()
    assert "not linked" in genuinely_none.reason.lower()


@pytest.mark.asyncio
async def test_an_inactive_project_still_carries_its_rank(
    db_session, test_tenant, test_user
):
    """`is_active=False` does NOT take a project out of the contention.

    THIS TEST EXISTS TO FAIL A "TIDY-UP". `Project.is_active` is deliberately
    absent from the join, and adding `& Project.is_active.is_(True)` to
    "harmonise" it with the UI pickers left every other test in this file green
    while every booking on an archived-but-not-deleted project silently flipped
    from `ranked` to `no_project`.

    A1's rule: `is_active` and `deleted_at` are two DIFFERENT retirement states,
    and `get_project` does not check `is_active` either. `is_active=False` means
    "stop offering this in pickers"; the project is still running, its bookings
    are still real, and its rank still has to decide the arguments they are in.
    `deleted_at` is the one that means gone — and that one IS filtered, by
    `test_a_soft_deleted_project_never_wins_an_argument`. Changing this is a
    product decision, not a clean-up.
    """
    inactive = await _project(
        db_session, test_tenant.id, "Inactive", rank=1, is_active=False
    )
    live = await _project(db_session, test_tenant.id, "Live", rank=5)
    a = await _booking(db_session, test_tenant.id, test_user.id, project_id=inactive.id)
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=live.id, slot=2
    )

    verdict = await contention_service.verdict_for_pair(
        db_session, a.id, b.id, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_RANKED
    assert verdict.winner_booking_id == a.id


@pytest.mark.asyncio
async def test_a_booking_id_that_does_not_exist_is_no_project(
    db_session, test_tenant, test_user
):
    """An unresolvable id decides nothing and raises nothing.

    The verdict feeds a warning, not a permission decision, so a stale id gets
    the same silence a project-less booking gets.
    """
    ranked = await _project(db_session, test_tenant.id, "Ranked", rank=1)
    live = await _booking(db_session, test_tenant.id, test_user.id, project_id=ranked.id)

    verdict = await contention_service.verdict_for_pair(
        db_session, live.id, live.id + 10_000, test_tenant.id
    )
    assert verdict.outcome == OUTCOME_NO_PROJECT
    assert verdict.winner_booking_id is None
    # A booking we cannot resolve named no project we can see, so it must NOT
    # claim an archived or cross-tenant PROJECT — that is a statement about a
    # project, and there is none to make it about.
    assert verdict.reason == REASON_NO_PROJECT


# ---------------------------------------------------------------------------
# The batch form.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_rank_lookup_reads_only_the_bookings_it_was_asked_about(
    db_session, test_tenant, test_user
):
    """`_ranks_for` is bounded to the ids it is given.

    Pinned at the helper deliberately, and this is the one rule in the module
    with no visible effect on a verdict: the decision only ever reads the two
    ids in the pair, so an unbounded lookup returns the SAME verdicts while
    loading every booking in the tenant on every conflicts page. A behavioural
    test cannot see that; the same standing as the health-history tiebreaker,
    which is likewise pinned structurally and says so.
    """
    project = await _project(db_session, test_tenant.id, "Only", rank=1)
    asked = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=project.id
    )
    unasked = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=project.id, slot=2
    )

    found = await contention_service._ranks_for(db_session, {asked.id}, test_tenant.id)
    assert set(found) == {asked.id}
    assert unasked.id not in found


@pytest.mark.asyncio
async def test_the_rank_lookup_reports_a_project_less_booking_rather_than_dropping_it(
    db_session, test_tenant, test_user
):
    """The Project join is OUTER, so "this booking exists and has no project" is
    a different answer from "this booking id resolves to nothing".

    The verdict cannot tell them apart — both reach `_decide` as `(None, None)`
    and both are `no_project` — so an inner join would pass every other test in
    this file while quietly changing what the map means. Task 3 records an
    escalation against a booking, and a helper whose keys silently omit the
    commonest booking on the estate is the kind of thing a later task reads once
    and trusts.
    """
    no_project = await _booking(db_session, test_tenant.id, test_user.id)

    found = await contention_service._ranks_for(
        db_session, {no_project.id}, test_tenant.id
    )
    assert found == {no_project.id: (None, None, None)}


@pytest.mark.asyncio
async def test_the_rank_lookup_keeps_the_requested_project_id_apart_from_the_resolved_one(
    db_session, test_tenant, test_user
):
    """`_ranks_for` returns what the request NAMES and what this tenant can SEE
    as two separate values, and they differ for an unresolvable link.

    This is the distinction the two `no_project` reasons are built on, and it
    exists only here: once the requested id is dropped, "names no project" and
    "names an archived project" are the same `(None, ...)` to `_decide`, and the
    verdict tells a user their booking has no project while the row beside it
    renders that project's name (`get_project_names` deliberately does not
    filter `deleted_at`).
    """
    archived = await _project(
        db_session,
        test_tenant.id,
        "Archived",
        rank=1,
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    on_archived = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=archived.id
    )
    without = await _booking(db_session, test_tenant.id, test_user.id, slot=2)

    found = await contention_service._ranks_for(
        db_session, {on_archived.id, without.id}, test_tenant.id
    )
    # The request still names it; the tenant-and-liveness-filtered join does not.
    assert found[on_archived.id] == (archived.id, None, None)
    # Nothing named, nothing resolved — and that is a different pair of values.
    assert found[without.id] == (None, None, None)


@pytest.mark.asyncio
async def test_verdicts_for_pairs_answers_only_about_the_pairs_it_was_given(
    db_session, test_tenant, test_user
):
    """Keyed by the pair AS GIVEN, and no other pair is invented from the ids.

    Three bookings make three possible pairs; asking for one must not answer
    for the other two, and asking for `(b, a)` must not answer under `(a, b)`.
    """
    high = await _project(db_session, test_tenant.id, "High", rank=1)
    low = await _project(db_session, test_tenant.id, "Low", rank=5)
    a = await _booking(db_session, test_tenant.id, test_user.id, project_id=high.id)
    b = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=low.id, slot=2
    )
    c = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=low.id, slot=3
    )

    results = await contention_service.verdicts_for_pairs(
        db_session, [(b.id, a.id)], test_tenant.id
    )
    assert set(results) == {(b.id, a.id)}
    assert results[(b.id, a.id)].winner_booking_id == a.id
    assert (a.id, b.id) not in results
    assert (a.id, c.id) not in results


@pytest.mark.asyncio
async def test_an_empty_pair_list_asks_the_database_nothing():
    """No pairs, no query — and the assertion is made by handing the function a
    database that cannot answer one."""
    assert await contention_service.verdicts_for_pairs(_NoDatabase(), [], 1) == {}


@pytest.mark.asyncio
async def test_the_batch_and_the_single_form_agree(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """One population, all four outcomes, and the two forms asserted AGAINST
    EACH OTHER rather than separately.

    A1 shipped a count and a list, written three tasks apart, that disagreed
    two ways: each was asserted against its own expectations and neither
    against the other. The four-outcome assertion is what stops this passing
    vacuously over a population that happens to be all `no_project`.

    THE POPULATION IS NOT ALL WELL-FORMED, and that is deliberate. The malformed
    shapes — a cross-tenant project link, an archived one, a booking id that
    resolves to nothing, and another tenant's booking — are precisely the paths
    whose behaviour CHANGED during implementation, so they are the likeliest
    place for the two forms to drift apart. Asserting them only through the
    single form would leave the batch path unchecked on exactly the four cases
    that moved.
    """
    other_tenant, other_admin = await second_tenant_factory()

    high = await _project(db_session, test_tenant.id, "High", rank=1)
    low = await _project(db_session, test_tenant.id, "Low", rank=5)
    same = await _project(db_session, test_tenant.id, "Same", rank=5)
    unranked = await _project(db_session, test_tenant.id, "Unranked", rank=None)
    archived = await _project(
        db_session,
        test_tenant.id,
        "Archived",
        rank=1,
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    theirs = await _project(db_session, other_tenant.id, "Theirs", rank=1)

    b_high = await _booking(db_session, test_tenant.id, test_user.id, project_id=high.id)
    b_low = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=low.id, slot=2
    )
    b_same = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=same.id, slot=3
    )
    b_unranked = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=unranked.id, slot=4
    )
    b_none = await _booking(db_session, test_tenant.id, test_user.id, slot=5)
    b_archived = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=archived.id, slot=6
    )
    b_cross_project = await _booking(
        db_session, test_tenant.id, test_user.id, project_id=theirs.id, slot=7
    )
    b_other_tenant = await _booking(
        db_session, other_tenant.id, other_admin.id, project_id=high.id
    )
    stale_id = (
        max(
            b.id
            for b in (
                b_high, b_low, b_same, b_unranked, b_none,
                b_archived, b_cross_project, b_other_tenant,
            )
        )
        + 10_000
    )

    pairs = [
        (b_high.id, b_low.id),          # ranked
        (b_low.id, b_same.id),          # equal_rank
        (b_high.id, b_unranked.id),     # unranked
        (b_high.id, b_none.id),         # no_project — nothing named
        (b_high.id, b_archived.id),     # no_project — named but archived
        (b_cross_project.id, b_high.id),  # no_project — named in another tenant
        (b_high.id, stale_id),          # no_project — the id resolves to nothing
        (b_other_tenant.id, b_high.id),  # no_project — the BOOKING is not ours
    ]
    batch = await contention_service.verdicts_for_pairs(db_session, pairs, test_tenant.id)

    for pair in pairs:
        single = await contention_service.verdict_for_pair(
            db_session, pair[0], pair[1], test_tenant.id
        )
        assert batch[pair] == single, pair

    assert {verdict.outcome for verdict in batch.values()} == {
        OUTCOME_RANKED,
        OUTCOME_EQUAL_RANK,
        OUTCOME_UNRANKED,
        OUTCOME_NO_PROJECT,
    }
    assert batch[(b_high.id, b_low.id)].winner_booking_id == b_high.id
    # Not merely "some no_project": the batch must reach BOTH of its reasons,
    # or the malformed half of the population is being answered generically.
    assert {
        verdict.reason
        for verdict in batch.values()
        if verdict.outcome == OUTCOME_NO_PROJECT
    } == {REASON_NO_PROJECT, REASON_PROJECT_UNRESOLVABLE}
