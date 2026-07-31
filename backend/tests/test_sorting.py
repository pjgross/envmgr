"""Server-side sorting: the whitelist, and that it composes with the tiebreaker.

The whitelist is the security boundary — `sort_by` is a client string and must
never reach the query as a column name. And a sort column is almost never
unique, so the sort must PRECEDE the existing primary-key tiebreaker rather
than replace it; sub-project A showed that dropping a tiebreaker breaks paging
deterministically on PostgreSQL.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1 import builds as builds_api
from app.api.v1 import deployments as deployments_api
from app.core.pagination import TOTAL_COUNT_HEADER, Page, Sort, apply_sort, fetch_page, sorting
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.build import Build
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
from app.db.models.incident import Incident
from app.db.models.infrastructure_component import InfrastructureComponent
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.system import System
from app.services import (
    booking_service,
    change_request_service,
    incident_service,
    infrastructure_component_service,
    release_service,
    system_service,
)
from tests.conftest import IS_POSTGRES
from tests.factories import (
    ensure_booking_type,
    ensure_build,
    ensure_change_request,
    ensure_environment,
    ensure_user,
)

ALLOWED = {"name": Environment.name, "created_at": Environment.created_at}


def _probe_app():
    probe = FastAPI()

    @probe.get("/probe")
    async def _probe(sort: Sort = Depends(sorting(ALLOWED, default="name"))):
        return {"column": str(sort.column.key), "descending": sort.descending}

    return probe


@pytest.mark.asyncio
async def test_default_is_used_when_no_sort_requested():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {"column": "name", "descending": False}


@pytest.mark.asyncio
async def test_requested_field_and_direction_are_honoured():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        body = (await ac.get("/probe?sort_by=created_at&sort_dir=desc")).json()
        assert body == {"column": "created_at", "descending": True}


@pytest.mark.asyncio
async def test_unknown_field_is_422_not_a_silent_default():
    """A client that asked for a sort it did not get is worse off than one
    told its request was impossible."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe?sort_by=nonexistent")).status_code == 422


@pytest.mark.asyncio
async def test_injection_shaped_input_is_rejected_by_the_whitelist():
    """Not escaped downstream — rejected outright, because nothing interpolates."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        hostile = "name; DROP TABLE environment--"
        assert (await ac.get(f"/probe?sort_by={hostile}")).status_code == 422


@pytest.mark.asyncio
async def test_bad_direction_is_422():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe?sort_dir=sideways")).status_code == 422


# ── default_dir: an endpoint may declare its own default direction ───────────
# (incidents/change-requests pre-date sorting() and always defaulted to
# newest-first; sorting() must be able to preserve that instead of forcing
# every adopter back to ascending.)


def _probe_app_desc_default():
    probe = FastAPI()

    @probe.get("/probe")
    async def _probe(
        sort: Sort = Depends(sorting(ALLOWED, default="created_at", default_dir="desc"))
    ):
        return {"column": str(sort.column.key), "descending": sort.descending}

    return probe


@pytest.mark.asyncio
async def test_default_dir_is_honoured_when_no_sort_dir_requested():
    """No sort_dir at all: falls back to the endpoint's declared default_dir,
    not a hardcoded 'asc'. If this regressed to always-ascending, an endpoint
    like incidents that has always defaulted to newest-first would silently
    flip its default page order the moment it adopted sorting()."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app_desc_default()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {
            "column": "created_at",
            "descending": True,
        }


@pytest.mark.asyncio
async def test_explicit_sort_dir_overrides_default_dir():
    """A client-supplied sort_dir always wins over default_dir, whatever field
    is requested."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app_desc_default()), base_url="http://probe"
    ) as ac:
        body = (await ac.get("/probe?sort_by=name&sort_dir=asc")).json()
        assert body == {"column": "name", "descending": False}


@pytest.mark.asyncio
async def test_default_dir_defaults_to_asc_for_existing_callers():
    """Task 2's endpoints call sorting(...) without default_dir at all — this
    pins that omission still means ascending, so they keep working unchanged."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json()["descending"] is False


# ── apply_sort composes with, and does not replace, the tiebreaker ───────────


