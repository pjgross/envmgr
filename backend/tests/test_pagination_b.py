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
    outgoing-then-incoming grouping preserved.

    The incoming row is created FIRST so it holds the lower autoincrement id.
    If the outgoing rows were created first their ids would already sort
    outgoing-then-incoming and this test would pass with the ORDER BY's CASE
    removed — guarding nothing. Creating the incoming row first makes the CASE
    load-bearing.
    """
    from app.db.models.dependency import DependencyType, SystemDependency
    from app.services import dependency_service

    me = await _make_system(db_session, tenant.id, "me")
    a = await _make_system(db_session, tenant.id, "a")
    b = await _make_system(db_session, tenant.id, "b")

    inc1 = SystemDependency(tenant_id=tenant.id, from_system_id=a.id,
                            to_system_id=me.id, dependency_type=DependencyType.EVENT)
    db_session.add(inc1)
    await db_session.flush()

    out1 = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                            to_system_id=a.id, dependency_type=DependencyType.API_CALL)
    out2 = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                            to_system_id=b.id, dependency_type=DependencyType.DATABASE)
    db_session.add(out1)
    db_session.add(out2)
    await db_session.flush()

    assert inc1.id < out1.id < out2.id, "fixture must give the incoming row the lowest id"

    rows, total = await dependency_service.list_system_dependencies(
        db_session, me.id, tenant.id
    )

    # outgoing first, despite holding the HIGHER ids — this is the grouping check
    assert [r.id for r in rows] == [out1.id, out2.id, inc1.id]
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


# ── Component dependencies ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_dependencies_return_same_rows_and_order(db_session, tenant):
    from app.db.models.dependency import ComponentDependency, DependencyType
    from app.services import dependency_service
    from tests.factories import ensure_subsystem

    me = await ensure_subsystem(db_session, tenant.id, name="dep-me")
    other = await ensure_subsystem(db_session, tenant.id, name="dep-other")

    # INSERT THE INCOMING ROW FIRST so it gets the LOWER autoincrement id.
    # If outgoing rows were created first their ids already sort
    # outgoing-then-incoming, and the test would still pass with the CASE
    # removed — i.e. it would not actually guard the grouping. Creating the
    # incoming row first makes the CASE load-bearing: a plain ORDER BY id
    # would put it first and fail this assertion.
    inc = ComponentDependency(tenant_id=tenant.id, from_subsystem_id=other.id,
                              to_subsystem_id=me.id,
                              dependency_type=DependencyType.DATABASE)
    db_session.add(inc)
    await db_session.flush()

    out = ComponentDependency(tenant_id=tenant.id, from_subsystem_id=me.id,
                              to_subsystem_id=other.id,
                              dependency_type=DependencyType.API_CALL)
    db_session.add(out)
    await db_session.flush()

    assert inc.id < out.id, "fixture must give the incoming row the lower id"

    rows, total = await dependency_service.list_component_dependencies(
        db_session, me.id, tenant.id
    )
    # outgoing first despite having the HIGHER id — this is the grouping check
    assert [r.id for r in rows] == [out.id, inc.id]
    assert total == 2


# ── Versions ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_current_only_returns_one_row_per_subsystem(db_session, tenant):
    """The Python dedup kept the first row per subsystem under an ORDER BY that
    did not break ties; the window function makes that deterministic. So this
    asserts the invariant (one row per subsystem, and it is the latest), not a
    specific winner for the tied case.
    """
    from app.db.models.version import EnvironmentSubSystemVersion
    from app.services import version_service
    from tests.factories import ensure_environment, ensure_subsystem

    env = await ensure_environment(db_session, tenant.id)
    sub_a = await ensure_subsystem(db_session, tenant.id, name="ver-a")
    sub_b = await ensure_subsystem(db_session, tenant.id, name="ver-b")
    now = datetime.now(timezone.utc)

    def _v(sub_id, label, installed):
        return EnvironmentSubSystemVersion(
            tenant_id=tenant.id, environment_id=env.id, subsystem_id=sub_id,
            build_identifier=f"build-{label}", version_label=label,
            installed_at=installed,
        )

    db_session.add(_v(sub_a.id, "a-old", now - timedelta(days=2)))
    db_session.add(_v(sub_a.id, "a-new", now))
    db_session.add(_v(sub_b.id, "b-only", now - timedelta(days=1)))
    await db_session.flush()

    all_rows, all_total = await version_service.list_versions(
        db_session, env.id, tenant.id, current_only=False
    )
    assert all_total == 3

    current, total = await version_service.list_versions(
        db_session, env.id, tenant.id, current_only=True
    )
    assert total == 2
    by_sub = {v.subsystem_id: v.version_label for v in current}
    assert by_sub == {sub_a.id: "a-new", sub_b.id: "b-only"}


@pytest.mark.asyncio
async def test_dependency_alerts_match_the_python_filter_they_replaced(
    db_session, tenant, user
):
    """Covers: unchanged dates (skip), both-None (skip), one-None (alert),
    changed (alert), and a soft-deleted target release (skip)."""
    from app.db.models.release_dependency import ReleaseDependency
    from app.services import release_dependency_service

    rel = await _make_release(db_session, tenant.id, user.id, name="alerts-parent")
    now = datetime.now(timezone.utc)

    async def _dep(name, target_date, prior, deleted=False):
        target = await _make_release(db_session, tenant.id, user.id, name=name)
        target.target_date = target_date
        if deleted:
            target.deleted_at = now
        d = ReleaseDependency(
            tenant_id=tenant.id, release_id=rel.id,
            depends_on_release_id=target.id, kind="deploys_after",
            last_dependency_target_date=prior,
        )
        db_session.add(d)
        await db_session.flush()
        return d

    unchanged = await _dep("unchanged", now, now)
    both_none = await _dep("both-none", None, None)
    now_set = await _dep("now-set", now, None)
    now_gone = await _dep("now-gone", None, now)
    shifted = await _dep("shifted", now + timedelta(days=5), now)
    deleted = await _dep("deleted-target", now + timedelta(days=5), now, deleted=True)

    alerts, total = await release_dependency_service.get_dependency_alerts(
        db_session, rel.id, tenant.id
    )

    alerted_dep_ids = {a.dependency_id for a in alerts}
    assert alerted_dep_ids == {now_set.id, now_gone.id, shifted.id}
    assert unchanged.id not in alerted_dep_ids
    assert both_none.id not in alerted_dep_ids
    assert deleted.id not in alerted_dep_ids, "soft-deleted target must not alert"
    assert total == 3


@pytest.mark.asyncio
async def test_current_only_picks_exactly_one_row_when_timestamps_tie(db_session, tenant):
    """installed_at is not unique. The old code's winner was undefined; the new
    one is deterministic. Assert the invariant, not which row wins."""
    from app.db.models.version import EnvironmentSubSystemVersion
    from app.services import version_service
    from tests.factories import ensure_environment, ensure_subsystem

    env = await ensure_environment(db_session, tenant.id)
    sub = await ensure_subsystem(db_session, tenant.id, name="ver-tied")
    same = datetime.now(timezone.utc)

    for label in ("tied-1", "tied-2"):
        db_session.add(EnvironmentSubSystemVersion(
            tenant_id=tenant.id, environment_id=env.id, subsystem_id=sub.id,
            build_identifier=f"b-{label}", version_label=label, installed_at=same,
        ))
    await db_session.flush()

    current, total = await version_service.list_versions(
        db_session, env.id, tenant.id, current_only=True
    )
    assert total == 1
    assert len(current) == 1
