"""Release service — CRUD + lifecycle transition.

All state-changing operations publish outbox events via publish_event()
inside the same transaction. Never call db.commit() here — get_db handles it.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release, ReleaseStatusHistory
from app.services import lifecycle_service
from app.api.v1.schemas.release import ReleaseCreate, ReleaseUpdate
from app.api.v1.schemas.booking_lifecycle import ENTITY_FIELD_SPECS
from app.services.custom_field_service import get_active_field_keys


# Deferred import to avoid circular dependency: release_event_service imports nothing from here.
# Import at call-site inside update_release.

# ── Terminal states that indicate the release was deployed ───────────────────
_DEPLOYED_TERMINAL_STATES = {"completed", "completed_with_issues"}

SCOPE_SIGNOFF_GATE_NAME = "Scope Sign-off"
_SCOPE_SIGNOFF_CRITERION_TITLE = "Scope signed off"


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _resolve_lifecycle_template(
    db: AsyncSession, lifecycle_template_id: Optional[int], tenant_id: int, release_kind: str
) -> LifecycleTemplate:
    """Return the requested lifecycle template, or the tenant's default for 'release'.

    Validates that the template's applies_to_kind is NULL (universal) or matches
    the release's kind.  A mismatch raises HTTP 422.
    """
    if lifecycle_template_id is not None:
        tpl = (
            await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.id == lifecycle_template_id,
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.entity_type == "release",
                    LifecycleTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if tpl is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "lifecycle_template_id must refer to an active release lifecycle template for this tenant",
            )
        # Enforce kind match
        if tpl.applies_to_kind is not None and tpl.applies_to_kind != release_kind:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Lifecycle template's applies_to_kind={tpl.applies_to_kind} does not match release kind {release_kind}",
            )
        return tpl

    # Fall back to tenant default: prefer kind-specific default, then universal default
    kind_specific_tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == "release",
                LifecycleTemplate.is_default.is_(True),
                LifecycleTemplate.applies_to_kind == release_kind,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if kind_specific_tpl is not None:
        return kind_specific_tpl

    universal_tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == "release",
                LifecycleTemplate.is_default.is_(True),
                LifecycleTemplate.applies_to_kind.is_(None),
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if universal_tpl is not None:
        return universal_tpl

    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "No default release lifecycle template found for this tenant. "
        "Provide lifecycle_template_id explicitly or seed defaults.",
    )


async def _get_release(db: AsyncSession, release_id: int, tenant_id: int) -> Release:
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
    return release


async def _find_scope_signoff_gate(db: AsyncSession, release_id: int, tenant_id: int):
    from app.db.models.release_gate import ReleaseGate
    return (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.name == SCOPE_SIGNOFF_GATE_NAME,
                ReleaseGate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _ensure_scope_signoff_gate(
    db: AsyncSession, release: Release, tenant_id: int, user_id: int
) -> None:
    """Idempotently create the Scope Sign-off gate + its role-assigned criterion.
    No-op if a gate with that name already exists on the release."""
    from app.core.security import Role
    from app.services import release_gate_service, gate_criterion_service
    from app.api.v1.schemas.release_gate import ReleaseGateCreate
    from app.api.v1.schemas.gate_criterion import GateCriterionCreate

    if release.scope_deadline is None:
        return
    if await _find_scope_signoff_gate(db, release.id, tenant_id) is not None:
        return

    gate = await release_gate_service.create_gate(
        db, release.id,
        ReleaseGateCreate(name=SCOPE_SIGNOFF_GATE_NAME, due_date=release.scope_deadline),
        tenant_id,
    )
    await gate_criterion_service.create_criterion(
        db, gate_id=gate.id, tenant_id=tenant_id, user_id=user_id,
        data=GateCriterionCreate(
            title=_SCOPE_SIGNOFF_CRITERION_TITLE,
            assigned_role=Role.RELEASE_MANAGER,
        ),
    )


async def _sync_scope_signoff_due_date(
    db: AsyncSession, release: Release, tenant_id: int
) -> None:
    """If a pending Scope Sign-off gate exists, re-sync its due_date to the
    current scope_deadline. Decided gates are left untouched."""
    if release.scope_deadline is None:
        return
    gate = await _find_scope_signoff_gate(db, release.id, tenant_id)
    if gate is not None and gate.status == "pending":
        gate.due_date = release.scope_deadline
        await db.flush()


# ── Public API ───────────────────────────────────────────────────────────────

async def create_release(
    db: AsyncSession,
    data: ReleaseCreate,
    tenant_id: int,
    user_id: int,
) -> Release:
    tpl = await _resolve_lifecycle_template(db, data.lifecycle_template_id, tenant_id, data.release_kind)

    if data.scope_deadline is not None and data.release_kind == "enterprise":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "scope_deadline is only valid on project releases",
        )

    release = Release(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        release_type=data.release_type,
        release_kind=data.release_kind,
        template_id=data.template_id,
        lifecycle_template_id=tpl.id,
        status="draft",
        target_date=data.target_date,
        scope_deadline=data.scope_deadline,
        custom_fields=data.custom_fields,
        raised_by=user_id,
    )
    db.add(release)
    await db.flush()

    # Status history: initial entry (from=None, to='draft')
    db.add(
        ReleaseStatusHistory(
            release_id=release.id,
            from_state=None,
            to_state="draft",
            changed_by=user_id,
            changed_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseCreated",
        aggregate_id=release.id,
        aggregate_type="Release",
        payload={
            "id": release.id,
            "name": release.name,
            "release_type": release.release_type,
            "release_kind": release.release_kind,
            "status": release.status,
            "lifecycle_template_id": release.lifecycle_template_id,
        },
        tenant_id=tenant_id,
    )

    await _ensure_scope_signoff_gate(db, release, tenant_id, user_id)

    return release


async def list_releases(
    db: AsyncSession,
    tenant_id: int,
    *,
    release_type: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    has_dependency_alert: Optional[bool] = None,
    owner_id: Optional[int] = None,
    search: Optional[str] = None,
    release_kind: Optional[str] = None,
    system_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    sort: Optional[Sort] = None,
) -> tuple[list[Release], int]:
    base_where = [
        Release.tenant_id == tenant_id,
        Release.deleted_at.is_(None),
    ]

    if release_type is not None:
        base_where.append(Release.release_type == release_type)
    if status is not None:
        base_where.append(Release.status == status)
    if release_kind is not None:
        base_where.append(Release.release_kind == release_kind)
    if system_id is not None:
        from app.db.models.release_system import ReleaseSystem
        base_where.append(
            Release.id.in_(
                select(ReleaseSystem.release_id).where(
                    ReleaseSystem.system_id == system_id,
                    ReleaseSystem.tenant_id == tenant_id,
                )
            )
        )
    if date_from is not None:
        base_where.append(Release.target_date >= date_from)
    if date_to is not None:
        base_where.append(Release.target_date <= date_to)
    if owner_id is not None:
        base_where.append(Release.raised_by == owner_id)
    if search is not None:
        base_where.append(Release.name.ilike(f"%{search}%"))

    count_stmt = select(func.count()).select_from(Release).where(*base_where)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        apply_sort(select(Release).where(*base_where), sort)
        .order_by(Release.created_at.desc(), Release.id)
        .limit(limit)
        .offset(offset)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, total


async def get_release(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> Release:
    return await _get_release(db, release_id, tenant_id)


async def update_release(
    db: AsyncSession,
    release_id: int,
    data: ReleaseUpdate,
    tenant_id: int,
    user_id: int,
) -> Release:
    release = await _get_release(db, release_id, tenant_id)

    # Check if target_date is changing on a non-draft release
    target_date_changed = (
        data.target_date is not None
        and release.target_date != data.target_date
        and release.status != "draft"
    )
    old_target_date = release.target_date
    old_scope_deadline = release.scope_deadline

    update_data = data.model_dump(exclude_unset=True)

    if (
        "scope_deadline" in update_data
        and update_data["scope_deadline"] is not None
        and release.release_kind == "enterprise"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "scope_deadline is only valid on project releases",
        )

    for field, value in update_data.items():
        setattr(release, field, value)

    await db.flush()
    await db.refresh(release)

    if target_date_changed:
        from app.services import release_event_service
        await release_event_service.record_auto_event(
            db,
            release_id=release.id,
            tenant_id=tenant_id,
            user_id=user_id,
            event_type_name="Reschedule Reason",
            description=f"target_date: {old_target_date} → {release.target_date}",
        )

    if "scope_deadline" in update_data:
        new_deadline = release.scope_deadline
        if old_scope_deadline is None and new_deadline is not None:
            await _ensure_scope_signoff_gate(db, release, tenant_id, user_id)
        elif (
            old_scope_deadline is not None
            and new_deadline is not None
            and old_scope_deadline != new_deadline
        ):
            await _sync_scope_signoff_due_date(db, release, tenant_id)
        # cleared (set -> None): keep the gate, do nothing

    return release


async def transition_release(
    db: AsyncSession,
    release_id: int,
    to_state: str,
    notes: Optional[str],
    tenant_id: int,
    user_id: int,
    user_role: str,
) -> Release:
    release = await _get_release(db, release_id, tenant_id)

    # Load the lifecycle template (tenant-scoped)
    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == release.lifecycle_template_id,
                LifecycleTemplate.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Release lifecycle template not found",
        )

    # Build record_values for required_fields check
    record_values = {
        "name": release.name,
        "description": release.description,
        "release_type": release.release_type,
        "target_date": release.target_date,
        "actual_date": release.actual_date,
        "raised_by": release.raised_by,
        "custom_fields": release.custom_fields or {},
    }

    allowed, reason = lifecycle_service.validate_transition(
        tpl.definition,
        release.status,
        to_state,
        user_role,
        record_values,
    )
    if not allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, reason)

    old_state = release.status
    release.status = to_state

    # Stamp actual_date when transitioning to a deployed terminal state (only once)
    if to_state in _DEPLOYED_TERMINAL_STATES and release.actual_date is None:
        release.actual_date = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(release)

    # Status history entry
    db.add(
        ReleaseStatusHistory(
            release_id=release.id,
            from_state=old_state,
            to_state=to_state,
            changed_by=user_id,
            changed_at=datetime.now(timezone.utc),
            notes=notes,
        )
    )
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseStateChanged",
        aggregate_id=release.id,
        aggregate_type="Release",
        payload={
            "id": release.id,
            "name": release.name,
            "from_state": old_state,
            "to_state": to_state,
            "notes": notes,
        },
        tenant_id=tenant_id,
    )

    return release


async def delete_release(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    user_id: int = 0,
) -> None:
    release = await _get_release(db, release_id, tenant_id)
    now = datetime.now(timezone.utc)

    # Drop attached, non-deleted scope items to the backlog so they remain
    # available for re-prioritisation into a future release. FK ON DELETE
    # SET NULL would handle physical deletes, but release deletion is soft —
    # so we null out release_id explicitly here and log the unlink as
    # release-history for each affected scope item.
    from app.db.models.release_change import ReleaseChange
    from app.db.models.release_change_history import ReleaseChangeReleaseHistory

    attached_rows = (
        await db.execute(
            select(ReleaseChange).where(
                ReleaseChange.release_id == release_id,
                ReleaseChange.tenant_id == tenant_id,
                ReleaseChange.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    for scope_item in attached_rows:
        db.add(
            ReleaseChangeReleaseHistory(
                tenant_id=tenant_id,
                change_id=scope_item.id,
                from_release_id=release_id,
                to_release_id=None,
                moved_at=now,
                moved_by=user_id or None,
                notes=f"Release '{release.name}' deleted; scope item returned to backlog.",
            )
        )
        scope_item.release_id = None

    release.deleted_at = now
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseDeleted",
        aggregate_id=release.id,
        aggregate_type="Release",
        payload={"id": release.id, "name": release.name},
        tenant_id=tenant_id,
    )


async def get_release_field_permissions(
    db: AsyncSession, release: Release, user_role: str
) -> dict:
    """Return {custom_field_permissions, standard_field_permissions} for this release.

    Loads the release's lifecycle template and the tenant's active release
    custom-field definitions, then delegates to lifecycle_service. Fail-closed
    if the template can't be loaded (empty custom map, all-not-editable standard
    map)."""
    template = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == release.lifecycle_template_id
            )
        )
    ).scalar_one_or_none()

    valid_standard = ENTITY_FIELD_SPECS["release"]["valid"]

    if template is None:
        return {
            "custom_field_permissions": {},
            "standard_field_permissions": {f: {"editable": False} for f in valid_standard},
        }

    active_keys = await get_active_field_keys(db, release.tenant_id, "release")
    return lifecycle_service.get_field_permissions_for_state(
        template.definition,
        release.status,
        user_role,
        active_keys,
        valid_standard,
    )


async def list_release_history(
    db: AsyncSession,
    release_id: int,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseStatusHistory], int]:
    """Lifecycle state-change history for a release, oldest first.

    No tenant predicate: release_status_history has no tenant_id column — it is
    scoped through its release, and callers must check that with
    _require_release before calling here.
    """
    query = (
        select(ReleaseStatusHistory)
        .where(ReleaseStatusHistory.release_id == release_id)
        .order_by(ReleaseStatusHistory.changed_at.asc(), ReleaseStatusHistory.id)
    )
    return await fetch_page(db, query, page)
