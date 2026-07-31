"""Bounded list results.

Most list endpoints returned every matching row for the tenant. That is fine at
demo scale and a problem at real scale: a tenant with 50k bookings gets one query
that loads 50k ORM objects, serialises them all, and hands the browser a response
it then renders into a DataGrid. Nothing in the stack said no.

The shape here is deliberately backward compatible. Endpoints keep returning a
JSON array, so no client changes are required, and the total goes in an
`X-Total-Count` header. A client that ignores it behaves exactly as before up to
the cap; one that reads it can tell there is more and page through with
`?offset=`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Generous enough that no realistic current page truncates, low enough that a
# pathological tenant cannot take the API down with one request.
DEFAULT_LIMIT = 500
MAX_LIMIT = 1000

TOTAL_COUNT_HEADER = "X-Total-Count"


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int


def pagination(
    *, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT
) -> Callable[..., Page]:
    """Build the FastAPI dependency supplying the window for a list endpoint.

    Most endpoints want the shared default. The two that already had their own
    limit contract when this primitive arrived keep it by passing overrides,
    because both do per-row work after the query — raising their default would
    multiply real work, not just serialisation.
    """

    def _pagination(
        limit: int = Query(
            default_limit,
            ge=1,
            le=max_limit,
            description=f"Maximum rows to return (max {max_limit}).",
        ),
        offset: int = Query(0, ge=0, description="Rows to skip."),
    ) -> Page:
        return Page(limit=limit, offset=offset)

    return _pagination


def _window(query: Select, page: Optional[Page]) -> Select:
    if page is None:
        return query
    return query.limit(page.limit).offset(page.offset)


async def _total_for(db: AsyncSession, query: Select) -> int:
    """Count against the same filters, as a separate query rather than a window
    function, so it stays correct for joins and DISTINCT where a window count
    would double-count.
    """
    return (
        await db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
    ).scalar_one()


async def fetch_page(
    db: AsyncSession, query: Select, page: Optional[Page]
) -> tuple[list, int]:
    """Run `query` windowed by `page`, and return (entities, total)."""
    rows = list((await db.execute(_window(query, page))).scalars().all())
    total = len(rows) if page is None else await _total_for(db, query)
    return rows, total


async def fetch_page_rows(
    db: AsyncSession, query: Select, page: Optional[Page]
) -> tuple[list, int]:
    """As `fetch_page`, but for multi-column selects.

    `fetch_page` ends in `.scalars()`, which keeps only the first column. A query
    like `select(Deployment, Build.git_sha, Environment.name)` needs whole rows.
    """
    rows = list((await db.execute(_window(query, page))).all())
    total = len(rows) if page is None else await _total_for(db, query)
    return rows, total


def set_total_count(response: Response, total: int) -> None:
    """Advertise the unwindowed total so a client can tell it has a partial page."""
    response.headers[TOTAL_COUNT_HEADER] = str(total)
