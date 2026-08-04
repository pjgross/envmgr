"""GET /api/v1/deployments + detail + link-change + env deployments."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db.models.deployment import Deployment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services import change_request_service
from tests.factories import ensure_environment_tier, ensure_build, ensure_change_request, ensure_environment


async def _seed(db_session, test_tenant, test_user, status="success"):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.deployment import Deployment
    await change_request_service.seed_default_lifecycles(db_session, test_tenant.id)

    sys = System(tenant_id=test_tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="orders-api")
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(tenant_id=test_tenant.id, name="sit", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.flush()
    build = Build(
        tenant_id=test_tenant.id, subsystem_id=sub.id, git_sha="a" * 40,
        build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(build)
    await db_session.flush()
    cr = await change_request_service.create_code_deployment(
        db_session, tenant_id=test_tenant.id, raised_by=test_user.id,
        title="x", description="y",
    )
    dep = Deployment(
        tenant_id=test_tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=str(uuid4()),
        deployed_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        status=status,
    )
    db_session.add(dep)
    await db_session.commit()
    return env, build, cr, dep


@pytest.mark.asyncio
async def test_list_and_detail(client, auth_headers, db_session, test_tenant, test_user):
    env, build, cr, dep = await _seed(db_session, test_tenant, test_user)

    r = await client.get("/api/v1/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert any(d["id"] == dep.id for d in r.json())

    r = await client.get(f"/api/v1/deployments/{dep.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "success"


@pytest.mark.asyncio
async def test_env_deployments(client, auth_headers, db_session, test_tenant, test_user):
    env, build, cr, dep = await _seed(db_session, test_tenant, test_user)
    r = await client.get(f"/api/v1/environments/{env.id}/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert any(d["id"] == dep.id for d in r.json())


@pytest.mark.asyncio
async def test_link_change_replaces_autocreated_cr(client, auth_headers, db_session, test_tenant, test_user):
    """The seeded CR is created via create_code_deployment → uses the Code
    Deployment lifecycle template → swap allowed."""
    env, build, cr_auto, dep = await _seed(db_session, test_tenant, test_user)

    # Create a second human-authored CR using a different lifecycle template.
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.lifecycle import LifecycleTemplate
    from sqlalchemy import select
    other_tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "change_request",
            LifecycleTemplate.name == "Simple Approval",
        )
    )).scalar_one()
    cr_human = ChangeRequest(
        tenant_id=test_tenant.id, title="Human CR", description="",
        change_type=ChangeType.CONFIGURATION, status="draft",
        lifecycle_id=other_tpl.id,
        raised_by=test_user.id,
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc),
    )
    db_session.add(cr_human)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/deployments/{dep.id}/link-change",
        headers=auth_headers,
        json={"change_request_id": cr_human.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["change_request_id"] == cr_human.id


# ── server-side sort + name searches (sub-project C1 task 6) ────────────────
#
# `list_deployments` is inline in the endpoint, not a service function, and
# selects a 5-column join via `_select_with_joins()` (fetch_page_rows, not
# fetch_page). `environment_search`/`release_search` are ilike predicates on
# Environment.name/Release.name — both already joined, and both joins are
# PK-equality (Environment.id / Release.id are each the table's primary key,
# so at most one row on the right per Deployment row), which is why they
# cannot fan out and inflate X-Total-Count.

def _t(offset_seconds: float):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


async def _direct_deployment(
    db_session,
    tenant_id,
    *,
    build,
    environment,
    change_request,
    release=None,
    status="success",
    deployer_name=None,
    deployed_at=None,
):
    """Insert a Deployment directly, bypassing the webhook ingest path, so tests
    can seed exact status/deployer_name/deployed_at/release combinations that
    deliberately disagree with insertion order."""
    dep = Deployment(
        tenant_id=tenant_id,
        build_id=build.id,
        environment_id=environment.id,
        change_request_id=change_request.id,
        release_id=release.id if release is not None else None,
        event_id=str(uuid4()),
        status=status,
        deployer_name=deployer_name,
        deployed_at=deployed_at if deployed_at is not None else datetime.now(timezone.utc),
    )
    db_session.add(dep)
    await db_session.flush()
    return dep


async def _direct_release(db_session, tenant_id, raised_by, *, name) -> Release:
    """Insert a Release (+ the lifecycle template it requires) directly, so
    tests can give it an exact name to search on."""
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=f"lifecycle-for-{name}",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    release = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="major",
        release_kind="project",
        lifecycle_template_id=tpl.id,
        status="draft",
        raised_by=raised_by,
    )
    db_session.add(release)
    await db_session.flush()
    return release


@pytest.mark.asyncio
async def test_list_deployments_default_order_unchanged(
    client, auth_headers, db_session, test_tenant, test_user
):
    """No sort_by: order must stay `deployed_at DESC, id` — today's ordering,
    byte for byte.

    Insertion order (a, b, c) deliberately disagrees with both id-ascending
    and deployed_at-ascending order, so a response that happened to preserve
    insertion order — or that silently flipped direction the moment this
    endpoint gained the sorting() dependency — would not accidentally satisfy
    this assertion.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)

    a = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployed_at=_t(2),
    )
    b = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployed_at=_t(0),
    )
    c = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployed_at=_t(1),
    )
    await db_session.commit()

    resp = await client.get("/api/v1/deployments", headers=auth_headers)
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert ids == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_deployments_sort_by_status_both_directions(
    client, auth_headers, db_session, test_tenant, test_user
):
    env = await ensure_environment(db_session, test_tenant.id)
    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)

    mu = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        status="mu", deployed_at=_t(0),
    )
    alpha = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        status="alpha", deployed_at=_t(1),
    )
    zeta = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        status="zeta", deployed_at=_t(2),
    )
    await db_session.commit()

    asc = await client.get(
        "/api/v1/deployments?sort_by=status&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await client.get(
        "/api/v1/deployments?sort_by=status&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_deployments_sort_by_deployer_name_both_directions(
    client, auth_headers, db_session, test_tenant, test_user
):
    env = await ensure_environment(db_session, test_tenant.id)
    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)

    mu = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployer_name="mu", deployed_at=_t(0),
    )
    alpha = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployer_name="alpha", deployed_at=_t(1),
    )
    zeta = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployer_name="zeta", deployed_at=_t(2),
    )
    await db_session.commit()

    asc = await client.get(
        "/api/v1/deployments?sort_by=deployer_name&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await client.get(
        "/api/v1/deployments?sort_by=deployer_name&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_deployments_sort_by_deployed_at_both_directions(
    client, auth_headers, db_session, test_tenant, test_user
):
    env = await ensure_environment(db_session, test_tenant.id)
    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)

    a = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployed_at=_t(2),
    )
    b = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployed_at=_t(0),
    )
    c = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        deployed_at=_t(1),
    )
    await db_session.commit()

    asc = await client.get(
        "/api/v1/deployments?sort_by=deployed_at&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [b.id, c.id, a.id]

    desc = await client.get(
        "/api/v1/deployments?sort_by=deployed_at&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_deployments_unknown_sort_by_is_422(client, auth_headers):
    resp = await client.get(
        "/api/v1/deployments?sort_by=nonexistent", headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_environment_search_filters_to_matching_environment_name(
    client, auth_headers, db_session, test_tenant, test_user
):
    """environment_search is an ilike on the *joined* Environment.name, not on
    any column of Deployment itself — the grid filters on `environment_name`.
    Two deployments point at the same matching environment (env_prod), which
    is the case that would double-count if the join fanned out: Environment.id
    is the join's PK-equality target, so it cannot.
    """
    env_prod = await ensure_environment(db_session, test_tenant.id, slot=1)
    env_prod.name = "prod-east"
    env_stage = await ensure_environment(db_session, test_tenant.id, slot=2)
    env_stage.name = "staging-west"
    await db_session.flush()

    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)

    d1 = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env_prod, change_request=cr,
        deployed_at=_t(0),
    )
    d2 = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env_stage, change_request=cr,
        deployed_at=_t(1),
    )
    d3 = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env_prod, change_request=cr,
        deployed_at=_t(2),
    )
    await db_session.commit()

    # Case-insensitive, and matches two rows against one environment without
    # inflating the total to 3 (the unfiltered count).
    resp = await client.get(
        "/api/v1/deployments?environment_search=PROD", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {row["id"] for row in body} == {d1.id, d3.id}
    assert len(body) == 2
    assert resp.headers["x-total-count"] == "2"

    # Sanity: the unfiltered total really is 3, so the assertion above is
    # discriminating rather than accidentally true.
    unfiltered = await client.get("/api/v1/deployments", headers=auth_headers)
    assert unfiltered.headers["x-total-count"] == "3"


@pytest.mark.asyncio
async def test_release_search_matches_joined_release_name_case_insensitively(
    client, auth_headers, db_session, test_tenant, test_user
):
    env = await ensure_environment(db_session, test_tenant.id)
    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)
    matching_release = await _direct_release(
        db_session, test_tenant.id, test_user.id, name="Payments Release"
    )
    other_release = await _direct_release(
        db_session, test_tenant.id, test_user.id, name="Unrelated Release"
    )

    matching = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        release=matching_release, deployed_at=_t(0),
    )
    non_matching = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        release=other_release, deployed_at=_t(1),
    )
    await db_session.commit()

    # A non-matching row exists alongside the matching one, so this proves
    # release_search actually filters rather than passing every row through
    # unfiltered (an unknown query param FastAPI simply ignores).
    resp = await client.get(
        "/api/v1/deployments?release_search=payments", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [row["id"] for row in body] == [matching.id]
    assert resp.headers["x-total-count"] == "1"

    unfiltered = await client.get("/api/v1/deployments", headers=auth_headers)
    assert unfiltered.headers["x-total-count"] == "2"
    assert non_matching.release_id == other_release.id


@pytest.mark.asyncio
async def test_release_search_excludes_null_release_matching_grid_behaviour(
    client, auth_headers, db_session, test_tenant, test_user
):
    """Both joins are outerjoins: a deployment with no release has a NULL
    Release.name, so `Release.name.ilike(...)` excludes it (NULL ILIKE x is
    NULL, not true) for any non-empty search term. The grid does
    `(d.release_name ?? '').toLowerCase().includes(needle)`, and an empty
    string only contains an empty needle — so a non-empty search excludes the
    same row there too. This test is the assertion the brief asks for rather
    than reasoning about it: seed one deployment with a release whose name
    does NOT match, and one with release_id=None, and confirm neither survives
    a non-empty release_search.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    build = await ensure_build(db_session, test_tenant.id)
    cr = await ensure_change_request(db_session, test_tenant.id)
    matching_release = await _direct_release(
        db_session, test_tenant.id, test_user.id, name="Payments Release"
    )
    other_release = await _direct_release(
        db_session, test_tenant.id, test_user.id, name="Unrelated Release"
    )

    matching = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        release=matching_release, deployed_at=_t(0),
    )
    no_release = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        release=None, deployed_at=_t(1),
    )
    other = await _direct_deployment(
        db_session, test_tenant.id, build=build, environment=env, change_request=cr,
        release=other_release, deployed_at=_t(2),
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/deployments?release_search=payments", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [row["id"] for row in body] == [matching.id]
    assert resp.headers["x-total-count"] == "1"

    # Confirm the no-release row really is in the tenant's data (unfiltered
    # total is 3), so its absence above is the search excluding it, not it
    # never existing.
    unfiltered = await client.get("/api/v1/deployments", headers=auth_headers)
    assert unfiltered.headers["x-total-count"] == "3"
    assert no_release.release_id is None
    assert other.release_id == other_release.id
