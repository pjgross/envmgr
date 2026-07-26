"""Releases API — CRUD, lifecycle transition, calendar, timeline, history,
and all release sub-resources (phases, gates, systems, dependencies, events,
scope/changes, bookings, linked CRs).

Field-permissions contract (GET/PUT/transition on a single release):
  Responses include `custom_field_permissions` and `standard_field_permissions`
  computed for the caller's role at the release's current state. This mirrors
  the booking endpoints — clients get permissions in a single round-trip and do
  not need to call GET /releases/{id}/lifecycle just to determine editability.
  The dedicated /lifecycle endpoint remains available for clients that need the
  full state-machine definition (e.g. to drive transition UIs).
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, status, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_change import ReleaseChange
from app.db.models.test_phase import TestPhase
from app.services import (
    release_service,
    release_gate_service,
    release_event_service,
    release_dependency_service,
    release_scope_service,
    release_booking_service,
)
from app.api.v1.schemas.release import (
    ReleaseCreate,
    ReleaseUpdate,
    ReleaseRead,
    ReleaseListItemRead,
    ReleaseTransition,
    ReleaseStatusHistoryRead,
)
from app.api.v1.schemas.test_phase import TestPhaseCreate, TestPhaseUpdate, TestPhaseRead
from app.api.v1.schemas.release_gate import (
    ReleaseGateCreate,
    ReleaseGateUpdate,
    ReleaseGateDecision,
    ReleaseGateRead,
)
from app.api.v1.schemas.release_system import ReleaseSystemCreate, ReleaseSystemRead
from app.api.v1.schemas.release_dependency import (
    ReleaseDependencyCreate,
    ReleaseDependencyRead,
    ReleaseDependencyAlert,
)
from app.api.v1.schemas.release_event import (
    ReleaseEventCreate,
    ReleaseEventRead,
)
from app.api.v1.schemas.release_change import (
    ReleaseChangeCreate,
    ReleaseChangeUpdate,
    ReleaseChangeRead,
    ReleaseChangeMovePayload,
    ReleaseChangeReleaseHistoryRead,
    ReleaseChangeStatusHistoryRead,
    ScopeImportResult,
)

router = APIRouter(prefix="/releases", tags=["Releases"])

# ── Additional sub-resource routers mounted at /phases, /gates etc. ──────────
phases_router = APIRouter(prefix="/phases", tags=["Releases"])
gates_router = APIRouter(prefix="/gates", tags=["Releases"])
release_systems_router = APIRouter(prefix="/release-systems", tags=["Releases"])
release_deps_router = APIRouter(prefix="/release-dependencies", tags=["Releases"])
release_changes_router = APIRouter(prefix="/release-changes", tags=["Releases"])


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _require_release(db: AsyncSession, release_id: int, tenant_id: int) -> Release:
    """Return the release or raise 404."""
    return await release_service.get_release(db, release_id, tenant_id)


async def _release_with_permissions(
    db: AsyncSession, release: Release, user_role: str, current_user=None
) -> ReleaseRead:
    """Materialize a ReleaseRead response with permissions attached."""
    from app.services import enterprise_membership_service
    from app.api.v1.schemas.release_membership import MembershipSummary

    perms = await release_service.get_release_field_permissions(db, release, user_role)
    resp = ReleaseRead.model_validate(release)
    resp.custom_field_permissions = perms["custom_field_permissions"]
    resp.standard_field_permissions = perms["standard_field_permissions"]
    if release.release_kind == "enterprise" and current_user is not None:
        summary_dict = await enterprise_membership_service.get_membership_summary(
            db, user=current_user, enterprise_id=release.id
        )
        resp.membership_summary = MembershipSummary(**summary_dict)
    creep = await release_scope_service.scope_creep_counts(db, [release.id], release.tenant_id)
    resp.scope_creep_count = creep.get(release.id, 0)
    return resp


async def _require_phase(db: AsyncSession, phase_id: int, tenant_id: int) -> TestPhase:
    phase = (
        await db.execute(
            select(TestPhase).where(
                TestPhase.id == phase_id,
                TestPhase.tenant_id == tenant_id,
                TestPhase.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if phase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test phase not found")
    return phase


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ReleaseListItemRead])
async def list_releases(
    release_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    owner_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    release_kind: Optional[str] = Query(None, pattern="^(project|enterprise)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    releases, _total = await release_service.list_releases(
        db,
        tenant_id,
        release_type=release_type,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        owner_id=owner_id,
        search=search,
        release_kind=release_kind,
        limit=limit,
        offset=offset,
    )
    if not releases:
        return []
    release_ids = [r.id for r in releases]

    # Phase counts per release
    phase_rows = (
        await db.execute(
            select(TestPhase.release_id, func.count(TestPhase.id).label("cnt"))
            .where(
                TestPhase.release_id.in_(release_ids),
                TestPhase.deleted_at.is_(None),
            )
            .group_by(TestPhase.release_id)
        )
    ).all()
    phase_counts = {row.release_id: row.cnt for row in phase_rows}

    # Scope (change) counts per release
    scope_rows = (
        await db.execute(
            select(ReleaseChange.release_id, func.count(ReleaseChange.id).label("cnt"))
            .where(
                ReleaseChange.release_id.in_(release_ids),
                ReleaseChange.deleted_at.is_(None),
            )
            .group_by(ReleaseChange.release_id)
        )
    ).all()
    scope_counts = {row.release_id: row.cnt for row in scope_rows}

    # Blocker (pending gate) counts per release
    gate_rows = (
        await db.execute(
            select(ReleaseGate.release_id, func.count(ReleaseGate.id).label("cnt"))
            .where(
                ReleaseGate.release_id.in_(release_ids),
                ReleaseGate.status == "pending",
                ReleaseGate.deleted_at.is_(None),
            )
            .group_by(ReleaseGate.release_id)
        )
    ).all()
    gate_counts = {row.release_id: row.cnt for row in gate_rows}

    # Overdue criterion counts per release
    from datetime import datetime, timezone
    from app.db.models.gate_criterion import GateCriterion
    now = datetime.now(timezone.utc)
    overdue_rows = (
        await db.execute(
            select(ReleaseGate.release_id, func.count(GateCriterion.id).label("cnt"))
            .join(GateCriterion, GateCriterion.gate_id == ReleaseGate.id)
            .where(
                ReleaseGate.release_id.in_(release_ids),
                ReleaseGate.deleted_at.is_(None),
                GateCriterion.deleted_at.is_(None),
                GateCriterion.status == "open",
                ReleaseGate.due_date < now,
            )
            .group_by(ReleaseGate.release_id)
        )
    ).all()
    overdue_counts = {row.release_id: row.cnt for row in overdue_rows}

    # Scope-change counts (additions + removals) per release, filtered by
    # scope_change_kind_rule.counts_as_scope_change = True. Two grouped
    # queries, one on to_release_id (additions) and one on from_release_id
    # (removals). The count includes the "initial assignment" history row
    # so a brand-new item's first attach counts as an addition. The join
    # goes through release_change (for change_kind) to scope_change_kind_rule.
    from app.db.models.release_change_history import ReleaseChangeReleaseHistory
    from app.db.models.scope_change_kind_rule import ScopeChangeKindRule

    def _scope_change_stmt(direction_col):
        return (
            select(direction_col, func.count(ReleaseChangeReleaseHistory.id).label("cnt"))
            .join(
                ReleaseChange,
                ReleaseChange.id == ReleaseChangeReleaseHistory.change_id,
            )
            .join(
                ScopeChangeKindRule,
                (ScopeChangeKindRule.tenant_id == ReleaseChange.tenant_id)
                & (ScopeChangeKindRule.change_kind == ReleaseChange.change_kind)
                & (ScopeChangeKindRule.deleted_at.is_(None)),
            )
            .where(
                direction_col.in_(release_ids),
                ReleaseChangeReleaseHistory.tenant_id == tenant_id,
                ReleaseChange.deleted_at.is_(None),
                ScopeChangeKindRule.counts_as_scope_change.is_(True),
            )
            .group_by(direction_col)
        )

    addition_rows = (
        await db.execute(_scope_change_stmt(ReleaseChangeReleaseHistory.to_release_id))
    ).all()
    additions = {row[0]: row[1] for row in addition_rows}

    removal_rows = (
        await db.execute(_scope_change_stmt(ReleaseChangeReleaseHistory.from_release_id))
    ).all()
    removals = {row[0]: row[1] for row in removal_rows}

    creep_counts = await release_scope_service.scope_creep_counts(db, release_ids, tenant_id)

    result = []
    for r in releases:
        item = ReleaseListItemRead.model_validate(r)
        item.phase_count = phase_counts.get(r.id, 0)
        item.scope_count = scope_counts.get(r.id, 0)
        item.blocker_count = gate_counts.get(r.id, 0)
        item.overdue_criterion_count = overdue_counts.get(r.id, 0)
        adds = additions.get(r.id, 0)
        rems = removals.get(r.id, 0)
        item.scope_additions_count = adds
        item.scope_removals_count = rems
        item.scope_change_count = adds + rems
        item.scope_creep_count = creep_counts.get(r.id, 0)
        result.append(item)
    return result


@router.post("", response_model=ReleaseRead, status_code=status.HTTP_201_CREATED)
async def create_release(
    data: ReleaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await release_service.create_release(
        db, data, tenant_id, current_user.id
    )
    return release


@router.get("/calendar")
async def get_releases_calendar(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return releases formatted for FullCalendar consumption.

    Each entry has: id, title (=name), start (=target_date), status, release_type.
    Releases without a target_date are omitted.
    """
    tenant_id = current_user.active_tenant_id
    releases, _total = await release_service.list_releases(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        limit=500,
        offset=0,
    )
    return [
        {
            "id": r.id,
            "title": r.name,
            "start": r.target_date.isoformat() if r.target_date else None,
            "end": r.actual_date.isoformat() if r.actual_date else None,
            "status": r.status,
            "release_type": r.release_type,
        }
        for r in releases
        if r.target_date is not None
    ]


