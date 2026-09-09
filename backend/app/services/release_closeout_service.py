# backend/app/services/release_closeout_service.py
"""Phase 9 C6 — hyper-care and closeout.

THE ONE PLACE IN PHASE 9 THAT REFUSES. `assert_may_close` (Task 5) raises a
422 from `release_service.transition_release` when the target state is
flagged `is_closed` and asks for something that is not there. Everything
else here computes on read and stores nothing.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_boundaries import expiry_boundary
from app.core.events import publish_event
from app.core.pagination import Page, Sort
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.pir import PIR
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase
from app.db.models.user import User
from app.services import incident_service, pir_service, release_event_service, user_group_service
from app.api.v1.schemas.closeout import (
    CloseoutRead, CloseTargetRead, HandoverRead, HypercarePhaseRead, HypercareRead,
    IncidentsWindowRead, IncidentWindowItem, PirStateRead,
)

PHASE_KINDS = frozenset({"test", "hypercare"})
HYPERCARE = "hypercare"


async def live_hypercare_phase(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Optional[TestPhase]:
    """The release's one live hyper-care phase, or None."""
    return (
        await db.execute(
            select(TestPhase).where(
                TestPhase.release_id == release_id,
                TestPhase.tenant_id == tenant_id,
                TestPhase.kind == HYPERCARE,
                TestPhase.deleted_at.is_(None),
            ).order_by(TestPhase.id).limit(1)
        )
    ).scalar_one_or_none()


async def assert_hypercare_slot_free(
    db: AsyncSession, release_id: int, tenant_id: int, *, exclude_phase_id: Optional[int] = None
) -> None:
    """At most one live hyper-care phase per release. In code, not a partial
    unique index — that would be inert on SQLite and untested there."""
    existing = await live_hypercare_phase(db, release_id, tenant_id)
    if existing is not None and existing.id != exclude_phase_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This release already has a hyper-care phase ('{existing.name}'); "
            "edit or delete it rather than adding a second.",
        )


HYPERCARE_STATES = ("none", "planned", "active", "overdue", "stable")
PIR_INCOMPLETE = "the post-implementation review is not complete"
HANDOVER_UNCONFIRMED = "ops handover is not confirmed"


def _day(value: Optional[datetime]) -> Optional[datetime]:
    """Start of the UTC day `value` falls in, tolerant of SQLite's naive datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        # Belt-and-braces: `expiry_boundary` already normalises through its own
        # `_utc` helper, but stamping here too means this function never
        # depends on that internal behaviour to be correct.
        value = value.replace(tzinfo=timezone.utc)
    return expiry_boundary(value)


def hypercare_state(phase: Optional[TestPhase], declared_stable_at: Optional[datetime], now: datetime) -> str:
    """First match wins: stable, none, planned, overdue, active. A window's
    bounds are DAYS — the end day itself still reads active."""
    if declared_stable_at is not None:
        return "stable"
    if phase is None:
        return "none"
    today = _day(now)
    start, end = _day(phase.start_date), _day(phase.end_date)
    if start is not None and start > today:
        return "planned"
    if end is not None and end < today:
        return "overdue"
    return "active"


def state_for_key(definition: dict, key: str) -> Optional[dict]:
    return next((s for s in definition.get("states", []) if s.get("key") == key), None)


def unmet_requirements(state: dict, pir: Optional[PIR], release: Release) -> list[str]:
    """Reasons a closed state cannot be entered. ONE wording, used by the 422
    and by GET /closeout, so the tab and the refusal cannot disagree."""
    if not state.get("is_closed"):
        return []
    unmet: list[str] = []
    if state.get("requires_pir_complete") and (pir is None or pir.status != "complete"):
        unmet.append(PIR_INCOMPLETE)
    if state.get("requires_handover_confirmed") and release.handover_confirmed_at is None:
        unmet.append(HANDOVER_UNCONFIRMED)
    return unmet


async def assert_may_close(
    db: AsyncSession, release: Release, target_state: Optional[dict], tenant_id: int
) -> None:
    """THE ONE REFUSAL IN PHASE 9. Returns at once unless `target_state` is
    flagged `is_closed`; then raises one 422 naming everything unmet."""
    if not target_state or not target_state.get("is_closed"):
        return
    pir = await pir_service.get_for_release(db, tenant_id, release.id)
    unmet = unmet_requirements(target_state, pir, release)
    if unmet:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Cannot close this release: " + "; ".join(unmet) + ".",
        )


async def usernames_for(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """DELIBERATELY NOT TENANT-QUALIFIED — see gate_waiver_service.usernames_for."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {r.id: r.username for r in rows}


EVENT_DECLARED_STABLE = "Declared stable"
EVENT_STABLE_WITHDRAWN = "Stability declaration withdrawn"
EVENT_HANDOVER_CONFIRMED = "Ops handover confirmed"
EVENT_HANDOVER_WITHDRAWN = "Ops handover withdrawn"


def _require_project_release(release: Release) -> None:
    if release.release_kind == "enterprise":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Hyper-care and closeout apply to project releases only")


async def _audit(db, release, tenant_id, user_id, event_name, note):
    await release_event_service.record_auto_event(
        db, release_id=release.id, tenant_id=tenant_id, user_id=user_id,
        event_type_name=event_name, description=note or event_name,
    )


