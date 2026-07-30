"""Server-side sorting: the whitelist, and that it composes with the tiebreaker.

The whitelist is the security boundary — `sort_by` is a client string and must
never reach the query as a column name. And a sort column is almost never
unique, so the sort must PRECEDE the existing primary-key tiebreaker rather
than replace it; sub-project A showed that dropping a tiebreaker breaks paging
deterministically on PostgreSQL.
"""
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.pagination import Page, Sort, apply_sort, fetch_page, sorting
from app.db.models.environment import Environment
from tests.conftest import IS_POSTGRES

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
