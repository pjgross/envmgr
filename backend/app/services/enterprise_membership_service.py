"""Enterprise release membership service.

Workflow: request → accept/reject/withdraw; accept → remove.
All mutations publish outbox events. Never call db.commit() here.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.user import User


async def _get_release(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Release:
    r = (
        await db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release not found")
    return r


async def _get_open_membership_for_project(
    db: AsyncSession, project_release_id: int
) -> Optional[ReleaseMembership]:
    return (
        await db.execute(
            select(ReleaseMembership).where(
                ReleaseMembership.project_release_id == project_release_id,
                ReleaseMembership.state.in_(
                    [MembershipState.PENDING_REQUEST.value, MembershipState.ACCEPTED.value]
                ),
            )
        )
    ).scalar_one_or_none()


async def request_membership(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
    project_release_id: int,
    notes: Optional[str] = None,
) -> ReleaseMembership:
    tenant_id = user.active_tenant_id
    enterprise = await _get_release(db, enterprise_id, tenant_id)
    project = await _get_release(db, project_release_id, tenant_id)

    if enterprise.release_kind != "enterprise":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Target is not an enterprise release",
        )
    if project.release_kind != "project":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only project releases can be admitted",
        )
    if await _get_open_membership_for_project(db, project_release_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Project release already has a pending or accepted membership",
        )

    m = ReleaseMembership(
        tenant_id=tenant_id,
        enterprise_release_id=enterprise_id,
        project_release_id=project_release_id,
        state=MembershipState.PENDING_REQUEST.value,
        requested_by=user.id,
        requested_at=datetime.now(timezone.utc),
        notes=notes,
        late_scope=False,
    )
    try:
        db.add(m)
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Project release already has a pending or accepted membership",
        ) from e
    await publish_event(
        db,
        event_type="EnterpriseMembershipRequested",
        aggregate_id=enterprise_id,
        aggregate_type="Release",
        payload={
            "membership_id": m.id,
            "project_release_id": project_release_id,
            "actor_id": user.id,
        },
        tenant_id=tenant_id,
    )
    return m
