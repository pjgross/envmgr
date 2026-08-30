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


async def get_finding_in_pir(db: AsyncSession, tenant_id: int, pir: PIR, finding_id: int) -> PirFinding:
    """A finding scoped to tenant AND to the specific PIR the caller's URL
    named. `get_finding` alone checks only tenant_id, so within one tenant a
    caller could pair release A's path with a finding id belonging to release
    B's PIR and read or mutate it — the release_id in the URL would be pure
    decoration. 422, not 404: the id is real, it just doesn't belong here.
    """
    finding = await get_finding(db, tenant_id, finding_id)
    if finding.pir_id != pir.id:
        raise HTTPException(
            status_code=422, detail="finding_id does not belong to that release's PIR")
    return finding


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


from app.core.day_boundaries import expiry_boundary
from app.db.models.pir_finding import (
    CLOSED_ACTION_STATUSES,
    LIVE_ACTION_STATUSES,
    PirAction,
)
from app.db.models.user import User


def is_overdue(action: PirAction, now: datetime) -> bool:
    """Past its due DAY, and still live.

    `expiry_boundary` is the one place that decides a deadline is a day — the
    same rule A4's escalations, B2's grace periods, B5's teardown dates and C2's
    waivers follow. Do not write a second copy of it.

    `_utc` normalisation matters: SQLite hands back naive datetimes where
    PostgreSQL hands back aware ones, and comparing the two is a TypeError — an
    engine-dependent 500 invisible on one leg of CI.
    """
    if action.due_date is None or action.status not in LIVE_ACTION_STATUSES:
        return False
    due = action.due_date
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due < expiry_boundary(now)


