"""Release dependency service — list/create/delete + alert computation.

Alert logic: compare current depends_on.target_date vs stored last_dependency_target_date.
Returns only dependencies with a non-zero diff_days.
Never calls db.commit(). Rejects self-dependencies.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release import Release
from app.db.models.release_dependency import ReleaseDependency
from app.api.v1.schemas.release_dependency import ReleaseDependencyAlert, ReleaseDependencyCreate


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _get_dep(
    db: AsyncSession, dep_id: int, tenant_id: int
) -> ReleaseDependency:
    dep = (
        await db.execute(
            select(ReleaseDependency).where(
                ReleaseDependency.id == dep_id,
                ReleaseDependency.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if dep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release dependency not found")
    return dep


async def _get_release(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Release:
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
    return release


# ── Public API ───────────────────────────────────────────────────────────────

async def list_dependencies(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[ReleaseDependency]:
    rows = (
        await db.execute(
            select(ReleaseDependency).where(
                ReleaseDependency.release_id == release_id,
                ReleaseDependency.tenant_id == tenant_id,
            ).order_by(ReleaseDependency.id)
        )
    ).scalars().all()
    return list(rows)


async def create_dependency(
    db: AsyncSession,
    release_id: int,
    data: ReleaseDependencyCreate,
    tenant_id: int,
) -> ReleaseDependency:
    if release_id == data.depends_on_release_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A release cannot depend on itself",
        )

    # Verify the dependency target exists (and belongs to the same tenant)
    dep_release = await _get_release(db, data.depends_on_release_id, tenant_id)

    dep = ReleaseDependency(
        tenant_id=tenant_id,
        release_id=release_id,
        depends_on_release_id=data.depends_on_release_id,
        kind=data.kind,
        notes=data.notes,
        last_dependency_target_date=dep_release.target_date,
    )
    db.add(dep)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseDependencyAdded",
        aggregate_id=dep.id,
        aggregate_type="ReleaseDependency",
        payload={
            "id": dep.id,
            "release_id": release_id,
            "depends_on_release_id": data.depends_on_release_id,
            "kind": data.kind,
        },
        tenant_id=tenant_id,
    )
    return dep


async def delete_dependency(
    db: AsyncSession,
    dep_id: int,
    tenant_id: int,
) -> None:
    dep = await _get_dep(db, dep_id, tenant_id)

    await db.delete(dep)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseDependencyRemoved",
        aggregate_id=dep_id,
        aggregate_type="ReleaseDependency",
        payload={"id": dep_id},
        tenant_id=tenant_id,
    )


async def get_dependency_alerts(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[ReleaseDependencyAlert]:
    """Return dependencies where the dependency's target_date has shifted."""
    deps = await list_dependencies(db, release_id, tenant_id)
    alerts: list[ReleaseDependencyAlert] = []

    for dep in deps:
        dep_release = (
            await db.execute(
                select(Release).where(
                    Release.id == dep.depends_on_release_id,
                    Release.tenant_id == tenant_id,
                    Release.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if dep_release is None:
            continue

        current = dep_release.target_date
        prior = dep.last_dependency_target_date

        if current == prior:
            continue

        # Compute diff in days (None dates are treated as 0 for diff calculation)
        if current is not None and prior is not None:
            diff_days = (
                current.replace(tzinfo=None) - prior.replace(tzinfo=None)
            ).days
        elif current is not None:
            diff_days = 1  # prior was None, now has a date — non-zero
        elif prior is not None:
            diff_days = -1  # was set, now gone
        else:
            continue  # both None, no change

        if diff_days == 0:
            continue

        alerts.append(
            ReleaseDependencyAlert(
                dependency_id=dep.id,
                depends_on_release_id=dep.depends_on_release_id,
                depends_on_name=dep_release.name,
                prior_target_date=prior,
                current_target_date=current,
                diff_days=diff_days,
            )
        )
    return alerts


async def acknowledge_alert(
    db: AsyncSession,
    release_id: int,
    dep_id: int,
    tenant_id: int,
) -> None:
    """Update last_dependency_target_date to the dependency's current target_date."""
    dep = await _get_dep(db, dep_id, tenant_id)
    if dep.release_id != release_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Release dependency not found"
        )

    dep_release = (
        await db.execute(
            select(Release).where(
                Release.id == dep.depends_on_release_id,
                Release.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()

    dep.last_dependency_target_date = dep_release.target_date if dep_release else None
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseDependencyAlertAcknowledged",
        aggregate_id=dep.id,
        aggregate_type="ReleaseDependency",
        payload={
            "id": dep.id,
            "release_id": release_id,
            "depends_on_release_id": dep.depends_on_release_id,
        },
        tenant_id=tenant_id,
    )
