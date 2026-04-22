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
from app.db.models.lifecycle import LifecycleTemplate
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


# ── accept helpers ────────────────────────────────────────────────────────────


def _compute_late_scope(enterprise: Release, template: LifecycleTemplate) -> bool:
    states = template.definition.get("states", [])
    try:
        lockdown_idx = next(
            i for i, s in enumerate(states) if s.get("is_admission_lockdown")
        )
    except StopIteration:
        return False
    try:
        current_idx = next(
            i for i, s in enumerate(states) if s["key"] == enterprise.status
        )
    except StopIteration:
        return False
    return current_idx >= lockdown_idx


async def _check_action_permission(
    db: AsyncSession,
    enterprise: Release,
    user: User,
    action_key: str,
) -> None:
    tpl = await db.get(LifecycleTemplate, enterprise.lifecycle_template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lifecycle template missing")
    perms = (tpl.definition or {}).get("action_permissions", {}) or {}
    roles_for_state = perms.get(enterprise.status, {}).get(action_key, [])
    user_role_name = getattr(user.role, "name", user.role)
    if user_role_name not in roles_for_state:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Not permitted: {action_key}")


async def _get_membership(
    db: AsyncSession, membership_id: int, tenant_id: int
) -> ReleaseMembership:
    m = (
        await db.execute(
            select(ReleaseMembership).where(
                ReleaseMembership.id == membership_id,
                ReleaseMembership.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    return m


async def accept(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.PENDING_REQUEST.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot accept",
        )
    enterprise = await _get_release(db, m.enterprise_release_id, user.active_tenant_id)
    project = await _get_release(db, m.project_release_id, user.active_tenant_id)

    await _check_action_permission(db, enterprise, user, "membership.admit")

    # Double-check no other accepted exists (race protection; partial unique also enforces in PG)
    existing = (
        await db.execute(
            select(ReleaseMembership).where(
                ReleaseMembership.project_release_id == project.id,
                ReleaseMembership.state == MembershipState.ACCEPTED.value,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Project already has an accepted membership",
        )

    tpl = await db.get(LifecycleTemplate, enterprise.lifecycle_template_id)
    m.late_scope = _compute_late_scope(enterprise, tpl)
    m.state = MembershipState.ACCEPTED.value
    m.decided_by = user.id
    m.decided_at = datetime.now(timezone.utc)
    project.parent_release_id = enterprise.id

    await publish_event(
        db,
        event_type="EnterpriseMembershipAccepted",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={
            "membership_id": m.id,
            "project_release_id": project.id,
            "actor_id": user.id,
            "late_scope": m.late_scope,
        },
        tenant_id=user.active_tenant_id,
    )
    return m


async def reject(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
    notes: str,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.PENDING_REQUEST.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot reject",
        )
    enterprise = await _get_release(db, m.enterprise_release_id, user.active_tenant_id)
    await _check_action_permission(db, enterprise, user, "membership.reject")

    m.state = MembershipState.REJECTED.value
    m.decided_by = user.id
    m.decided_at = datetime.now(timezone.utc)
    m.notes = notes
    await publish_event(
        db,
        event_type="EnterpriseMembershipRejected",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={"membership_id": m.id, "actor_id": user.id, "notes": notes},
        tenant_id=user.active_tenant_id,
    )
    return m


async def withdraw(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.PENDING_REQUEST.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot withdraw",
        )
    user_role_name = getattr(user.role, "name", user.role) if hasattr(user, "role") else None
    if m.requested_by != user.id and user_role_name != "Admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the requester or a tenant admin can withdraw",
        )
    m.state = MembershipState.WITHDRAWN.value
    m.decided_by = user.id
    m.decided_at = datetime.now(timezone.utc)
    await publish_event(
        db,
        event_type="EnterpriseMembershipWithdrawn",
        aggregate_id=m.enterprise_release_id,
        aggregate_type="Release",
        payload={"membership_id": m.id, "actor_id": user.id},
        tenant_id=user.active_tenant_id,
    )
    return m


async def remove(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
    reason: str,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.ACCEPTED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot remove",
        )
    enterprise = await _get_release(db, m.enterprise_release_id, user.active_tenant_id)
    project = await _get_release(db, m.project_release_id, user.active_tenant_id)
    await _check_action_permission(db, enterprise, user, "membership.remove")

    project.parent_release_id = None
    m.state = MembershipState.REMOVED.value
    m.removed_by = user.id
    m.removed_at = datetime.now(timezone.utc)
    m.removal_reason = reason
    await publish_event(
        db,
        event_type="EnterpriseMembershipRemoved",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={
            "membership_id": m.id,
            "project_release_id": project.id,
            "actor_id": user.id,
            "reason": reason,
        },
        tenant_id=user.active_tenant_id,
    )
    return m
