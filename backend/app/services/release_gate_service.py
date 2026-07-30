"""Release gate service — list/create/update + pass/fail/override decisions.

All state-changing operations publish outbox events.
Never calls db.commit().
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.api.v1.schemas.release_gate import ReleaseGateCreate, ReleaseGateUpdate


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _get_gate(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> ReleaseGate:
    gate = (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.id == gate_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if gate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release gate not found")
    return gate


async def get_gate(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> ReleaseGate:
    """Public tenant-scoped gate fetch. Raises 404 if not found."""
    return await _get_gate(db, gate_id, tenant_id)


async def _find_event_type(
    db: AsyncSession, tenant_id: int, name: str
) -> Optional[ReleaseEventType]:
    return (
        await db.execute(
            select(ReleaseEventType).where(
                ReleaseEventType.tenant_id == tenant_id,
                ReleaseEventType.name == name,
                ReleaseEventType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _record_gate_event(
    db: AsyncSession,
    gate: ReleaseGate,
    tenant_id: int,
    user_id: int,
    description: str,
) -> None:
    """Write a Stakeholder Note event row for the gate decision."""
    event_type = await _find_event_type(db, tenant_id, "Stakeholder Note")
    if event_type is None:
        return
    db.add(
        ReleaseEvent(
            tenant_id=tenant_id,
            release_id=gate.release_id,
            event_type_id=event_type.id,
            description=description,
            occurred_at=datetime.now(timezone.utc),
            recorded_by=user_id,
        )
    )
    await db.flush()


# ── Public API ───────────────────────────────────────────────────────────────

async def list_gates(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[dict]:
    """Return gates plus nested criteria + overdue_criterion_count per gate.

    overdue_criterion_count is N for a gate whose due_date < now (count of its
    open criteria) and 0 otherwise — criteria no longer carry their own date.
    """
    from datetime import datetime, timezone
    from app.db.models.gate_criterion import GateCriterion

    gate_rows = (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            ).order_by(ReleaseGate.id)
        )
    ).scalars().all()
    if not gate_rows:
        return []

    gate_ids = [g.id for g in gate_rows]
    crit_rows = (
        await db.execute(
            select(GateCriterion).where(
                GateCriterion.gate_id.in_(gate_ids),
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            ).order_by(GateCriterion.id)
        )
    ).scalars().all()

    from app.db.models.user import User
    assignee_ids = {c.assigned_to_user_id for c in crit_rows if c.assigned_to_user_id is not None}
    username_by_id: dict[int, str] = {}
    if assignee_ids:
        user_rows = (
            await db.execute(select(User.id, User.username).where(User.id.in_(assignee_ids)))
        ).all()
        username_by_id = {row.id: row.username for row in user_rows}

    now = datetime.now(timezone.utc)
    open_counts: dict[int, int] = {gid: 0 for gid in gate_ids}
    by_gate: dict[int, list[dict]] = {gid: [] for gid in gate_ids}
    for c in crit_rows:
        by_gate[c.gate_id].append({
            "id": c.id, "gate_id": c.gate_id, "title": c.title, "notes": c.notes,
            "assigned_to_user_id": c.assigned_to_user_id,
            "assigned_role": c.assigned_role,
            "assigned_to_username": username_by_id.get(c.assigned_to_user_id) if c.assigned_to_user_id else None,
            "status": c.status,
            "completed_at": c.completed_at, "completed_by_user_id": c.completed_by_user_id,
            "created_at": c.created_at, "updated_at": c.updated_at,
        })
        if c.status == "open":
            open_counts[c.gate_id] += 1

    def _overdue(gate: ReleaseGate) -> int:
        due = gate.due_date
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return open_counts[gate.id] if due < now else 0

    return [
        {
            "id": g.id, "tenant_id": g.tenant_id, "release_id": g.release_id,
            "name": g.name, "due_date": g.due_date, "status": g.status,
            "decided_by": g.decided_by, "decided_at": g.decided_at,
            "decision_notes": g.decision_notes,
            "criteria": by_gate[g.id],
            "overdue_criterion_count": _overdue(g),
        }
        for g in gate_rows
    ]


async def create_gate(
    db: AsyncSession,
    release_id: int,
    data: ReleaseGateCreate,
    tenant_id: int,
) -> ReleaseGate:
    gate = ReleaseGate(
        tenant_id=tenant_id,
        release_id=release_id,
        name=data.name,
        due_date=data.due_date,
        status="pending",
    )
    db.add(gate)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseGateCreated",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": release_id,
            "name": gate.name,
            "due_date": gate.due_date.isoformat(),
        },
        tenant_id=tenant_id,
    )
    return gate


async def update_gate(
    db: AsyncSession,
    gate_id: int,
    data: ReleaseGateUpdate,
    tenant_id: int,
) -> ReleaseGate:
    gate = await _get_gate(db, gate_id, tenant_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(gate, field, value)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseGateUpdated",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "due_date": gate.due_date.isoformat(),
        },
        tenant_id=tenant_id,
    )
    return gate


async def delete_gate(
    db: AsyncSession,
    gate_id: int,
    tenant_id: int,
) -> None:
    """Soft-delete a gate. Already-decided gates can still be removed (audit
    trail is the ReleaseGatePassed/Failed/Overridden event log)."""
    gate = await _get_gate(db, gate_id, tenant_id)
    gate.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="ReleaseGateDeleted",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={"id": gate.id, "release_id": gate.release_id},
        tenant_id=tenant_id,
    )


async def pass_gate(
    db: AsyncSession,
    gate_id: int,
    notes: Optional[str],
    tenant_id: int,
    user_id: int,
) -> ReleaseGate:
    gate = await _get_gate(db, gate_id, tenant_id)

    gate.status = "passed"
    gate.decided_by = user_id
    gate.decided_at = datetime.now(timezone.utc)
    gate.decision_notes = notes
    await db.flush()

    await _record_gate_event(
        db, gate, tenant_id, user_id,
        f"Gate '{gate.name}' passed." + (f" Notes: {notes}" if notes else ""),
    )

    await publish_event(
        db,
        event_type="ReleaseGatePassed",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "decided_by": user_id,
            "notes": notes,
        },
        tenant_id=tenant_id,
    )
    return gate


async def fail_gate(
    db: AsyncSession,
    gate_id: int,
    notes: Optional[str],
    tenant_id: int,
    user_id: int,
) -> ReleaseGate:
    gate = await _get_gate(db, gate_id, tenant_id)

    gate.status = "failed"
    gate.decided_by = user_id
    gate.decided_at = datetime.now(timezone.utc)
    gate.decision_notes = notes
    await db.flush()

    await _record_gate_event(
        db, gate, tenant_id, user_id,
        f"Gate '{gate.name}' failed." + (f" Notes: {notes}" if notes else ""),
    )

    await publish_event(
        db,
        event_type="ReleaseGateFailed",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "decided_by": user_id,
            "notes": notes,
        },
        tenant_id=tenant_id,
    )
    return gate


async def override_gate(
    db: AsyncSession,
    gate_id: int,
    notes: Optional[str],
    tenant_id: int,
    user_id: int,
) -> ReleaseGate:
    if not notes or not notes.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "notes are required when overriding a gate",
        )

    gate = await _get_gate(db, gate_id, tenant_id)

    gate.status = "overridden"
    gate.decided_by = user_id
    gate.decided_at = datetime.now(timezone.utc)
    gate.decision_notes = notes
    await db.flush()

    await _record_gate_event(
        db, gate, tenant_id, user_id,
        f"Gate '{gate.name}' overridden. Notes: {notes}",
    )

    await publish_event(
        db,
        event_type="ReleaseGateOverridden",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "decided_by": user_id,
            "notes": notes,
        },
        tenant_id=tenant_id,
    )
    return gate


async def maybe_auto_pass_gate(
    db: AsyncSession,
    gate: ReleaseGate,
    tenant_id: int,
    user_id: int,
) -> bool:
    """If the gate is still pending AND has ≥1 non-deleted criterion AND every
    non-deleted criterion is 'done', transition it to passed. Returns True if
    the gate was transitioned. One-way: reopening a criterion later does NOT
    flip the gate back."""
    from app.db.models.gate_criterion import GateCriterion

    if gate.status != "pending":
        return False

    rows = (
        await db.execute(
            select(GateCriterion.status).where(
                GateCriterion.gate_id == gate.id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not rows:
        return False  # zero-criteria gate never auto-passes
    if any(s != "done" for s in rows):
        return False

    gate.status = "passed"
    gate.decided_by = user_id
    gate.decided_at = datetime.now(timezone.utc)
    gate.decision_notes = "auto: all criteria met"
    await db.flush()

    await _record_gate_event(
        db, gate, tenant_id, user_id,
        f"Gate '{gate.name}' passed automatically (all criteria met).",
    )
    await publish_event(
        db,
        event_type="GateAutoPassed",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "decided_by": user_id,
        },
        tenant_id=tenant_id,
    )
    return True
