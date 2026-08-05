"""Tenant-scoped user groups — CRUD plus the counts the UI needs.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
Same reasoning as environment_tier_service.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.user_group import UserGroupCreate, UserGroupUpdate
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment
from app.db.models.user import User
from app.db.models.user_group import UserGroup, UserGroupMember

# A 409 listing 200 environment names is not a message a human can read. Name
# the first few and count the rest.
_MAX_NAMED_BLOCKERS = 10


@dataclass
class UserGroupView:
    """A group plus the counts a UI needs without extra round-trips, following
    environment_service.EnvironmentView."""

    group: UserGroup
    member_count: int
    environment_count: int


def _member_count_clause():
    return (
        select(func.count(UserGroupMember.id))
        .where(UserGroupMember.group_id == UserGroup.id)
        .correlate(UserGroup)
        .scalar_subquery()
    )


def _environment_count_clause(tenant_id: int):
    return (
        select(func.count(Environment.id))
        .where(
            Environment.operations_group_id == UserGroup.id,
            Environment.tenant_id == tenant_id,
            # A soft-deleted environment is not a reference — counting it would
            # make a group undeletable forever once anything using it was
            # removed. Same call as environment_tier_service.delete_tier.
            Environment.deleted_at.is_(None),
        )
        .correlate(UserGroup)
        .scalar_subquery()
    )


def _view_query(tenant_id: int):
    return select(
        UserGroup,
        _member_count_clause(),
        _environment_count_clause(tenant_id),
    ).where(UserGroup.tenant_id == tenant_id, UserGroup.deleted_at.is_(None))


async def list_groups(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
) -> tuple[list[UserGroupView], int]:
    """Groups for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter — see docs/pagination.md.
    """
    query = _view_query(tenant_id)
    # Names are unique per tenant, but the case fold in apply_sort means two
    # names differing only in case stop being distinct keys — so the id
    # tiebreaker is what makes the order total.
    query = apply_sort(query, sort).order_by(func.lower(UserGroup.name), UserGroup.id)
    rows, total = await fetch_page_rows(db, query, page)
    return (
        [
            UserGroupView(group=g, member_count=m, environment_count=e)
            for g, m, e in rows
        ],
        total,
    )


async def get_group_view(
    db: AsyncSession, group_id: int, tenant_id: int
) -> UserGroupView:
    row = (
        await db.execute(_view_query(tenant_id).where(UserGroup.id == group_id))
    ).first()
    if row is None:
        # 404 rather than 403: a 403 would confirm the row exists in another
        # tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User group not found"
        )
    group, member_count, environment_count = row
    return UserGroupView(
        group=group, member_count=member_count, environment_count=environment_count
    )


async def get_group(db: AsyncSession, group_id: int, tenant_id: int) -> UserGroup:
    """The bare entity, for callers that do not need the counts."""
    group = (
        await db.execute(
            select(UserGroup).where(
                UserGroup.id == group_id,
                UserGroup.tenant_id == tenant_id,
                UserGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User group not found"
        )
    return group


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(UserGroup.id).where(
        UserGroup.tenant_id == tenant_id,
        UserGroup.deleted_at.is_(None),
        func.lower(UserGroup.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(UserGroup.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A group named '{name.strip()}' already exists in this tenant",
        )


async def create_group(
    db: AsyncSession, data: UserGroupCreate, tenant_id: int
) -> UserGroupView:
    await _assert_name_free(db, tenant_id, data.name)
    group = UserGroup(
        tenant_id=tenant_id, name=data.name.strip(), description=data.description
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return UserGroupView(group=group, member_count=0, environment_count=0)


async def update_group(
    db: AsyncSession, group_id: int, data: UserGroupUpdate, tenant_id: int
) -> UserGroupView:
    """`description` keys on `model_fields_set`: an omitted key means "leave
    alone", only an explicit null clears it — the same contract
    environment_service.update_environment gives expires_at and
    operations_group_id. `data.description is not None` could not tell an
    explicit `null` apart from an omitted key, so a client-emptied description
    silently reverted to its old value after a 200. `name` has no such
    "explicit null clears it" state — the schema's field_validator already
    rejects a null name with a 422 before this function runs, so `is not
    None` remains correct for it.
    """
    group = await get_group(db, group_id, tenant_id)
    if data.name is not None and data.name.strip().lower() != group.name.lower():
        await _assert_name_free(db, tenant_id, data.name, exclude_id=group_id)
    if data.name is not None:
        group.name = data.name.strip()
    if "description" in data.model_fields_set:
        group.description = data.description
    await db.flush()
    return await get_group_view(db, group_id, tenant_id)


async def delete_group(db: AsyncSession, group_id: int, tenant_id: int) -> None:
    group = await get_group(db, group_id, tenant_id)
    blocker_filter = (
        Environment.operations_group_id == group_id,
        Environment.tenant_id == tenant_id,
        # A soft-deleted environment is not a reference — counting it would
        # make a group undeletable forever.
        Environment.deleted_at.is_(None),
    )
    # The true count is a separate query from the named subset: a query
    # capped with LIMIT can never report more than the cap, so deriving the
    # remainder from the length of a limited result is always wrong once the
    # true count exceeds the cap by more than one.
    total_blockers = (
        await db.execute(select(func.count(Environment.id)).where(*blocker_filter))
    ).scalar_one()
    if total_blockers:
        named = list(
            (
                await db.execute(
                    select(Environment.name)
                    .where(*blocker_filter)
                    # `Environment.name` carries no uniqueness constraint, so
                    # the id tiebreaker is what stops two identically-named
                    # environments at the LIMIT boundary yielding a different
                    # named subset on each retry of the same failed delete.
                    .order_by(Environment.name, Environment.id)
                    .limit(_MAX_NAMED_BLOCKERS)
                )
            )
            .scalars()
            .all()
        )
        remainder = total_blockers - len(named)
        detail = (
            "This group operates "
            + ", ".join(named)
            + (f" and {remainder} more" if remainder > 0 else "")
            + ". Reassign them before deleting it."
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # Membership rows are hard-deleted with the group: they are junction rows,
    # and a member of a retired group is not information anything reads.
    await db.execute(
        UserGroupMember.__table__.delete().where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.tenant_id == tenant_id,
        )
    )
    group.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def list_members(
    db: AsyncSession,
    group_id: int,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
) -> tuple[list[tuple[UserGroupMember, str]], int]:
    """Members of a group, each paired with the username.

    The username travels with the row rather than being resolved in the browser
    against `/tenant/users/lite`, which is capped — a `.find()` miss there would
    render the member as '—' and lose information no banner can recover.
    """
    await get_group(db, group_id, tenant_id)  # 404s for another tenant's group
    query = (
        select(UserGroupMember, User.username)
        .join(User, User.id == UserGroupMember.user_id)
        .where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.tenant_id == tenant_id,
        )
        # `username` is unique per tenant, but the case fold means two names
        # differing only in case stop being distinct keys — the id makes the
        # order total, which is what LIMIT/OFFSET requires.
        .order_by(func.lower(User.username), UserGroupMember.id)
    )
    return await fetch_page_rows(db, query, page)


async def add_member(
    db: AsyncSession, group_id: int, user_id: int, tenant_id: int
) -> tuple[UserGroupMember, str]:
    await get_group(db, group_id, tenant_id)

    # Validate the user against the ACTIVE tenant, not the caller's home
    # tenant: under master-admin impersonation those differ, and scoping this
    # to the wrong one 404s a legitimate request.
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    existing = (
        await db.execute(
            select(UserGroupMember.id).where(
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
            )
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{user.username} is already a member of this group",
        )

    member = UserGroupMember(
        tenant_id=tenant_id, group_id=group_id, user_id=user_id
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member, user.username


async def remove_member(
    db: AsyncSession, group_id: int, user_id: int, tenant_id: int
) -> None:
    await get_group(db, group_id, tenant_id)
    member = (
        await db.execute(
            select(UserGroupMember).where(
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
                UserGroupMember.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This user is not a member of this group",
        )
    # Hard delete — a junction row, per this codebase's convention.
    await db.delete(member)
    await db.flush()