async def get_action(db: AsyncSession, tenant_id: int, action_id: int) -> PirAction:
    a = (await db.execute(select(PirAction).where(
        PirAction.id == action_id,
        PirAction.tenant_id == tenant_id,
        PirAction.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return a


async def get_action_in_finding(
    db: AsyncSession, tenant_id: int, finding: PirFinding, action_id: int
) -> PirAction:
    """An action scoped to tenant AND to the specific finding the caller's URL
    named — the action-side sibling of `get_finding_in_pir`, for the same
    reason: `get_action` alone checks only tenant_id, so a caller could pair
    one finding's path with another finding's action id and mutate or delete
    it. 422, not 404: the id is real, it just doesn't belong here.
    """
    action = await get_action(db, tenant_id, action_id)
    if action.finding_id != finding.id:
        raise HTTPException(
            status_code=422, detail="action_id does not belong to that finding")
    return action


async def _next_action_seq(db: AsyncSession, finding_id: int) -> int:
    current = (await db.execute(select(func.max(PirAction.seq)).where(
        PirAction.finding_id == finding_id, PirAction.deleted_at.is_(None),
    ))).scalar_one_or_none()
    return (current or 0) + 1


async def _validate_owner(db: AsyncSession, tenant_id: int, owner_id: Optional[int]) -> None:
    """An owner must be a live user in this tenant.

    Deliberately does NOT check `is_active`: an action assigned to someone who
    has since been deactivated still names them, the way A4's contention owners
    do. And this is a validation on a WRITE, so a full-form save that re-sends an
    unchanged owner who has since been archived would 404 — hence the
    unchanged-value carve-out in `update_action`.
    """
    if owner_id is None:
        return
    exists = (await db.execute(select(User.id).where(
        User.id == owner_id, User.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=422, detail="owner_id does not reference a user in this tenant")


async def create_action(
    db: AsyncSession, tenant_id: int, finding: PirFinding, data, user_id: Optional[int]
) -> PirAction:
    await _validate_owner(db, tenant_id, data.owner_id)
    action = PirAction(
        tenant_id=tenant_id,
        finding_id=finding.id,
        seq=await _next_action_seq(db, finding.id),
        title=data.title,
        detail=data.detail,
        owner_id=data.owner_id,
        due_date=data.due_date,
        status=data.status,
        created_by=user_id,
    )
    if action.status in CLOSED_ACTION_STATUSES:
        action.closed_at = datetime.now(timezone.utc)
    db.add(action)
    await db.flush()
    return action


async def update_action(db: AsyncSession, tenant_id: int, action_id: int, data) -> PirAction:
    action = await get_action(db, tenant_id, action_id)
    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] is None:
        raise HTTPException(status_code=422, detail="title cannot be null")
    # The carve-out: re-sending the owner the row already has is always allowed,
    # so a full-form save never 404s because that user was archived since.
    if "owner_id" in payload and payload["owner_id"] != action.owner_id:
        await _validate_owner(db, tenant_id, payload["owner_id"])
    for key, value in payload.items():
        setattr(action, key, value)
    if action.status in CLOSED_ACTION_STATUSES:
        if action.closed_at is None:
            action.closed_at = datetime.now(timezone.utc)
    else:
        action.closed_at = None
    await db.flush()
    return action


async def delete_action(db: AsyncSession, tenant_id: int, action_id: int) -> None:
    action = await get_action(db, tenant_id, action_id)
    action.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def actions_for_findings(
    db: AsyncSession, tenant_id: int, finding_ids: list[int]
) -> dict[int, list[PirAction]]:
    """One query for a whole PIR, keyed by finding id, `[]` for a finding with none."""
    by_finding: dict[int, list[PirAction]] = {fid: [] for fid in finding_ids}
    if not finding_ids:
        return by_finding
    rows = (await db.execute(select(PirAction).where(
        PirAction.finding_id.in_(finding_ids),
        PirAction.tenant_id == tenant_id,
        PirAction.deleted_at.is_(None),
    ).order_by(PirAction.finding_id, PirAction.seq))).scalars().all()
    for row in rows:
        by_finding[row.finding_id].append(row)
    return by_finding


async def usernames_for(db: AsyncSession, user_ids) -> dict[int, str]:
    """Batched id -> username.

    NOT tenant-qualified, deliberately — the rule A3's `acknowledged_by_username`,
    A4's `usernames_for`, B5's and C2's all follow. Under master-admin
    impersonation an owner can legitimately sit outside the PIR's own tenant, and
    a `User.tenant_id ==` join renders them as nobody: the record losing the one
    name it exists to hold.
    """
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {uid: username for uid, username in rows}


from app.db.models.incident import Incident
from app.db.models.pir_finding import PirFindingIncident
from app.db.models.release import Release


async def add_citation(
    db: AsyncSession, tenant_id: int, finding: PirFinding, incident_id: int, note
) -> PirFindingIncident:
    """Cite an incident as evidence for a finding.

    Idempotent on (finding, incident): the citation is a fact, not a counter, so
    citing twice updates the note and returns the same row rather than surfacing
    `uq_pir_finding_incident` to the browser as a bare 500 — the shape C4's
    rollback-plan revive bug took.
    """
    incident = (await db.execute(select(Incident).where(
        Incident.id == incident_id,
        Incident.tenant_id == tenant_id,
        Incident.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if incident is None:
        raise HTTPException(
            status_code=422,
            detail="incident_id does not reference a valid incident for this tenant",
        )
    existing = (await db.execute(select(PirFindingIncident).where(
        PirFindingIncident.finding_id == finding.id,
        PirFindingIncident.incident_id == incident_id,
    ))).scalar_one_or_none()
    if existing is not None:
        existing.note = note
        await db.flush()
        return existing
    citation = PirFindingIncident(
        tenant_id=tenant_id, finding_id=finding.id, incident_id=incident_id, note=note)
    db.add(citation)
    await db.flush()
    return citation


async def remove_citation(
    db: AsyncSession, tenant_id: int, finding_id: int, incident_id: int
) -> None:
    """Hard delete — removing a citation is a correction, not history."""
    citation = (await db.execute(select(PirFindingIncident).where(
        PirFindingIncident.finding_id == finding_id,
        PirFindingIncident.incident_id == incident_id,
        PirFindingIncident.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if citation is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    await db.delete(citation)
    await db.flush()


async def citations_for_findings(
    db: AsyncSession, tenant_id: int, finding_ids: list[int]
) -> dict[int, list[dict]]:
    """One query for a whole PIR. The incident's title, severity and status travel
    with the citation — a chip reading `#41` identifies nothing."""
    by_finding: dict[int, list[dict]] = {fid: [] for fid in finding_ids}
    if not finding_ids:
        return by_finding
    rows = (await db.execute(
        select(PirFindingIncident.finding_id, Incident.id, Incident.title, Incident.severity,
               Incident.status, PirFindingIncident.note)
        .join(Incident, Incident.id == PirFindingIncident.incident_id)
        .where(
            PirFindingIncident.finding_id.in_(finding_ids),
            PirFindingIncident.tenant_id == tenant_id,
        )
        .order_by(PirFindingIncident.finding_id, Incident.detected_at.desc(), Incident.id)
    )).all()
    for finding_id, inc_id, title, severity, inc_status, note in rows:
        by_finding[finding_id].append({
            "incident_id": inc_id, "incident_title": title, "severity": severity,
            "status": inc_status, "note": note,
        })
    return by_finding


async def citations_for_incident(
    db: AsyncSession, tenant_id: int, incident_id: int
) -> list[dict]:
    """Everything the incident page renders about the reviews citing it.

    The joins filter `deleted_at` on the finding and the PIR: a review someone
    withdrew is not evidence of anything. The RELEASE join deliberately does not
    — an archived release still renders its name on the citation that references
    it, the read-rendering rule A1 and A2 both settled.
    """
    rows = (await db.execute(
        select(PIR.id, PIR.release_id, Release.name, PIR.status, PirFinding.id,
               PirFinding.title, PirFinding.root_cause, PirFindingIncident.note)
        .join(PirFinding, PirFinding.id == PirFindingIncident.finding_id)
        .join(PIR, PIR.id == PirFinding.pir_id)
        .join(Release, Release.id == PIR.release_id)
        .where(
            PirFindingIncident.incident_id == incident_id,
            PirFindingIncident.tenant_id == tenant_id,
            PirFinding.deleted_at.is_(None),
            PIR.deleted_at.is_(None),
        )
        .order_by(PIR.release_id, PirFinding.seq)
    )).all()
    if not rows:
        return []

    finding_ids = [r[4] for r in rows]
    counts = (await db.execute(
        select(PirAction.finding_id, PirAction.status, func.count())
        .where(PirAction.finding_id.in_(finding_ids), PirAction.deleted_at.is_(None))
        .group_by(PirAction.finding_id, PirAction.status)
    )).all()
    total: dict[int, int] = {}
    open_: dict[int, int] = {}
    for finding_id, action_status, count in counts:
        total[finding_id] = total.get(finding_id, 0) + count
        if action_status in LIVE_ACTION_STATUSES:
            open_[finding_id] = open_.get(finding_id, 0) + count

    return [
        {
            "pir_id": pir_id, "release_id": release_id, "release_name": release_name,
            "pir_status": pir_status, "finding_id": finding_id, "finding_title": finding_title,
            "root_cause": root_cause, "note": note,
            "action_count": total.get(finding_id, 0),
            "open_action_count": open_.get(finding_id, 0),
        }
        for (pir_id, release_id, release_name, pir_status, finding_id, finding_title,
             root_cause, note) in rows
    ]


async def review_status_for_incidents(
    db: AsyncSession, tenant_id: int, incident_ids
) -> dict[int, str]:
    """Batched `{incident_id: 'draft' | 'complete'}` for the incident list column.

    An uncited incident is ABSENT rather than 'none', so the caller decides what
    an unreviewed incident is called and there is one such decision, not two.
    One query for the page — a per-row lookup on a 50-row grid is 50 queries.
    """
    ids = [i for i in incident_ids if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(
        select(PirFindingIncident.incident_id, PIR.status)
        .join(PirFinding, PirFinding.id == PirFindingIncident.finding_id)
        .join(PIR, PIR.id == PirFinding.pir_id)
        .where(
            PirFindingIncident.incident_id.in_(ids),
            PirFindingIncident.tenant_id == tenant_id,
            PirFinding.deleted_at.is_(None),
            PIR.deleted_at.is_(None),
        )
    )).all()
    out: dict[int, str] = {}
    for incident_id, pir_status in rows:
        # complete wins: an incident reviewed to completion anywhere is reviewed.
        if out.get(incident_id) != "complete":
            out[incident_id] = pir_status
    return out
