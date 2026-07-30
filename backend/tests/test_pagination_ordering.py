"""Paging over ties.

LIMIT/OFFSET is only correct over a total order. If the ORDER BY leaves ties,
the database may break them differently between two queries, so a row can come
back on page 1 and page 2 while another never appears at all. Nothing errors.

SQLite's plans are stable enough that it usually passes this by luck, so the
PostgreSQL leg is the one that matters:

    TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
        uv run pytest tests/test_pagination_ordering.py -q
"""
import pytest
from sqlalchemy import select

from app.core.pagination import Page, fetch_page
from app.services import environment_service


@pytest.mark.asyncio
async def test_walking_pages_over_identical_sort_keys_sees_each_row_once(
    db_session, test_tenant
):
    """Every environment shares a name, so `ORDER BY name` alone leaves 30 ties."""
    from app.db.models.environment import Environment

    total_rows = 30
    for _ in range(total_rows):
        db_session.add(Environment(
            tenant_id=test_tenant.id,
            name="identical",            # every row ties on the sort column
            environment_type="SIT",
        ))
    await db_session.flush()

    seen: list[int] = []
    page_size = 7
    offset = 0
    while True:
        rows, total = await environment_service.list_environments(
            db_session, test_tenant.id, page=Page(limit=page_size, offset=offset)
        )
        assert total == total_rows
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += page_size

    assert len(seen) == total_rows, f"expected {total_rows} rows, saw {len(seen)}"
    assert len(set(seen)) == total_rows, "a row was returned on more than one page"


@pytest.mark.asyncio
async def test_only_the_total_order_gives_a_reproducible_sequence(
    db_session, test_tenant
):
    """The walk test above is only meaningful if the tiebreaker is what pins the
    sequence. Under `ORDER BY name` alone every row ties, so nothing in the SQL
    determines the order; adding the primary key makes it unique and sorted.
    """
    from app.db.models.environment import Environment

    for _ in range(20):
        db_session.add(Environment(
            tenant_id=test_tenant.id, name="identical", environment_type="SIT",
        ))
    await db_session.flush()

    total_order = select(Environment).order_by(Environment.name, Environment.id)

    first, _ = await fetch_page(db_session, total_order, Page(limit=20, offset=0))
    again, _ = await fetch_page(db_session, total_order, Page(limit=20, offset=0))

    ids = [r.id for r in first]
    assert ids == [r.id for r in again], "a total order must be reproducible"
    assert ids == sorted(ids), "the tiebreaker must determine the sequence"
    assert len(set(ids)) == 20
