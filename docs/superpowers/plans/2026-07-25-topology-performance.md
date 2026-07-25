# Topology Diagram Performance (Sub-Project 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the system topology diagram usable at ~300 densely-linked components without freezing the UI, and prepare a data-source seam so scaling to ~1000 later needs no rewrite.

**Architecture:** Four increments, each its own branch → PR → cumulative `main`: (1) a reproducible synthetic seed + dev instrumentation to capture a baseline; (2) move ELK layout off the main thread into a web worker with a main-thread fallback; (3) cheap render wins (`React.memo`, viewport culling, zoom clamps); (4) a typed `TopologySource` seam at the data→pipeline boundary. The pipeline shape (`computeVisibleGraph → computeCollapseModel → buildElkGraph → layout → elkToReactFlow → React Flow`) is unchanged.

**Tech Stack:** Backend: FastAPI, SQLAlchemy async, `uv`. Frontend: React 18, TypeScript, `reactflow` ^11, `elkjs` ^0.12, Vitest + Testing Library.

**Spec:** [docs/superpowers/specs/2026-07-25-topology-performance-design.md](../specs/2026-07-25-topology-performance-design.md)

**Commands:**
- Backend tests: `cd backend && uv run pytest <path> -v`
- Frontend tests: `cd frontend && npx vitest run <path>`
- Seed: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_large_topology.py`

---

## File Structure

**Create:**
- `backend/scripts/seed_large_topology.py` — synthetic multi-system topology generator + seeder. Pure `build_topology_plan()` planner (testable) + `main()` DB writer.
- `backend/tests/test_seed_large_topology.py` — tests for the pure planner.
- `frontend/src/components/topology/topologyPerf.ts` — dev-only instrumentation (`logLayout`, `useRenderCount`).
- `frontend/src/components/topology/topologyLayout.ts` — layout engine: `createLayoutEngine()` + default `layoutTopology()`; worker with main-thread fallback; owns the three-step compose (build → layout → elkToReactFlow) + timing.
- `frontend/src/components/topology/SubsystemNode.tsx` — extracted from `SystemTopologyDiagram.tsx`, memoized.
- `frontend/src/components/topology/topologySource.ts` — `TopologySource` interface + `fromTopologyResponse()`.
- `frontend/src/components/topology/__tests__/topologyPerf.test.ts`
- `frontend/src/components/topology/__tests__/topologyLayout.test.ts`
- `frontend/src/components/topology/__tests__/nodeMemo.test.tsx`
- `frontend/src/components/topology/__tests__/topologySource.test.ts`

**Modify:**
- `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — use `SubsystemNode` from its own file; call `layoutTopology()` instead of inline `elk.layout()`; add `onlyRenderVisibleElements` + zoom clamps; build graph via `TopologySource`.
- `frontend/src/components/topology/SystemGroupNode.tsx` — wrap in `React.memo`, add `useRenderCount`.
- `frontend/src/components/topology/CollapsedSystemNode.tsx` — wrap in `React.memo`, add `useRenderCount`.

---

## INCREMENT 1 — Seed + Instrumentation

Branch: `feature/topology-perf-seed`

### Task 1: Synthetic topology planner (pure logic)

