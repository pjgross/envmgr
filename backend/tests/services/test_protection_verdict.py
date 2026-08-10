"""Phase 7 B4 — protection as the tie-break in A4's verdict.

RANK STAYS STRICTLY PRIMARY. Protection speaks only where rank cannot
separate the pair. Every test here that asserts a winner must be readable as
"and rank could not decide this".
"""
import pytest

from app.core.protection_levels import PROTECTION_HARD, PROTECTION_SOFT
from app.db.models.booking_request import BookingRequest
from app.services import contention_service as cs
from tests.factories import ensure_environment, make_booking


# (requested_project_id, resolved_project_id, priority_rank, protection_level)
def side(rank=None, project=None, level=PROTECTION_SOFT, requested=None):
    return (requested if requested is not None else project, project, rank, level)


def test_rank_still_decides_and_protection_is_not_consulted():
    """A SOFT booking on a better rank beats a HARD one. If this ever flips,
    B4 has stopped being additive and has reweighted A4."""
    v = cs._decide(
        1, side(rank=1, project=10, level=PROTECTION_SOFT),
        2, side(rank=5, project=20, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_RANKED
    assert v.winner_booking_id == 1
    assert v.reason == "the higher-priority project wins"


def test_equal_rank_is_broken_by_protection():
    v = cs._decide(
        1, side(rank=3, project=10, level=PROTECTION_SOFT),
        2, side(rank=3, project=20, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 2
    assert v.reason == (
        "both projects have the same priority rank; the protected booking holds"
    )


def test_unranked_is_broken_by_protection():
    v = cs._decide(
        1, side(rank=None, project=10, level=PROTECTION_HARD),
        2, side(rank=4, project=20, level=PROTECTION_SOFT),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 1
    assert v.reason == (
        "at least one project has no priority rank; the protected booking holds"
    )


def test_no_project_is_broken_by_protection():
    v = cs._decide(
        1, side(project=None, level=PROTECTION_HARD),
        2, side(project=None, level=PROTECTION_SOFT),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 1
    assert v.reason == (
        "at least one booking is not linked to a project; "
        "the protected booking holds"
    )


def test_an_unresolvable_project_keeps_its_own_reason_when_protection_speaks():
    """A4's second no_project reason exists so a user staring at an archived
    project's name is told the real problem. Composing must not lose it."""
    v = cs._decide(
        1, side(project=None, requested=99, level=PROTECTION_HARD),
        2, side(project=None, level=PROTECTION_SOFT),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 1
    assert v.reason == (
        "at least one booking's project is archived or belongs to another "
        "tenant; the protected booking holds"
    )


@pytest.mark.parametrize(
    "a,b",
    [
        (side(rank=3, project=10), side(rank=3, project=20)),
        (side(rank=None, project=10), side(rank=2, project=20)),
        (side(project=None), side(project=None)),
    ],
)
def test_equal_levels_change_nothing(a, b):
    """THE MIGRATION IS INERT. Every existing row is 'soft', so every pair is
    soft-vs-soft and every verdict is exactly what A4 rendered before B4.

    This is the test that fails if someone later "simplifies" the protection
    branch to fire on equality rather than on difference."""
    v = cs._decide(1, a, 2, b)
    assert v.outcome in (cs.OUTCOME_EQUAL_RANK, cs.OUTCOME_UNRANKED, cs.OUTCOME_NO_PROJECT)
    assert v.winner_booking_id is None
    assert "protected" not in v.reason


def test_an_unknown_level_never_loses():
    """A booking absent from `_ranks_for` — another tenant's, or stale — has a
    level of None, not 'soft'. Defaulting the sentinel to 'soft' is the
    obvious implementation and it silently makes every unresolvable booking
    lose to any hard one."""
    v = cs._decide(
        1, (None, None, None, None),
        2, side(project=None, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_NO_PROJECT
    assert v.winner_booking_id is None


def test_both_hard_has_no_winner():
    v = cs._decide(
        1, side(rank=3, project=10, level=PROTECTION_HARD),
        2, side(rank=3, project=20, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_EQUAL_RANK
    assert v.winner_booking_id is None


async def test_the_batch_sentinel_never_defaults_a_missing_booking_to_soft(
    db_session, test_tenant, test_user
):
    """`_decide` is exercised directly by every other test in this file, but
    `verdicts_for_pairs` keeps its OWN copy of the missing-booking sentinel —
    the one thing here that is not pure Python. A booking id that never
    resolves (deleted, another tenant's, or simply made up) is looked up
    through the real batch path, against a HARD live booking, so a sentinel
    that silently defaulted to PROTECTION_SOFT would make the unresolvable
    side lose an argument it was never actually compared into.
    """
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    live = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
    )
    request = await db_session.get(BookingRequest, live.booking_request_id)
    request.protection_level = PROTECTION_HARD
    await db_session.flush()

    verdict = await cs.verdict_for_pair(
        db_session, live.id, live.id + 10_000, test_tenant.id
    )
    assert verdict.outcome == cs.OUTCOME_NO_PROJECT
    assert verdict.winner_booking_id is None
    assert "protected" not in verdict.reason
