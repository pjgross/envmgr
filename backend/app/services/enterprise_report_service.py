"""Enterprise release report — deterministic payload generator."""
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.enterprise_rollup import (
    EnterpriseReportRead,
    EnterpriseReportEvent,
)
from app.core.events import publish_event
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.user import User
from app.services import enterprise_rollup_service


async def generate_report(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> EnterpriseReportRead:
    tenant_id = user.active_tenant_id

    enterprise = (
        await db.execute(
            select(Release).where(
                Release.id == enterprise_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if enterprise is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enterprise release not found")

    members = await enterprise_rollup_service.members_rollup(
        db, user=user, enterprise_id=enterprise_id
    )
    systems = await enterprise_rollup_service.systems_rollup(
        db, user=user, enterprise_id=enterprise_id
    )
    scope_items, _ = await enterprise_rollup_service.scope_rollup(
        db, user=user, enterprise_id=enterprise_id
    )

    scope_by_project: dict[str, list] = defaultdict(list)
    for it in scope_items:
        scope_by_project[it.project_release_name].append(it)

    events: list[EnterpriseReportEvent] = []

    # Own release events (join ReleaseEventType to resolve name string)
    own_events_rows = (
        await db.execute(
            select(ReleaseEvent, ReleaseEventType)
            .join(ReleaseEventType, ReleaseEvent.event_type_id == ReleaseEventType.id)
            .where(
                ReleaseEvent.release_id == enterprise_id,
                ReleaseEvent.tenant_id == tenant_id,
            )
            .order_by(ReleaseEvent.occurred_at.desc())
        )
    ).all()
    for e, et in own_events_rows:
        events.append(
            EnterpriseReportEvent(
                release_id=enterprise.id,
                release_name=enterprise.name,
                occurred_at=e.occurred_at,
                event_type=et.name,
                description=e.description,
            )
        )

    # Status-history events from accepted child releases
    child_ids = [m.project_release_id for m in members]
    if child_ids:
        child_histories = (
            await db.execute(
                select(ReleaseStatusHistory, Release)
                .join(Release, ReleaseStatusHistory.release_id == Release.id)
                .where(
                    ReleaseStatusHistory.release_id.in_(child_ids),
                    # tenant filter via Release (ReleaseStatusHistory has no tenant_id)
                    Release.tenant_id == tenant_id,
                )
                .order_by(ReleaseStatusHistory.changed_at.desc())
                .limit(20 * max(len(child_ids), 1))
            )
        ).all()
        for h, rel in child_histories:
            events.append(
                EnterpriseReportEvent(
                    release_id=rel.id,
                    release_name=rel.name,
                    occurred_at=h.changed_at,
                    event_type=f"status:{h.from_state or 'null'}\u2192{h.to_state}",
                    description=h.notes,
                )
            )

    tl = await enterprise_rollup_service.timeline_rollup(
        db, user=user, enterprise_id=enterprise_id
    )

    now = datetime.now(timezone.utc).isoformat()
    username = getattr(user, "username", None) or str(user.id)

    report = EnterpriseReportRead(
        enterprise_id=enterprise.id,
        name=enterprise.name,
        status=enterprise.status,
        target_date=enterprise.target_date,
        actual_date=enterprise.actual_date,
        description=enterprise.description,
        members=members,
        systems=systems,
        scope_by_project={k: v for k, v in scope_by_project.items()},
        events=sorted(events, key=lambda e: e.occurred_at, reverse=True),
        dependencies=tl.dependencies,
        generated_at=now,
        generated_by=username,
    )

    await publish_event(
        db,
        event_type="EnterpriseReportGenerated",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={
            "enterprise_id": enterprise.id,
            "generated_by": user.id,
            "generated_at": now,
        },
        tenant_id=tenant_id,
    )

    return report
