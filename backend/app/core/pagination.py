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
from typing import Callable, Mapping, Optional

from fastapi import HTTPException, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

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


@dataclass(frozen=True)
class Sort:
    column: InstrumentedAttribute
    descending: bool


def sorting(
    allowed: Mapping[str, InstrumentedAttribute],
    default: str,
    *,
    default_dir: str = "asc",
) -> Callable[..., Sort]:
    """Build a FastAPI dependency resolving `sort_by`/`sort_dir` against a whitelist.

    `allowed` maps the client-facing field name to the column it sorts by. The
    mapping is the entire security boundary: `sort_by` is a client-supplied
    string and is looked up, never used to address a column. An unknown field is
    a 422 rather than a silent fallback — a client that receives a different
    order than it asked for, with no error, will render it as though it were the
    order it requested.

    The returned Sort is applied by `apply_sort` BEFORE the caller's existing
    tiebreaker. A sort column is almost never unique, so a sort that replaced the
    tiebreaker would reintroduce the duplicate/missing-row bug that LIMIT/OFFSET
    over a partial order produces.

    `default_dir` is the direction used when the client sends no `sort_dir` at
    all — most endpoints' pre-existing default order is ascending, but a couple
    (incidents, change requests) have always defaulted to newest-first. Without
    this, an endpoint adopting `sorting()` would silently flip its own default
    page from descending to ascending the moment it started depending on this
    primitive, which is exactly the kind of behaviour change C1 must not cause.
    An explicit `sort_dir` from the client always wins over `default_dir`,
    regardless of which `sort_by` was requested.
    """
    if default not in allowed:
        raise ValueError(f"default sort {default!r} is not in the whitelist")
    if default_dir not in ("asc", "desc"):
        raise ValueError(f"default_dir must be 'asc' or 'desc', got {default_dir!r}")

    field_names = sorted(allowed)

    def _sorting(
        sort_by: str = Query(
            default,
            description=f"Field to sort by. One of: {', '.join(field_names)}.",
        ),
        sort_dir: Optional[str] = Query(
            None,
            pattern="^(asc|desc)$",
            description=f"Sort direction. Defaults to {default_dir!r} when omitted.",
        ),
    ) -> Sort:
        column = allowed.get(sort_by)
        if column is None:
            raise HTTPException(
                status_code=422,
                detail=f"sort_by must be one of: {', '.join(field_names)}",
            )
        direction = default_dir if sort_dir is None else sort_dir
        return Sort(column=column, descending=direction == "desc")

    return _sorting


def apply_sort(query: Select, sort: Optional[Sort]) -> Select:
    """Order `query` by `sort`, if given.

    Chain the caller's unique tiebreaker after this — `apply_sort(q, s).order_by(Model.id)`.
    SQLAlchemy appends, so the tiebreaker stays the final key.

    NULLs are pinned explicitly. SQLite sorts NULL first on ASC and PostgreSQL
    sorts it last, so an unqualified ORDER BY on a nullable column returns a
    different page per engine. Pinning them last on ASC and first on DESC keeps
    the two identical and matches the more common expectation that "no value"
    sorts after values.
    """
    if sort is None:
        return query
    column = sort.column.desc() if sort.descending else sort.column.asc()
    return query.order_by(column.nullsfirst() if sort.descending else column.nullslast())
