"""B5 Task 9 — the decommission worklist: `GET /decommissions`.

Fixture rows are built directly through the ORM, following
`tests/services/test_decommission_state.py`'s `decommission_fixtures` — the
worklist is a thin SQL query over exactly these rows, so a direct insert
exercises the query the same way the HTTP layer sees it, without going
through every permission gate a `POST .../decommission` would need.

The route takes its own clock (`datetime.now(timezone.utc)`, not injectable),
so every fixture here is built relative to the real clock at fixture-build
time rather than a frozen constant — the same call
`test_contention_api.py`'s worklist tests make.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core.day_boundaries import expiry_boundary
from app.core.pagination import Sort
from app.db.models.environment_decommission import EnvironmentDecommission
from app.services import environment_decommission_service
from tests.factories import ensure_environment, ensure_user


async def _make(db, tenant_id, environment, user, **kw) -> EnvironmentDecommission:
    now = datetime.now(timezone.utc)
    fields = dict(
        tenant_id=tenant_id,
        environment_id=environment.id,
        reason="worklist fixture",
        initiated_by=user.id,
        warned_at=now - timedelta(days=1),
        scheduled_teardown_at=now + timedelta(days=4),
    )
    fields.update(kw)
    row = EnvironmentDecommission(**fields)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


@pytest_asyncio.fixture
async def mixed_decommissions(db_session, test_tenant):
    """One row in each of the five states, plus a second `due` row — six
    total, so `state=due` (2) and the no-selection total (6, `len(...)`) pin
    two independently checkable counts rather than one number that could be
    right by coincidence."""
    now = datetime.now(timezone.utc)
    user = await ensure_user(db_session, test_tenant.id, username="worklist-initiator")
    envs = [
        await ensure_environment(db_session, test_tenant.id, slot=i)
        for i in range(1, 7)
    ]
    rows = [
        await _make(
            db_session, test_tenant.id, envs[0], user,
            scheduled_teardown_at=now + timedelta(days=4),
        ),  # warned
        await _make(
            db_session, test_tenant.id, envs[1], user,
            scheduled_teardown_at=now - timedelta(days=1),
        ),  # due
        await _make(
            db_session, test_tenant.id, envs[2], user,
            scheduled_teardown_at=now - timedelta(days=2),
        ),  # due
        await _make(
            db_session, test_tenant.id, envs[3], user,
            scheduled_teardown_at=now - timedelta(days=1),
            extension_requested_at=now - timedelta(hours=2),
        ),  # extension_requested
        await _make(
            db_session, test_tenant.id, envs[4], user,
            torn_down_at=now - timedelta(hours=1),
        ),  # torn_down
        await _make(
            db_session, test_tenant.id, envs[5], user,
            cancelled_at=now - timedelta(minutes=1),
        ),  # cancelled
    ]
    return rows


@pytest_asyncio.fixture
async def boundary_decommission(db_session, test_tenant):
    """Teardown at exactly today's midnight boundary — `expiry_boundary(now)`
    — the day `decommission_state`'s own tests call WARNED, not DUE. If the
    filter's clock and the render's clock were taken separately, this row
    could be selected by one and rendered by the other."""
    now = datetime.now(timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id, slot=51)
    user = await ensure_user(db_session, test_tenant.id, username="boundary-initiator")
    boundary = expiry_boundary(now)
    return await _make(
        db_session, test_tenant.id, env, user, scheduled_teardown_at=boundary
    )


@pytest_asyncio.fixture
async def same_date_decommissions(db_session, test_tenant):
    """Four rows sharing one `scheduled_teardown_at` — ties are ordinary on
    this column (a batch of environments decommissioned together shares one
    date), so paging across them is where a missing tiebreaker shows up."""
    now = datetime.now(timezone.utc)
    shared_date = now + timedelta(days=10)
    user = await ensure_user(db_session, test_tenant.id, username="tie-initiator")
    rows = []
    for slot in range(61, 65):
        env = await ensure_environment(db_session, test_tenant.id, slot=slot)
        rows.append(
            await _make(
                db_session, test_tenant.id, env, user,
                scheduled_teardown_at=shared_date,
            )
        )
    return rows


@pytest_asyncio.fixture
async def foreign_decommission(db_session, second_tenant_factory):
    other_tenant, other_user = await second_tenant_factory(
        "Decom Worklist Foreign Org", "decom-worklist-foreign-org"
    )
    env = await ensure_environment(db_session, other_tenant.id, slot=901)
    return await _make(db_session, other_tenant.id, env, other_user)


@pytest.mark.asyncio
async def test_the_worklist_filters_by_state_in_sql(client, auth_headers, mixed_decommissions):
    r = await client.get("/api/v1/decommissions?state=due", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "2"
    assert {row["state"] for row in r.json()} == {"due"}


@pytest.mark.asyncio
async def test_no_state_selection_is_an_omitted_key(client, auth_headers, mixed_decommissions):
    """`any` client-side, an OMITTED key on the wire. Never `all` — that is
    buildParams' own sentinel, and A3, A4, B2 and B4 each collided with it."""
    r = await client.get("/api/v1/decommissions", headers=auth_headers)
    assert int(r.headers["X-Total-Count"]) == len(mixed_decommissions)

    refused = await client.get("/api/v1/decommissions?state=all", headers=auth_headers)
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_an_empty_state_is_a_422_not_an_ignored_param(client, auth_headers):
    r = await client.get("/api/v1/decommissions?state=", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_the_rendered_state_matches_the_filter(client, auth_headers, boundary_decommission):
    """ONE CLOCK decides the filter and every rendered state. Taken twice, a row
    whose deadline falls between the two reads is selected as warned and
    rendered as due."""
    r = await client.get("/api/v1/decommissions?state=warned", headers=auth_headers)
    ids = [row["id"] for row in r.json()]
    assert boundary_decommission.id in ids
    row = next(x for x in r.json() if x["id"] == boundary_decommission.id)
    assert row["state"] == "warned"


@pytest.mark.asyncio
async def test_paging_is_stable_across_ties(client, auth_headers, same_date_decommissions):
    """Ordered by a UNIQUE key: without the primary-key tiebreaker LIMIT/OFFSET
    duplicates and drops rows once ties exist, and these all share a date."""
    first = await client.get("/api/v1/decommissions?limit=2&offset=0", headers=auth_headers)
    second = await client.get("/api/v1/decommissions?limit=2&offset=2", headers=auth_headers)
    ids = [r["id"] for r in first.json()] + [r["id"] for r in second.json()]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_an_unknown_sort_is_a_422_not_a_silent_fallback(client, auth_headers):
    r = await client.get("/api/v1/decommissions?sort_by=invented", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_names_travel_with_the_row(client, auth_headers, mixed_decommissions):
    """The environment name, the initiator and the owner resolve server-side —
    a picker fetch would read a capped list and render `—`."""
    row = (await client.get("/api/v1/decommissions", headers=auth_headers)).json()[0]
    assert row["environment_name"]
    assert row["initiated_by_username"]


@pytest.mark.asyncio
async def test_another_tenants_decommissions_are_invisible(client, auth_headers, foreign_decommission):
    r = await client.get("/api/v1/decommissions", headers=auth_headers)
    assert foreign_decommission.id not in [row["id"] for row in r.json()]


@pytest.mark.asyncio
async def test_a_soft_deleted_decommission_never_appears(
    client, auth_headers, db_session, test_tenant
):
    """`state_predicate` DELIBERATELY DOES NOT FILTER `deleted_at` — only
    `live_predicate` does — so the worklist query must AND an explicit
    `deleted_at IS NULL` itself, the thing Task 4's reviewer flagged this task
    would trip over. Nothing writes this column today, but the guard must
    hold regardless — the house soft-delete convention applies to every
    tenant-scoped table."""
    env = await ensure_environment(db_session, test_tenant.id, slot=41)
    user = await ensure_user(db_session, test_tenant.id, username="soft-delete-initiator")
    row = await _make(db_session, test_tenant.id, env, user)
    row.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    r = await client.get("/api/v1/decommissions", headers=auth_headers)
    assert row.id not in [x["id"] for x in r.json()]
    assert int(r.headers["X-Total-Count"]) == 0


def test_the_worklist_orders_by_a_unique_key():
    """A STRUCTURAL ASSERTION, deliberately — the health-history precedent.

    Discrimination-proof (c) found this could NOT be caught behaviourally on
    this fixture set: `test_paging_is_stable_across_ties` stayed green, five
    runs in a row on SQLite, with `.order_by(EnvironmentDecommission.id)`
    removed from `worklist_query` — the same shape
    `test_contention_escalation.py::test_the_worklist_orders_by_a_unique_key`
    already recorded for the sibling worklist. `apply_sort`'s tiebreaker is
    the documented exception to this repo's don't-assert-emitted-SQL rule,
    checked against the SERVICE'S OWN query rather than one rebuilt here —
    rebuilding it would assert only that the test wrote a tiebreaker.
    """
    now = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)
    compiled = str(
        environment_decommission_service.worklist_query(
            1,
            now=now,
            sort=Sort(
                column=environment_decommission_service.DECOMMISSION_SORTS[
                    "scheduled_teardown_at"
                ],
                descending=False,
            ),
        )
    )
    assert "ORDER BY" in compiled
    assert compiled.rstrip().endswith("environment_decommission.id"), (
        "the ORDER BY must END in a unique key, after whatever apply_sort added"
    )
    # And the sort itself is still in front of it — chained AFTER apply_sort,
    # never instead of it.
    assert "scheduled_teardown_at" in compiled.split("ORDER BY", 1)[1]
