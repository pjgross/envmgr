"""Findings on a post-implementation review.

A finding is one thing the review found: `went_well` (keep doing it) or
`went_wrong` (analyse it, then act). `kind` is immutable once set — it is which
LIST the item is in, and flipping it would drag a root cause and its actions
across from "this failed" to "keep doing this".

Everything here is tenant-scoped on the way in. `get_finding` filters
`tenant_id` and that filter is load-bearing, not defence in depth: without it a
caller with any finding id reads another tenant's review.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pir import PIR
from app.db.models.pir_finding import PirFinding

# went_well first, so the page reads "here is what worked" before "here is what
# did not". Decided once here rather than per surface.
_KIND_ORDER = {"went_well": 0, "went_wrong": 1}


async def get_pir_or_404(db: AsyncSession, tenant_id: int, release_id: int) -> PIR:
    pir = (await db.execute(select(PIR).where(
        PIR.release_id == release_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    return pir


async def get_finding(db: AsyncSession, tenant_id: int, finding_id: int) -> PirFinding:
    f = (await db.execute(select(PirFinding).where(
        PirFinding.id == finding_id,
        PirFinding.tenant_id == tenant_id,
        PirFinding.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return f


async def _next_seq(db: AsyncSession, pir_id: int, kind: str) -> int:
    """Max of the LIVE rows plus one, per (pir, kind).

    Counting rows instead would reuse a deleted item's number and collide with a
    survivor that already holds it.
    """
    current = (await db.execute(select(func.max(PirFinding.seq)).where(
        PirFinding.pir_id == pir_id,
        PirFinding.kind == kind,
        PirFinding.deleted_at.is_(None),
    ))).scalar_one_or_none()
    return (current or 0) + 1


async def create_finding(
    db: AsyncSession, tenant_id: int, pir: PIR, data, user_id: Optional[int]
) -> PirFinding:
    finding = PirFinding(
        tenant_id=tenant_id,
        pir_id=pir.id,
        kind=data.kind,
        seq=await _next_seq(db, pir.id, data.kind),
        title=data.title,
        detail=data.detail,
        root_cause=data.root_cause,
        created_by=user_id,
    )
    db.add(finding)
    await db.flush()
    return finding


async def update_finding(db: AsyncSession, tenant_id: int, finding_id: int, data) -> PirFinding:
    finding = await get_finding(db, tenant_id, finding_id)
    payload = data.model_dump(exclude_unset=True)
    if "kind" in payload and payload["kind"] != finding.kind:
        raise HTTPException(
            status_code=422,
            detail="kind cannot be changed; delete the finding and raise it under the other kind",
        )
    payload.pop("kind", None)
    if "title" in payload and payload["title"] is None:
        raise HTTPException(status_code=422, detail="title cannot be null")
    for key, value in payload.items():
        setattr(finding, key, value)
    await db.flush()
    return finding


async def delete_finding(db: AsyncSession, tenant_id: int, finding_id: int) -> None:
    finding = await get_finding(db, tenant_id, finding_id)
    finding.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def findings_for_pir(db: AsyncSession, tenant_id: int, pir_id: int) -> list[PirFinding]:
    rows = list((await db.execute(select(PirFinding).where(
        PirFinding.pir_id == pir_id,
        PirFinding.tenant_id == tenant_id,
        PirFinding.deleted_at.is_(None),
    ))).scalars().all())
    # Ordered in Python, not SQL: the kind order is a two-value preference, not a
    # collation, and a CASE in the query would need reproducing anywhere else
    # that reads these rows. A PIR holds tens of findings, not thousands.
    return sorted(rows, key=lambda f: (_KIND_ORDER[f.kind], f.seq))