@router.get("/timeline")
async def get_releases_timeline(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return releases with their test phases for Gantt / timeline rendering.

    Each entry has: release fields + phases list.
    """
    tenant_id = current_user.active_tenant_id
    releases, _total = await release_service.list_releases(
        db,
        tenant_id,
        date_from=date_from,
        date_to=date_to,
        limit=500,
        offset=0,
    )

    from app.db.models.release_dependency import ReleaseDependency

    result = []
    for r in releases:
        phases = (
            await db.execute(
                select(TestPhase).where(
                    TestPhase.release_id == r.id,
                    TestPhase.tenant_id == tenant_id,
                    TestPhase.deleted_at.is_(None),
                ).order_by(TestPhase.order)
            )
        ).scalars().all()
        dependencies = (
            await db.execute(
                select(ReleaseDependency).where(
                    ReleaseDependency.release_id == r.id,
                    ReleaseDependency.tenant_id == tenant_id,
                )
            )
        ).scalars().all()
        gates = (
            await db.execute(
                select(ReleaseGate).where(
                    ReleaseGate.release_id == r.id,
                    ReleaseGate.tenant_id == tenant_id,
                    ReleaseGate.deleted_at.is_(None),
                ).order_by(ReleaseGate.due_date)
            )
        ).scalars().all()
        result.append(
            {
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "release_type": r.release_type,
                "target_date": r.target_date.isoformat() if r.target_date else None,
                "actual_date": r.actual_date.isoformat() if r.actual_date else None,
                "phases": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "order": p.order,
                        "start_date": p.start_date.isoformat() if p.start_date else None,
                        "end_date": p.end_date.isoformat() if p.end_date else None,
                        "status": p.status,
                    }
                    for p in phases
                ],
                "dependencies": [
                    {
                        "id": d.id,
                        "tenant_id": d.tenant_id,
                        "release_id": d.release_id,
                        "depends_on_release_id": d.depends_on_release_id,
                        "kind": d.kind,
                        "notes": d.notes,
                        "last_dependency_target_date": (
                            d.last_dependency_target_date.isoformat()
                            if d.last_dependency_target_date else None
                        ),
                    }
                    for d in dependencies
                ],
                "gates": [
                    {
                        "id": g.id,
                        "name": g.name,
                        "due_date": g.due_date.isoformat(),
                        "status": g.status,
                    }
                    for g in gates
                ],
            }
        )
    return result


@router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return a single release with field_permissions attached for the caller's role."""
    tenant_id = current_user.active_tenant_id
    release = await _require_release(db, release_id, tenant_id)
    return await _release_with_permissions(db, release, current_user.role, current_user)


@router.put("/{release_id}", response_model=ReleaseRead)
async def update_release(
    release_id: int,
    data: ReleaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await release_service.update_release(
        db, release_id, data, tenant_id, current_user.id
    )
    return await _release_with_permissions(db, release, current_user.role, current_user)


@router.delete("/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await release_service.delete_release(
        db, release_id, current_user.active_tenant_id, current_user.id
    )


@router.post("/{release_id}/transition", response_model=ReleaseRead)
async def transition_release(
    release_id: int,
    data: ReleaseTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await release_service.transition_release(
        db,
        release_id,
        to_state=data.to_state,
        notes=data.notes,
        tenant_id=tenant_id,
        user_id=current_user.id,
        user_role=current_user.role,
    )
    return await _release_with_permissions(db, release, current_user.role, current_user)


@router.get("/{release_id}/lifecycle")
async def get_release_lifecycle(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the lifecycle template (including definition JSON) for a release.

    Used by the frontend ReleaseMainTab to drive TransitionControls and
    LifecycleAwareFieldsPanel without an extra round-trip.
    """
    tenant_id = current_user.active_tenant_id
    release = await _require_release(db, release_id, tenant_id)
    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(LifecycleTemplate.id == release.lifecycle_template_id)
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lifecycle template not found")
    return {
        "id": tpl.id,
        "name": tpl.name,
        "entity_type": tpl.entity_type,
        "is_default": tpl.is_default,
        "definition": tpl.definition,
    }


@router.get("/{release_id}/history", response_model=list[ReleaseStatusHistoryRead])
async def get_release_history(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return lifecycle state-change history for a release."""
    from app.db.models.release import ReleaseStatusHistory
    tenant_id = current_user.active_tenant_id
    # Verify release belongs to tenant first
    await _require_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(ReleaseStatusHistory)
            .where(ReleaseStatusHistory.release_id == release_id)
            .order_by(ReleaseStatusHistory.changed_at.asc())
        )
    ).scalars().all()
    return list(rows)


# ── Phases ────────────────────────────────────────────────────────────────────

@router.get("/{release_id}/phases", response_model=list[TestPhaseRead])
async def list_phases(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(TestPhase).where(
                TestPhase.release_id == release_id,
                TestPhase.tenant_id == tenant_id,
                TestPhase.deleted_at.is_(None),
            ).order_by(TestPhase.order)
        )
    ).scalars().all()
    return list(rows)


@router.post("/{release_id}/phases", response_model=TestPhaseRead, status_code=status.HTTP_201_CREATED)
async def create_phase(
    release_id: int,
    data: TestPhaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    phase = TestPhase(
        tenant_id=tenant_id,
        release_id=release_id,
        name=data.name,
        order=data.order,
        start_date=data.start_date,
        end_date=data.end_date,
        status=data.status,
    )
    db.add(phase)
    await db.flush()
    return phase


@phases_router.put("/{phase_id}", response_model=TestPhaseRead)
async def update_phase(
    phase_id: int,
    data: TestPhaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    phase = await _require_phase(db, phase_id, tenant_id)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(phase, field, value)
    await db.flush()
    return phase


@phases_router.delete("/{phase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from datetime import timezone
    tenant_id = current_user.active_tenant_id
    phase = await _require_phase(db, phase_id, tenant_id)
    phase.deleted_at = datetime.now(timezone.utc)
    await db.flush()


# ── Gates ─────────────────────────────────────────────────────────────────────

@router.get("/{release_id}/gates", response_model=list[ReleaseGateRead])
async def list_gates(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_gate_service.list_gates(db, release_id, tenant_id)


@router.post("/{release_id}/gates", response_model=ReleaseGateRead, status_code=status.HTTP_201_CREATED)
async def create_gate(
    release_id: int,
    data: ReleaseGateCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_gate_service.create_gate(db, release_id, data, tenant_id)


@gates_router.put("/{gate_id}", response_model=ReleaseGateRead)
async def update_gate(
    gate_id: int,
    data: ReleaseGateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_gate_service.update_gate(db, gate_id, data, current_user.active_tenant_id)


@gates_router.delete("/{gate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gate(
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await release_gate_service.delete_gate(db, gate_id, current_user.active_tenant_id)


@gates_router.post("/{gate_id}/pass", response_model=ReleaseGateRead)
async def pass_gate(
    gate_id: int,
    data: ReleaseGateDecision = ReleaseGateDecision(),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_gate_service.pass_gate(
        db, gate_id, data.notes, current_user.active_tenant_id, current_user.id
    )


@gates_router.post("/{gate_id}/fail", response_model=ReleaseGateRead)
async def fail_gate(
    gate_id: int,
    data: ReleaseGateDecision = ReleaseGateDecision(),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_gate_service.fail_gate(
        db, gate_id, data.notes, current_user.active_tenant_id, current_user.id
    )


@gates_router.post("/{gate_id}/override", response_model=ReleaseGateRead)
async def override_gate(
    gate_id: int,
    data: ReleaseGateDecision,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_gate_service.override_gate(
        db, gate_id, data.notes, current_user.active_tenant_id, current_user.id
    )


# ── Systems ───────────────────────────────────────────────────────────────────

@router.get("/{release_id}/systems", response_model=list[ReleaseSystemRead])
async def list_release_systems(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.db.models.release_system import ReleaseSystem
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(ReleaseSystem).where(
                ReleaseSystem.release_id == release_id,
                ReleaseSystem.tenant_id == tenant_id,
            ).order_by(ReleaseSystem.id)
        )
    ).scalars().all()
    return list(rows)


@router.post("/{release_id}/systems", response_model=ReleaseSystemRead, status_code=status.HTTP_201_CREATED)
async def add_release_system(
    release_id: int,
    data: ReleaseSystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.db.models.release_system import ReleaseSystem
    from app.db.models.system import System
    from sqlalchemy.exc import IntegrityError
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)

    # Tenant isolation: the system must belong to this tenant. Prevents
    # linking another tenant's system to this release.
    system_ok = (
        await db.execute(
            select(System.id).where(
                System.id == data.system_id,
                System.tenant_id == tenant_id,
                System.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if system_ok is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "system_id must refer to an active system in this tenant",
        )

    rs = ReleaseSystem(
        tenant_id=tenant_id,
        release_id=release_id,
        system_id=data.system_id,
        role=data.role,
        deployment_date=data.deployment_date,
    )
    db.add(rs)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "System already linked to this release",
        )
    return rs


@release_systems_router.delete("/{rs_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_release_system(
    rs_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.db.models.release_system import ReleaseSystem
    tenant_id = current_user.active_tenant_id
    rs = (
        await db.execute(
            select(ReleaseSystem).where(
                ReleaseSystem.id == rs_id,
                ReleaseSystem.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if rs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release system link not found")
    await db.delete(rs)
    await db.flush()


# ── Dependencies ──────────────────────────────────────────────────────────────

@router.get("/{release_id}/dependencies", response_model=list[ReleaseDependencyRead])
async def list_dependencies(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_dependency_service.list_dependencies(db, release_id, tenant_id)


@router.post("/{release_id}/dependencies", response_model=ReleaseDependencyRead, status_code=status.HTTP_201_CREATED)
async def create_dependency(
    release_id: int,
    data: ReleaseDependencyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_dependency_service.create_dependency(db, release_id, data, tenant_id)


@release_deps_router.delete("/{dep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dependency(
    dep_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await release_dependency_service.delete_dependency(
        db, dep_id, current_user.active_tenant_id
    )


@router.get("/{release_id}/dependency-alerts", response_model=list[ReleaseDependencyAlert])
async def get_dependency_alerts(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_dependency_service.get_dependency_alerts(db, release_id, tenant_id)


@router.post("/{release_id}/dependency-alerts/{dep_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_dependency_alert(
    release_id: int,
    dep_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    await release_dependency_service.acknowledge_alert(db, release_id, dep_id, tenant_id)


# ── Events ────────────────────────────────────────────────────────────────────

@router.get("/{release_id}/events", response_model=list[ReleaseEventRead])
async def list_events(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_event_service.list_events(db, release_id, tenant_id)


@router.post("/{release_id}/events", response_model=ReleaseEventRead, status_code=status.HTTP_201_CREATED)
async def create_event(
    release_id: int,
    data: ReleaseEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_event_service.create_event(db, release_id, data, tenant_id, current_user.id)


# ── Scope / Changes ───────────────────────────────────────────────────────────

@router.get("/{release_id}/changes", response_model=list[ReleaseChangeRead])
async def list_changes(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await _require_release(db, release_id, tenant_id)
    rows = await release_scope_service.list_changes(db, release_id, tenant_id)
    creep_ids = await release_scope_service.scope_creep_change_ids(db, release, tenant_id)
    out: list[ReleaseChangeRead] = []
    for r in rows:
        item = ReleaseChangeRead.model_validate(r)
        item.is_scope_creep = r.id in creep_ids
        out.append(item)
    return out


@router.post("/{release_id}/changes", response_model=ReleaseChangeRead, status_code=status.HTTP_201_CREATED)
async def create_change(
    release_id: int,
    data: ReleaseChangeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_scope_service.create_change(db, release_id, data, tenant_id, current_user.id)


@router.post("/{release_id}/scope/import", response_model=ScopeImportResult)
async def import_scope(
    release_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    from app.services import scope_import_service
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    file_bytes = await file.read()
    return await scope_import_service.import_scope(db, file_bytes, release_id, tenant_id)


@router.get("/scope/import-template")
async def scope_import_template(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    import openpyxl
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from app.services import custom_field_service
    defs = await custom_field_service.list_definitions(
        db, current_user.active_tenant_id, "release_change")
    custom_headers = [d.field_key for d in defs]
    base = ["external_key", "title", "description", "change_kind",
            "external_status", "project_code", "project_name"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(base + custom_headers)
    ws.append(["PAY-1", "Example story", "Optional description", "story",
               "In Progress", "PAY", "Payments Platform"] + [""] * len(custom_headers))
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=scope_import_template.xlsx"},
    )


@release_changes_router.put("/{change_id}", response_model=ReleaseChangeRead)
async def update_change(
    change_id: int,
    data: ReleaseChangeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_scope_service.update_change(
        db, change_id, data, current_user.active_tenant_id, current_user.id
    )


@release_changes_router.delete("/{change_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_change(
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await release_scope_service.delete_change(
        db, change_id, current_user.active_tenant_id, current_user.id
    )


@release_changes_router.get("", response_model=list[ReleaseChangeRead])
async def list_changes_flat(
    backlog: bool = Query(False, description="If true, return unassigned scope items (release_id IS NULL)"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Flat list — primarily the backlog view. Per-release listing is under
    GET /releases/{release_id}/changes."""
    tenant_id = current_user.active_tenant_id
    return await release_scope_service.list_changes(
        db, release_id=None, tenant_id=tenant_id, backlog=backlog,
    )


@release_changes_router.post("/{change_id}/move", response_model=ReleaseChangeRead)
async def move_change(
    change_id: int,
    data: ReleaseChangeMovePayload,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Move a scope item to another release, or to the backlog (release_id=null).
    Jira-sourced items cannot be moved (422)."""
    return await release_scope_service.move_change(
        db,
        change_id=change_id,
        to_release_id=data.release_id,
        tenant_id=current_user.active_tenant_id,
        user_id=current_user.id,
        notes=data.notes,
    )


@release_changes_router.get(
    "/{change_id}/release-history",
    response_model=list[ReleaseChangeReleaseHistoryRead],
)
async def get_release_history(
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_scope_service.list_release_history(
        db, change_id, current_user.active_tenant_id,
    )


@release_changes_router.get(
    "/{change_id}/status-history",
    response_model=list[ReleaseChangeStatusHistoryRead],
)
async def get_status_history(
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_scope_service.list_status_history(
        db, change_id, current_user.active_tenant_id,
    )


# ── Bookings (sub-resource) ───────────────────────────────────────────────────

from pydantic import BaseModel


class ReleaseBookingRequest(BaseModel):
    environment_id: int
    start: datetime
    end: datetime
    booking_type_id: int
    phase_id: Optional[int] = None
    project_name: Optional[str] = None
    notes: Optional[str] = None
    exclusive_use: bool = False


@router.get("/{release_id}/bookings")
async def list_release_bookings(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return bookings linked to this release."""
    from app.db.models.booking import Booking
    from sqlalchemy.orm import selectinload
    from app.db.models.booking_request import BookingRequest

    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(Booking)
            .options(
                selectinload(Booking.environment),
                selectinload(Booking.booking_request).selectinload(BookingRequest.booker),
            )
            .where(
                Booking.release_id == release_id,
                Booking.tenant_id == tenant_id,
                Booking.deleted_at.is_(None),
            )
            .order_by(Booking.start_date.asc())
        )
    ).scalars().all()
    # Return minimal shape — clients use the bookings endpoint for full detail
    return [
        {
            "id": b.id,
            "environment_id": b.environment_id,
            "environment_name": b.environment.name if b.environment else None,
            "project_name": b.booking_request.project_name if b.booking_request else None,
            "start_date": b.start_date.isoformat(),
            "end_date": b.end_date.isoformat(),
            "status": b.status,
            "test_phase_id": b.test_phase_id,
        }
        for b in rows
    ]


@router.post("/{release_id}/bookings", status_code=status.HTTP_201_CREATED)
async def create_release_booking(
    release_id: int,
    data: ReleaseBookingRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a booking linked to this release (and optionally a test phase)."""
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    booking = await release_booking_service.book_environment_for_phase(
        db,
        release_id=release_id,
        phase_id=data.phase_id,
        environment_id=data.environment_id,
        start=data.start,
        end=data.end,
        booking_type_id=data.booking_type_id,
        tenant_id=tenant_id,
        user_id=current_user.id,
        project_name=data.project_name,
        notes=data.notes,
        exclusive_use=data.exclusive_use,
    )
    return {
        "id": booking.id,
        "environment_id": booking.environment_id,
        "start_date": booking.start_date.isoformat(),
        "end_date": booking.end_date.isoformat(),
        "status": booking.status,
        "release_id": booking.release_id,
        "test_phase_id": booking.test_phase_id,
    }


# ── Linked CRs ────────────────────────────────────────────────────────────────

@router.get("/{release_id}/change-requests")
async def list_linked_crs(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return change requests whose release_id points to this release."""
    from app.db.models.change_request import ChangeRequest
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(ChangeRequest).where(
                ChangeRequest.release_id == release_id,
                ChangeRequest.tenant_id == tenant_id,
                ChangeRequest.deleted_at.is_(None),
            ).order_by(ChangeRequest.id)
        )
    ).scalars().all()
    return [
        {
            "id": cr.id,
            "title": cr.title,
            "status": cr.status,
            "change_type": cr.change_type,
            "scheduled_start": cr.scheduled_start.isoformat() if cr.scheduled_start else None,
            "scheduled_end": cr.scheduled_end.isoformat() if cr.scheduled_end else None,
        }
        for cr in rows
    ]


@router.post("/{release_id}/change-requests/{cr_id}/link", status_code=status.HTTP_204_NO_CONTENT)
async def link_cr_to_release(
    release_id: int,
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Set ChangeRequest.release_id = release_id for the given CR."""
    from app.db.models.change_request import ChangeRequest
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    cr = (
        await db.execute(
            select(ChangeRequest).where(
                ChangeRequest.id == cr_id,
                ChangeRequest.tenant_id == tenant_id,
                ChangeRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if cr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found")
    cr.release_id = release_id
    await db.flush()


@router.delete("/{release_id}/change-requests/{cr_id}/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_cr_from_release(
    release_id: int,
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Clear ChangeRequest.release_id for the given CR."""
    from app.db.models.change_request import ChangeRequest
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    cr = (
        await db.execute(
            select(ChangeRequest).where(
                ChangeRequest.id == cr_id,
                ChangeRequest.tenant_id == tenant_id,
                ChangeRequest.release_id == release_id,
                ChangeRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if cr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found or not linked to this release")
    cr.release_id = None
    await db.flush()
