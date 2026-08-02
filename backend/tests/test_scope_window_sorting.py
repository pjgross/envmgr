"""Sorting by the scope-window cutoff.

`days_to_cutoff` is computed in Python after the query, so it cannot be
sorted on directly. It is monotonic in `scope_deadline`, so the whitelist
sorts by the deadline instead — and it is NULL exactly when the release is
shipped or has no deadline, which the mapped expression reproduces by
folding "shipped" into NULL. `apply_sort` then pins those rows last on
ascending, which is the order the UI has always shown.
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.api.v1.releases import RELEASE_SORTS
from app.core.pagination import Sort, apply_sort
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from tests.factories import ensure_user


async def _release(db_session, tenant_id, name, *, deadline, actual=None):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=f"scope-window-lifecycle-{name}",
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


async def _sorted_names(db_session, tenant_id, *, descending):
    query = apply_sort(
        select(Release).where(Release.tenant_id == tenant_id, Release.deleted_at.is_(None)),
        Sort(column=RELEASE_SORTS["scope_deadline"], descending=descending),
    ).order_by(Release.id)
    rows = (await db_session.execute(query)).scalars().all()
    return [r.name for r in rows]


@pytest.mark.asyncio
async def test_a_shipped_release_sorts_last_even_with_a_deadline(
    db_session, test_tenant
):
    """The case that motivated the design. A plain `ORDER BY scope_deadline`
    would sort this release by its date; the UI has always shown it last,
    because its days_to_cutoff is None."""
    early = await _release(db_session, test_tenant.id, "early-open",
                           deadline=datetime(2026, 3, 1, tzinfo=timezone.utc))
    shipped = await _release(db_session, test_tenant.id, "shipped-with-deadline",
                             deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
                             actual=datetime(2026, 1, 5, tzinfo=timezone.utc))
    later = await _release(db_session, test_tenant.id, "later-open",
                           deadline=datetime(2026, 4, 1, tzinfo=timezone.utc))

    names = await _sorted_names(db_session, test_tenant.id, descending=False)

    assert names == ["early-open", "later-open", "shipped-with-deadline"]
    assert (early.id, later.id, shipped.id)  # keep the fixtures referenced


@pytest.mark.asyncio
async def test_a_release_with_no_deadline_also_sorts_last(db_session, test_tenant):
    await _release(db_session, test_tenant.id, "has-deadline",
                   deadline=datetime(2026, 3, 1, tzinfo=timezone.utc))
    await _release(db_session, test_tenant.id, "no-deadline", deadline=None)

    names = await _sorted_names(db_session, test_tenant.id, descending=False)

    assert names == ["has-deadline", "no-deadline"]


@pytest.mark.asyncio
async def test_descending_mirrors_the_grouping(db_session, test_tenant):
    """Consistent with every other nullable column: NULLs first on DESC."""
    await _release(db_session, test_tenant.id, "has-deadline",
                   deadline=datetime(2026, 3, 1, tzinfo=timezone.utc))
    await _release(db_session, test_tenant.id, "no-deadline", deadline=None)

    names = await _sorted_names(db_session, test_tenant.id, descending=True)

    assert names == ["no-deadline", "has-deadline"]


@pytest.mark.asyncio
async def test_the_sort_precedes_the_id_tiebreaker(test_tenant):
    """Standing rule: a sort composes with the unique tiebreaker, never
    replaces it, or LIMIT/OFFSET duplicates and drops rows across pages."""
    from sqlalchemy.dialects import postgresql

    query = apply_sort(
        select(Release).where(Release.tenant_id == test_tenant.id),
        Sort(column=RELEASE_SORTS["scope_deadline"], descending=False),
    ).order_by(Release.id)

    order_by = str(query.compile(dialect=postgresql.dialect())).split("ORDER BY", 1)[1]
    assert "CASE" in order_by
    assert "NULLS LAST" in order_by
    assert order_by.rstrip().endswith("release.id")
