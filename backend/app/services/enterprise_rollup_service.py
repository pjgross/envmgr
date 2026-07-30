"""Read-only rollup queries for an enterprise release.

All queries join on accepted memberships only.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, fetch_page_rows
from app.api.v1.schemas.enterprise_rollup import (
    MemberRollupRow,
    MemberStateCount,
    ScopeRollupItem,
    SystemRollupRow,
    TimelineDependencyEdge,
    TimelinePhaseRead,
    TimelineRollupRead,
)
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_dependency import ReleaseDependency
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.db.models.test_phase import TestPhase
from app.db.models.user import User


async def _accepted_child_ids(
    db: AsyncSession, tenant_id: int, enterprise_id: int
) -> list[int]:
    stmt = select(ReleaseMembership.project_release_id).where(
        ReleaseMembership.enterprise_release_id == enterprise_id,
        ReleaseMembership.tenant_id == tenant_id,
        ReleaseMembership.state == MembershipState.ACCEPTED.value,
    )
    return [r for (r,) in (await db.execute(stmt)).all()]


async def systems_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[SystemRollupRow]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []

    stmt = (
        select(ReleaseSystem, System, Release)
        .join(System, ReleaseSystem.system_id == System.id)
        .join(Release, ReleaseSystem.release_id == Release.id)
        .where(
            ReleaseSystem.release_id.in_(child_ids),
            ReleaseSystem.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    by_system: dict[int, dict] = {}
    for rs, sys, rel in (await db.execute(stmt)).all():
        entry = by_system.setdefault(
            sys.id,
            {"system_id": sys.id, "system_name": sys.name, "roles_by_project": {}},
        )
        entry["roles_by_project"].setdefault(rel.name, []).append(rs.role)
    return [SystemRollupRow(**v) for v in by_system.values()]


async def scope_rollup(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
    change_kind: Optional[str] = None,
    status: Optional[str] = None,
    project_release_id: Optional[int] = None,
    system_id: Optional[int] = None,
    search: Optional[str] = None,
    page: Optional[Page] = None,
) -> tuple[list[ScopeRollupItem], int]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return [], 0
    if project_release_id is not None:
        if project_release_id not in child_ids:
            return [], 0
        child_ids = [project_release_id]

    stmt = (
        select(ReleaseChange, Release, System)
        .join(Release, ReleaseChange.release_id == Release.id)
        .outerjoin(System, ReleaseChange.system_id == System.id)
        .where(
            ReleaseChange.release_id.in_(child_ids),
            ReleaseChange.tenant_id == tenant_id,
            ReleaseChange.deleted_at.is_(None),
        )
    )
    if change_kind:
        stmt = stmt.where(ReleaseChange.change_kind == change_kind)
    if status:
        stmt = stmt.where(ReleaseChange.external_status == status)
    if system_id:
        stmt = stmt.where(ReleaseChange.system_id == system_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (ReleaseChange.title.ilike(like)) | (ReleaseChange.external_key.ilike(like))
        )

    stmt = stmt.order_by(ReleaseChange.id)
    rows, total = await fetch_page_rows(db, stmt, page)

    items: list[ScopeRollupItem] = []
    for rc, rel, sys in rows:
        items.append(ScopeRollupItem(
            release_change_id=rc.id,
            project_release_id=rel.id,
            project_release_name=rel.name,
            external_key=rc.external_key,
            title=rc.title,
            change_kind=rc.change_kind,
            external_status=rc.external_status,
            system_id=rc.system_id,
            system_name=sys.name if sys else None,
        ))
    return items, total


async def timeline_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> TimelineRollupRead:
    tenant_id = user.active_tenant_id

    # Enterprise's own phases
    enterprise_rows = (await db.execute(
        select(TestPhase, Release)
        .join(Release, TestPhase.release_id == Release.id)
        .where(
            TestPhase.release_id == enterprise_id,
            TestPhase.tenant_id == tenant_id,
            TestPhase.deleted_at.is_(None),
        )
    )).all()
    enterprise_phases = [
        TimelinePhaseRead(
            release_id=rel.id,
            release_name=rel.name,
            release_kind=rel.release_kind,
            phase_id=tp.id,
            phase_name=tp.name,
            start_date=tp.start_date,
            end_date=tp.end_date,
            status=tp.status,
        )
        for tp, rel in enterprise_rows
    ]

    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    child_phases: dict[int, list[TimelinePhaseRead]] = {cid: [] for cid in child_ids}
    if child_ids:
        rows = (await db.execute(
            select(TestPhase, Release)
            .join(Release, TestPhase.release_id == Release.id)
            .where(
                TestPhase.release_id.in_(child_ids),
                TestPhase.tenant_id == tenant_id,
                TestPhase.deleted_at.is_(None),
            )
        )).all()
        for tp, rel in rows:
            child_phases[rel.id].append(TimelinePhaseRead(
                release_id=rel.id,
                release_name=rel.name,
                release_kind=rel.release_kind,
                phase_id=tp.id,
                phase_name=tp.name,
                start_date=tp.start_date,
                end_date=tp.end_date,
                status=tp.status,
            ))

    dependencies: list[TimelineDependencyEdge] = []
    if child_ids:
        dep_rows = (await db.execute(
            select(ReleaseDependency).where(
                ReleaseDependency.release_id.in_(child_ids),
                ReleaseDependency.depends_on_release_id.in_(child_ids),
                ReleaseDependency.tenant_id == tenant_id,
            )
        )).scalars().all()

        # Build a name map for all child releases (already fetched above, re-use rows)
        name_by_id: dict[int, str] = {}
        if child_ids:
            rel_rows = (await db.execute(
                select(Release.id, Release.name).where(
                    Release.id.in_(child_ids), Release.tenant_id == tenant_id
                )
            )).all()
            name_by_id = {rid: name for rid, name in rel_rows}

        dependencies = [
            TimelineDependencyEdge(
                from_release_id=d.release_id,
                to_release_id=d.depends_on_release_id,
                from_release_name=name_by_id.get(d.release_id),
                to_release_name=name_by_id.get(d.depends_on_release_id),
                alert=None,
            )
            for d in dep_rows
        ]

    return TimelineRollupRead(
        enterprise_phases=enterprise_phases,
        child_phases_by_release=child_phases,
        dependencies=dependencies,
    )


async def raid_rollup(
    db: AsyncSession, enterprise_id: int, tenant_id: int, config
) -> dict:
    """Aggregate RAID items across an enterprise release's accepted members."""
    from datetime import datetime, timezone

    from app.db.models.raid import RaidItem
    from app.services import raid_service

    cfg = raid_service._config_dict(config)
    counts_by_type = {"risk": 0, "assumption": 0, "issue": 0, "dependency": 0}
    counts_by_rag = {"green": 0, "amber": 0, "red": 0}
    open_issues = 0
    overdue_reviews = 0
    top_risks: list[dict] = []

    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return {
            "counts_by_type": counts_by_type,
            "counts_by_rag": counts_by_rag,
            "open_issues": open_issues,
            "overdue_reviews": overdue_reviews,
            "top_risks": top_risks,
        }

    items = (await db.execute(
        select(RaidItem).where(
            RaidItem.release_id.in_(child_ids),
            RaidItem.tenant_id == tenant_id,
            RaidItem.deleted_at.is_(None),
        )
    )).scalars().all()

    now = datetime.now(timezone.utc)
    candidates: list[dict] = []
    for it in items:
        counts_by_type[it.item_type] = counts_by_type.get(it.item_type, 0) + 1
        sev = raid_service.severity(it.probability, it.impact)
        r = raid_service.rag(sev, cfg)
        if r in counts_by_rag:
            counts_by_rag[r] += 1
        if it.item_type == "issue" and it.status != "closed":
            open_issues += 1
        if it.review_date and it.review_date < now and it.status not in ("closed", "promoted", "met"):
            overdue_reviews += 1
        if it.item_type in ("risk", "issue") and sev is not None:
            candidates.append({
                "ref_code": raid_service.ref_code(it),
                "release_id": it.release_id,
                "title": it.title,
                "severity": sev,
                "rag": r,
            })

    candidates.sort(key=lambda c: c["severity"], reverse=True)
    top_risks = candidates[:10]

    return {
        "counts_by_type": counts_by_type,
        "counts_by_rag": counts_by_rag,
        "open_issues": open_issues,
        "overdue_reviews": overdue_reviews,
        "top_risks": top_risks,
    }


async def member_state_summary(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[MemberStateCount]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []
    rows = (await db.execute(
        select(Release).where(Release.id.in_(child_ids))
    )).scalars().all()
    grouped: dict[str, list[str]] = {}
    for r in rows:
        grouped.setdefault(r.status, []).append(r.name)
    return [
        MemberStateCount(state=s, count=len(names), projects=names)
        for s, names in grouped.items()
    ]


async def members_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[MemberRollupRow]:
    tenant_id = user.active_tenant_id
    rows = (await db.execute(
        select(ReleaseMembership, Release)
        .join(Release, ReleaseMembership.project_release_id == Release.id)
        .where(
            ReleaseMembership.enterprise_release_id == enterprise_id,
            ReleaseMembership.tenant_id == tenant_id,
            ReleaseMembership.state == MembershipState.ACCEPTED.value,
        )
    )).all()
    return [
        MemberRollupRow(
            project_release_id=rel.id,
            project_release_name=rel.name,
            status=rel.status,
            admitted_at=m.decided_at,
            late_scope=m.late_scope,
        )
        for m, rel in rows
    ]
