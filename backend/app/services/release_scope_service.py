"""Release scope service — ReleaseChange CRUD with source-aware edit rules.

- Rows with source='jira' reject edits to title/description/external_status/external_key.
- Always allow system_id + custom_fields edits.
- Emits 'Scope Change' event when release is past 'approved' status.
Never calls db.commit().
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.api.v1.schemas.release_change import ReleaseChangeCreate, ReleaseChangeUpdate

# Statuses where the release is considered "post-approval"
_POST_APPROVAL_STATUSES = {
    "approved", "in_progress", "ready_for_release",
    "completed", "completed_with_issues", "backed_out",
}

# Fields that are read-only for jira-sourced items
_JIRA_READONLY_FIELDS = {"external_key", "title", "description", "external_status"}


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _get_change(
    db: AsyncSession, change_id: int, tenant_id: int
) -> ReleaseChange:
    row = (
        await db.execute(
            select(ReleaseChange).where(
                ReleaseChange.id == change_id,
                ReleaseChange.tenant_id == tenant_id,
                ReleaseChange.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release change not found")
    return row


async def _get_release_status(
    db: AsyncSession, release_id: int, tenant_id: int
) -> str:
    release = (
        await db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release not found")
    return release.status


async def _maybe_emit_scope_change_event(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    user_id: int,
    description: str,
    release_status: str,
) -> None:
    """Emit a Scope Change event if the release is past the 'approved' threshold."""
    if release_status not in _POST_APPROVAL_STATUSES:
        return

    event_type = (
        await db.execute(
            select(ReleaseEventType).where(
                ReleaseEventType.tenant_id == tenant_id,
                ReleaseEventType.name == "Scope Change",
                ReleaseEventType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if event_type is None:
        return

    db.add(
        ReleaseEvent(
            tenant_id=tenant_id,
            release_id=release_id,
            event_type_id=event_type.id,
            description=description,
            occurred_at=datetime.now(timezone.utc),
            recorded_by=user_id,
        )
    )
    await db.flush()


# ── Public API ───────────────────────────────────────────────────────────────

async def list_changes(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[ReleaseChange]:
    rows = (
        await db.execute(
            select(ReleaseChange).where(
                ReleaseChange.release_id == release_id,
                ReleaseChange.tenant_id == tenant_id,
                ReleaseChange.deleted_at.is_(None),
            ).order_by(ReleaseChange.id)
        )
    ).scalars().all()
    return list(rows)


async def create_change(
    db: AsyncSession,
    release_id: int,
    data: ReleaseChangeCreate,
    tenant_id: int,
    user_id: int = 0,
) -> ReleaseChange:
    release_status = await _get_release_status(db, release_id, tenant_id)

    change = ReleaseChange(
        tenant_id=tenant_id,
        release_id=release_id,
        external_key=data.external_key,
        title=data.title,
        description=data.description,
        change_kind=data.change_kind,
        external_status=data.external_status,
        system_id=data.system_id,
        custom_fields=data.custom_fields,
        source="manual",
    )
    db.add(change)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseScopeItemAdded",
        aggregate_id=change.id,
        aggregate_type="ReleaseChange",
        payload={
            "id": change.id,
            "release_id": release_id,
            "title": change.title,
            "source": change.source,
        },
        tenant_id=tenant_id,
    )

    await _maybe_emit_scope_change_event(
        db, release_id, tenant_id, user_id,
        f"Scope item added: '{change.title}'",
        release_status,
    )

    return change


async def update_change(
    db: AsyncSession,
    change_id: int,
    data: ReleaseChangeUpdate,
    tenant_id: int,
    user_id: int = 0,
) -> ReleaseChange:
    change = await _get_change(db, change_id, tenant_id)

    update_data = data.model_dump(exclude_unset=True)

    # Reject edits to read-only fields for jira-sourced items
    if change.source == "jira":
        bad_fields = _JIRA_READONLY_FIELDS & set(update_data.keys())
        if bad_fields:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Cannot edit fields {sorted(bad_fields)} on a jira-sourced change item",
            )

    for field, value in update_data.items():
        setattr(change, field, value)
    await db.flush()

    release_status = await _get_release_status(db, change.release_id, tenant_id)

    await publish_event(
        db,
        event_type="ReleaseScopeItemUpdated",
        aggregate_id=change.id,
        aggregate_type="ReleaseChange",
        payload={
            "id": change.id,
            "release_id": change.release_id,
            "title": change.title,
        },
        tenant_id=tenant_id,
    )

    await _maybe_emit_scope_change_event(
        db, change.release_id, tenant_id, user_id,
        f"Scope item updated: '{change.title}'",
        release_status,
    )

    return change


async def delete_change(
    db: AsyncSession,
    change_id: int,
    tenant_id: int,
    user_id: int = 0,
) -> None:
    change = await _get_change(db, change_id, tenant_id)
    release_status = await _get_release_status(db, change.release_id, tenant_id)

    change.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseScopeItemRemoved",
        aggregate_id=change.id,
        aggregate_type="ReleaseChange",
        payload={"id": change.id, "release_id": change.release_id},
        tenant_id=tenant_id,
    )

    await _maybe_emit_scope_change_event(
        db, change.release_id, tenant_id, user_id,
        f"Scope item removed: '{change.title}'",
        release_status,
    )
