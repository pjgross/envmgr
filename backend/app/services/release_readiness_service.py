"""The ONE place the gate rules — and, since Phase 9 C4, rollback governance
rules — live.

The release detail panel and GET /api/v1/webhooks/release-ready both call
evaluate(), so they cannot disagree. A gate chip contradicting the endpoint a
pipeline obeys would be worse than neither. C4's rollback findings JOIN this
verdict rather than getting a second endpoint, for the same reason.

NOTHING HERE REFUSES ANYTHING. A "block" behaviour makes a gate — or a
rollback finding — a blocker in this response; it does not stop a
transition, a booking or a deployment.
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
from app.services import (
    gate_evidence_service,
    gate_waiver_service,
    rollback_plan_service,
    rollback_policy_service,
    rollback_rehearsal_service,
)


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
            .outerjoin(
                GateType,
                (GateType.id == ReleaseGate.gate_type_id)
                # Defence in depth, per M3 in the C2 final review: the id
                # itself only ever gets here through _validate_gate_type_id,
                # which already refuses a cross-tenant type at write time, so
                # no test can currently make this clause the difference
                # between pass and fail — it is a second lock on a door the
                # write path's own guard already keeps shut, in the house
                # convention every tenant-scoped join here follows anyway.
                & (GateType.tenant_id == tenant_id),
            )
            .where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            )
            .order_by(ReleaseGate.due_date, ReleaseGate.id)
        )
    ).all()

    gate_ids = [g.id for g, _ in rows]
    # Four batch calls, ONCE PER RESPONSE — never once per row.
    waivers = await gate_waiver_service.latest_waivers_for_gates(db, tenant_id, gate_ids)
    # Resolve approver usernames for the wire text below. Deliberately reuses
    # gate_waiver_service.usernames_for, which is deliberately NOT
    # tenant-qualified (a master-admin approver may sit outside this tenant).
    approver_usernames = await gate_waiver_service.usernames_for(
        db, {w.approved_by_user_id for w in waivers.values()}
    )
    evidence = await gate_evidence_service.evidence_for_gates(db, tenant_id, gate_ids)
    all_evidence = [e for items in evidence.values() for e in items]
    # The detail form, not just the id set: the warning must name BOTH the
    # superseded deployment the evidence cites and the one that superseded it.
    stale_details = await gate_evidence_service.stale_evidence_details(db, tenant_id, all_evidence)

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
                # Naming the approver AND the expiry, per the rules table —
                # a bare "Waived by user 3" told nobody who approved it.
                approver = approver_usernames.get(
                    waiver.approved_by_user_id, f"user {waiver.approved_by_user_id}"
                )
                if waiver.expires_at is not None:
                    detail = f"Waived by {approver}, expires {waiver.expires_at:%Y-%m-%d}."
                else:
                    detail = f"Waived by {approver}; no expiry."
                warning("gate_waived", detail)
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
            detail = stale_details.get(item.id)
            if detail is not None:
                warning(
                    "evidence_stale",
                    (
                        f"'{item.label}' cites {detail.superseded_build_label} "
                        f"deployed {detail.superseded_deployed_at:%Y-%m-%d} to "
                        f"{detail.environment_name}, superseded by "
                        f"{detail.superseding_build_label} deployed "
                        f"{detail.superseding_deployed_at:%Y-%m-%d}."
                    ),
                    ref_id=item.id,
                )

    # ── Rollback governance (C4) ─────────────────────────────────────────
    #
    # Joins THIS verdict rather than a second endpoint, so a pipeline has one
    # thing to ask and there is never a second definition of "ready". Uses
    # the SAME `now` resolved above — one clock decides every freshness
    # comparison in this response, gate and rollback alike.
    def _add(kind: str, is_blocker: bool, system_id: int, system_name: str, detail: str) -> None:
        if is_blocker:
            blockers.append(ReadinessBlocker(
                type=kind, ref_kind="system", ref_id=system_id,
                gate_name=None, gate_type=None, detail=detail,
            ))
        else:
            warnings.append(ReadinessWarning(
                type=kind, ref_kind="system", ref_id=system_id,
                gate_name=None, gate_type=None, detail=detail,
            ))

    policy = await rollback_policy_service.get_or_create_policy(db, tenant_id)

    # Only components actually being CHANGED can be rolled back. A regression
    # component is not being changed and produces no findings at all.
    changing = await rollback_plan_service.changing_systems_for_release(
        db, release_id, tenant_id
    )  # -> list[(system_id, system_name)]
    plans = (await rollback_plan_service.plans_for_releases(
        db, tenant_id, [release_id]
    )).get(release_id, [])
    rehearsals = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db, tenant_id, [s_id for s_id, _ in changing]
    )
    by_system = {p.system_id: p for p in plans}

    for system_id, system_name in changing:
        plan = by_system.get(system_id)
        if plan is None:
            _add("rollback_plan_missing", policy.require_rollback_plan, system_id,
                 system_name, f"{system_name} has no rollback plan.")
        else:
            if plan.agreed_at is None:
                _add("rollback_plan_unagreed", policy.require_rollback_plan, system_id,
                     system_name, f"{system_name}'s rollback plan has not been agreed.")
            if plan.reversibility == "irreversible":
                # ALWAYS a warning, whatever the policy says.
                _add("rollback_irreversible", False, system_id, system_name,
                     f"{system_name} cannot be rolled back — roll forward only.")
            elif plan.reversibility == "lossy":
                _add("rollback_lossy", False, system_id, system_name,
                     f"{system_name} can be rolled back, but data written since "
                     f"deploy is lost.")

        rehearsal = rehearsals.get(system_id)
        # A FAILED rehearsal is not a current rehearsal — it proves the opposite.
        if rehearsal is None or rehearsal.outcome == "failed":
            _add("rehearsal_missing", policy.require_current_rehearsal, system_id,
                 system_name, f"No successful rollback rehearsal recorded for {system_name}.")
        elif rollback_rehearsal_service.rehearsal_state(
            rehearsal, policy.rehearsal_validity_days, now
        ) == "stale":
            _add("rehearsal_stale", policy.require_current_rehearsal, system_id,
                 system_name,
                 f"{system_name}'s last rollback rehearsal was "
                 f"{rehearsal.rehearsed_at.date()}.")

    # Roll up over the SAME component set the findings above were computed
    # over — plans_for_releases returns every LIVE plan on the release with
    # no role filter, but a plan can legitimately outlive the release_system
    # row it was written against (DELETE /release-systems/{id} hard-deletes
    # the row and touches no plan). Feeding rollup() the unfiltered set means
    # an orphaned plan keeps driving reversibility with zero findings to
    # explain it — the single-verdict guarantee broken by an ordinary UI
    # action, not just a hand-crafted API call. See
    # tests/test_rollback_readiness.py::test_an_orphaned_plan_does_not_move_reversibility.
    changing_ids = {system_id for system_id, _ in changing}
    reversibility = rollback_plan_service.rollup(
        [p for p in plans if p.system_id in changing_ids]
    )

    return ReleaseReadinessResponse(
        # Derived in one expression, mirroring preflight_service. `ok` cannot
        # drift from `blockers` because it IS `blockers`.
        ok=len(blockers) == 0,
        release_id=release_id,
        checked_at=now,
        blockers=blockers,
        warnings=warnings,
        reversibility=reversibility,
    )
