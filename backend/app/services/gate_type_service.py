"""Gate type vocabulary — tenant-scoped CRUD.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
Same call environment_tier and user_group made.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_type import GateTypeCreate, GateTypeUpdate
from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.db.models.gate_type import GateType


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(GateType.id).where(
        GateType.tenant_id == tenant_id,
        func.lower(GateType.name) == name.lower(),
        GateType.deleted_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(GateType.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A gate type named {name} already exists"
        )


async def list_types(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    include_inactive: bool = True,
) -> tuple[list[GateType], int]:
    query = select(GateType).where(
        GateType.tenant_id == tenant_id, GateType.deleted_at.is_(None)
    )
    if not include_inactive:
        query = query.where(GateType.is_active.is_(True))
    # display_order defaults to 0, so ties are the normal case, not the
    # exception — the id tiebreaker is what stops LIMIT/OFFSET duplicating and
    # dropping rows across pages.
    query = apply_sort(query, sort).order_by(GateType.display_order, GateType.id)
    return await fetch_page(db, query, page)


async def create_type(
    db: AsyncSession, tenant_id: int, data: GateTypeCreate
) -> GateType:
    await _assert_name_free(db, tenant_id, data.name)
    row = GateType(tenant_id=tenant_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return row


async def update_type(
    db: AsyncSession, type_id: int, tenant_id: int, data: GateTypeUpdate
) -> GateType:
    row = await get_type(db, type_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)  # omitted key means "leave alone"
    if "name" in fields:
        await _assert_name_free(db, tenant_id, fields["name"], exclude_id=type_id)
    for key, value in fields.items():
        setattr(row, key, value)
    await db.flush()
    return row


async def get_type(db: AsyncSession, type_id: int, tenant_id: int) -> GateType:
    row = (
        await db.execute(
            select(GateType).where(
                GateType.id == type_id,
                GateType.tenant_id == tenant_id,
                GateType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate type not found")
    return row


async def delete_type(db: AsyncSession, type_id: int, tenant_id: int) -> None:
    """Soft delete. Deliberately does NOT cascade to gates: a gate whose type
    is archived keeps pointing at it and renders the archived name — A1's
    read-rendering rule. A NEW assignment to an archived type is refused by
    get_type; an existing one is left alone."""
    row = await get_type(db, type_id, tenant_id)
    row.deleted_at = datetime.now(timezone.utc)
    await db.flush()
