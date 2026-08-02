"""The calendar and timeline endpoints honour their date range and advertise a total.

Both used to call `list_releases` with a hardcoded `limit=500` and discard the
total, so a tenant past 500 releases got a silently partial view. The calendar
additionally dropped undated releases *after* the query, which is the pattern
that makes bounding unsafe: the window is applied first, so a page can come back
short while the total says otherwise.
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services import release_service
from tests.factories import ensure_user


async def _release(db_session, tenant_id, name, *, target=None):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=f"cal-timeline-lifecycle-{name}",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    user = await ensure_user(db_session, tenant_id)

    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="major",
        release_kind="project",
        lifecycle_template_id=tpl.id,
        status="draft",
        raised_by=user.id,
        target_date=target,
    )
    db_session.add(r)
    await db_session.flush()
    return r


@pytest.mark.asyncio
async def test_has_target_date_drops_undated_releases_in_sql(db_session, test_tenant):
    """The count must describe the same set as the rows.

    If this filter moved back into Python after the query, the total would
    include undated releases the caller never receives.
    """
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "dated", target=now)
    await _release(db_session, test_tenant.id, "undated-1", target=None)
    await _release(db_session, test_tenant.id, "undated-2", target=None)

    rows, total = await release_service.list_releases(
        db_session, test_tenant.id, has_target_date=True, limit=50
    )

    assert {r.name for r in rows} == {"dated"}
    assert total == 1

    # Without the flag, all three are in scope — proving the flag is what filters.
    _rows, total_unfiltered = await release_service.list_releases(
        db_session, test_tenant.id, limit=50
    )
    assert total_unfiltered == 3


@pytest.mark.asyncio
async def test_the_date_range_bounds_target_date(db_session, test_tenant):
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "before", target=now - timedelta(days=40))
    await _release(db_session, test_tenant.id, "inside", target=now)
    await _release(db_session, test_tenant.id, "after", target=now + timedelta(days=40))

    rows, total = await release_service.list_releases(
        db_session,
        test_tenant.id,
        date_from=now - timedelta(days=5),
        date_to=now + timedelta(days=5),
        has_target_date=True,
        limit=50,
    )

    assert {r.name for r in rows} == {"inside"}
    assert total == 1


@pytest.mark.asyncio
async def test_the_total_describes_the_whole_range_not_the_page(db_session, test_tenant):
    """This is what the endpoints previously threw away, leaving a client no way
    to tell a full calendar from a truncated one."""
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i in range(6):
        await _release(db_session, test_tenant.id, f"r{i}", target=now + timedelta(days=i))

    rows, total = await release_service.list_releases(
        db_session, test_tenant.id, has_target_date=True, limit=2
    )

    assert len(rows) == 2
    assert total == 6


@pytest.mark.asyncio
async def test_calendar_endpoint_applies_the_range_and_sets_the_total(
    client, auth_headers, db_session, test_tenant
):
    """The regression guard for the defect that motivated this change: the
    endpoint's parameters are `date_from`/`date_to`. The frontend was sending
    `from`/`to`, which FastAPI ignores — so every range returned the same set.

    Asserting the *narrow* range returns fewer entries than the wide one is what
    makes this discriminating; asserting only that a request succeeds would have
    stayed green throughout the bug.
    """
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "inside", target=now)
    await _release(db_session, test_tenant.id, "far-future", target=now + timedelta(days=400))
    await _release(db_session, test_tenant.id, "undated", target=None)
    await db_session.commit()

    narrow = await client.get(
        "/api/v1/releases/calendar",
        headers=auth_headers,
        params={
            "date_from": (now - timedelta(days=5)).isoformat(),
            "date_to": (now + timedelta(days=5)).isoformat(),
        },
    )
    assert narrow.status_code == 200
    assert [e["title"] for e in narrow.json()] == ["inside"]
    assert narrow.headers["X-Total-Count"] == "1"

    wide = await client.get("/api/v1/releases/calendar", headers=auth_headers)
    assert wide.status_code == 200
    # The undated release is excluded from both; the far-future one only from
    # the narrow range.
    assert {e["title"] for e in wide.json()} == {"inside", "far-future"}
    assert wide.headers["X-Total-Count"] == "2"


@pytest.mark.asyncio
async def test_timeline_endpoint_sets_the_total(
    client, auth_headers, db_session, test_tenant
):
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "t1", target=now)
    await _release(db_session, test_tenant.id, "t2", target=now + timedelta(days=1))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/releases/timeline", headers=auth_headers, params={"limit": 1}
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.headers["X-Total-Count"] == "2"


@pytest.mark.asyncio
async def test_a_release_spanning_the_window_is_returned(db_session, test_tenant):
    """A calendar wants everything *overlapping* the visible month, not only
    what starts inside it.

    Found by opening the page: filtering on target_date alone made June render
    blank while a release running 01/05 -> 29/07 should have been drawn across
    it. The release occupies [target_date, COALESCE(actual_date, target_date)].
    """
    may = datetime(2026, 5, 1, tzinfo=timezone.utc)
    july = datetime(2026, 7, 29, tzinfo=timezone.utc)
    spanning = await _release(db_session, test_tenant.id, "spans-june", target=may)
    spanning.actual_date = july
    await db_session.flush()
    # A release that ended before the window must still be excluded.
    ended = await _release(db_session, test_tenant.id, "ended-in-april", target=datetime(2026, 4, 1, tzinfo=timezone.utc))
    ended.actual_date = datetime(2026, 4, 20, tzinfo=timezone.utc)
    await db_session.flush()
    # And one starting after it.
    await _release(db_session, test_tenant.id, "starts-august", target=datetime(2026, 8, 15, tzinfo=timezone.utc))

    rows, total = await release_service.list_releases(
        db_session,
        test_tenant.id,
        date_from=datetime(2026, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 30, tzinfo=timezone.utc),
        has_target_date=True,
        date_overlaps_range=True,
        limit=50,
    )

    assert {r.name for r in rows} == {"spans-june"}
    assert total == 1


@pytest.mark.asyncio
async def test_an_open_ended_release_is_bounded_by_its_target_date(db_session, test_tenant):
    """With no actual_date the interval collapses to a point, so COALESCE must
    fall back to target_date rather than treating the release as open-ended
    forever — otherwise every undelivered release would appear in every future
    month."""
    await _release(db_session, test_tenant.id, "undelivered-may", target=datetime(2026, 5, 1, tzinfo=timezone.utc))

    rows, _total = await release_service.list_releases(
        db_session,
        test_tenant.id,
        date_from=datetime(2026, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 30, tzinfo=timezone.utc),
        has_target_date=True,
        date_overlaps_range=True,
        limit=50,
    )

    assert rows == []
