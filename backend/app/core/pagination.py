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
from typing import Optional

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
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Maximum rows to return (max {MAX_LIMIT}).",
    ),
    offset: int = Query(0, ge=0, description="Rows to skip."),
) -> Page:
    """FastAPI dependency supplying the window for a list endpoint."""
    return Page(limit=limit, offset=offset)


async def fetch_page(
    db: AsyncSession, query: Select, page: Optional[Page]
) -> tuple[list, int]:
    """Run `query` windowed by `page`, and return (rows, total).

    The count is a separate query against the same filters rather than a window
    function, so it stays correct for queries with joins or DISTINCT where a
    window count would double-count.
    """
    total = (
        await db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
    ).scalar_one()

    if page is not None:
        query = query.limit(page.limit).offset(page.offset)

    rows = list((await db.execute(query)).scalars().all())
    return rows, total


def set_total_count(response: Response, total: int) -> None:
    """Advertise the unwindowed total so a client can tell it has a partial page."""
    response.headers[TOTAL_COUNT_HEADER] = str(total)