@pytest.mark.asyncio
async def test_apply_sort_precedes_the_tiebreaker_in_the_emitted_sql(test_tenant):
    """The engine-independent half of the guard.

    The paging walk below only discriminates on PostgreSQL, so this asserts the
    property structurally: the requested sort key comes first, the unique
    tiebreaker stays last. If apply_sort ever replaced the ordering instead of
    prepending to it, this fails on any engine.
    """
    from sqlalchemy.dialects import postgresql

    query = apply_sort(
        select(Environment).where(Environment.tenant_id == test_tenant.id),
        Sort(column=Environment.name, descending=False),
    ).order_by(Environment.id)

    compiled = str(query.compile(dialect=postgresql.dialect()))
    assert "ORDER BY" in compiled
    order_by = compiled.split("ORDER BY", 1)[1].strip()

    assert order_by.startswith("environment.name")
    assert order_by.rstrip().endswith("environment.id")


@pytest.mark.asyncio
async def test_apply_sort_descending_still_precedes_the_tiebreaker(test_tenant):
    """Same structural guard, descending direction."""
    from sqlalchemy.dialects import postgresql

    query = apply_sort(
        select(Environment).where(Environment.tenant_id == test_tenant.id),
        Sort(column=Environment.name, descending=True),
    ).order_by(Environment.id)

    compiled = str(query.compile(dialect=postgresql.dialect()))
    assert "ORDER BY" in compiled
    order_by = compiled.split("ORDER BY", 1)[1].strip()

    assert order_by.startswith("environment.name DESC")
    assert order_by.rstrip().endswith("environment.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_paging_a_sorted_query_over_ties_sees_each_row_once(db_session, test_tenant):
    """Every row shares a name, so the sort column alone leaves 25 ties. If
    apply_sort replaced the tiebreaker instead of preceding it, rows would
    duplicate and vanish across pages."""
    created = []
    for _ in range(25):
        env = Environment(
            tenant_id=test_tenant.id, name="identical", environment_type="SIT"
        )
        created.append(env)
        db_session.add(env)
    await db_session.flush()

    query = apply_sort(
        select(Environment).where(Environment.tenant_id == test_tenant.id),
        Sort(column=Environment.name, descending=False),
    ).order_by(Environment.id)

    seen, offset = [], 0
    while True:
        rows, total = await fetch_page(db_session, query, Page(limit=6, offset=offset))
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# ── Part A: NULL ordering must agree across engines ──────────────────────────
#
# Measured directly: sorting a nullable column ASC puts NULL first on SQLite
# and last on PostgreSQL (DESC is the mirror). apply_sort now pins NULLS LAST
# on ASC / NULLS FIRST on DESC explicitly, so both engines agree. This is the
# one place in C1 where a green SQLite run genuinely cannot substitute for
# PostgreSQL — every test below must be run against both.
#
# This deliberately CHANGES today's ordering behaviour for these columns on
# whichever engine previously disagreed with "NULLs sort after values" — see
# the report for the was/now table.


async def _assert_null_pinned(db_session, tenant_id, model, column, low, high, null):
    """`low`/`high` are two rows with real, ordered values; `null` has NULL in
    `column`. Confirms ASC puts NULL last and DESC puts NULL first, for both
    the requested column's ORDER BY and the underlying stored rows."""
    base = select(model).where(model.tenant_id == tenant_id, model.id.in_(
        [low.id, high.id, null.id]
    ))

    asc_rows = (
        await db_session.execute(apply_sort(base, Sort(column=column, descending=False)))
    ).scalars().all()
    assert [r.id for r in asc_rows] == [low.id, high.id, null.id], (
        "ASC must sort real values first and pin NULL last on both engines"
    )

    desc_rows = (
        await db_session.execute(apply_sort(base, Sort(column=column, descending=True)))
    ).scalars().all()
    assert [r.id for r in desc_rows] == [null.id, high.id, low.id], (
        "DESC must pin NULL first and sort real values after it on both engines"
    )


@pytest.mark.asyncio
async def test_null_pinning_is_deterministic_for_deployment_deployer_name(
    db_session, test_tenant
):
    build = await ensure_build(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)
    deployed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def _deployment(deployer_name):
        d = Deployment(
            tenant_id=test_tenant.id,
            build_id=build.id,
            environment_id=env.id,
            change_request_id=cr.id,
            event_id=str(uuid.uuid4()),
            deployer_name=deployer_name,
            status="succeeded",
            deployed_at=deployed_at,
        )
        db_session.add(d)
        return d

    low = _deployment("alice")
    high = _deployment("bob")
    null = _deployment(None)
    await db_session.flush()

    await _assert_null_pinned(
        db_session, test_tenant.id, Deployment, Deployment.deployer_name, low, high, null
    )


@pytest.mark.asyncio
async def test_null_pinning_is_deterministic_for_release_target_date(
    db_session, test_tenant
):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="null-order-lifecycle",
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    user = await ensure_user(db_session, test_tenant.id)

    def _release(name, target_date):
        r = Release(
            tenant_id=test_tenant.id,
            name=name,
            release_type="major",
            release_kind="project",
            lifecycle_template_id=tpl.id,
            status="draft",
            raised_by=user.id,
            target_date=target_date,
        )
        db_session.add(r)
        return r

    low = _release("null-order-low", datetime(2026, 6, 1, tzinfo=timezone.utc))
    high = _release("null-order-high", datetime(2026, 7, 1, tzinfo=timezone.utc))
    null = _release("null-order-null", None)
    await db_session.flush()

    await _assert_null_pinned(
        db_session, test_tenant.id, Release, Release.target_date, low, high, null
    )


@pytest.mark.asyncio
async def test_null_pinning_is_deterministic_for_incident_resolved_at(
    db_session, test_tenant
):
    detected_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    def _incident(title, resolved_at):
        inc = Incident(
            tenant_id=test_tenant.id,
            title=title,
            severity="P3",
            status="open",
            detected_at=detected_at,
            resolved_at=resolved_at,
        )
        db_session.add(inc)
        return inc

    low = _incident("null-order-low", datetime(2026, 2, 2, tzinfo=timezone.utc))
    high = _incident("null-order-high", datetime(2026, 2, 3, tzinfo=timezone.utc))
    null = _incident("null-order-null", None)
    await db_session.flush()

    await _assert_null_pinned(
        db_session, test_tenant.id, Incident, Incident.resolved_at, low, high, null
    )


@pytest.mark.asyncio
async def test_null_pinning_is_deterministic_for_infrastructure_component_provider(
    db_session, test_tenant
):
    def _component(name, provider):
        c = InfrastructureComponent(tenant_id=test_tenant.id, name=name, provider=provider)
        db_session.add(c)
        return c

    low = _component("null-order-low", "aws")
    high = _component("null-order-high", "gcp")
    null = _component("null-order-null", None)
    await db_session.flush()

    await _assert_null_pinned(
        db_session,
        test_tenant.id,
        InfrastructureComponent,
        InfrastructureComponent.provider,
        low,
        high,
        null,
    )


@pytest.mark.asyncio
async def test_null_pinning_is_deterministic_for_infrastructure_component_region(
    db_session, test_tenant
):
    def _component(name, region):
        c = InfrastructureComponent(tenant_id=test_tenant.id, name=name, region=region)
        db_session.add(c)
        return c

    low = _component("null-order-low", "us-east")
    high = _component("null-order-high", "us-west")
    null = _component("null-order-null", None)
    await db_session.flush()

    await _assert_null_pinned(
        db_session,
        test_tenant.id,
        InfrastructureComponent,
        InfrastructureComponent.region,
        low,
        high,
        null,
    )


# ── Part B: sort-aware tie paging per endpoint ────────────────────────────────
#
# The environments test above (Task 1) proved the primitive composes with a
# tiebreaker in isolation. This proves it per real endpoint — the case where a
# sort could silently replace the tiebreaker in that endpoint's own service
# code rather than precede it, which the primitive-level test cannot catch.
#
# Each endpoint gets two assertions:
#   1. A structural one, engine-independent: compile the REAL query the
#      service builds (captured off db.execute, not reconstructed by hand —
#      see `_spy_on_execute`) and confirm the requested sort key comes first
#      and the unique tiebreaker comes last.
#   2. The seed-and-walk one, which only discriminates on PostgreSQL — see the
#      skip reason on every occurrence below — kept because it is the
#      end-to-end proof the structural check cannot give by itself.


def _spy_on_execute(db_session):
    """Wrap `db_session.execute` to record every statement passed through it.

    Lets a test call the real service function and inspect the query it
    actually built, instead of reconstructing the query by hand — so a
    mutation to the service's ordering (Step 3) shows up here too, which a
    hand-built query never would.
    """
    original = db_session.execute
    captured: list = []

    async def _spy(stmt, *args, **kwargs):
        captured.append(stmt)
        return await original(stmt, *args, **kwargs)

    db_session.execute = _spy
    return captured


def _query_with_order_by(captured) -> str:
    """The one captured statement whose compiled SQL carries an ORDER BY.

    `fetch_page`/`fetch_page_rows` issue the windowed row query and a separate
    COUNT query (which explicitly strips ordering); `release_service` builds
    its own COUNT statement by hand. Either way exactly one captured statement
    has the ORDER BY under test.
    """
    hits = [
        str(stmt.compile(dialect=postgresql.dialect()))
        for stmt in captured
        if "ORDER BY" in str(stmt.compile(dialect=postgresql.dialect()))
    ]
    assert len(hits) == 1, f"expected exactly one ORDER BY-bearing query, got {len(hits)}"
    return hits[0]


def _order_by_clause(compiled: str) -> str:
    """The ORDER BY clause in isolation, with any trailing LIMIT/OFFSET
    stripped — several of these endpoints always paginate (release_service's
    `limit`/`offset` default to real ints, not an Optional Page), so the
    captured statement's ORDER BY is not the last thing in it."""
    clause = compiled.split("ORDER BY", 1)[1]
    clause = clause.split("LIMIT", 1)[0]
    return clause.strip()


# -- systems -------------------------------------------------------------


async def _tied_systems(db_session, tenant_id, count=25):
    created = [System(tenant_id=tenant_id, name="identical") for _ in range(count)]
    db_session.add_all(created)
    await db_session.flush()
    return created


@pytest.mark.asyncio
async def test_systems_sort_precedes_the_tiebreaker_in_the_emitted_sql(db_session, test_tenant):
    """The service's hardcoded tail is `.order_by(System.name, System.id)` — an
    implicit-ASC lead on the same column apply_sort would default to. Request
    DESC instead so only apply_sort, not the tail, could have produced the
    leading token; see the guard-proof in the C1 final-fixes report."""
    captured = _spy_on_execute(db_session)
    await system_service.list_systems(
        db_session, test_tenant.id, sort=Sort(column=System.name, descending=True)
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("system.name DESC NULLS FIRST")
    assert order_by.rstrip().endswith("system.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_systems_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant
):
    await _tied_systems(db_session, test_tenant.id, 25)
    sort = Sort(column=System.name, descending=False)

    seen, offset = [], 0
    while True:
        rows, total = await system_service.list_systems(
            db_session, test_tenant.id, page=Page(limit=6, offset=offset), sort=sort
        )
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- incidents -------------------------------------------------------------


async def _tied_incidents(db_session, tenant_id, count=25):
    detected_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    created = [
        Incident(
            tenant_id=tenant_id,
            title=f"tie-{i}",
            severity="P3",
            status="open",
            detected_at=detected_at,
        )
        for i in range(count)
    ]
    db_session.add_all(created)
    await db_session.flush()
    return created


@pytest.mark.asyncio
async def test_incidents_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant
):
    """The service's hardcoded tail is `.order_by(Incident.detected_at.desc(),
    Incident.id)`. Request ASC — the leading token's direction and NULLS
    placement then only match if apply_sort actually ran."""
    captured = _spy_on_execute(db_session)
    await incident_service.list_incidents(
        db_session,
        test_tenant.id,
        {},
        sort=Sort(column=Incident.detected_at, descending=False),
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("incident.detected_at ASC NULLS LAST")
    assert order_by.rstrip().endswith("incident.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_incidents_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant
):
    await _tied_incidents(db_session, test_tenant.id, 25)
    # detected_at is also the service's pre-existing tiebreaker-chain column
    # (`.order_by(Incident.detected_at.desc(), Incident.id)`), so tying on it
    # alone ties the whole chain except `id` — the only thing left to page by.
    sort = Sort(column=Incident.detected_at, descending=False)

    seen, offset = [], 0
    while True:
        rows, total = await incident_service.list_incidents(
            db_session, test_tenant.id, {}, page=Page(limit=6, offset=offset), sort=sort
        )
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- change requests -------------------------------------------------------------


async def _tied_change_requests(db_session, tenant_id, count=25):
    created = []
    for i in range(count):
        cr = await ensure_change_request(db_session, tenant_id, title=f"tie-cr-{i}")
        created.append(cr)
    return created


@pytest.mark.asyncio
async def test_change_requests_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant
):
    """The service's hardcoded tail is
    `.order_by(ChangeRequest.scheduled_start.desc(), ChangeRequest.id)`. Request
    ASC — the leading token's direction and NULLS placement then only match if
    apply_sort actually ran."""
    captured = _spy_on_execute(db_session)
    await change_request_service.list_change_requests(
        db_session,
        test_tenant.id,
        sort=Sort(column=ChangeRequest.scheduled_start, descending=False),
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("change_request.scheduled_start ASC NULLS LAST")
    assert order_by.rstrip().endswith("change_request.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_change_requests_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant
):
    await _tied_change_requests(db_session, test_tenant.id, 25)
    # ensure_change_request hardcodes the same scheduled_start for every row,
    # which is also the service's tiebreaker-chain column, so tying on it ties
    # the whole chain except `id`.
    sort = Sort(column=ChangeRequest.scheduled_start, descending=False)

    seen, offset = [], 0
    while True:
        rows, total = await change_request_service.list_change_requests(
            db_session, test_tenant.id, page=Page(limit=6, offset=offset), sort=sort
        )
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- bookings -------------------------------------------------------------


async def _tied_bookings(db_session, tenant_id, count=25):
    env = await ensure_environment(db_session, tenant_id)
    booking_type = await ensure_booking_type(db_session, tenant_id)
    user = await ensure_user(db_session, tenant_id)
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    created = []
    for i in range(count):
        req = BookingRequest(
            tenant_id=tenant_id,
            project_name=f"tie-{i}",
            booking_type_id=booking_type.id,
            start_date=start,
            end_date=end,
            booked_by=user.id,
        )
        db_session.add(req)
        await db_session.flush()
        booking = Booking(
            tenant_id=tenant_id,
            environment_id=env.id,
            start_date=start,
            end_date=end,
            booking_request_id=req.id,
        )
        db_session.add(booking)
        created.append(booking)
    await db_session.flush()
    return created


@pytest.mark.asyncio
async def test_bookings_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant
):
    """The service's hardcoded tail is `.order_by(Booking.start_date.asc(),
    Booking.id)` — the same column AND direction apply_sort would default to.
    Request DESC instead so only apply_sort could have produced the leading
    token; see the guard-proof in the C1 final-fixes report."""
    captured = _spy_on_execute(db_session)
    await booking_service.list_bookings(
        db_session, test_tenant.id, sort=Sort(column=Booking.start_date, descending=True)
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("booking.start_date DESC NULLS FIRST")
    assert order_by.rstrip().endswith("booking.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_bookings_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant
):
    await _tied_bookings(db_session, test_tenant.id, 25)
    # start_date is shared by every row here and is also the service's
    # tiebreaker-chain column, so tying on it ties the whole chain except `id`.
    sort = Sort(column=Booking.start_date, descending=False)

    seen, offset = [], 0
    while True:
        rows, total = await booking_service.list_bookings(
            db_session, test_tenant.id, page=Page(limit=6, offset=offset), sort=sort
        )
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- releases -------------------------------------------------------------


async def _tied_releases(db_session, tenant_id, count=25):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="tie-lifecycle",
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    user = await ensure_user(db_session, tenant_id)
    created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)

    created = []
    for i in range(count):
        r = Release(
            tenant_id=tenant_id,
            name=f"tie-{i}",
            release_type="major",
            release_kind="project",
            lifecycle_template_id=tpl.id,
            status="draft",
            raised_by=user.id,
            created_at=created_at,
        )
        db_session.add(r)
        created.append(r)
    await db_session.flush()
    return created


@pytest.mark.asyncio
async def test_releases_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant
):
    """The service's hardcoded tail is `.order_by(Release.created_at.desc(),
    Release.id)`. Request ASC — the leading token's direction and NULLS
    placement then only match if apply_sort actually ran."""
    captured = _spy_on_execute(db_session)
    await release_service.list_releases(
        db_session, test_tenant.id, sort=Sort(column=Release.created_at, descending=False)
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("release.created_at ASC NULLS LAST")
    assert order_by.rstrip().endswith("release.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_releases_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant
):
    await _tied_releases(db_session, test_tenant.id, 25)
    # created_at is forced identical above and is also the service's
    # tiebreaker-chain column, so tying on it ties the whole chain except `id`.
    sort = Sort(column=Release.created_at, descending=False)

    seen, offset = [], 0
    while True:
        rows, total = await release_service.list_releases(
            db_session, test_tenant.id, limit=6, offset=offset, sort=sort
        )
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- infrastructure components -------------------------------------------------------------


async def _tied_infrastructure_components(db_session, tenant_id, count=25):
    # `(tenant_id, name)` is UNIQUE on this table (uq_infra_component_tenant_name),
    # so — unlike every other endpoint here — names cannot tie. Sort on
    # `provider` instead, which every row below shares. NOTE: because `name`
    # (unique per tenant) is the service's pre-existing secondary sort key
    # (`.order_by(InfrastructureComponent.name, InfrastructureComponent.id)`),
    # it already fully disambiguates rows on its own — so unlike the other
    # eight endpoints, this walk cannot demonstrate that dropping the `id`
    # tiebreaker causes duplicate/missing rows; see the report.
    created = [
        InfrastructureComponent(tenant_id=tenant_id, name=f"tie-{i}", provider="aws")
        for i in range(count)
    ]
    db_session.add_all(created)
    await db_session.flush()
    return created


@pytest.mark.asyncio
async def test_infrastructure_components_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant
):
    """The service's hardcoded tail is
    `.order_by(InfrastructureComponent.name, InfrastructureComponent.id)` — an
    implicit-ASC lead on the same column apply_sort would default to. Request
    DESC instead so only apply_sort, not the tail, could have produced the
    leading token; see the guard-proof in the C1 final-fixes report."""
    captured = _spy_on_execute(db_session)
    await infrastructure_component_service.list_infrastructure_components(
        db_session,
        test_tenant.id,
        sort=Sort(column=InfrastructureComponent.name, descending=True),
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("infrastructure_component.name DESC NULLS FIRST")
    assert order_by.rstrip().endswith("infrastructure_component.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_infrastructure_components_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant
):
    await _tied_infrastructure_components(db_session, test_tenant.id, 25)
    sort = Sort(column=InfrastructureComponent.provider, descending=False)

    seen, offset = [], 0
    while True:
        rows, total = await infrastructure_component_service.list_infrastructure_components(
            db_session, test_tenant.id, page=Page(limit=6, offset=offset), sort=sort
        )
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- builds -------------------------------------------------------------
#
# builds and deployments build their query directly in the API layer, not a
# service module — call the route function itself, bypassing FastAPI's
# Depends() resolution by passing Page/Sort/db/current_user straight in.


async def _tied_builds(db_session, tenant_id, count=25):
    # ensure_build always uses the same fixed commit_timestamp, which is also
    # the service's tiebreaker-chain column, so 25 calls already tie on it.
    return [await ensure_build(db_session, tenant_id) for _ in range(count)]


@pytest.mark.asyncio
async def test_builds_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant, test_user
):
    """The endpoint's hardcoded tail is `.order_by(Build.commit_timestamp.desc(),
    Build.id)`. Request ASC — the leading token's direction and NULLS placement
    then only match if apply_sort actually ran."""
    test_user.active_tenant_id = test_user.tenant_id
    captured = _spy_on_execute(db_session)
    await builds_api.list_builds(
        response=Response(),
        subsystem_id=None,
        release_id=None,
        branch=None,
        date_from=None,
        date_to=None,
        subsystem_search=None,
        page=Page(limit=500, offset=0),
        sort=Sort(column=Build.commit_timestamp, descending=False),
        db=db_session,
        current_user=test_user,
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("build.commit_timestamp ASC NULLS LAST")
    assert order_by.rstrip().endswith("build.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_builds_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant, test_user
):
    test_user.active_tenant_id = test_user.tenant_id
    await _tied_builds(db_session, test_tenant.id, 25)
    sort = Sort(column=Build.commit_timestamp, descending=False)

    # list_builds is a route handler: it returns a bare list[BuildRead] (no
    # client change required by sub-project A) and advertises the unwindowed
    # total via the response header instead of a return-value tuple.
    seen, offset = [], 0
    while True:
        response = Response()
        rows = await builds_api.list_builds(
            response=response,
            subsystem_id=None,
            release_id=None,
            branch=None,
            date_from=None,
            date_to=None,
            subsystem_search=None,
            page=Page(limit=6, offset=offset),
            sort=sort,
            db=db_session,
            current_user=test_user,
        )
        assert int(response.headers[TOTAL_COUNT_HEADER]) == 25
        if not rows:
            break
        seen.extend(b.id for b in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"


# -- deployments -------------------------------------------------------------


async def _tied_deployments(db_session, tenant_id, count=25):
    build = await ensure_build(db_session, tenant_id)
    env = await ensure_environment(db_session, tenant_id)
    cr = await ensure_change_request(db_session, tenant_id)
    deployed_at = datetime(2026, 5, 1, tzinfo=timezone.utc)

    created = []
    for _ in range(count):
        d = Deployment(
            tenant_id=tenant_id,
            build_id=build.id,
            environment_id=env.id,
            change_request_id=cr.id,
            event_id=str(uuid.uuid4()),
            status="succeeded",
            deployed_at=deployed_at,
        )
        db_session.add(d)
        created.append(d)
    await db_session.flush()
    return created


@pytest.mark.asyncio
async def test_deployments_sort_precedes_the_tiebreaker_in_the_emitted_sql(
    db_session, test_tenant, test_user
):
    """The endpoint's hardcoded tail is `.order_by(Deployment.deployed_at.desc(),
    Deployment.id)`. Request ASC — the leading token's direction and NULLS
    placement then only match if apply_sort actually ran."""
    test_user.active_tenant_id = test_user.tenant_id
    captured = _spy_on_execute(db_session)
    await deployments_api.list_deployments(
        response=Response(),
        environment_id=None,
        release_id=None,
        build_id=None,
        status_filter=None,
        date_from=None,
        date_to=None,
        environment_search=None,
        release_search=None,
        page=Page(limit=500, offset=0),
        sort=Sort(column=Deployment.deployed_at, descending=False),
        db=db_session,
        current_user=test_user,
    )
    order_by = _order_by_clause(_query_with_order_by(captured))
    assert order_by.startswith("deployment.deployed_at ASC NULLS LAST")
    assert order_by.rstrip().endswith("deployment.id")


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite returns rows in stable rowid order regardless of ORDER BY, so this "
    "walk passes even with no ordering at all — it only discriminates on PostgreSQL",
)
@pytest.mark.asyncio
async def test_deployments_paging_a_sorted_query_over_ties_sees_each_row_once(
    db_session, test_tenant, test_user
):
    test_user.active_tenant_id = test_user.tenant_id
    await _tied_deployments(db_session, test_tenant.id, 25)
    sort = Sort(column=Deployment.deployed_at, descending=False)

    # list_deployments is a route handler: it returns a bare list[DeploymentRead]
    # and advertises the unwindowed total via the response header, not a
    # return-value tuple.
    seen, offset = [], 0
    while True:
        response = Response()
        rows = await deployments_api.list_deployments(
            response=response,
            environment_id=None,
            release_id=None,
            build_id=None,
            status_filter=None,
            date_from=None,
            date_to=None,
            environment_search=None,
            release_search=None,
            page=Page(limit=6, offset=offset),
            sort=sort,
            db=db_session,
            current_user=test_user,
        )
        assert int(response.headers[TOTAL_COUNT_HEADER]) == 25
        if not rows:
            break
        seen.extend(d.id for d in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"
