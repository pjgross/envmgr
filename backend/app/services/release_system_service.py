"""Systems attached to a release.

Extracted from the endpoint when the list was bounded: the query is a
multi-column select (the joined system name is not a ReleaseSystem column), so
it goes through fetch_page_rows rather than fetch_page.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, fetch_page_rows
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System


async def list_release_systems(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    page: Optional[Page] = None,
) -> tuple[list, int]:
    """Return (ReleaseSystem, system_name) rows for a release, plus the total."""
    query = (
        select(ReleaseSystem, System.name)
        .join(System, System.id == ReleaseSystem.system_id)
        .where(
            ReleaseSystem.release_id == release_id,
            ReleaseSystem.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
        .order_by(ReleaseSystem.id)
    )
    return await fetch_page_rows(db, query, page)
