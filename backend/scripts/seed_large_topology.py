"""
Seed a large synthetic topology into the dev database for performance testing.

Run after migrations:
    cd backend
    DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_large_topology.py

Idempotent: removes any previously-seeded "Perf System *" data for the demo
tenant first, then recreates it. Tune scale with CLI args:
    --systems 7 --components 300 --deps 600
"""
import argparse
import asyncio
import os
import random
from dataclasses import dataclass, field

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.models.user import Tenant
from app.db.models.system import System, SubSystem, ComponentType
from app.db.models.dependency import (
    ComponentDependency,
    DependencyType,
    DependencyDirection,
    DependencySource,
)

SYSTEM_NAME_PREFIX = "Perf System "
COMPONENT_TYPES = [t.value for t in ComponentType]
DEPENDENCY_TYPES = [t.value for t in DependencyType]


@dataclass
class PlanSystem:
    index: int
    name: str
    is_hub: bool


@dataclass
class PlanComponent:
    index: int
    system_index: int
    component_type: str
    name: str


@dataclass
class PlanDep:
    from_index: int
    to_index: int
    dependency_type: str
    cross: bool


@dataclass
class TopologyPlan:
    systems: list[PlanSystem] = field(default_factory=list)
    components: list[PlanComponent] = field(default_factory=list)
    deps: list[PlanDep] = field(default_factory=list)


def build_topology_plan(
    num_systems: int, num_components: int, num_deps: int, seed: int = 0
) -> TopologyPlan:
    """Pure planner: produce a deterministic multi-system topology description.

    ~25% of deps are cross-system; the first system is the hub and receives the
    largest share of cross-system edges so a single topology view stresses both
    intra-system layout and external fan-in.
    """
    rng = random.Random(seed)
    plan = TopologyPlan()

    hub_index = 0
    for i in range(num_systems):
        plan.systems.append(
            PlanSystem(index=i, name=f"{SYSTEM_NAME_PREFIX}{i}", is_hub=(i == hub_index))
        )

    comps_by_system: dict[int, list[int]] = {i: [] for i in range(num_systems)}
    for j in range(num_components):
        system_index = j % num_systems  # even distribution, deterministic
        plan.components.append(
            PlanComponent(
                index=j,
                system_index=system_index,
                component_type=rng.choice(COMPONENT_TYPES),
                name=f"comp-{j}",
            )
        )
        comps_by_system[system_index].append(j)

    target_cross = num_deps // 4
    seen: set[tuple[int, int]] = set()

    def add_dep(a: int, b: int, cross: bool) -> bool:
        key = (a, b)
        if a == b or key in seen:
            return False
        seen.add(key)
        plan.deps.append(
            PlanDep(from_index=a, to_index=b, dependency_type=rng.choice(DEPENDENCY_TYPES), cross=cross)
        )
        return True

    # Cross-system deps: one endpoint biased toward the hub.
    non_hub = [i for i in range(num_systems) if i != hub_index]
    guard = 0
    while sum(1 for d in plan.deps if d.cross) < target_cross and guard < target_cross * 50:
        guard += 1
        other = rng.choice(non_hub)
        hub_comp = rng.choice(comps_by_system[hub_index])
        other_comp = rng.choice(comps_by_system[other])
        if rng.random() < 0.5:
            add_dep(hub_comp, other_comp, cross=True)
        else:
            add_dep(other_comp, hub_comp, cross=True)

    # Intra-system deps fill the remainder.
    guard = 0
    while len(plan.deps) < num_deps and guard < num_deps * 50:
        guard += 1
        system_index = rng.randrange(num_systems)
        comps = comps_by_system[system_index]
        if len(comps) < 2:
            continue
        a, b = rng.sample(comps, 2)
        add_dep(a, b, cross=False)

    return plan


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr",
)


async def _clear_previous(session: AsyncSession, tenant_id: int) -> None:
    """Remove previously-seeded Perf System data for this tenant (idempotency)."""
    result = await session.execute(
        select(System).where(
            System.tenant_id == tenant_id,
            System.name.like(f"{SYSTEM_NAME_PREFIX}%"),
        )
    )
    systems = result.scalars().all()
    if not systems:
        return
    system_ids = [s.id for s in systems]

    sub_result = await session.execute(
        select(SubSystem.id).where(SubSystem.system_id.in_(system_ids))
    )
    sub_ids = [row[0] for row in sub_result.all()]
    if sub_ids:
        await session.execute(
            delete(ComponentDependency).where(
                ComponentDependency.from_subsystem_id.in_(sub_ids)
            )
        )
        await session.execute(
            delete(ComponentDependency).where(
                ComponentDependency.to_subsystem_id.in_(sub_ids)
            )
        )
        await session.execute(delete(SubSystem).where(SubSystem.id.in_(sub_ids)))
    await session.execute(delete(System).where(System.id.in_(system_ids)))
    print(f"✓ Cleared {len(system_ids)} previous Perf Systems")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a large synthetic topology")
    parser.add_argument("--systems", type=int, default=7)
    parser.add_argument("--components", type=int, default=300)
    parser.add_argument("--deps", type=int, default=600)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    plan = build_topology_plan(args.systems, args.components, args.deps, seed=args.seed)

    engine = create_async_engine(DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        result = await session.execute(select(Tenant).where(Tenant.slug == args.tenant))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise SystemExit(f"Tenant '{args.tenant}' not found — seed it first")

        await _clear_previous(session, tenant.id)

        system_ids: dict[int, int] = {}
        for ps in plan.systems:
            suffix = " (hub)" if ps.is_hub else ""
            sys = System(name=f"{ps.name}{suffix}", tenant_id=tenant.id)
            session.add(sys)
            await session.flush()
            system_ids[ps.index] = sys.id

        component_ids: dict[int, int] = {}
        for pc in plan.components:
            sub = SubSystem(
                name=pc.name,
                component_type=pc.component_type,
                system_id=system_ids[pc.system_index],
                tenant_id=tenant.id,
            )
            session.add(sub)
            await session.flush()
            component_ids[pc.index] = sub.id

        for pd in plan.deps:
            session.add(
                ComponentDependency(
                    from_subsystem_id=component_ids[pd.from_index],
                    to_subsystem_id=component_ids[pd.to_index],
                    dependency_type=pd.dependency_type,
                    direction=DependencyDirection.ONE_WAY.value,
                    source=DependencySource.MANUAL.value,
                    tenant_id=tenant.id,
                )
            )

        await session.commit()

    await engine.dispose()
    hub = next(s for s in plan.systems if s.is_hub)
    print(
        f"✓ Seeded {len(plan.systems)} systems, {len(plan.components)} components, "
        f"{len(plan.deps)} deps into tenant '{args.tenant}'"
    )
    print(f"  Benchmark from the hub system: '{hub.name} (hub)' (id {system_ids[hub.index]})")


if __name__ == "__main__":
    asyncio.run(main())
