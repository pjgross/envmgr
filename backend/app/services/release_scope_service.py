"""Release scope service — ReleaseChange CRUD + moves + history.

- Rows with source='jira' reject edits to title/description/external_status/external_key
  AND reject manual moves (release_id is owned by EnvManager, but Jira-sourced
  items are treated as read-only for release membership too per design).
- Always allow system_id + custom_fields edits.
- Emits 'Scope Change' release events when release is past 'approved' AND
  the change_kind has scope_change_kind_rule.counts_as_scope_change=True.
- Records every release_id change (including initial assign + unlinks) in
  release_change_release_history.
- Records every external_status change in release_change_status_history.

Never calls db.commit().
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.services import custom_field_service, scope_change_rule_service
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_change_history import (
    ReleaseChangeReleaseHistory,
    ReleaseChangeStatusHistory,
)
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.api.v1.schemas.release_change import ReleaseChangeCreate, ReleaseChangeUpdate

# Statuses where the release is considered "post-approval"
_POST_APPROVAL_STATUSES = {
    "approved", "in_progress", "ready_for_release",
    "completed", "completed_with_issues", "backed_out",
}

# Fields that are read-only for jira-sourced items (via PUT)
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


async def _record_release_move(
    db: AsyncSession,
    change: ReleaseChange,
    from_release_id: Optional[int],
    to_release_id: Optional[int],
    user_id: int,
    notes: Optional[str] = None,
) -> ReleaseChangeReleaseHistory:
    """Insert an immutable release-history row. No-op guard is the caller's
    responsibility (we don't assume same-release updates should be skipped —
    create uses `from=None → to=X`, where same=same isn't meaningful)."""
    row = ReleaseChangeReleaseHistory(
        tenant_id=change.tenant_id,
        change_id=change.id,
        from_release_id=from_release_id,
        to_release_id=to_release_id,
        moved_at=datetime.now(timezone.utc),
        moved_by=user_id or None,
        notes=notes,
    )
    db.add(row)
    await db.flush()
    return row


async def _record_status_change(
    db: AsyncSession,
    change: ReleaseChange,
    from_status: Optional[str],
    to_status: Optional[str],
    user_id: int,
    notes: Optional[str] = None,
) -> Optional[ReleaseChangeStatusHistory]:
    """Insert a status-history row. Returns None and writes nothing if
    from_status == to_status (idempotent no-op)."""
    if from_status == to_status:
        return None
    row = ReleaseChangeStatusHistory(
        tenant_id=change.tenant_id,
        change_id=change.id,
        from_status=from_status,
        to_status=to_status,
        changed_at=datetime.now(timezone.utc),
        changed_by=user_id or None,
        notes=notes,
    )
    db.add(row)
    await db.flush()
    return row


async def _maybe_emit_scope_change_event(
    db: AsyncSession,
    release_id: Optional[int],
    tenant_id: int,
    user_id: int,
    description: str,
    release_status: Optional[str],
    change_kind: Optional[str],
    rules: Optional[dict[str, bool]] = None,
) -> None:
    """Emit a Scope Change event iff:
      - release_id is not None (we have a release to attach the event to)
      - release is past the 'approved' threshold
      - the change_kind has counts_as_scope_change=True in this tenant's rules
    Caller may pass a preloaded rules map to avoid extra queries; if omitted
    we load it here."""
    if release_id is None:
        return
    if release_status not in _POST_APPROVAL_STATUSES:
        return

    if rules is None:
        rules = await scope_change_rule_service.load_rule_map(db, tenant_id)
    if not scope_change_rule_service.counts_for_kind(rules, change_kind):
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
    release_id: Optional[int],
    tenant_id: int,
    backlog: bool = False,
) -> list[ReleaseChange]:
    """List scope items. Pass `release_id` for a specific release; pass
    `backlog=True` for unassigned items (release_id IS NULL)."""
    stmt = select(ReleaseChange).where(
        ReleaseChange.tenant_id == tenant_id,
        ReleaseChange.deleted_at.is_(None),
    )
    if backlog:
        stmt = stmt.where(ReleaseChange.release_id.is_(None))
    elif release_id is not None:
        stmt = stmt.where(ReleaseChange.release_id == release_id)
    stmt = stmt.order_by(ReleaseChange.id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


async def list_release_history(
    db: AsyncSession, change_id: int, tenant_id: int
) -> list[ReleaseChangeReleaseHistory]:
    """Chronological release-move history for a scope item."""
    await _get_change(db, change_id, tenant_id)  # tenant-scope + 404 check
    rows = (
        await db.execute(
            select(ReleaseChangeReleaseHistory).where(
                ReleaseChangeReleaseHistory.change_id == change_id,
                ReleaseChangeReleaseHistory.tenant_id == tenant_id,
            ).order_by(ReleaseChangeReleaseHistory.moved_at, ReleaseChangeReleaseHistory.id)
        )
    ).scalars().all()
    return list(rows)


async def list_status_history(
    db: AsyncSession, change_id: int, tenant_id: int
) -> list[ReleaseChangeStatusHistory]:
    """Chronological external_status history for a scope item."""
    await _get_change(db, change_id, tenant_id)  # tenant-scope + 404 check
    rows = (
        await db.execute(
            select(ReleaseChangeStatusHistory).where(
                ReleaseChangeStatusHistory.change_id == change_id,
                ReleaseChangeStatusHistory.tenant_id == tenant_id,
            ).order_by(ReleaseChangeStatusHistory.changed_at, ReleaseChangeStatusHistory.id)
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
    rules = await scope_change_rule_service.load_rule_map(db, tenant_id)

    # Validate custom_fields against definitions for this change_kind.
    defs = await custom_field_service.list_definitions_for_subtype(
        db, tenant_id, "release_change", data.change_kind,
    )
    visible_keys = {d.field_key for d in defs}
    await custom_field_service.validate_custom_fields(
        db, tenant_id, "release_change", data.custom_fields, visible_field_keys=visible_keys,
    )

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

    # History: initial release assignment (from=None → to=release_id).
    await _record_release_move(db, change, None, release_id, user_id)
    # History: initial external_status if provided.
    if data.external_status:
        await _record_status_change(db, change, None, data.external_status, user_id)

    await publish_event(
        db,
        event_type="ReleaseScopeItemAdded",
        aggregate_id=change.id,
        aggregate_type="ReleaseChange",
        payload={
            "id": change.id,
            "release_id": release_id,
            "title": change.title,
            "change_kind": change.change_kind,
            "source": change.source,
        },
        tenant_id=tenant_id,
    )

    await _maybe_emit_scope_change_event(
        db, release_id, tenant_id, user_id,
        f"Scope item added: '{change.title}'",
        release_status,
        change.change_kind,
        rules=rules,
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

    # If custom_fields are being updated, re-validate against the current change_kind.
    if "custom_fields" in update_data:
        defs = await custom_field_service.list_definitions_for_subtype(
            db, tenant_id, "release_change", change.change_kind,
        )
        visible_keys = {d.field_key for d in defs}
        await custom_field_service.validate_custom_fields(
            db, tenant_id, "release_change", update_data["custom_fields"],
            visible_field_keys=visible_keys,
        )

    # Record external_status history if it's changing.
    previous_status = change.external_status
    status_changed = (
        "external_status" in update_data
        and update_data["external_status"] != previous_status
    )

    for field, value in update_data.items():
        setattr(change, field, value)
    await db.flush()

    if status_changed:
        await _record_status_change(
            db, change, previous_status, change.external_status, user_id,
        )

    # Release status lookup + scope-change emit only when item is actually
    # attached to a release. Backlog items (release_id IS NULL) skip this.
    release_status: Optional[str] = None
    if change.release_id is not None:
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
            "change_kind": change.change_kind,
        },
        tenant_id=tenant_id,
    )

    await _maybe_emit_scope_change_event(
        db, change.release_id, tenant_id, user_id,
        f"Scope item updated: '{change.title}'",
        release_status,
        change.change_kind,
    )

    return change


async def move_change(
    db: AsyncSession,
    change_id: int,
    to_release_id: Optional[int],
    tenant_id: int,
    user_id: int,
    notes: Optional[str] = None,
) -> ReleaseChange:
    """Move a scope item to a different release, or to the backlog (None).

    - 422 for jira-sourced items (release membership is Jira's responsibility).
    - 422 if target release is in a different tenant.
    - Idempotent: same release → no-op, returns the row unchanged.
    - Records a release-history row and publishes ReleaseScopeItemMoved.
    - Emits scope-change release events on source + target (each gated
      independently by release status and the kind rule).
    """
    change = await _get_change(db, change_id, tenant_id)

    if change.source == "jira":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Cannot move jira-sourced scope items",
        )

    from_release_id = change.release_id
    if from_release_id == to_release_id:
        return change  # idempotent no-op

    # Verify target release exists + in-tenant (when not unlinking).
    target_status: Optional[str] = None
    if to_release_id is not None:
        target_status = await _get_release_status(db, to_release_id, tenant_id)

    # Source status (for the outbound scope-change event). May be None if the
    # item was in the backlog or the source release got deleted.
    source_status: Optional[str] = None
    if from_release_id is not None:
        source_status = await _get_release_status(db, from_release_id, tenant_id)

    rules = await scope_change_rule_service.load_rule_map(db, tenant_id)

    change.release_id = to_release_id
    await db.flush()

    await _record_release_move(
        db, change, from_release_id, to_release_id, user_id, notes=notes,
    )

    await publish_event(
        db,
        event_type="ReleaseScopeItemMoved",
        aggregate_id=change.id,
        aggregate_type="ReleaseChange",
        payload={
            "id": change.id,
            "title": change.title,
            "change_kind": change.change_kind,
            "from_release_id": from_release_id,
            "to_release_id": to_release_id,
        },
        tenant_id=tenant_id,
    )

    # Scope-change event on the source release (item leaving).
    if from_release_id is not None:
        await _maybe_emit_scope_change_event(
            db, from_release_id, tenant_id, user_id,
            f"Scope item moved out: '{change.title}'",
            source_status,
            change.change_kind,
            rules=rules,
        )
    # Scope-change event on the target release (item arriving).
    if to_release_id is not None:
        await _maybe_emit_scope_change_event(
            db, to_release_id, tenant_id, user_id,
            f"Scope item moved in: '{change.title}'",
            target_status,
            change.change_kind,
            rules=rules,
        )

    return change


async def delete_change(
    db: AsyncSession,
    change_id: int,
    tenant_id: int,
    user_id: int = 0,
) -> None:
    change = await _get_change(db, change_id, tenant_id)
    release_status: Optional[str] = None
    if change.release_id is not None:
        release_status = await _get_release_status(db, change.release_id, tenant_id)

    change.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseScopeItemRemoved",
        aggregate_id=change.id,
        aggregate_type="ReleaseChange",
        payload={
            "id": change.id,
            "release_id": change.release_id,
            "change_kind": change.change_kind,
        },
        tenant_id=tenant_id,
    )

    await _maybe_emit_scope_change_event(
        db, change.release_id, tenant_id, user_id,
        f"Scope item removed: '{change.title}'",
        release_status,
        change.change_kind,
    )
