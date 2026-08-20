"""The ONE place the gate rules live.

The release detail panel and GET /api/v1/webhooks/release-ready both call
evaluate(), so they cannot disagree. A gate chip contradicting the endpoint a
pipeline obeys would be worse than neither.

NOTHING HERE REFUSES ANYTHING. A "block" behaviour makes a gate a blocker in
this response; it does not stop a transition, a booking or a deployment.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_readiness import (
    ReadinessBlocker,
    ReadinessWarning,
    ReleaseReadinessResponse,
)
from app.db.models.gate_type import GateType
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_evidence_service, gate_waiver_service


async def evaluate(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    now: Optional[datetime] = None,
) -> ReleaseReadinessResponse:
    # ONE CLOCK decides every waiver state in this response. Called per row,
    # two gates in one payload could disagree about what day it is.
    now = now or datetime.now(timezone.utc)

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

    rows = (
        await db.execute(
            select(ReleaseGate, GateType)
            .outerjoin(GateType, GateType.id == ReleaseGate.gate_type_id)
            .where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            )
            .order_by(ReleaseGate.due_date, ReleaseGate.id)
        )
    ).all()

    gate_ids = [g.id for g, _ in rows]
    # Three batch calls, ONCE PER RESPONSE — never once per row.
    waivers = await gate_waiver_service.latest_waivers_for_gates(db, tenant_id, gate_ids)
    evidence = await gate_evidence_service.evidence_for_gates(db, tenant_id, gate_ids)
    all_evidence = [e for items in evidence.values() for e in items]
    stale_ids = await gate_evidence_service.stale_evidence_ids(db, tenant_id, all_evidence)

    blockers: list[ReadinessBlocker] = []
    warnings: list[ReadinessWarning] = []

    for gate, gate_type in rows:
        type_name = gate_type.name if gate_type else None
        behaviour = gate_type.failure_behaviour if gate_type else None

        def blocker(kind: str, detail: str) -> None:
            blockers.append(ReadinessBlocker(
                type=kind, ref_kind="gate", ref_id=gate.id,
                gate_name=gate.name, gate_type=type_name, detail=detail,
            ))

        def warning(kind: str, detail: str, ref_id: Optional[int] = None) -> None:
            warnings.append(ReadinessWarning(
                type=kind, ref_kind="evidence" if ref_id else "gate",
                ref_id=ref_id or gate.id, gate_name=gate.name,
                gate_type=type_name, detail=detail,
            ))

        # FIRST MATCH WINS, in this order.
        if gate.status == "failed":
            # A failure is not waived, it is failed. To waive it you override it.
            blocker("gate_failed", "The gate was failed.")
        elif gate.status == "overridden":
            waiver = waivers.get(gate.id)
            if waiver is None:
                # Overridden before C2 shipped. These must NOT become blockers
                # on the day this deploys.
                warning("gate_waived_no_record", "Waived, no expiry recorded.")
            elif gate_waiver_service.waiver_state(waiver, now) == "expired":
                blocker("waiver_expired", "The waiver has expired; the gate is unmet again.")
            else:
                warning("gate_waived", f"Waived by user {waiver.approved_by_user_id}.")
        elif gate.status == "pending":
            if behaviour is None:
                # EVERY gate in EVERY existing tenant is untyped until someone
                # types it. Inventing "block" would turn on a wall of blockers
                # nobody configured.
                warning("gate_untyped", "No gate type set, so no behaviour was declared.")
            elif behaviour == "block":
                blocker("gate_pending", "The gate has not been decided.")
            else:
                warning("gate_pending", "The gate has not been decided.")

        # Evidence checks run regardless of gate status: a passed gate missing
        # its expected evidence is exactly the case worth surfacing.
        items = evidence.get(gate.id, [])
        if gate_type and gate_type.expected_evidence:
            supplied = {e.kind for e in items}
            missing = [k for k in gate_type.expected_evidence if k not in supplied]
            if missing:
                warning("evidence_missing", "Expected but not supplied: " + ", ".join(missing))
        for item in items:
            if item.id in stale_ids:
                warning(
                    "evidence_stale",
                    f"'{item.label}' vouches for a deployment that has since been superseded.",
                    ref_id=item.id,
                )

    return ReleaseReadinessResponse(
        # Derived in one expression, mirroring preflight_service. `ok` cannot
        # drift from `blockers` because it IS `blockers`.
        ok=len(blockers) == 0,
        release_id=release_id,
        checked_at=now,
        blockers=blockers,
        warnings=warnings,
    )
