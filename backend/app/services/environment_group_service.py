"""Environment groups — CRUD plus the member count the UI needs.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise
it. Same call as environment_tier_service, user_group_service and
project_service.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_group import (
    EnvironmentGroupCreate, EnvironmentGroupUpdate, MemberCreate,
)
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment
from app.db.models.environment_group import EnvironmentGroup, EnvironmentGroupMember


@dataclass
class GroupView:
    """A group plus the labels a UI needs without extra round-trips,
    following project_service.ProjectView."""

    group: EnvironmentGroup
    member_count: int


def _member_count_clause(tenant_id: int):
    """Live members only: the membership row AND its environment must both be
    undeleted, so the count agrees with what `list_members` returns. A1
    shipped a count and a list that disagreed because they were written three
    tasks apart and nobody reconciled them."""
    return (
        select(func.count(EnvironmentGroupMember.id))
        .select_from(EnvironmentGroupMember)
        .join(Environment, Environment.id == EnvironmentGroupMember.environment_id)
        .where(
            EnvironmentGroupMember.group_id == EnvironmentGroup.id,
            EnvironmentGroupMember.tenant_id == tenant_id,
            EnvironmentGroupMember.deleted_at.is_(None),
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
        .correlate(EnvironmentGroup)
        .scalar_subquery()
    )


def _view_query(tenant_id: int):
    return (
        select(EnvironmentGroup, _member_count_clause(tenant_id))
        .where(
            EnvironmentGroup.tenant_id == tenant_id,
            EnvironmentGroup.deleted_at.is_(None),
        )
    )


def _to_view(row) -> GroupView:
    group, member_count = row
    return GroupView(group=group, member_count=member_count)


ENVIRONMENT_GROUP_SORTS = {
    "name": EnvironmentGroup.name,
    "created_at": EnvironmentGroup.created_at,
}


async def list_groups(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> tuple[list[GroupView], int]:
    query = _view_query(tenant_id)
    if search:
        query = query.where(EnvironmentGroup.name.ilike(f"%{search}%"))
    if is_active is not None:
        query = query.where(EnvironmentGroup.is_active.is_(is_active))
    # apply_sort folds case, so two names differing only in case stop being
    # distinct keys — the id tiebreaker is what makes the order total, which
    # LIMIT/OFFSET requires.
    query = apply_sort(query, sort).order_by(
        func.lower(EnvironmentGroup.name), EnvironmentGroup.id
    )
    rows, total = await fetch_page_rows(db, query, page)
    return [_to_view(r) for r in rows], total


async def get_group_view(
    db: AsyncSession, group_id: int, tenant_id: int
) -> GroupView:
    row = (
        await db.execute(_view_query(tenant_id).where(EnvironmentGroup.id == group_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment group not found")
    return _to_view(row)


async def get_group(
    db: AsyncSession, group_id: int, tenant_id: int
) -> EnvironmentGroup:
    """The bare entity, for callers that do not need the count."""
    group = (
        await db.execute(
            select(EnvironmentGroup).where(
                EnvironmentGroup.id == group_id,
                EnvironmentGroup.tenant_id == tenant_id,
                EnvironmentGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        # 404 rather than 403: a 403 confirms the row exists in another tenant.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment group not found")
    return group


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(EnvironmentGroup.id).where(
        EnvironmentGroup.tenant_id == tenant_id,
        EnvironmentGroup.deleted_at.is_(None),
        func.lower(EnvironmentGroup.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(EnvironmentGroup.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An environment group named '{name.strip()}' already exists in this tenant",
        )


async def create_group(
    db: AsyncSession, data: EnvironmentGroupCreate, tenant_id: int
) -> GroupView:
    await _assert_name_free(db, tenant_id, data.name)
    group = EnvironmentGroup(
        tenant_id=tenant_id,
        name=data.name.strip(),
        description=data.description,
        is_active=data.is_active,
    )
    db.add(group)
    await db.flush()
    return await get_group_view(db, group.id, tenant_id)


async def update_group(
    db: AsyncSession, group_id: int, data: EnvironmentGroupUpdate, tenant_id: int
) -> GroupView:
    group = await get_group(db, group_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"].strip().lower() != group.name.lower():
        await _assert_name_free(db, tenant_id, fields["name"], exclude_id=group_id)

    for key, value in fields.items():
        setattr(group, key, value.strip() if key == "name" else value)
    await db.flush()
    return await get_group_view(db, group_id, tenant_id)


async def delete_group(db: AsyncSession, group_id: int, tenant_id: int) -> None:
    """Soft delete, never refused.

    Deliberately unlike user_group_service.delete_group, which 409s while any
    environment references it. A group accumulates every booking ever made
    against it, so a reference check would make it permanently undeletable the
    moment someone booked it. Existing bookings keep rendering the name;
    `is_active` is what removes it from pickers going forward.

    Membership rows are soft-deleted with it — the group is gone, so its
    membership is meaningless, and leaving them live would let
    `GET /environments/{id}/groups` keep advertising a deleted group.
    """
    group = await get_group(db, group_id, tenant_id)
    now = datetime.now(timezone.utc)
    group.deleted_at = now

    await db.execute(
        update(EnvironmentGroupMember)
        .where(
            EnvironmentGroupMember.group_id == group_id,
            # Tenant-scoped: deleting our group must never touch another
            # tenant's rows, however malformed. A1's equivalent cascade
            # shipped with this filter unguarded by any test.
            EnvironmentGroupMember.tenant_id == tenant_id,
            EnvironmentGroupMember.deleted_at.is_(None),
        )
        .values(deleted_at=now)
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Membership: which environments are in a group, readable from both
# directions. Follows project_service._agreement_query exactly.
# ---------------------------------------------------------------------------


def _member_query(tenant_id: int):
    """One select carrying both ends' names, tenant-qualified on each join.

    Both joins filter deleted_at: a membership row whose group or environment
    is gone should not appear from either direction. This is the OPPOSITE
    judgement from a name-rendering lookup, where an archived thing must still
    render its name on a live row — here we are asking whether the row should
    exist at all.
    """
    return (
        select(EnvironmentGroupMember, EnvironmentGroup.name, Environment.name)
        .join(
            EnvironmentGroup,
            and_(
                EnvironmentGroup.id == EnvironmentGroupMember.group_id,
                EnvironmentGroup.tenant_id == tenant_id,
                EnvironmentGroup.deleted_at.is_(None),
            ),
        )
        .join(
            Environment,
            and_(
                Environment.id == EnvironmentGroupMember.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            ),
        )
        .where(
            EnvironmentGroupMember.tenant_id == tenant_id,
            EnvironmentGroupMember.deleted_at.is_(None),
        )
    )


async def list_members(
    db: AsyncSession, group_id: int, tenant_id: int, *, page: Optional[Page] = None
):
    await get_group(db, group_id, tenant_id)  # 404s for another tenant's group
    query = (
        _member_query(tenant_id)
        .where(EnvironmentGroupMember.group_id == group_id)
        .order_by(func.lower(Environment.name), EnvironmentGroupMember.id)
    )
    return await fetch_page_rows(db, query, page)


async def list_groups_for_environment(
    db: AsyncSession, environment_id: int, tenant_id: int, *, page: Optional[Page] = None
):
    found = (
        await db.execute(
            select(Environment.id).where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    query = (
        _member_query(tenant_id)
        .where(EnvironmentGroupMember.environment_id == environment_id)
        .order_by(func.lower(EnvironmentGroup.name), EnvironmentGroupMember.id)
    )
    return await fetch_page_rows(db, query, page)


async def add_member(
    db: AsyncSession, group_id: int, data: MemberCreate, tenant_id: int
):
    group = await get_group(db, group_id, tenant_id)

    env = (
        await db.execute(
            select(Environment).where(
                Environment.id == data.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    # Only a LIVE duplicate is refused — a previously removed membership
    # (soft-deleted) must not block re-adding the same environment, and
    # re-adding must produce exactly one live row, not two.
    duplicate = (
        await db.execute(
            select(EnvironmentGroupMember.id).where(
                EnvironmentGroupMember.tenant_id == tenant_id,
                EnvironmentGroupMember.group_id == group_id,
                EnvironmentGroupMember.environment_id == data.environment_id,
                EnvironmentGroupMember.deleted_at.is_(None),
            )
        )
    ).first()
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{env.name}' is already a member of this group",
        )

    member = EnvironmentGroupMember(
        tenant_id=tenant_id, group_id=group_id, environment_id=data.environment_id,
    )
    db.add(member)
    await db.flush()

    row = (
        await db.execute(
            _member_query(tenant_id).where(EnvironmentGroupMember.id == member.id)
        )
    ).first()
    return row


async def remove_member(
    db: AsyncSession, group_id: int, member_id: int, tenant_id: int
) -> None:
    await get_group(db, group_id, tenant_id)  # 404s for another tenant's group
    member = (
        await db.execute(
            select(EnvironmentGroupMember).where(
                EnvironmentGroupMember.id == member_id,
                EnvironmentGroupMember.group_id == group_id,
                EnvironmentGroupMember.tenant_id == tenant_id,
                EnvironmentGroupMember.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    # Soft, not hard: a booking against this group records only the group id,
    # so "which environments did this group hold when that booking was made"
    # later needs removed rows to still exist.
    member.deleted_at = datetime.now(timezone.utc)
    await db.flush()
