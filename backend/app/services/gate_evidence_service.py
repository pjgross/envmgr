"""Gate evidence — a reference vouching for a gate.

NOT an artefact: this application has no file storage, so evidence is a URL
plus an attestation of who added it. `deployment_id` is optional and, when
present, only validated as belonging to the caller's tenant — never to the
gate's own release, because a QA sign-off legitimately cites a deployment
made under an earlier release into the same environment.

Never calls db.commit() — see get_db()'s auto-commit / outbox note.
"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_evidence import GateEvidenceCreate
from app.db.models.deployment import Deployment
from app.db.models.gate_evidence import GateEvidence
from app.services import release_gate_service


async def list_evidence(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> list[GateEvidence]:
    await release_gate_service.get_gate(db, gate_id, tenant_id)  # 404s if not ours
    rows = (
        await db.execute(
            select(GateEvidence)
            .where(
                GateEvidence.tenant_id == tenant_id,
                GateEvidence.gate_id == gate_id,
                GateEvidence.deleted_at.is_(None),
            )
            .order_by(GateEvidence.id)
        )
    ).scalars().all()
    return list(rows)


async def add_evidence(
    db: AsyncSession,
    gate_id: int,
    tenant_id: int,
    user_id: int,
    data: GateEvidenceCreate,
) -> GateEvidence:
    await release_gate_service.get_gate(db, gate_id, tenant_id)  # 404s if not ours

    if data.deployment_id is not None:
        # Validate ONLY that the deployment is in this tenant. Do NOT also
        # require it to belong to the gate's release: a QA sign-off legitimately
        # cites a deployment made under an earlier release into the same
        # environment, and refusing that would block real evidence.
        found = (
            await db.execute(
                select(Deployment.id).where(
                    Deployment.id == data.deployment_id,
                    Deployment.tenant_id == tenant_id,
                    Deployment.deleted_at.is_(None),
                )
            )
        ).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")

    row = GateEvidence(
        tenant_id=tenant_id, gate_id=gate_id, added_by=user_id, **data.model_dump()
    )
    db.add(row)
    await db.flush()
    return row


async def delete_evidence(
    db: AsyncSession, evidence_id: int, tenant_id: int
) -> None:
    row = (
        await db.execute(
            select(GateEvidence).where(
                GateEvidence.id == evidence_id,
                GateEvidence.tenant_id == tenant_id,
                GateEvidence.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence not found")
    row.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def evidence_for_gates(
    db: AsyncSession, tenant_id: int, gate_ids: list[int]
) -> dict[int, list[GateEvidence]]:
    """ONCE PER RESPONSE, never once per row. A 50-gate page through the
    single-gate function above is ~50 queries."""
    if not gate_ids:
        return {}
    rows = (
        await db.execute(
            select(GateEvidence)
            .where(
                GateEvidence.tenant_id == tenant_id,
                GateEvidence.gate_id.in_(gate_ids),
                GateEvidence.deleted_at.is_(None),
            )
            .order_by(GateEvidence.gate_id, GateEvidence.id)
        )
    ).scalars().all()
    grouped: dict[int, list[GateEvidence]] = {gid: [] for gid in gate_ids}
    for row in rows:
        grouped[row.gate_id].append(row)
    return grouped
