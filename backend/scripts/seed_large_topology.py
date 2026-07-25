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
