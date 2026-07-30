"""Bounded list results: the shared primitive and the endpoints using it."""
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    TOTAL_COUNT_HEADER,
    Page,
    fetch_page,
    fetch_page_rows,
    pagination,
)
from app.db.models.environment import Environment


async def _make_environments(db, tenant_id: int, count: int) -> None:
    for n in range(count):
        db.add(
            Environment(
                tenant_id=tenant_id,
                name=f"env-{n:03d}",
                environment_type="SIT",
            )
        )
    await db.flush()


# ── the primitive ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_page_windows_the_query(db_session, tenant):
    await _make_environments(db_session, tenant.id, 10)
    query = select(Environment).order_by(Environment.name)

    rows, total = await fetch_page(db_session, query, Page(limit=3, offset=0))

    assert [r.name for r in rows] == ["env-000", "env-001", "env-002"]
    assert total == 10


@pytest.mark.asyncio
async def test_fetch_page_offset_walks_the_result_set(db_session, tenant):
    await _make_environments(db_session, tenant.id, 10)
    query = select(Environment).order_by(Environment.name)

    rows, total = await fetch_page(db_session, query, Page(limit=3, offset=3))

    assert [r.name for r in rows] == ["env-003", "env-004", "env-005"]
    assert total == 10


@pytest.mark.asyncio
async def test_total_is_the_unwindowed_count(db_session, tenant):
    """The point of returning it: telling the client the page is partial."""
    await _make_environments(db_session, tenant.id, 7)
    _, total = await fetch_page(
        db_session, select(Environment), Page(limit=2, offset=0)
    )
    assert total == 7


@pytest.mark.asyncio
async def test_total_respects_the_query_filters(db_session, tenant):
    """A count that ignored the WHERE clause would be worse than none."""
    await _make_environments(db_session, tenant.id, 6)
    query = select(Environment).where(Environment.name.in_(["env-000", "env-001"]))

    rows, total = await fetch_page(db_session, query, Page(limit=10, offset=0))

    assert len(rows) == 2
    assert total == 2


@pytest.mark.asyncio
async def test_no_page_returns_everything(db_session, tenant):
    """Service callers that are not request-scoped keep their old behaviour."""
    await _make_environments(db_session, tenant.id, 5)
    rows, total = await fetch_page(db_session, select(Environment), None)
    assert len(rows) == 5 == total


# ── endpoint behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_endpoint_still_returns_a_bare_array(
    client, db_session, test_tenant, auth_headers
):
    """Backward compatibility: no client change was required by this work."""
    await _make_environments(db_session, test_tenant.id, 3)

    response = await client.get("/api/v1/environments/", headers=auth_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_endpoint_advertises_the_total(
    client, db_session, test_tenant, auth_headers
):
    await _make_environments(db_session, test_tenant.id, 4)

    response = await client.get("/api/v1/environments/?limit=2", headers=auth_headers)

    assert len(response.json()) == 2
    assert int(response.headers[TOTAL_COUNT_HEADER]) >= 4


@pytest.mark.asyncio
async def test_list_endpoint_bounds_an_oversized_request(
    client, test_tenant, auth_headers
):
    """A caller cannot opt out of the cap by asking for more."""
    response = await client.get(
        f"/api/v1/environments/?limit={MAX_LIMIT + 1}", headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_endpoint_defaults_to_a_bounded_page(
    client, db_session, test_tenant, auth_headers
):
    """The unbounded default is what this change exists to remove."""
    await _make_environments(db_session, test_tenant.id, 3)
    response = await client.get("/api/v1/environments/", headers=auth_headers)
    assert len(response.json()) <= DEFAULT_LIMIT


# ── the factory ──────────────────────────────────────────────────────────────
#
# Tested against a throwaway app rather than a real endpoint: no endpoint uses
# per-endpoint overrides until a later task, and the factory's whole contract is
# visible from one route.


def _probe_app(**overrides) -> FastAPI:
    probe = FastAPI()

    @probe.get("/probe")
    async def _probe(page: Page = Depends(pagination(**overrides))):
        return {"limit": page.limit, "offset": page.offset}

    return probe


@pytest.mark.asyncio
async def test_factory_defaults_to_the_shared_window():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {"limit": DEFAULT_LIMIT, "offset": 0}
        assert (await ac.get(f"/probe?limit={MAX_LIMIT}")).status_code == 200
        assert (await ac.get(f"/probe?limit={MAX_LIMIT + 1}")).status_code == 422


@pytest.mark.asyncio
async def test_factory_overrides_are_enforced_not_clamped():
    """A per-endpoint cap is a real 422, so a caller cannot opt out of it."""
    app_50_200 = _probe_app(default_limit=50, max_limit=200)
    async with AsyncClient(
        transport=ASGITransport(app=app_50_200), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {"limit": 50, "offset": 0}
        assert (await ac.get("/probe?limit=200")).status_code == 200
        assert (await ac.get("/probe?limit=201")).status_code == 422


# ── the row variant ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_page_rows_returns_tuples_not_scalars(db_session, tenant):
    await _make_environments(db_session, tenant.id, 4)
    query = select(Environment.id, Environment.name).order_by(Environment.name)

    rows, total = await fetch_page_rows(db_session, query, Page(limit=2, offset=0))

    assert total == 4
    assert len(rows) == 2
    # each row is a tuple of the selected columns, not an entity
    assert [r[1] for r in rows] == ["env-000", "env-001"]


@pytest.mark.asyncio
async def test_fetch_page_rows_total_ignores_the_window(db_session, tenant):
    await _make_environments(db_session, tenant.id, 9)
    query = select(Environment, Environment.name).order_by(Environment.name)

    rows, total = await fetch_page_rows(db_session, query, Page(limit=3, offset=6))

    assert total == 9
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_fetch_page_rows_without_a_page_returns_everything(db_session, tenant):
    await _make_environments(db_session, tenant.id, 5)
    rows, total = await fetch_page_rows(
        db_session, select(Environment.id, Environment.name), None
    )
    assert len(rows) == 5 == total
