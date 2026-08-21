"""Phase 9 C4 Task 4 — rollback rehearsals: computed freshness, the batch
"latest per system" lookup, and the tenant filter on both.

Covers: A DEADLINE IS A DAY (current all through its final day, stale the day
after), naive-vs-aware datetimes not raising, "latest per system" picking the
newest row by (rehearsed_at, id), and that the tenant filter on the batch
lookup is load-bearing, not incidental — proven by mutation.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.db.models.rollback import RollbackRehearsal
from app.db.models.system import System
from app.services.rollback_rehearsal_service import rehearsal_state


def _r(rehearsed_at):
    return RollbackRehearsal(
        tenant_id=1, system_id=1, rehearsed_at=rehearsed_at,
        rehearsed_by_user_id=1, outcome="passed",
    )


def test_a_rehearsal_is_current_all_through_its_final_day():
    """A DEADLINE IS A DAY. At instant precision a rehearsal recorded at 15:00
    would expire mid-afternoon on its last day — the bug A4 shipped, B2
    inherited and C2's waiver expiry had to avoid."""
    rehearsed = datetime(2026, 5, 23, 15, 0, tzinfo=timezone.utc)  # 90 days before 21 Aug
    last_day_early = datetime(2026, 8, 21, 0, 1, tzinfo=timezone.utc)
    last_day_late = datetime(2026, 8, 21, 23, 59, tzinfo=timezone.utc)

    assert rehearsal_state(_r(rehearsed), 90, last_day_early) == "current"
    assert rehearsal_state(_r(rehearsed), 90, last_day_late) == "current"


def test_a_rehearsal_is_stale_the_day_after():
    rehearsed = datetime(2026, 5, 23, 15, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc)
    assert rehearsal_state(_r(rehearsed), 90, next_day) == "stale"


def test_a_naive_timestamp_does_not_raise():
    """SQLite returns naive datetimes where PostgreSQL returns aware ones, and
    comparing the two is a TypeError — an engine-dependent 500 invisible on the
    PostgreSQL leg."""
    naive = datetime(2026, 8, 20, 12, 0)
    assert rehearsal_state(_r(naive), 90, datetime(2026, 8, 21, 0, 1, tzinfo=timezone.utc)) == "current"


# ── Shared fixtures ───────────────────────────────────────────────────────
#
# NOT the global `system` fixture from conftest.py — that one is built
# against the `tenant` fixture ("Phase3 Org"), a DIFFERENT tenant from
# `test_tenant` ("Test Org"). Combining it with `test_tenant`/`test_user`
# would make record_rehearsal's own tenant check 404 immediately, not because
# of a bug here but because the fixtures would name two different tenants.
# Same shadowing test_rollback_plan.py and its HTTP twin already do for this
# exact reason.

@pytest_asyncio.fixture
async def system(db_session, test_tenant) -> System:
    s = System(tenant_id=test_tenant.id, name="Payments API")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.mark.asyncio
async def test_the_latest_rehearsal_per_system_is_returned(
    db_session, test_tenant, test_user, system
):
    from app.services import rollback_rehearsal_service
    from app.api.v1.schemas.rollback import RehearsalCreate

    older = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        outcome="failed"),
    )
    newer = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                        outcome="passed"),
    )
    await db_session.flush()

    latest = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db_session, test_tenant.id, [system.id]
    )
    assert latest[system.id].id == newer.id, "history accumulates; the latest is current"
    assert older.id != newer.id


@pytest.mark.asyncio
async def test_a_tied_rehearsed_at_breaks_on_id_descending(
    db_session, test_tenant, test_user, system
):
    """rehearsed_at is caller-supplied, so ties are ordinary. The id
    tiebreaker (not insertion order, not database default ordering) is what
    makes "latest" deterministic."""
    from app.services import rollback_rehearsal_service
    from app.api.v1.schemas.rollback import RehearsalCreate

    same_instant = datetime(2026, 3, 1, tzinfo=timezone.utc)
    first = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=same_instant, outcome="partial"),
    )
    second = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=same_instant, outcome="passed"),
    )
    await db_session.flush()
    assert second.id > first.id

    latest = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db_session, test_tenant.id, [system.id]
    )
    assert latest[system.id].id == second.id


@pytest.mark.asyncio
async def test_record_rehearsal_404s_for_a_system_in_another_tenant(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """record_rehearsal's tenant check is input validation on the FK, not a
    gate-state rule — a system belonging to another tenant must read as
    not-found, the same way rollback_plan_service's release check does."""
    from app.services import rollback_rehearsal_service
    from app.api.v1.schemas.rollback import RehearsalCreate

    other_tenant, _other_admin = await second_tenant_factory("Other Org", "other-org-rehearsal")
    other_system = System(tenant_id=other_tenant.id, name="Other Org System")
    db_session.add(other_system)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await rollback_rehearsal_service.record_rehearsal(
            db_session, other_system.id, test_tenant.id, test_user.id,
            RehearsalCreate(rehearsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            outcome="passed"),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_latest_rehearsals_for_systems_does_not_leak_across_tenants(
    db_session, test_tenant, test_user, system, second_tenant_factory
):
    """The batch lookup is called with the CALLER's tenant_id, and must not
    return a rehearsal for a system_id that happens to belong to a different
    tenant — even though that system_id is explicitly present in the
    requested list, which is what makes this fixture non-vacuous: without the
    tenant_id filter, the other tenant's row genuinely would come back keyed
    under its own (distinct, real) system_id.
    """
    from app.services import rollback_rehearsal_service
    from app.api.v1.schemas.rollback import RehearsalCreate

    other_tenant, other_admin = await second_tenant_factory("Other Org", "other-org-rehearsal-2")
    other_system = System(tenant_id=other_tenant.id, name="Other Org System")
    db_session.add(other_system)
    await db_session.flush()

    await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 4, 1, tzinfo=timezone.utc), outcome="passed"),
    )
    await rollback_rehearsal_service.record_rehearsal(
        db_session, other_system.id, other_tenant.id, other_admin.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 4, 1, tzinfo=timezone.utc), outcome="passed"),
    )
    await db_session.flush()

    # test_tenant's caller asks for BOTH system ids — including the other
    # tenant's. The correct answer names only its own.
    latest = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db_session, test_tenant.id, [system.id, other_system.id]
    )
    assert set(latest.keys()) == {system.id}


@pytest.mark.asyncio
async def test_a_failed_rehearsal_is_recorded_faithfully_and_not_dropped(
    db_session, test_tenant, test_user, system
):
    """A failed rehearsal is still a rehearsal that happened — it must appear
    in history and in the batch lookup exactly like any other outcome. Task 5
    decides whether it counts as current for readiness; this layer never
    filters it out."""
    from app.services import rollback_rehearsal_service
    from app.api.v1.schemas.rollback import RehearsalCreate

    failed = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 7, 1, tzinfo=timezone.utc), outcome="failed"),
    )
    await db_session.flush()

    history = await rollback_rehearsal_service.list_rehearsals(db_session, system.id, test_tenant.id)
    assert [r.id for r in history] == [failed.id]
    assert history[0].outcome == "failed"

    latest = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db_session, test_tenant.id, [system.id]
    )
    assert latest[system.id].id == failed.id
