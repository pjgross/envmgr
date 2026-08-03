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
from app.services.scanning.declared import DeclaredEdge, DeclaredState, DeclaredSubsystem


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


@dataclass(frozen=True)
class ChangedSubsystem:
    name: str
    field: str  # "component_type" | "technology"
    catalogue: str | None
    declared: str | None
    source_path: str


@dataclass(frozen=True)
class EdgeRef:
    from_name: str
    to_name: str
    port: int | None


@dataclass(frozen=True)
class ChangedEdge:
    from_name: str
    to_name: str
    catalogue_port: int | None
    declared_port: int | None
    source_path: str


@dataclass
class DriftReport:
    subsystems_missing_in_catalogue: list[DeclaredSubsystem]
    subsystems_missing_in_code: list[str] | None
    subsystems_changed: list[ChangedSubsystem]
    edges_missing_in_catalogue: list[DeclaredEdge]
    edges_missing_in_code: list[EdgeRef] | None
    edges_changed: list[ChangedEdge]
    absence_computed: bool
    absence_reason: str | None
    warnings: list[str]

    @property
    def has_drift(self) -> bool:
        return bool(
            self.subsystems_missing_in_catalogue
            or self.subsystems_missing_in_code
            or self.subsystems_changed
            or self.edges_missing_in_catalogue
            or self.edges_missing_in_code
            or self.edges_changed
        )


def _column_value(value) -> str | None:
    """Enum columns come back as the enum on one path and the raw string on
    another depending on how the row was loaded."""
    return getattr(value, "value", value)


async def diff(
    db: AsyncSession,
    *,
    system_id: int,
    tenant_id: int,
    source: SubSystemSource,
    edge_source: DependencySource | None,
    declared: DeclaredState,
    absence_computed: bool,
    absence_reason: str | None,
) -> DriftReport:
    """Compare `declared` against the catalogue. Writes nothing.

    `absence_computed=False` means the repository was read only in part, so
    files never read cannot be told apart from deleted ones. The absence
    categories are then left as None rather than computed wrong.
    """
    existing = await catalogue(db, system_id=system_id, tenant_id=tenant_id)
    warnings = list(declared.warnings)

    declared_by_name: dict[str, DeclaredSubsystem] = {}
    for sub in declared.subsystems:
        previous = declared_by_name.get(sub.name)
        if previous is not None and previous.source_path != sub.source_path:
            warnings.append(
                f"{sub.name!r} is declared in both {previous.source_path} and "
                f"{sub.source_path}; only the last is kept"
            )
        declared_by_name[sub.name] = sub

    missing_in_catalogue = [
        sub for name, sub in declared_by_name.items() if name not in existing
    ]

    changed: list[ChangedSubsystem] = []
    for name, sub in declared_by_name.items():
        row = existing.get(name)
        if row is None:
            continue
        row_type = _column_value(row.component_type)
        if row_type != sub.component_type:
            changed.append(ChangedSubsystem(
                name=name, field="component_type", catalogue=row_type,
                declared=sub.component_type, source_path=sub.source_path,
            ))
        if (row.technology or None) != (sub.technology or None):
            changed.append(ChangedSubsystem(
                name=name, field="technology", catalogue=row.technology,
                declared=sub.technology, source_path=sub.source_path,
            ))

    missing_in_code: list[str] | None = None
    if absence_computed:
        missing_in_code = sorted(
            name for name, row in existing.items()
            if _column_value(row.source) == source.value and name not in declared_by_name
        )

    edges_missing_in_catalogue: list[DeclaredEdge] = []
    edges_changed: list[ChangedEdge] = []
    edges_missing_in_code: list[EdgeRef] | None = None

    if edge_source is not None:
        name_by_id = {row.id: name for name, row in existing.items()}
        rows = []
        if name_by_id:
            rows = (await db.execute(
                select(ComponentDependency).where(
                    ComponentDependency.tenant_id == tenant_id,
                    ComponentDependency.source == edge_source,
                    ComponentDependency.from_subsystem_id.in_(list(name_by_id)),
                    ComponentDependency.to_subsystem_id.in_(list(name_by_id)),
                )
            )).scalars().all()
        catalogue_edges = {
            (name_by_id[row.from_subsystem_id], name_by_id[row.to_subsystem_id]): row
            for row in rows
        }

        declared_edges: dict[tuple[str, str], DeclaredEdge] = {}
        for edge in declared.edges:
            # Exactly the edges apply() would skip. Reporting one it cannot
            # write would leave the round-trip permanently non-zero.
            if edge.from_name == edge.to_name:
                continue
            if edge.from_name not in declared_by_name or edge.to_name not in declared_by_name:
                continue
            declared_edges[(edge.from_name, edge.to_name)] = edge

        for key, edge in declared_edges.items():
            row = catalogue_edges.get(key)
            if row is None:
                edges_missing_in_catalogue.append(edge)
            elif row.port != edge.port:
                edges_changed.append(ChangedEdge(
                    from_name=key[0], to_name=key[1], catalogue_port=row.port,
                    declared_port=edge.port, source_path=edge.source_path,
                ))

        if absence_computed:
            edges_missing_in_code = sorted(
                (
                    EdgeRef(from_name=key[0], to_name=key[1], port=row.port)
                    for key, row in catalogue_edges.items()
                    if key not in declared_edges
                ),
                key=lambda ref: (ref.from_name, ref.to_name),
            )

    return DriftReport(
        subsystems_missing_in_catalogue=missing_in_catalogue,
        subsystems_missing_in_code=missing_in_code,
        subsystems_changed=changed,
        edges_missing_in_catalogue=edges_missing_in_catalogue,
        edges_missing_in_code=edges_missing_in_code,
        edges_changed=edges_changed,
        absence_computed=absence_computed,
        absence_reason=absence_reason,
        warnings=warnings,
    )