**Files:**
- Create: `backend/scripts/seed_large_topology.py`
- Test: `backend/tests/test_seed_large_topology.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_seed_large_topology.py
from scripts.seed_large_topology import build_topology_plan


def test_plan_honours_requested_counts():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    assert len(plan.systems) == 7
    assert len(plan.components) == 300
    assert len(plan.deps) == 600


def test_plan_has_exactly_one_hub_with_most_cross_edges():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    hubs = [s for s in plan.systems if s.is_hub]
    assert len(hubs) == 1
    hub = hubs[0]
    cross_by_system: dict[int, int] = {}
    for d in plan.deps:
        if not d.cross:
            continue
        from_sys = plan.components[d.from_index].system_index
        to_sys = plan.components[d.to_index].system_index
        cross_by_system[from_sys] = cross_by_system.get(from_sys, 0) + 1
        cross_by_system[to_sys] = cross_by_system.get(to_sys, 0) + 1
    assert cross_by_system[hub.index] == max(cross_by_system.values())


def test_deps_are_well_formed():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    n = len(plan.components)
    for d in plan.deps:
        assert 0 <= d.from_index < n and 0 <= d.to_index < n
        assert d.from_index != d.to_index
        same_system = (
            plan.components[d.from_index].system_index
            == plan.components[d.to_index].system_index
        )
        assert d.cross != same_system  # cross <=> different systems


def test_plan_is_deterministic_for_a_seed():
    a = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    b = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    assert [(d.from_index, d.to_index, d.cross) for d in a.deps] == [
        (d.from_index, d.to_index, d.cross) for d in b.deps
    ]


def test_cross_ratio_is_roughly_a_quarter():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    cross = sum(1 for d in plan.deps if d.cross)
    assert 120 <= cross <= 180  # ~25% of 600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_seed_large_topology.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'build_topology_plan'`

- [ ] **Step 3: Write minimal implementation (planner only)**

```python
# backend/scripts/seed_large_topology.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_seed_large_topology.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/seed_large_topology.py backend/tests/test_seed_large_topology.py
git commit -m "feat(topology): synthetic large-topology planner for perf testing"
```

### Task 2: Seed writer (DB insertion + idempotency)

**Files:**
- Modify: `backend/scripts/seed_large_topology.py` (append `main()` + CLI)

- [ ] **Step 1: Append the writer and CLI entrypoint**

```python
# backend/scripts/seed_large_topology.py  (append below build_topology_plan)

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
```

- [ ] **Step 2: Run it against the dev DB**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_large_topology.py`
Expected: prints `✓ Seeded 7 systems, 300 components, 600 deps ...` and the hub system id. Run it a **second time**; expected: prints `✓ Cleared 7 previous Perf Systems` then re-seeds (no duplication).

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/seed_large_topology.py
git commit -m "feat(topology): idempotent DB writer + CLI for large-topology seed"
```

### Task 3: Dev instrumentation module

**Files:**
- Create: `frontend/src/components/topology/topologyPerf.ts`
- Test: `frontend/src/components/topology/__tests__/topologyPerf.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/topology/__tests__/topologyPerf.test.ts
import { describe, expect, it, vi, afterEach } from 'vitest';
import { logLayout, PERF_PREFIX } from '../topologyPerf';

afterEach(() => vi.restoreAllMocks());

describe('logLayout', () => {
  it('logs layout stats with the perf prefix in dev', () => {
    const spy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    logLayout({ layoutMs: 12.5, nodeCount: 300, edgeCount: 600, engine: 'worker' });
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0]).toContain(PERF_PREFIX);
    expect(spy.mock.calls[0][1]).toMatchObject({ nodeCount: 300, edgeCount: 600, engine: 'worker' });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyPerf.test.ts`
Expected: FAIL — cannot resolve `../topologyPerf`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/components/topology/topologyPerf.ts
import { useRef } from 'react';

export const PERF_PREFIX = '[topo-perf]';

export interface LayoutStats {
  layoutMs: number;
  nodeCount: number;
  edgeCount: number;
  engine: 'worker' | 'bundled';
}

/** Dev-only: log ELK layout timing + graph size. No-op in production builds. */
export function logLayout(stats: LayoutStats): void {
  if (!import.meta.env.DEV) return;
  // eslint-disable-next-line no-console
  console.debug(`${PERF_PREFIX} layout`, stats);
}

