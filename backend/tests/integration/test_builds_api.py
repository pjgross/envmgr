"""GET /api/v1/builds + /{id} — JWT auth, filters, detail."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.factories import ensure_subsystem


@pytest.mark.asyncio
async def test_list_and_detail(client, auth_headers, db_session, test_tenant):
    from app.db.models.system import System, SubSystem
    from app.db.models.build import Build
    sys = System(tenant_id=test_tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="orders-api")
    db_session.add(sub)
    await db_session.flush()
    b = Build(
        tenant_id=test_tenant.id, subsystem_id=sub.id, git_sha="deadbeef1234",
        build_number="#5", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(b)
    await db_session.commit()

    r = await client.get("/api/v1/builds", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(x["id"] == b.id for x in items)

    r = await client.get(f"/api/v1/builds/{b.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["git_sha"] == "deadbeef1234"


@pytest.mark.asyncio
async def test_filter_by_subsystem(client, auth_headers, db_session, test_tenant):
    from app.db.models.system import System, SubSystem
    from app.db.models.build import Build
    sys = System(tenant_id=test_tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub_a = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="a")
    sub_b = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="b")
    db_session.add_all([sub_a, sub_b])
    await db_session.flush()
    for sub, sha in [(sub_a, "aaaa"), (sub_b, "bbbb")]:
        db_session.add(Build(
            tenant_id=test_tenant.id, subsystem_id=sub.id, git_sha=sha * 4,
            build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
        ))
    await db_session.commit()

    r = await client.get(f"/api/v1/builds?subsystem_id={sub_a.id}", headers=auth_headers)
    shas = {x["git_sha"] for x in r.json()}
    assert shas == {"aaaa" * 4}


# ── bounding + server-side sort + subsystem_search (sub-project C1 task 7) ──
#
# `/builds` was the one list endpoint never bounded by sub-project A: its own
# `limit=Query(100, le=500)`, no `set_total_count`, and `order_by(commit_
# timestamp.desc())` with no tiebreaker at all. This section proves the
# `pagination()`/`sorting()` conversion preserves the old contract (default
# 100, cap 500) while adding the missing tiebreaker, and that `subsystem_search`
# behaves like the other already-shipped joined-column searches.


def _t(offset_seconds: float):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


async def _direct_build(
    db_session,
    tenant_id,
    subsystem,
    *,
    git_sha,
    build_number="#1",
    git_branch=None,
    commit_timestamp=None,
):
    from app.db.models.build import Build

    build = Build(
        tenant_id=tenant_id,
        subsystem_id=subsystem.id,
        git_sha=git_sha,
        git_branch=git_branch,
        build_number=build_number,
        commit_timestamp=commit_timestamp if commit_timestamp is not None else _t(0),
    )
    db_session.add(build)
    await db_session.flush()
    return build


@pytest.mark.asyncio
async def test_list_builds_default_order_unchanged_for_distinct_timestamps(
    client, auth_headers, db_session, test_tenant
):
    """No query params: order stays `commit_timestamp DESC` for rows whose
    timestamps are distinct — the id tiebreaker this task adds only breaks
    ties, so it cannot move rows relative to each other here. Insertion order
    (a, b, c) deliberately disagrees with both id-ascending and
    commit_timestamp-ascending order, so a response that happened to preserve
    insertion order, or that flipped to ascending the moment sorting() was
    adopted, would not accidentally satisfy this assertion.

    Mutation this kills: swapping `.desc()` for ascending (or dropping the
    `order_by` clause and relying on `apply_sort` alone when sort is None).
    """
    sub = await ensure_subsystem(db_session, test_tenant.id)
    a = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="a" * 40, build_number="a", commit_timestamp=_t(2)
    )
    b = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="b" * 40, build_number="b", commit_timestamp=_t(0)
    )
    c = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="c" * 40, build_number="c", commit_timestamp=_t(1)
    )
    await db_session.commit()

    resp = await client.get("/api/v1/builds", headers=auth_headers)
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [a.id, c.id, b.id]


# A same-timestamp "does the id tiebreaker win" test was deliberately not
# added here: on a freshly-seeded table, physical (ctid) row order matches
# insertion/id order anyway, so a single-query assertion that two tied rows
# come back id-ascending passes whether or not `, Build.id` is actually in the
# `order_by` call — verified by mutation (removing it) and re-running: the
# test kept passing on Postgres. That is exactly the false-confidence shape
# flagged elsewhere in this sub-project (a tie-order test with no
# discriminating power). Proving the tiebreaker actually matters requires
# walking LIMIT/OFFSET across a tie boundary across separate page fetches,
# which is C1-8's job (sort-aware tie paging per endpoint), not this task's.


@pytest.mark.asyncio
async def test_list_builds_sort_by_git_branch_both_directions(
    client, auth_headers, db_session, test_tenant
):
    sub = await ensure_subsystem(db_session, test_tenant.id)
    mu = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="d" * 40, build_number="d",
        git_branch="mu", commit_timestamp=_t(0),
    )
    alpha = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="e" * 40, build_number="e",
        git_branch="alpha", commit_timestamp=_t(1),
    )
    zeta = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="f" * 40, build_number="f",
        git_branch="zeta", commit_timestamp=_t(2),
    )
    await db_session.commit()

    asc = await client.get("/api/v1/builds?sort_by=git_branch&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await client.get("/api/v1/builds?sort_by=git_branch&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_builds_sort_by_build_number_both_directions(
    client, auth_headers, db_session, test_tenant
):
    sub = await ensure_subsystem(db_session, test_tenant.id)
    mu = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="1a" * 20, build_number="mu", commit_timestamp=_t(0),
    )
    alpha = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="1b" * 20, build_number="alpha", commit_timestamp=_t(1),
    )
    zeta = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="1c" * 20, build_number="zeta", commit_timestamp=_t(2),
    )
    await db_session.commit()

    asc = await client.get("/api/v1/builds?sort_by=build_number&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await client.get("/api/v1/builds?sort_by=build_number&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_builds_sort_by_commit_timestamp_ascending(
    client, auth_headers, db_session, test_tenant
):
    """The default already covers descending (see the order-unchanged test
    above); this covers the explicit ascending direction so both halves of
    the whitelist entry are exercised."""
    sub = await ensure_subsystem(db_session, test_tenant.id)
    a = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="2a" * 20, build_number="2a", commit_timestamp=_t(2)
    )
    b = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="2b" * 20, build_number="2b", commit_timestamp=_t(0)
    )
    c = await _direct_build(
        db_session, test_tenant.id, sub, git_sha="2c" * 20, build_number="2c", commit_timestamp=_t(1)
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/builds?sort_by=commit_timestamp&sort_dir=asc", headers=auth_headers
    )
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [b.id, c.id, a.id]


@pytest.mark.asyncio
async def test_list_builds_unknown_sort_by_is_422(client, auth_headers):
    resp = await client.get("/api/v1/builds?sort_by=nonexistent", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_subsystem_search_filters_to_matching_subsystem_name(
    client, auth_headers, db_session, test_tenant
):
    """`subsystem_search` is an ilike on the *joined* SubSystem.name. Two
    builds point at the same matching subsystem (orders-api), which is the
    case that would double-count if the join fanned out: SubSystem.id is the
    join's PK-equality target, so it cannot.

    Mutation this kills: filtering on `Build.git_branch` instead of the
    joined `SubSystem.name` (wrong column, would 500 or silently no-op);
    dropping the `if subsystem_search:` guard's application to the query
    (would return all 3 rows instead of 2).
    """
    orders = await ensure_subsystem(db_session, test_tenant.id, name="orders-api")
    payments = await ensure_subsystem(db_session, test_tenant.id, name="payments-api")

    d1 = await _direct_build(db_session, test_tenant.id, orders, git_sha="3a" * 20, build_number="3a")
    d2 = await _direct_build(db_session, test_tenant.id, payments, git_sha="3b" * 20, build_number="3b")
    d3 = await _direct_build(db_session, test_tenant.id, orders, git_sha="3c" * 20, build_number="3c")
    await db_session.commit()

    resp = await client.get("/api/v1/builds?subsystem_search=ORDERS", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert {row["id"] for row in body} == {d1.id, d3.id}
    assert len(body) == 2
    assert resp.headers["x-total-count"] == "2"

    unfiltered = await client.get("/api/v1/builds", headers=auth_headers)
    assert unfiltered.headers["x-total-count"] == "3"


# NULL-subsystem case: the brief asks us to confirm `subsystem_search`
# excludes a build whose joined SubSystem.name is NULL (matching the grid's
# `(b.subsystem_name ?? '').toLowerCase().includes(needle)`, which also
# excludes it for any non-empty needle). We cannot construct that row: unlike
# Deployment.release_id, Build.subsystem_id is `Mapped[int]` with
# `nullable=False` and a `ForeignKey(..., ondelete="RESTRICT")` — there is no
# NULL to insert, at the ORM layer or the database's. See the report for the
# full reasoning; no test is written here because there is nothing for it to
# exercise.


@pytest.mark.asyncio
async def test_list_builds_limit_bounds_the_page_and_advertises_total(
    client, auth_headers, db_session, test_tenant
):
    sub = await ensure_subsystem(db_session, test_tenant.id)
    for n in range(4):
        await _direct_build(
            db_session, test_tenant.id, sub, git_sha=f"{n}4" * 20, build_number=f"lim-{n}",
            commit_timestamp=_t(n),
        )
    await db_session.commit()

    resp = await client.get("/api/v1/builds?limit=2", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert int(resp.headers["x-total-count"]) >= 4


@pytest.mark.asyncio
async def test_list_builds_over_cap_is_422(client, auth_headers):
    resp = await client.get("/api/v1/builds?limit=501", headers=auth_headers)
    assert resp.status_code == 422
