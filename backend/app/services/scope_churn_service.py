"""Scope-churn analytics — does changing a release's scope correlate with
delays / issues? Read-only aggregation over shipped project releases."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.release import Release
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.deployment import Deployment
from app.services import release_scope_service

_ISSUE_STATUSES = ("failed", "rolled_back")


def _cohort(rows: list[dict]) -> dict:
    count = len(rows)
    delayed = sum(1 for r in rows if r["delayed"])
    issue = sum(1 for r in rows if r["had_issue"])
    return {
        "count": count,
        "delayed_count": delayed,
        "delayed_pct": round(100 * delayed / count, 1) if count else 0.0,
        "issue_count": issue,
        "issue_pct": round(100 * issue / count, 1) if count else 0.0,
    }


async def compute_scope_churn(
    db: AsyncSession,
    tenant_id: int,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    where = [
        Release.tenant_id == tenant_id,
        Release.deleted_at.is_(None),
        Release.release_kind == "project",
        Release.actual_date.is_not(None),
    ]
    if date_from is not None:
        where.append(Release.actual_date >= date_from)
    if date_to is not None:
        where.append(Release.actual_date <= date_to)

    releases = (
        await db.execute(select(Release).where(*where).order_by(Release.actual_date.desc()))
    ).scalars().all()
    ids = [r.id for r in releases]

    if not ids:
        empty = _cohort([])
        return {
            "date_from": date_from, "date_to": date_to,
            "scope_changed": empty, "stable": dict(empty), "releases": [],
        }

    creep = await release_scope_service.scope_creep_counts(db, ids, tenant_id)

    async def _event_release_ids(name: str) -> set[int]:
        rows = (
            await db.execute(
                select(ReleaseEvent.release_id)
                .join(ReleaseEventType, ReleaseEventType.id == ReleaseEvent.event_type_id)
                .where(
                    ReleaseEvent.release_id.in_(ids),
                    ReleaseEvent.tenant_id == tenant_id,
                    ReleaseEventType.name == name,
                    ReleaseEventType.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        return set(rows)

    scope_change_ids = await _event_release_ids("Scope Change")
    reschedule_ids = await _event_release_ids("Reschedule Reason")
    issue_ids = set(
        (
            await db.execute(
                select(Deployment.release_id).where(
                    Deployment.release_id.in_(ids),
                    Deployment.tenant_id == tenant_id,
                    Deployment.deleted_at.is_(None),
                    Deployment.status.in_(_ISSUE_STATUSES),
                )
            )
        ).scalars().all()
    )

    rows: list[dict] = []
    for r in releases:
        scope_changed = creep.get(r.id, 0) > 0 or r.id in scope_change_ids
        delayed = r.id in reschedule_ids or (
            r.target_date is not None and r.actual_date > r.target_date
        )
        rows.append({
            "release_id": r.id, "name": r.name, "shipped_at": r.actual_date,
            "scope_changed": scope_changed, "delayed": delayed,
            "had_issue": r.id in issue_ids,
        })

    changed = [x for x in rows if x["scope_changed"]]
    stable = [x for x in rows if not x["scope_changed"]]
    return {
        "date_from": date_from, "date_to": date_to,
        "scope_changed": _cohort(changed), "stable": _cohort(stable), "releases": rows,
    }
