"""Write or compare a DeclaredState against the subsystem catalogue.

Both consumers read the same declared value, which is what stops the drift
report describing a change a scan would not make. `diff` is added in Task 6.
"""
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dependency import (
    ComponentDependency,
    DependencyDirection,
    DependencySource,
    DependencyType,
)
from app.db.models.system import SubSystem, SubSystemSource
from app.services.scanning.declared import DeclaredState


@dataclass
class ApplyResult:
    subsystems_created: int = 0
    subsystems_updated: int = 0
    dependencies_written: int = 0


async def catalogue(
    db: AsyncSession, *, system_id: int, tenant_id: int
) -> dict[str, SubSystem]:
    """Every live subsystem of this system, keyed by name.

    Name is the match key both halves use — the same key the importers have
    always upserted on, so the writer and the differ cannot disagree about
    identity.

    Caveat: there is no database-level unique constraint on
    (name, system_id, tenant_id) — `system_service.create_subsystem`'s
    uniqueness check is application-level and racy. Two live subsystems that
    ended up sharing a name within one system collapse into a single dict
    entry here, silently: the loser is invisible to `apply()` and to `diff()`.
    """
    rows = (await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )).scalars().all()
    return {row.name: row for row in rows}


async def apply(
    db: AsyncSession,
    *,
    system_id: int,
    tenant_id: int,
    source: SubSystemSource,
    edge_source: DependencySource | None,
    declared: DeclaredState,
) -> ApplyResult:
    """Write what `declared` says into the catalogue.

    Never deletes a subsystem: a resource removed from the code stays in the
    catalogue, which is precisely the drift the report exists to surface.

    `edge_source=None` means this source declares no dependency edges. It must
    only be paired with a `declared` that carries none: the delete below keys
    on `ComponentDependency.source == edge_source`, and since that column is
    NOT NULL, `source IS NULL` can never match a row, so a `None` edge_source
    can never clean up edges it wrote. If edges were written anyway, each row
    would go in stamped `source=DependencySource.MANUAL` — SQLAlchemy applies
    a column's Python-side `default=` whenever the assigned value is `None`,
    even assigned explicitly — silently mislabelling a scan-written edge as
    hand-entered, and a re-scan would then raise `IntegrityError` on
    `uq_component_dep` because the dead delete never removed the first run's
    rows. Raise instead of writing edges no one will ever be able to reconcile.
    """
    existing = await catalogue(db, system_id=system_id, tenant_id=tenant_id)
    result = ApplyResult()
    declared_ids: dict[str, int] = {}

    for sub in declared.subsystems:
        row = existing.get(sub.name)
        if row is None:
            row = SubSystem(
                tenant_id=tenant_id,
                system_id=system_id,
                name=sub.name,
                component_type=sub.component_type,
                technology=sub.technology,
                source=source,
                source_path=sub.source_path,
            )
            db.add(row)
            await db.flush()  # assign the id the edges below need
            existing[sub.name] = row
            result.subsystems_created += 1
        else:
            row.component_type = sub.component_type
            row.technology = sub.technology
            # Stamped on update as well as insert, so rows that predate the
            # source column stop reading as hand-made once a scan matches them.
            row.source = source
            row.source_path = sub.source_path
            result.subsystems_updated += 1
        declared_ids[sub.name] = row.id

    if edge_source is None:
        if declared.edges:
            raise ValueError(
                "a source that declares dependency edges must supply an "
                "edge_source; got edge_source=None with "
                f"{len(declared.edges)} edge(s) to write"
            )
        await db.flush()
        return result

    all_ids = [row.id for row in existing.values()]
    if all_ids:
        # Delete-then-recreate: an edge dropped from the code disappears from
        # the catalogue, unlike a subsystem. The compose importer has always
        # behaved this way.
        await db.execute(
            delete(ComponentDependency).where(
                ComponentDependency.tenant_id == tenant_id,
                ComponentDependency.from_subsystem_id.in_(all_ids),
                ComponentDependency.source == edge_source,
            )
        )

    written: set[tuple[int, int]] = set()
    for edge in declared.edges:
        from_id = declared_ids.get(edge.from_name)
        to_id = declared_ids.get(edge.to_name)
        # An endpoint this declaration does not define cannot be written.
        # diff() skips the same edges, or the round-trip guarantee breaks.
        if from_id is None or to_id is None or from_id == to_id:
            continue
        if (from_id, to_id) in written:
            # uq_component_dep is (from, to, tenant): a repeat would raise
            # IntegrityError and cost this detector its whole savepoint.
            continue
        written.add((from_id, to_id))
        db.add(ComponentDependency(
            tenant_id=tenant_id,
            from_subsystem_id=from_id,
            to_subsystem_id=to_id,
            dependency_type=DependencyType.API_CALL,
            direction=DependencyDirection.ONE_WAY,
            source=edge_source,
            port=edge.port,
        ))
        result.dependencies_written += 1

    await db.flush()
    return result
