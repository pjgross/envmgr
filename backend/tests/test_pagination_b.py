"""Sub-project B: restructured queries, and the differential tests that pin them.

Each restructure moves filtering out of Python and into SQL. The tests below
embed the *old* Python predicate as a reference implementation and assert the
new SQL agrees with it, because a shape test cannot catch a predicate that
returns a subtly different set.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER, Page
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.raid import RaidItem
from app.db.models.release import Release
from app.services import raid_config_service, raid_service


async def _make_release(db_session, tenant_id, user_id, name="B-release"):
    """Mirrors tests/services/test_raid_service.py — lifecycle_template_id is NOT nullable."""
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name=f"{name}-tpl",
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    rel = Release(
        tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=user_id,
    )
    db_session.add(rel)
    await db_session.flush()
    return rel


# ── RAID: the reference implementation the SQL must agree with ───────────────

def _old_rag_filter(items, wanted, cfg):
    """Verbatim semantics of the Python filter this task replaces."""
    return [
        i for i in items
        if raid_service.rag(raid_service.severity(i.probability, i.impact), cfg) == wanted
    ]


def _old_overdue_filter(items, now):
    return [
        i for i in items
        if i.review_date and i.review_date < now
        and i.status not in ("closed", "promoted", "met")
    ]


@pytest.mark.asyncio
async def test_rag_filter_in_sql_matches_the_python_it_replaced(db_session, tenant, user):
    """Covers every severity in the domain, plus unset factors."""
    rel = await _make_release(db_session, tenant.id, user.id)
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)

    # one item per (probability, impact) pair, plus two with unset factors
    for p in range(1, 6):
        for i in range(1, 6):
            db_session.add(RaidItem(
                tenant_id=tenant.id, release_id=rel.id, item_type="risk",
                seq=p * 10 + i, title=f"p{p}i{i}", status="open",
                raised_by=user.id, raised_at=datetime.now(timezone.utc),
                probability=p, impact=i,
            ))
    db_session.add(RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=900,
        title="no-probability", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=None, impact=3,
    ))
    db_session.add(RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=901,
        title="no-impact", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=3, impact=None,
    ))
    await db_session.flush()

    all_items, _ = await raid_service.list_items(db_session, rel.id, tenant.id, config=cfg)

    for wanted in ("green", "amber", "red"):
        expected = {i.id for i in _old_rag_filter(all_items, wanted, raid_service._config_dict(cfg))}
        got, total = await raid_service.list_items(
            db_session, rel.id, tenant.id, rag=wanted, config=cfg
        )
        assert {i.id for i in got} == expected, f"{wanted} diverged"
        assert total == len(expected)


@pytest.mark.asyncio
async def test_rag_filter_honours_first_match_when_bands_overlap(db_session, tenant, user):
    """rag_bands has no validation, and rag() resolves by FIRST match.

    An OR-of-BETWEEN translation would wrongly include severity 5 in 'amber'.
    """
    rel = await _make_release(db_session, tenant.id, user.id, name="overlap")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    cfg = await raid_config_service.update_config(
        db_session, tenant.id,
        rag_bands=[
            {"rag": "green", "min": 1, "max": 5},
            {"rag": "amber", "min": 4, "max": 14},   # overlaps green on 4-5
            {"rag": "red", "min": 15, "max": 25},
        ],
    )
    for p, i, label in [(1, 4, "sev4"), (1, 5, "sev5"), (2, 3, "sev6")]:
        db_session.add(RaidItem(
            tenant_id=tenant.id, release_id=rel.id, item_type="risk",
            seq=p * 100 + i, title=label, status="open", raised_by=user.id,
            raised_at=datetime.now(timezone.utc), probability=p, impact=i,
        ))
    await db_session.flush()

    green, _ = await raid_service.list_items(db_session, rel.id, tenant.id, rag="green", config=cfg)
    amber, _ = await raid_service.list_items(db_session, rel.id, tenant.id, rag="amber", config=cfg)

    # severities 4 and 5 match green first, so amber must NOT claim them
    assert {i.title for i in green} == {"sev4", "sev5"}
    assert {i.title for i in amber} == {"sev6"}


@pytest.mark.asyncio
async def test_unknown_rag_label_matches_nothing(db_session, tenant, user):
    """An empty severity set must become false(), not a skipped filter."""
    rel = await _make_release(db_session, tenant.id, user.id, name="unknown-rag")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    db_session.add(RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=1,
        title="A", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=3, impact=3,
    ))
    await db_session.flush()

    got, total = await raid_service.list_items(
        db_session, rel.id, tenant.id, rag="chartreuse", config=cfg
    )
    assert got == []
    assert total == 0


@pytest.mark.asyncio
async def test_rag_filter_covers_severities_above_the_nominal_scale(db_session, tenant, user):
    """probability/impact carry no upper validation and bands are unvalidated, so
    a severity can exceed len(probability_scale) * len(impact_scale). A domain
    enumeration capped at that product would silently drop this item."""
    rel = await _make_release(db_session, tenant.id, user.id, name="wide-band")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    cfg = await raid_config_service.update_config(
        db_session, tenant.id,
        rag_bands=[
            {"rag": "green", "min": 1, "max": 5},
            {"rag": "amber", "min": 6, "max": 14},
            {"rag": "red", "min": 15, "max": 1000},
        ],
    )
    item = RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=1,
        title="way-off-scale", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=10, impact=10,
    )
    db_session.add(item)
    await db_session.flush()

    # the production function says this is red
    assert raid_service.rag(100, raid_service._config_dict(cfg)) == "red"

    got, total = await raid_service.list_items(
        db_session, rel.id, tenant.id, rag="red", config=cfg
    )
    assert [i.id for i in got] == [item.id]
    assert total == 1


@pytest.mark.asyncio
async def test_overdue_filter_in_sql_matches_the_python_it_replaced(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id, name="overdue")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    now = datetime.now(timezone.utc)
    past, future = now - timedelta(days=3), now + timedelta(days=3)

    rows = [
        ("past-open", past, "open"),
        ("past-closed", past, "closed"),
        ("past-promoted", past, "promoted"),
        ("past-met", past, "met"),
        ("future-open", future, "open"),
        ("none-open", None, "open"),
    ]
    # Hold a strong reference to each row: SQLite's DateTime(timezone=True)
    # does not actually preserve tzinfo across a real DB round-trip, and
    # SQLAlchemy's identity map only holds a *strong* ref while an object is
    # pending. Without a held reference, unreferenced rows are GC'd right
    # after flush() and the later query re-materialises them from the raw
    # DB row — naive on SQLite — which would make the reference filter
    # below crash comparing naive vs aware, unrelated to the SQL under test.
    created = []
    for n, (title, review, status) in enumerate(rows, start=1):
        item = RaidItem(
            tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=n,
            title=title, status=status, raised_by=user.id, raised_at=now,
            review_date=review,
        )
        db_session.add(item)
        created.append(item)
    await db_session.flush()

    all_items, _ = await raid_service.list_items(db_session, rel.id, tenant.id, config=cfg)
    expected = {i.id for i in _old_overdue_filter(all_items, datetime.now(timezone.utc))}

    got, total = await raid_service.list_items(
        db_session, rel.id, tenant.id, overdue=True, config=cfg
    )
    assert {i.id for i in got} == expected
    assert {i.title for i in got} == {"past-open"}
    assert total == len(expected)


@pytest.mark.asyncio
async def test_raid_endpoint_is_bounded(client, auth_headers, db_session, test_tenant, test_user):
    rel = await _make_release(db_session, test_tenant.id, test_user.id, name="api-raid")
    await raid_config_service.get_or_seed_config(db_session, test_tenant.id)
    for n in range(3):
        db_session.add(RaidItem(
            tenant_id=test_tenant.id, release_id=rel.id, item_type="risk", seq=n + 1,
            title=f"item-{n}", status="open", raised_by=test_user.id,
            raised_at=datetime.now(timezone.utc), probability=2, impact=2,
        ))
    await db_session.commit()

    url = f"/api/v1/releases/{rel.id}/raid"
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
    assert int(response.headers[TOTAL_COUNT_HEADER]) == 3

    windowed = await client.get(f"{url}?limit=2", headers=auth_headers)
    assert len(windowed.json()) == 2
    assert int(windowed.headers[TOTAL_COUNT_HEADER]) == 3

    over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
    assert over.status_code == 422


# ── System dependencies ──────────────────────────────────────────────────────

async def _make_system(db_session, tenant_id, name):
    from app.db.models.system import System
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.mark.asyncio
async def test_system_dependencies_return_same_rows_and_order_as_two_queries(
    db_session, tenant
):
    """The OR query must reproduce the concatenation exactly: same rows, and
    outgoing-then-incoming grouping preserved."""
    from app.db.models.dependency import DependencyType, SystemDependency
    from app.services import dependency_service

    me = await _make_system(db_session, tenant.id, "me")
    a = await _make_system(db_session, tenant.id, "a")
    b = await _make_system(db_session, tenant.id, "b")

    out1 = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                            to_system_id=a.id, dependency_type=DependencyType.API_CALL)
    out2 = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                            to_system_id=b.id, dependency_type=DependencyType.DATABASE)
    inc1 = SystemDependency(tenant_id=tenant.id, from_system_id=a.id,
                            to_system_id=me.id, dependency_type=DependencyType.EVENT)
    for d in (out1, out2, inc1):
        db_session.add(d)
    await db_session.flush()

    rows, total = await dependency_service.list_system_dependencies(
        db_session, me.id, tenant.id
    )

    # Reference: what the two-query version returned, concatenated.
    expected_ids = [out1.id, out2.id, inc1.id]
    assert [r.id for r in rows] == expected_ids, "grouping or membership changed"
    assert total == 3


@pytest.mark.asyncio
async def test_system_dependencies_handle_one_sided_cases(db_session, tenant):
    from app.db.models.dependency import DependencyType, SystemDependency
    from app.services import dependency_service

    me = await _make_system(db_session, tenant.id, "solo")
    other = await _make_system(db_session, tenant.id, "other")

    # outgoing only
    d = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                         to_system_id=other.id, dependency_type=DependencyType.API_CALL)
    db_session.add(d)
    await db_session.flush()
    rows, total = await dependency_service.list_system_dependencies(db_session, me.id, tenant.id)
    assert [r.id for r in rows] == [d.id] and total == 1

    # and from the other side it is incoming only
    rows, total = await dependency_service.list_system_dependencies(db_session, other.id, tenant.id)
    assert [r.id for r in rows] == [d.id] and total == 1
