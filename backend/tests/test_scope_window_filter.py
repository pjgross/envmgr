"""`scope_window=actionable` filters in SQL, not in the browser.

`actionable` means window_status is `open` or `closing_soon`. Both mean
`now < scope_deadline`, so the filter is three comparisons against one
bound `now` — the closing-soon threshold never enters SQL. These tests
assert against `compute_scope_window`'s own output rather than a
hardcoded list, so the SQL filter and the displayed status cannot drift
apart.
"""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services import release_service
from app.services.scope_window import compute_scope_window
from tests.factories import ensure_user


async def _release(db_session, tenant_id, name, *, deadline, actual=None):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=f"scope-window-filter-lifecycle-{name}",
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
        scope_deadline=deadline,
        actual_date=actual,
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _all(db_session, tenant_id):
    query = select(Release).where(
        Release.tenant_id == tenant_id, Release.deleted_at.is_(None)
    )
    return (await db_session.execute(query)).scalars().all()


@pytest.mark.asyncio
async def test_actionable_returns_exactly_the_open_and_closing_soon_releases(
    db_session, test_tenant
):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "open", deadline=now + timedelta(days=30))
    await _release(db_session, test_tenant.id, "closing-soon", deadline=now + timedelta(days=3))
    await _release(db_session, test_tenant.id, "closed", deadline=now - timedelta(days=1))
    await _release(db_session, test_tenant.id, "no-cutoff", deadline=None)
    await _release(db_session, test_tenant.id, "shipped", deadline=now + timedelta(days=10),
                   actual=now - timedelta(days=2))

    rows, total = await release_service.list_releases(
        db_session, test_tenant.id, scope_window="actionable", now=now, limit=50
    )

    # Cross-check against the Python computation rather than a literal list.
    expected = {
        r.name for r in await _all(db_session, test_tenant.id)
        if compute_scope_window(r.scope_deadline, r.actual_date, now)[0]
        in ("open", "closing_soon")
    }
    assert {r.name for r in rows} == expected == {"open", "closing-soon"}
    assert total == 2


@pytest.mark.asyncio
async def test_the_boundary_is_strict_and_matches_the_python_rule(
    db_session, test_tenant
):
    """`compute_scope_window` returns "closed" when `now >= deadline`, so a
    release sitting exactly ON its deadline is NOT actionable. The SQL
    comparison must therefore be strict `>`, not `>=`.

    This is also where a naive date-diff port would have gone wrong:
    Python's timedelta.days floors while both engines' date functions
    truncate toward zero, so the two would disagree about a just-passed
    deadline. Comparing timestamps sidesteps that entirely.
    """
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "just-open", deadline=now + timedelta(seconds=1))
    await _release(db_session, test_tenant.id, "exactly-now", deadline=now)
    await _release(db_session, test_tenant.id, "just-closed", deadline=now - timedelta(seconds=1))

    rows, _ = await release_service.list_releases(
        db_session, test_tenant.id, scope_window="actionable", now=now, limit=50
    )

    assert {r.name for r in rows} == {"just-open"}
    # And the SQL agrees with the Python rule for each of the three.
    for r in await _all(db_session, test_tenant.id):
        actionable = compute_scope_window(r.scope_deadline, r.actual_date, now)[0] in (
            "open", "closing_soon"
        )
        assert actionable == (r.name in {row.name for row in rows}), r.name


@pytest.mark.asyncio
async def test_all_and_omitted_apply_no_filter(db_session, test_tenant):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "open", deadline=now + timedelta(days=30))
    await _release(db_session, test_tenant.id, "closed", deadline=now - timedelta(days=1))

    for kwargs in ({"scope_window": "all", "now": now}, {}):
        rows, total = await release_service.list_releases(
            db_session, test_tenant.id, limit=50, **kwargs
        )
        assert total == 2, kwargs


@pytest.mark.asyncio
async def test_the_total_reflects_the_filter_not_the_page(db_session, test_tenant):
    """The footer count must describe the filtered set. The count query
    shares `base_where`, so this fails if the filter is applied to the row
    query alone."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        await _release(db_session, test_tenant.id, f"open-{i}", deadline=now + timedelta(days=30))
    for i in range(3):
        await _release(db_session, test_tenant.id, f"closed-{i}", deadline=now - timedelta(days=1))

    rows, total = await release_service.list_releases(
        db_session, test_tenant.id, scope_window="actionable", now=now, limit=2
    )

    assert len(rows) == 2
    assert total == 5