async def declare_stable(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                         note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.declared_stable_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This release is already declared stable; withdraw the declaration first")
    release.declared_stable_at = datetime.now(timezone.utc)
    release.declared_stable_by = user_id
    await db.flush()
    await db.refresh(release)
    await _audit(db, release, tenant_id, user_id, EVENT_DECLARED_STABLE, note)
    await publish_event(db, event_type="ReleaseDeclaredStable", aggregate_id=release.id,
                        aggregate_type="Release",
                        payload={"id": release.id, "name": release.name, "note": note},
                        tenant_id=tenant_id)
    return release


async def withdraw_stable(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                          note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.declared_stable_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This release is not declared stable")
    release.declared_stable_at = None
    release.declared_stable_by = None
    await db.flush()
    await db.refresh(release)
    await _audit(db, release, tenant_id, user_id, EVENT_STABLE_WITHDRAWN, note)
    return release


async def confirm_handover(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                           note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.operations_group_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Set the release's operations group before confirming the handover")
    if release.handover_confirmed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Handover is already confirmed; withdraw it first")
    release.handover_confirmed_at = datetime.now(timezone.utc)
    release.handover_confirmed_by = user_id
    await db.flush()
    await db.refresh(release)
    await _audit(db, release, tenant_id, user_id, EVENT_HANDOVER_CONFIRMED, note)
    return release


async def withdraw_handover(db: AsyncSession, release: Release, *, tenant_id: int, user_id: int,
                            note: Optional[str]) -> Release:
    _require_project_release(release)
    if release.handover_confirmed_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Handover is not confirmed")
    release.handover_confirmed_at = None
    release.handover_confirmed_by = None
    await db.flush()
    await db.refresh(release)
    await _audit(db, release, tenant_id, user_id, EVENT_HANDOVER_WITHDRAWN, note)
    return release


INCIDENT_ITEM_CAP = 50
SEVERITIES = ("P1", "P2", "P3", "P4")


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def incidents_in_window(db: AsyncSession, release: Release, phase, now: datetime) -> IncidentsWindowRead:
    """Incidents whose CAUSAL release is this one, detected inside the window.
    Window: phase start (or the phase's created_at if undated) → the earliest
    of declared_stable_at, phase end, now. No phase: no window, nothing counted."""
    if phase is None:
        return IncidentsWindowRead(window_start=None, window_end=None,
                                   by_severity={s: 0 for s in SEVERITIES}, total=0, items=[])
    start = _aware(phase.start_date) or _aware(phase.created_at)
    candidates = [v for v in (_aware(release.declared_stable_at), _aware(phase.end_date), now) if v is not None]
    end = min(candidates)
    filters = {"release_id": release.id, "date_from": start, "date_to": end}
    rows, total = await incident_service.list_incidents(
        db, release.tenant_id, filters, page=Page(limit=INCIDENT_ITEM_CAP, offset=0),
        sort=Sort(column=Incident.detected_at, descending=True),
    )
    counts = await incident_service.severity_counts(db, release.tenant_id, filters)
    by_severity = {s: counts.get(s, 0) for s in SEVERITIES}
    return IncidentsWindowRead(
        window_start=start, window_end=end, by_severity=by_severity, total=total,
        items=[IncidentWindowItem(id=r.id, title=r.title, severity=r.severity, status=r.status,
                                  detected_at=r.detected_at) for r in rows],
    )


async def build_closeout(db: AsyncSession, release: Release, tenant_id: int, now: datetime) -> CloseoutRead:
    _require_project_release(release)
    phase = await live_hypercare_phase(db, release.id, tenant_id)
    pir = await pir_service.get_for_release(db, tenant_id, release.id)
    names = await usernames_for(db, {release.declared_stable_by, release.handover_confirmed_by})
    group_name = None
    if release.operations_group_id is not None:
        group_name = (await user_group_service.get_group_names(db, {release.operations_group_id})
                      ).get(release.operations_group_id)
    tpl = await db.get(LifecycleTemplate, release.lifecycle_template_id)
    targets = []
    for state in (tpl.definition.get("states", []) if tpl else []):
        if not state.get("is_closed"):
            continue
        unmet = unmet_requirements(state, pir, release)
        targets.append(CloseTargetRead(
            state_key=state["key"], label=state.get("label", state["key"]),
            requires_pir_complete=bool(state.get("requires_pir_complete")),
            requires_handover_confirmed=bool(state.get("requires_handover_confirmed")),
            unmet=unmet, can_close=not unmet,
        ))
    return CloseoutRead(
        hypercare=HypercareRead(
            state=hypercare_state(phase, release.declared_stable_at, now),
            phase=HypercarePhaseRead(id=phase.id, name=phase.name, start_date=phase.start_date,
                                     end_date=phase.end_date) if phase else None,
            declared_stable_at=release.declared_stable_at,
            declared_stable_by_username=names.get(release.declared_stable_by),
        ),
        handover=HandoverRead(
            operations_group_id=release.operations_group_id, operations_group_name=group_name,
            confirmed_at=release.handover_confirmed_at,
            confirmed_by_username=names.get(release.handover_confirmed_by),
        ),
        pir=PirStateRead(exists=pir is not None, status=pir.status if pir else None,
                         completed_at=pir.completed_at if pir else None),
        incidents=await incidents_in_window(db, release, phase, now),
        close_targets=targets,
    )