/** Dev-only: count renders of a node component to validate memoization. */
export function useRenderCount(label: string): void {
  const n = useRef(0);
  n.current += 1;
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.debug(`${PERF_PREFIX} render ${label} #${n.current}`);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyPerf.test.ts`
Expected: PASS

- [ ] **Step 5: Wire timing into the existing layout effect**

In `frontend/src/pages/systems/SystemTopologyDiagram.tsx`, add the import near the other topology imports:

```ts
import { logLayout } from '../../components/topology/topologyPerf';
```

Replace the `elk.layout(...)` chain (currently lines ~190-201) with a timed version:

```ts
    const started = performance.now();
    elk
      .layout(buildElkGraph(model))
      .then((res) => {
        if (cancelled) return;
        const rf = elkToReactFlow(res, model, ctx);
        logLayout({
          layoutMs: performance.now() - started,
          nodeCount: rf.nodes.length,
          edgeCount: rf.edges.length,
          engine: 'bundled',
        });
        setLayout(rf);
      })
      .catch(() => {
        if (!cancelled) setLayout({ nodes: [], edges: [] });
      })
      .finally(() => {
        if (!cancelled) setLayingOut(false);
      });
```

- [ ] **Step 6: Verify the app builds and existing tests pass**

Run: `cd frontend && npx vitest run src/components/topology/`
Expected: PASS (all topology tests green)

- [ ] **Step 7: Capture the baseline (manual)**

Start the app (`npm run dev`), open the hub Perf System's Topology tab, filter DevTools console by `[topo-perf]`. Record `layoutMs`, node/edge counts, whether the UI froze, and pan/zoom feel in the spec's **Measurement Log** table, row "1 baseline".

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/topology/topologyPerf.ts \
        frontend/src/components/topology/__tests__/topologyPerf.test.ts \
        frontend/src/pages/systems/SystemTopologyDiagram.tsx \
        docs/superpowers/specs/2026-07-25-topology-performance-design.md
git commit -m "feat(topology): dev layout/render instrumentation + baseline"
```

---

## INCREMENT 2 — Worker Offload

Branch: `feature/topology-perf-worker`

### Task 4: Layout engine with worker + fallback

**Files:**
- Create: `frontend/src/components/topology/topologyLayout.ts`
- Test: `frontend/src/components/topology/__tests__/topologyLayout.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/topology/__tests__/topologyLayout.test.ts
import { describe, expect, it, vi } from 'vitest';
import { createLayoutEngine } from '../topologyLayout';
import type { TopologyModel } from '../topologyModel';
import type { ElkRenderContext } from '../topologyElkGraph';

const model: TopologyModel = {
  systems: [
    { systemId: 2, name: 'Customer', isCurrent: true, collapsed: false, componentCount: 1,
      components: [{ id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null }] },
  ],
  edges: [],
};

const ctx: ElkRenderContext = {
  systemNames: { '2': 'Customer' },
  subsystems: new Map([[5, { id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null }]]),
  colorFor: () => '#000',
};

// A fake ELK that echoes the requested graph back with fixed geometry.
function fakeElk(positions: Record<string, { x: number; y: number }>) {
  return {
    layout: vi.fn(async (graph: any) => ({
      ...graph,
      children: (graph.children ?? []).map((c: any) => ({
        ...c,
        ...(positions[c.id] ?? { x: 0, y: 0 }),
        width: c.width ?? 180,
        height: c.height ?? 70,
        children: (c.children ?? []).map((cc: any) => ({ ...cc, x: 1, y: 1, width: 180, height: 70 })),
      })),
    })),
  };
}

describe('createLayoutEngine', () => {
  it('composes build → layout → elkToReactFlow into nodes+edges', async () => {
    const worker = fakeElk({ 'group-2': { x: 10, y: 20 } });
    const bundled = fakeElk({});
    const layoutTopology = createLayoutEngine(() => worker, () => bundled);

    const { nodes } = await layoutTopology(model, ctx);
    const group = nodes.find((n) => n.id === 'group-2');
    expect(group?.position).toEqual({ x: 10, y: 20 });
    expect(worker.layout).toHaveBeenCalledOnce();
    expect(bundled.layout).not.toHaveBeenCalled();
  });

  it('falls back to the bundled engine when the worker layout rejects', async () => {
    const worker = { layout: vi.fn().mockRejectedValue(new Error('no Worker in jsdom')) };
    const bundled = fakeElk({ 'group-2': { x: 3, y: 4 } });
    const layoutTopology = createLayoutEngine(() => worker as any, () => bundled);

    const { nodes } = await layoutTopology(model, ctx);
    expect(worker.layout).toHaveBeenCalledOnce();
    expect(bundled.layout).toHaveBeenCalledOnce();
    expect(nodes.find((n) => n.id === 'group-2')?.position).toEqual({ x: 3, y: 4 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyLayout.test.ts`
Expected: FAIL — cannot resolve `../topologyLayout`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/components/topology/topologyLayout.ts
import ELK from 'elkjs/lib/elk-api';
import ELKBundled from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from 'reactflow';
import { buildElkGraph, elkToReactFlow, type ElkRenderContext } from './topologyElkGraph';
import type { TopologyModel } from './topologyModel';
import { logLayout } from './topologyPerf';

interface ElkLike {
  layout: (graph: any) => Promise<any>;
}

/** Real worker-backed ELK (Vite resolves the worker asset via import.meta.url). */
function defaultWorkerElk(): ElkLike {
  return new ELK({
    workerFactory: () =>
      new Worker(new URL('elkjs/lib/elk-worker.min.js', import.meta.url), { type: 'module' }),
  }) as unknown as ElkLike;
}

/** Main-thread ELK — used as a fallback if the worker path fails. */
function defaultBundledElk(): ElkLike {
  return new ELKBundled() as unknown as ElkLike;
}

export function createLayoutEngine(
  makeWorker: () => ElkLike = defaultWorkerElk,
  makeBundled: () => ElkLike = defaultBundledElk,
) {
  let worker: ElkLike | null = null;
  let bundled: ElkLike | null = null;

  return async function layoutTopology(
    model: TopologyModel,
    ctx: ElkRenderContext,
  ): Promise<{ nodes: Node[]; edges: Edge[] }> {
    const started = performance.now();
    let engine: 'worker' | 'bundled' = 'worker';
    let result: any;
    try {
      worker ??= makeWorker();
      result = await worker.layout(buildElkGraph(model));
    } catch {
      worker = null; // stop using the worker for subsequent layouts
      engine = 'bundled';
      bundled ??= makeBundled();
      result = await bundled.layout(buildElkGraph(model));
    }
    const rf = elkToReactFlow(result, model, ctx);
    logLayout({
      layoutMs: performance.now() - started,
      nodeCount: rf.nodes.length,
      edgeCount: rf.edges.length,
      engine,
    });
    return rf;
  };
}

export const layoutTopology = createLayoutEngine();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyLayout.test.ts`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyLayout.ts \
        frontend/src/components/topology/__tests__/topologyLayout.test.ts
git commit -m "feat(topology): worker-backed layout engine with main-thread fallback"
```

### Task 5: Wire the diagram to the layout engine

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Replace the inline ELK usage**

Remove these lines from `SystemTopologyDiagram.tsx`:

```ts
import ELK from 'elkjs/lib/elk.bundled.js';
```
```ts
const elk = new ELK();
```
```ts
import { logLayout } from '../../components/topology/topologyPerf';
```

Add the import (with the other topology imports):

```ts
import { layoutTopology } from '../../components/topology/topologyLayout';
```

Replace the timed `elk.layout(...)` chain from Task 3 Step 5 with:

```ts
    layoutTopology(model, ctx)
      .then((rf) => {
        if (!cancelled) setLayout(rf);
      })
      .catch(() => {
        if (!cancelled) setLayout({ nodes: [], edges: [] });
      })
      .finally(() => {
        if (!cancelled) setLayingOut(false);
      });
```

(`buildElkGraph` / `elkToReactFlow` / `logLayout` are no longer called directly here — remove any now-unused imports of `buildElkGraph`. Keep `elkToReactFlow`'s type imports `ElkRenderContext` / `RenderSubsystem` — they are still used to build `ctx`.)

- [ ] **Step 2: Verify the topology test suite still passes**

Run: `cd frontend && npx vitest run src/components/topology/`
Expected: PASS

- [ ] **Step 3: Verify no unused-import / type errors**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (if `buildElkGraph` import is now unused, tsc/eslint will flag it — remove it).

- [ ] **Step 4: Measure (manual)**

Reload the hub Perf System topology. Confirm `[topo-perf] layout` now reports `engine: 'worker'` and the UI no longer freezes during layout. Record numbers in the Measurement Log row "2 worker".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx \
        docs/superpowers/specs/2026-07-25-topology-performance-design.md
git commit -m "feat(topology): run ELK layout off the main thread"
```

---

## INCREMENT 3 — Render Wins

Branch: `feature/topology-perf-render`

### Task 6: Extract and memoize SubsystemNode

**Files:**
- Create: `frontend/src/components/topology/SubsystemNode.tsx`
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`
- Test: `frontend/src/components/topology/__tests__/nodeMemo.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/topology/__tests__/nodeMemo.test.tsx
import { describe, expect, it } from 'vitest';
import SubsystemNode from '../SubsystemNode';
import SystemGroupNode from '../SystemGroupNode';
import CollapsedSystemNode from '../CollapsedSystemNode';

const MEMO = Symbol.for('react.memo');

describe('node components are memoized', () => {
  it('SubsystemNode is wrapped in React.memo', () => {
    expect((SubsystemNode as any).$$typeof).toBe(MEMO);
  });
  it('SystemGroupNode is wrapped in React.memo', () => {
    expect((SystemGroupNode as any).$$typeof).toBe(MEMO);
  });
  it('CollapsedSystemNode is wrapped in React.memo', () => {
    expect((CollapsedSystemNode as any).$$typeof).toBe(MEMO);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/nodeMemo.test.tsx`
Expected: FAIL — cannot resolve `../SubsystemNode`

- [ ] **Step 3: Create the extracted, memoized SubsystemNode**

```tsx
// frontend/src/components/topology/SubsystemNode.tsx
import { memo } from 'react';
import { Box, Chip, Typography } from '@mui/material';
import { Handle, Position } from 'reactflow';
import type { SubSystemResponse } from '../../types/system';
import { useRenderCount } from './topologyPerf';

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 70;

interface SubsystemNodeProps {
  data: { label: SubSystemResponse; color: string; dimmed?: boolean };
}

function SubsystemNode({ data }: SubsystemNodeProps) {
  useRenderCount('SubsystemNode');
  const s = data.label;
  return (
    <Box
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px solid ${data.color}`,
        borderRadius: 1,
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: 'pointer',
        opacity: data.dimmed ? 0.25 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: data.color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {s.technology && (
        <Typography variant="caption" color="text.secondary" noWrap>
          {s.technology}
        </Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}

export default memo(SubsystemNode);
```

- [ ] **Step 4: Remove the inline SubsystemNode from the diagram and import the new one**

In `SystemTopologyDiagram.tsx`: delete the inline `SubsystemNode` function (lines ~50-96) and the now-duplicated `NODE_WIDTH`/`NODE_HEIGHT` consts (keep using the ones imported below). Add:

```ts
import SubsystemNode, { NODE_WIDTH, NODE_HEIGHT } from '../../components/topology/SubsystemNode';
```

Ensure `nodeTypes` still references `SubsystemNode`:

```ts
const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode, collapsedSystemNode: CollapsedSystemNode };
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/nodeMemo.test.tsx && npx tsc --noEmit`
Expected: `SubsystemNode` test PASSES; the other two still FAIL (fixed next task); no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/topology/SubsystemNode.tsx \
        frontend/src/components/topology/__tests__/nodeMemo.test.tsx \
        frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "refactor(topology): extract + memoize SubsystemNode"
```

### Task 7: Memoize SystemGroupNode and CollapsedSystemNode

**Files:**
- Modify: `frontend/src/components/topology/SystemGroupNode.tsx`
- Modify: `frontend/src/components/topology/CollapsedSystemNode.tsx`

- [ ] **Step 1: Wrap SystemGroupNode in memo + add render count**

In `SystemGroupNode.tsx`, change the imports and export:

```ts
import { memo } from 'react';
import { Box, IconButton, Typography } from '@mui/material';
import UnfoldLessIcon from '@mui/icons-material/UnfoldLess';
import { useRenderCount } from './topologyPerf';
```

Rename the exported function to a plain declaration and add the hook as its first line:

```ts
function SystemGroupNode({ data }: SystemGroupNodeProps) {
  useRenderCount('SystemGroupNode');
  // ...unchanged body...
}

export default memo(SystemGroupNode);
```

(Remove `export default` from the function declaration line.)

- [ ] **Step 2: Wrap CollapsedSystemNode in memo + add render count**

In `CollapsedSystemNode.tsx`, apply the same pattern:

```ts
import { memo } from 'react';
import { Box, Typography } from '@mui/material';
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore';
import { Handle, Position } from 'reactflow';
import { useRenderCount } from './topologyPerf';
```
```ts
function CollapsedSystemNode({ data }: CollapsedSystemNodeProps) {
  useRenderCount('CollapsedSystemNode');
  // ...unchanged body...
}

export default memo(CollapsedSystemNode);
```

- [ ] **Step 3: Run tests + typecheck**

Run: `cd frontend && npx vitest run src/components/topology/ && npx tsc --noEmit`
Expected: all `nodeMemo` tests PASS; existing SystemGroupNode/CollapsedSystemNode/collapse tests still PASS; no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/topology/SystemGroupNode.tsx \
        frontend/src/components/topology/CollapsedSystemNode.tsx
git commit -m "refactor(topology): memoize group + collapsed system nodes"
```

### Task 8: Viewport culling + zoom clamps

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Add the ReactFlow performance props**

In `SystemTopologyDiagram.tsx`, add these props to the `<ReactFlow>` element (alongside `fitView`):

```tsx
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            onlyRenderVisibleElements
            minZoom={0.1}
            maxZoom={2}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onEdgeClick={handleEdgeClick}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            onInit={(inst) => {
              rfRef.current = inst;
            }}
          >
```

- [ ] **Step 2: Verify tests + typecheck**

Run: `cd frontend && npx vitest run src/components/topology/ && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 3: Measure (manual)**

Reload the hub Perf System topology. Pan/zoom the full graph; confirm off-screen nodes are culled (smoother pan) and zoom is clamped to the 0.1–2 range. Confirm search-to-center (which uses `setCenter` zoom 1.2) still works. Record numbers + render-count observations in the Measurement Log row "3 render wins".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx \
        docs/superpowers/specs/2026-07-25-topology-performance-design.md
git commit -m "perf(topology): viewport culling + zoom clamps on the canvas"
```

---

## INCREMENT 4 — LOD-Readiness Seam

Branch: `feature/topology-perf-seam`

### Task 9: TopologySource boundary

**Files:**
- Create: `frontend/src/components/topology/topologySource.ts`
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`
- Test: `frontend/src/components/topology/__tests__/topologySource.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/topology/__tests__/topologySource.test.ts
import { describe, expect, it } from 'vitest';
import { fromTopologyResponse } from '../topologySource';
import type { TopologyResponse } from '../../../types/topology';

const data = {
  subsystems: [{ id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null }],
  dependencies: [{ id: 8, from_subsystem_id: 5, to_subsystem_id: 6, dependency_type: 'api_call', direction: 'one_way', label: null }],
  external_subsystems: [{ id: 1, name: 'ext', system_id: 1, component_type: 'other', technology: null }],
  external_dependencies: [{ id: 10, from_subsystem_id: 1, to_subsystem_id: 5, dependency_type: 'api_call', direction: 'one_way', label: null }],
  system_names: { '1': 'Mortgage', '2': 'Customer' },
} as unknown as TopologyResponse;

describe('fromTopologyResponse', () => {
  it('maps a TopologyResponse into the pipeline VisibilityInput shape', () => {
    const graph = fromTopologyResponse(data).getGraph();
    expect(graph.subsystems.map((s) => s.id)).toEqual([5]);
    expect(graph.dependencies.map((d) => d.id)).toEqual([8]);
    expect(graph.externalSubsystems.map((s) => s.id)).toEqual([1]);
    expect(graph.externalDependencies.map((d) => d.id)).toEqual([10]);
  });

  it('defaults missing external arrays to empty', () => {
    const graph = fromTopologyResponse({ ...data, external_subsystems: undefined, external_dependencies: undefined } as unknown as TopologyResponse).getGraph();
    expect(graph.externalSubsystems).toEqual([]);
    expect(graph.externalDependencies).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologySource.test.ts`
Expected: FAIL — cannot resolve `../topologySource`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/components/topology/topologySource.ts
import type { TopologyResponse } from '../../types/topology';
import type { VisibilityInput } from './topologyVisibility';

/**
 * The single boundary between the raw topology data and the render pipeline.
 *
 * Today the only implementation returns the full graph already held in Redux.
 * This seam exists so a future level-of-detail backend (for ~1000-component
 * graphs) can implement the SAME interface — e.g. returning collapsed-system
 * summaries and fetching component detail lazily on expand — WITHOUT touching
 * anything downstream (`computeVisibleGraph` onward). Nothing past `getGraph()`
 * may depend on the raw `TopologyResponse` shape.
 */
export interface TopologySource {
  getGraph(): VisibilityInput;
}

/** Full-graph source backed by the current unpaginated topology API response. */
export function fromTopologyResponse(data: TopologyResponse): TopologySource {
  return {
    getGraph: () => ({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.external_subsystems ?? [],
      externalDependencies: data.external_dependencies ?? [],
    }),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologySource.test.ts`
Expected: PASS (2 passed)

- [ ] **Step 5: Route the diagram's visibleGraph through the seam**

In `SystemTopologyDiagram.tsx`, add the import:

```ts
import { fromTopologyResponse } from '../../components/topology/topologySource';
```

Replace the `visibleGraph` useMemo (currently lines ~139-150) with a source-backed version:

```ts
  const source = useMemo(() => (data ? fromTopologyResponse(data) : null), [data]);

  const visibleGraph = useMemo(() => {
    if (!source) return null;
    return computeVisibleGraph(source.getGraph(), { hiddenTypes });
  }, [source, hiddenTypes]);
```

(The `availableComponentTypes` call at lines ~272-280 still reads `data` directly — that is a UI-only enumeration and is intentionally left as-is; only the render pipeline goes through the source.)

- [ ] **Step 6: Run tests + typecheck**

Run: `cd frontend && npx vitest run src/components/topology/ && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 7: Verify no behavior change (manual)**

Reload the hub Perf System topology. Confirm the diagram is visually identical to Increment 3 (this task is pure refactor). Record "no change" in the Measurement Log row "4 seam".

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/topology/topologySource.ts \
        frontend/src/components/topology/__tests__/topologySource.test.ts \
        frontend/src/pages/systems/SystemTopologyDiagram.tsx \
        docs/superpowers/specs/2026-07-25-topology-performance-design.md
git commit -m "refactor(topology): TopologySource seam for future LOD backend"
```

---

## Done Criteria

- Seed script produces a reproducible 7-system / 300-component / 600-dep topology; re-running does not duplicate.
- ELK layout runs in a web worker (`engine: 'worker'` in the perf log); UI no longer freezes during layout; main-thread fallback verified by unit test.
- All three node components are `React.memo`'d; `onlyRenderVisibleElements` + zoom clamps active.
- Render pipeline reads through the `TopologySource` seam; nothing downstream depends on the raw `TopologyResponse`.
- Measurement Log in the spec filled with before/after numbers for each increment.
- `npx vitest run src/components/topology/` and `npx tsc --noEmit` green; `uv run pytest tests/test_seed_large_topology.py` green.
```
