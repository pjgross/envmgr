"""Gate evidence — a reference vouching for a gate.

NOT an artefact: this application has no file storage, so evidence is a URL
plus an attestation of who added it. `deployment_id` is optional and, when
present, only validated as belonging to the caller's tenant — never to the
gate's own release, because a QA sign-off legitimately cites a deployment
made under an earlier release into the same environment.

Never calls db.commit() — see get_db()'s auto-commit / outbox note.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_evidence import GateEvidenceCreate
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
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


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes for `DateTime(timezone=True)` columns
    while PostgreSQL hands back aware ones. Comparing the two raises, so
    normalise before any Python-side comparison — the stored values are UTC on
    both engines. A copy of `agreement_gap_service._utc`, one of several in
    this codebase."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


async def stale_evidence_ids(
    db: AsyncSession, tenant_id: int, evidence_rows: list[GateEvidence]
) -> set[int]:
    """Evidence ids whose deployment has been superseded.

    Evidence links deployment D — build of subsystem S into environment E at
    time T. It is STALE if a later SUCCESSFUL deployment of S into E exists.

    'success' exactly, not 'not failed': a failed redeploy leaves the
    evidence's own build still running, and a rolled_back deployment means
    the earlier build is what is running again — so neither may supersede
    anything. Computed on read, in two queries never once per row — a stored
    flag would be falsified by the next deployment webhook.
    """
    linked = [e for e in evidence_rows if e.deployment_id is not None]
    if not linked:
        return set()

    referenced = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Deployment.id,
                    Build.subsystem_id,
                    Deployment.environment_id,
                    Deployment.deployed_at,
                )
                .join(Build, Build.id == Deployment.build_id)
                .where(
                    Deployment.id.in_([e.deployment_id for e in linked]),
                    Deployment.tenant_id == tenant_id,
                )
            )
        ).all()
    }
    if not referenced:
        return set()

    pairs = {(r.subsystem_id, r.environment_id) for r in referenced.values()}
    latest_rows = (
        await db.execute(
            select(
                Build.subsystem_id,
                Deployment.environment_id,
                func.max(Deployment.deployed_at).label("latest"),
            )
            .join(Build, Build.id == Deployment.build_id)
            .where(
                Deployment.tenant_id == tenant_id,
                Deployment.deleted_at.is_(None),
                Deployment.status == "success",
                # or_(and_(...)) rather than a tuple/row-value IN: SQLite has
                # no reliable row-value IN support, and this form compiles
                # identically on both engines.
                or_(*[
                    and_(Build.subsystem_id == s, Deployment.environment_id == e)
                    for s, e in pairs
                ]),
            )
            .group_by(Build.subsystem_id, Deployment.environment_id)
        )
    ).all()
    latest = {(r.subsystem_id, r.environment_id): r.latest for r in latest_rows}

    stale: set[int] = set()
    for evidence in linked:
        ref = referenced.get(evidence.deployment_id)
        if ref is None:
            continue
        newest = _utc(latest.get((ref.subsystem_id, ref.environment_id)))
        if newest is not None and newest > _utc(ref.deployed_at):
            stale.add(evidence.id)
    return stale


@dataclass(frozen=True)
class StaleEvidenceDetail:
    """Enough to name BOTH deployments an `evidence_stale` warning must
    mention: the one the evidence actually cites (now superseded) and the
    later successful one that superseded it. `stale_evidence_ids` above
    stays untouched — its callers (the evidence-list/create endpoints) only
    ever need the id set for a boolean `is_stale` flag."""

    environment_name: str
    superseded_build_label: str
    superseded_deployed_at: datetime
    superseding_build_label: str
    superseding_deployed_at: datetime


def _build_label(build_number: Optional[str], git_sha: str) -> str:
    return build_number or git_sha[:8]


async def stale_evidence_details(
    db: AsyncSession, tenant_id: int, evidence_rows: list[GateEvidence]
) -> dict[int, StaleEvidenceDetail]:
    """Like `stale_evidence_ids`, but keyed on evidence id with the detail
    needed to name both deployments in a warning. Same predicate, same two
    batch queries (plus one more for environment names) — never once per
    row."""
    linked = [e for e in evidence_rows if e.deployment_id is not None]
    if not linked:
        return {}

    referenced = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Deployment.id,
                    Build.subsystem_id,
                    Build.build_number,
                    Build.git_sha,
                    Deployment.environment_id,
                    Deployment.deployed_at,
                )
                .join(Build, Build.id == Deployment.build_id)
                .where(
                    Deployment.id.in_([e.deployment_id for e in linked]),
                    Deployment.tenant_id == tenant_id,
                )
            )
        ).all()
    }
    if not referenced:
        return {}

    pairs = {(r.subsystem_id, r.environment_id) for r in referenced.values()}
    candidate_rows = (
        await db.execute(
            select(
                Build.subsystem_id,
                Deployment.environment_id,
                Build.build_number,
                Build.git_sha,
                Deployment.deployed_at,
            )
            .join(Build, Build.id == Deployment.build_id)
            .where(
                Deployment.tenant_id == tenant_id,
                Deployment.deleted_at.is_(None),
                Deployment.status == "success",
                # or_(and_(...)) rather than a tuple/row-value IN, same
                # portability reason as stale_evidence_ids above.
                or_(*[
                    and_(Build.subsystem_id == s, Deployment.environment_id == e)
                    for s, e in pairs
                ]),
            )
        )
    ).all()

    latest: dict[tuple[int, int], object] = {}
    for row in candidate_rows:
        key = (row.subsystem_id, row.environment_id)
        current = latest.get(key)
        if current is None or _utc(row.deployed_at) > _utc(current.deployed_at):
            latest[key] = row

    env_ids = {r.environment_id for r in referenced.values()}
    env_names = {
        row.id: row.name
        for row in (
            await db.execute(
                select(Environment.id, Environment.name).where(Environment.id.in_(env_ids))
            )
        ).all()
    }

    details: dict[int, StaleEvidenceDetail] = {}
    for evidence in linked:
        ref = referenced.get(evidence.deployment_id)
        if ref is None:
            continue
        newest = latest.get((ref.subsystem_id, ref.environment_id))
        if newest is None:
            continue
        newest_at = _utc(newest.deployed_at)
        ref_at = _utc(ref.deployed_at)
        if newest_at is None or ref_at is None or newest_at <= ref_at:
            continue
        details[evidence.id] = StaleEvidenceDetail(
            environment_name=env_names.get(ref.environment_id, f"environment {ref.environment_id}"),
            superseded_build_label=_build_label(ref.build_number, ref.git_sha),
            superseded_deployed_at=ref_at,
            superseding_build_label=_build_label(newest.build_number, newest.git_sha),
            superseding_deployed_at=newest_at,
        )
    return details
