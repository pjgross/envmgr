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
from app.db.models.gate_type import GateType
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.gate_waiver import GateWaiver
from app.db.models.test_phase import TestPhase
from app.db.models.user import User
from app.api.v1.schemas.gate_criterion import GateCriterionRead
from app.api.v1.schemas.release_gate import ReleaseGateCreate, ReleaseGateRead, ReleaseGateUpdate
from app.services import gate_criterion_service, gate_waiver_service


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


async def _validate_gate_type_id(
    db: AsyncSession,
    tenant_id: int,
    gate_type_id: Optional[int],
    *,
    current_gate_type_id: Optional[int] = None,
) -> None:
    """Client-supplied FK, so it must resolve within the caller's tenant.

    Carve-out (A1's rule, environment_service._validate_client_foreign_keys'
    operations_group_id branch): a value UNCHANGED from what the gate already
    stores is accepted even if the type has since been soft-deleted — a
    full-form save that re-sends the existing gate_type_id must not 404 just
    because that type was archived in the meantime. Only a NEW assignment has
    to resolve to a live, in-tenant type.
    """
    if gate_type_id is None or gate_type_id == current_gate_type_id:
        return
    found = (
        await db.execute(
            select(GateType.id).where(
                GateType.id == gate_type_id,
                GateType.tenant_id == tenant_id,
                GateType.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate type not found")


async def _validate_test_phase_id(
    db: AsyncSession,
    tenant_id: int,
    test_phase_id: Optional[int],
    *,
    current_test_phase_id: Optional[int] = None,
) -> None:
    """Same rule as _validate_gate_type_id, for TestPhase. TestPhase has no
    soft-delete column of its own that reads differently here, but the
    unchanged-value carve-out still applies: a full-form save re-sending the
    stored id must not 404 on a phase that has since become otherwise
    unreachable (e.g. its release was deleted, tenant-scoped queries always
    exclude it going forward)."""
    if test_phase_id is None or test_phase_id == current_test_phase_id:
        return
    found = (
        await db.execute(
            select(TestPhase.id).where(
                TestPhase.id == test_phase_id,
                TestPhase.tenant_id == tenant_id,
                TestPhase.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test phase not found")


async def _validate_approver_user_id(
    db: AsyncSession, tenant_id: int, approved_by_user_id: int
) -> None:
    """`approved_by_user_id` is a client-supplied foreign key naming who
    accepted the risk on a waiver — a governance record, not a mention — so
    it must resolve to a real user in the CALLER'S ACTIVE TENANT. Mirrors
    `contention_service.escalate`'s owner-validation rule (A4's precedent)
    exactly, for the same IDOR-class reason: without it, any tenant member
    could attribute a waiver to anyone at all, including a real named
    colleague who never approved it, and — because
    `gate_waiver_service.usernames_for` is deliberately NOT tenant-qualified
    (master-admin impersonation needs that) — the response would then
    disclose a foreign tenant's username. An unknown id must be a 404 here,
    not the unhandled IntegrityError the write used to raise as a 500.

    Deliberately no `is_active` check, same as A4's owner rule: a
    deactivated account is a different retirement state, and a waiver
    already attributing risk-acceptance to someone who has since left
    should still name them.

    This is INPUT VALIDATION on a client-supplied identifier, not gate-state
    enforcement — it never refuses an override because of anything about the
    gate, only because the named approver does not exist in this tenant.
    """
    found = (
        await db.execute(
            select(User.id).where(
                User.id == approved_by_user_id, User.tenant_id == tenant_id
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approver not found")


# ── Public API ───────────────────────────────────────────────────────────────

async def list_gates(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[dict]:
    """Return gates plus nested criteria + overdue_criterion_count per gate.

    overdue_criterion_count is N for a gate whose due_date < now (count of its
    open criteria) and 0 otherwise — criteria no longer carry their own date.

    Criteria and overdue counts come from gate_criterion_service's batched
    helpers — the SAME ones gate_read_with_waiver uses for a single gate —
    so a page here and a single-gate response after a PUT/pass/fail/override
    can never disagree about what a gate's criteria are. See I3 in the C2
    final review.
    """
    from datetime import datetime, timezone

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
    now = datetime.now(timezone.utc)

    # Batched ONCE for the whole page — never once per gate.
    criteria_by_gate = await gate_criterion_service.criteria_reads_for_gates(
        db, tenant_id, gate_ids
    )

    # Task 10c — the current waiver per gate, batched ONCE for the whole
    # page (never one query per row). Only `overridden` gates can carry one;
    # asking for the rest would just cost queries for a result nothing uses.
    overridden_gate_ids = [g.id for g in gate_rows if g.status == "overridden"]
    waiver_reads = await gate_waiver_service.waiver_reads_for_gates(
        db, tenant_id, overridden_gate_ids, now=now
    )

    return [
        {
            "id": g.id, "tenant_id": g.tenant_id, "release_id": g.release_id,
            "name": g.name, "due_date": g.due_date, "status": g.status,
            "decided_by": g.decided_by, "decided_at": g.decided_at,
            "decision_notes": g.decision_notes,
            "gate_type_id": g.gate_type_id, "test_phase_id": g.test_phase_id,
            "criteria": criteria_by_gate[g.id],
            "overdue_criterion_count": gate_criterion_service.overdue_count(
                g, criteria_by_gate[g.id], now
            ),
            "waiver": waiver_reads.get(g.id),
        }
        for g in gate_rows
    ]


async def gate_read_with_waiver(
    db: AsyncSession, tenant_id: int, gate: ReleaseGate
) -> ReleaseGateRead:
    """Build a ReleaseGateRead for ONE gate fresh from a service call
    (create/update/pass/fail/override), with `waiver`, `criteria` and
    `overdue_criterion_count` enriched exactly the way list_gates enriches
    them — the SHARED site every gate-returning endpoint calls, so a single
    gate response can never disagree with what the list endpoint would show
    for the same gate.

    `model_validate(gate)` alone would silently leave `waiver: None`,
    `criteria: []` and `overdue_criterion_count: 0` — a ReleaseGate ORM row
    carries none of those as real attributes, so Pydantic never raises, it
    just defaults. That is exactly the trap A1 shipped once already for
    `waiver` (Task 10c fixed *that* field here) and the final C2 review (I3)
    found it repeated for `criteria`/`overdue_criterion_count`: changing a
    gate's type from the inline Select made its criteria list and its
    done/overdue chips disappear until a refetch, because `updateGate` does
    a full-row Redux replace with whatever this function returns.

    Waiver lookup still only queries when `gate.status == "overridden"` —
    mirrors list_gates' own restriction. Criteria are always fetched: a gate
    of any status can carry them, and it is exactly one extra query pair for
    a single-gate response (never once per row — there is only one row).
    """
    from datetime import datetime, timezone

    result = ReleaseGateRead.model_validate(gate)

    criteria_by_gate = await gate_criterion_service.criteria_reads_for_gates(
        db, tenant_id, [gate.id]
    )
    criteria = criteria_by_gate.get(gate.id, [])
    # GateCriterionRead.model_validate on each dict — not the raw dicts
    # themselves — so `result.criteria`'s runtime type matches what
    # list_gates produces (there, FastAPI's response_model does this
    # coercion implicitly; here, assigning straight to an already-built
    # ReleaseGateRead bypasses that, which is otherwise a silent
    # PydanticSerializationUnexpectedValue at response time).
    result.criteria = [GateCriterionRead.model_validate(c) for c in criteria]
    result.overdue_criterion_count = gate_criterion_service.overdue_count(
        gate, criteria, datetime.now(timezone.utc)
    )

    if gate.status == "overridden":
        waiver_reads = await gate_waiver_service.waiver_reads_for_gates(
            db, tenant_id, [gate.id]
        )
        result.waiver = waiver_reads.get(gate.id)
    return result


async def create_gate(
    db: AsyncSession,
    release_id: int,
    data: ReleaseGateCreate,
    tenant_id: int,
) -> ReleaseGate:
    await _validate_gate_type_id(db, tenant_id, data.gate_type_id)
    await _validate_test_phase_id(db, tenant_id, data.test_phase_id)

    gate = ReleaseGate(
        tenant_id=tenant_id,
        release_id=release_id,
        name=data.name,
        due_date=data.due_date,
        status="pending",
        gate_type_id=data.gate_type_id,
        test_phase_id=data.test_phase_id,
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

    # Omitted key means "leave alone"; only an explicit null clears it.
    update_data = data.model_dump(exclude_unset=True)
    if "gate_type_id" in update_data:
        await _validate_gate_type_id(
            db, tenant_id, update_data["gate_type_id"],
            current_gate_type_id=gate.gate_type_id,
        )
    if "test_phase_id" in update_data:
        await _validate_test_phase_id(
            db, tenant_id, update_data["test_phase_id"],
            current_test_phase_id=gate.test_phase_id,
        )
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
    *,
    expires_at: Optional[datetime] = None,
    remediation: Optional[str] = None,
    approved_by_user_id: Optional[int] = None,
) -> ReleaseGate:
    if not notes or not notes.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "notes are required when overriding a gate",
        )

    gate = await _get_gate(db, gate_id, tenant_id)

    # Client-supplied FK — validate BEFORE any mutation, same reason every
    # other validate-then-write in this module does: a refused approver must
    # leave nothing half-applied. See _validate_approver_user_id's docstring.
    if approved_by_user_id is not None:
        await _validate_approver_user_id(db, tenant_id, approved_by_user_id)

    gate.status = "overridden"
    gate.decided_by = user_id
    gate.decided_at = datetime.now(timezone.utc)
    gate.decision_notes = notes
    await db.flush()

    db.add(
        GateWaiver(
            tenant_id=tenant_id,
            gate_id=gate.id,
            reason=notes,
            approved_by_user_id=(
                approved_by_user_id if approved_by_user_id is not None else user_id
            ),
            expires_at=expires_at,
            remediation=remediation,
            created_by=user_id,
        )
    )
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
