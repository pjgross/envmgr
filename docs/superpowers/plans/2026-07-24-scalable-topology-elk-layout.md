# Scalable Topology Layout with ELK — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the heuristic topology layout (per-system dagre + side-placement + vertical columns) with an ELK (`elkjs`) hierarchical layout so a system's topology diagram positions correctly at hundreds of densely-linked components.

**Architecture:** Two pure functions — `buildElkGraph(input)` turns the topology response into an ELK graph (systems as containers, components as children, all dependencies as edges); `elkToReactFlow(result, ctx)` maps a laid-out ELK graph back to React Flow group + child nodes and floating edges. `SystemTopologyDiagram.tsx` runs ELK asynchronously in an effect (loading state + stale-result guard) and applies edge-selection highlight as a cheap restyle separate from layout. Floating edges are kept; the side/column heuristics are removed.

**Tech Stack:** React 18 + TypeScript (strict, `noUnusedLocals`), React Flow 11.11.4, `elkjs` (new), Vitest.

**Spec:** `docs/superpowers/specs/2026-07-24-scalable-topology-elk-design.md`

---

## Key facts (verified against the codebase)

- Constants in `SystemTopologyDiagram.tsx`: `NODE_WIDTH = 180`, `NODE_HEIGHT = 70`, `GROUP_PADDING = 40`, `GROUP_LABEL_HEIGHT = 20`, `GROUP_GAP = 80`.
- `COMPONENT_COLORS` map (by `component_type`) also lives in that file; the ELK mapping needs it, so it moves to a shared spot (Task 3 keeps it in the component and passes colours in via `ctx`).
- Types: `SubSystemResponse` = `{ id, name, system_id, component_type, technology }` (`src/types/system.ts`). `ComponentDependencyResponse` = `{ id, from_subsystem_id, to_subsystem_id, dependency_type, direction, label }` (`src/types/dependency.ts`). `TopologyResponse` = `{ subsystems, dependencies, external_subsystems, external_dependencies, system_names }` (`src/types/topology.ts`).
- `SystemGroupNode` data shape: `{ label: string; isCurrent: boolean }`.
- `SubsystemNode` (defined inside `SystemTopologyDiagram.tsx`) data shape: `{ label: SubSystemResponse; color: string }`, and has `<Handle type="target" position={Position.Left}/>` + `<Handle type="source" position={Position.Right}/>` (keep — floating edges still need handles to exist).
- **`@dagrejs/dagre` is also used by `src/pages/environments/EnvironmentTopologyDiagram.tsx`** → do NOT uninstall the package; only remove the `dagre` import from `SystemTopologyDiagram.tsx`.
- `elkjs` is NOT yet installed.
- Edge type `floating` is registered via `edgeTypes = { floating: FloatingEdge }`; edges are built with `type: 'floating'`, `markerEnd: { type: MarkerType.ArrowClosed }`, `markerStart` only for `direction === 'two_way'`, `label`, and a selection `style`.

---

## File Structure

- **Create** `frontend/src/components/topology/topologyElkGraph.ts` — `buildElkGraph` + `elkToReactFlow` + their shared types. One responsibility: translate topology data ⇄ ELK / React Flow. No React, no ELK execution (pure data transforms).
- **Create** `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts` — unit tests for both functions.
- **Modify** `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — async ELK layout effect, loading, stale guard, separated selection styling; remove dagre + heuristic usage.
- **Delete** `frontend/src/components/topology/externalSidePlacement.ts` + `__tests__/externalSidePlacement.test.ts`, `frontend/src/components/topology/topologyColumnLayout.ts` + `__tests__/topologyColumnLayout.test.ts`.

---

### Task 1: Install elkjs

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`

- [ ] **Step 1: Install the dependency**

Run: `cd frontend && npm install elkjs`
Expected: `elkjs` appears under `dependencies` in `package.json`; install completes without errors.

- [ ] **Step 2: Verify it imports in the test/build toolchain**

Run: `cd frontend && node -e "const ELK = require('elkjs'); console.log(typeof ELK)"`
Expected: prints `function` (the ELK constructor).

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "build(frontend): add elkjs for topology layout"
```

---

### Task 2: `buildElkGraph` (pure, TDD)

Turns the topology response into an ELK graph: one container per system, one child per component, one edge per dependency, with layout options.

**Files:**
- Create: `frontend/src/components/topology/topologyElkGraph.ts`
- Test: `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { buildElkGraph, type ElkGraphInput } from '../topologyElkGraph';

const sub = (id: number, systemId: number) => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: 'other',
  technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way',
  label: null,
});

// Customer(2): API(5)->db(6). External Mortgage(1) sys1 ->5; EnvMgr(19) sys3 ->5.
const input: ElkGraphInput = {
  subsystems: [sub(5, 2), sub(6, 2)],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1), sub(19, 3)],
  externalDependencies: [dep(1, 1, 5), dep(9, 19, 5)],
  currentSystemId: 2,
};

describe('buildElkGraph', () => {
  it('creates one container per system', () => {
    const g = buildElkGraph(input);
    const ids = (g.children ?? []).map((c) => c.id).sort();
    expect(ids).toEqual(['group-1', 'group-2', 'group-3']);
  });

  it('nests each component under its system container', () => {
    const g = buildElkGraph(input);
    const byId = new Map((g.children ?? []).map((c) => [c.id, c]));
    expect((byId.get('group-2')!.children ?? []).map((c) => c.id).sort()).toEqual(['5', '6']);
    expect((byId.get('group-1')!.children ?? []).map((c) => c.id)).toEqual(['1']);
    expect((byId.get('group-3')!.children ?? []).map((c) => c.id)).toEqual(['19']);
  });

  it('emits one edge per dependency (internal + external) with correct endpoints', () => {
    const g = buildElkGraph(input);
    const edges = (g.edges ?? []).map((e) => `${e.sources[0]}->${e.targets[0]}`).sort();
    expect(edges).toEqual(['1->5', '19->5', '5->6']);
  });

  it('gives every component node fixed width/height', () => {
    const g = buildElkGraph(input);
    const child = (g.children ?? [])
      .flatMap((c) => c.children ?? [])
      .find((c) => c.id === '5')!;
    expect(child.width).toBe(180);
    expect(child.height).toBe(70);
  });

  it('sets the layered algorithm, RIGHT direction and INCLUDE_CHILDREN on the root', () => {
    const g = buildElkGraph(input);
    expect(g.layoutOptions?.['elk.algorithm']).toBe('layered');
    expect(g.layoutOptions?.['elk.direction']).toBe('RIGHT');
    expect(g.layoutOptions?.['elk.hierarchyHandling']).toBe('INCLUDE_CHILDREN');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyElkGraph.test.ts`
Expected: FAIL — cannot resolve `../topologyElkGraph`.

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/topology/topologyElkGraph.ts`:

```ts
import type { ElkNode, ElkExtendedEdge } from 'elkjs/lib/elk-api';

/** Minimal shapes the graph builder needs (decoupled from the redux types). */
export interface ElkSubsystem {
  id: number;
  system_id: number;
}
export interface ElkDependency {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
}
export interface ElkGraphInput {
  subsystems: ElkSubsystem[];
  dependencies: ElkDependency[];
  externalSubsystems: ElkSubsystem[];
  externalDependencies: ElkDependency[];
  currentSystemId: number;
}

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 70;
export const GROUP_LABEL_HEIGHT = 20;

const ROOT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.layered.spacing.nodeNodeBetweenLayers': '80',
  'elk.spacing.nodeNode': '40',
  'elk.spacing.edgeNode': '20',
  'elk.spacing.edgeEdge': '15',
};

const CONTAINER_OPTIONS: Record<string, string> = {
  // Reserve space at the top for the system label; pad the other sides.
  'elk.padding': `[top=${GROUP_LABEL_HEIGHT + 16},left=12,bottom=12,right=12]`,
};

export function buildElkGraph(input: ElkGraphInput): ElkNode {
  const allSubsystems = [...input.subsystems, ...input.externalSubsystems];
  const allDependencies = [...input.dependencies, ...input.externalDependencies];

  // Group components by system, preserving first-seen order.
  const bySystem = new Map<number, ElkSubsystem[]>();
  for (const s of allSubsystems) {
    if (!bySystem.has(s.system_id)) bySystem.set(s.system_id, []);
    bySystem.get(s.system_id)!.push(s);
  }

  const containers: ElkNode[] = [...bySystem.entries()].map(([sysId, subs]) => ({
    id: `group-${sysId}`,
    layoutOptions: CONTAINER_OPTIONS,
    children: subs.map((s) => ({
      id: String(s.id),
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
  }));

  const edges: ElkExtendedEdge[] = allDependencies.map((d) => ({
    id: `e${d.id}`,
    sources: [String(d.from_subsystem_id)],
    targets: [String(d.to_subsystem_id)],
  }));

  return {
    id: 'root',
    layoutOptions: ROOT_OPTIONS,
    children: containers,
    edges,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyElkGraph.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyElkGraph.ts frontend/src/components/topology/__tests__/topologyElkGraph.test.ts
git commit -m "feat(ui): buildElkGraph — topology data to ELK graph"
```

---

### Task 3: `elkToReactFlow` (pure, TDD)

Maps a laid-out ELK graph back to React Flow group + child nodes and floating edges. ELK gives container children coordinates **relative to their container**, which is exactly what React Flow `parentId` children need.

**Files:**
- Modify: `frontend/src/components/topology/topologyElkGraph.ts`
- Modify: `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts`

- [ ] **Step 1: Add the failing test**

Append to `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts`:

```ts
import { elkToReactFlow, type ElkRenderContext } from '../topologyElkGraph';
import type { ElkNode } from 'elkjs/lib/elk-api';

// A hand-authored laid-out ELK result (as ELK would return it).
const laidOut: ElkNode = {
  id: 'root',
  children: [
    {
      id: 'group-2',
      x: 300, y: 0, width: 240, height: 140,
      children: [
        { id: '5', x: 12, y: 40, width: 180, height: 70 },
        { id: '6', x: 12, y: 40, width: 180, height: 70 }, // coords don't matter for the test
      ],
    },
    {
      id: 'group-1',
      x: 0, y: 0, width: 210, height: 110,
      children: [{ id: '1', x: 12, y: 36, width: 180, height: 70 }],
    },
  ],
  edges: [{ id: 'e1', sources: ['1'], targets: ['5'] }],
};

const ctx: ElkRenderContext = {
  currentSystemId: 2,
  systemNames: { '1': 'Mortgage', '2': 'Customer' },
  subsystems: new Map([
    [5, { id: 5, name: 'API', system_id: 2, component_type: 'api_gateway', technology: null }],
    [6, { id: 6, name: 'db', system_id: 2, component_type: 'database', technology: null }],
    [1, { id: 1, name: 'Mortgage Server', system_id: 1, component_type: 'web_service', technology: null }],
  ]),
  dependencies: new Map([
    [1, { id: 1, from_subsystem_id: 1, to_subsystem_id: 5, dependency_type: 'api_call', direction: 'one_way', label: null }],
  ]),
  colorFor: () => '#616161',
};

describe('elkToReactFlow', () => {
  it('returns group nodes before their child nodes', () => {
    const { nodes } = elkToReactFlow(laidOut, ctx);
    const firstChildIdx = nodes.findIndex((n) => n.type === 'subsystemNode');
    const lastGroupIdx = nodes.map((n) => n.type).lastIndexOf('systemGroupNode');
    expect(lastGroupIdx).toBeLessThan(firstChildIdx);
  });

  it('maps container position/size to the group node', () => {
    const { nodes } = elkToReactFlow(laidOut, ctx);
    const g = nodes.find((n) => n.id === 'group-2')!;
    expect(g.position).toEqual({ x: 300, y: 0 });
    expect(g.style).toMatchObject({ width: 240, height: 140 });
    expect(g.data).toMatchObject({ label: 'Customer', isCurrent: true });
  });

  it('places children under their parent with ELK-relative positions', () => {
    const { nodes } = elkToReactFlow(laidOut, ctx);
    const child = nodes.find((n) => n.id === '5')!;
    expect(child.parentId).toBe('group-2');
    expect(child.position).toEqual({ x: 12, y: 40 });
    expect(child.data).toMatchObject({ color: '#616161' });
  });

  it('maps each ELK edge to a floating edge with the dependency label/markers', () => {
    const { edges } = elkToReactFlow(laidOut, ctx);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      id: '1',
      source: '1',
      target: '5',
      type: 'floating',
      label: 'api_call',
    });
    expect(edges[0].markerStart).toBeUndefined(); // one_way
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyElkGraph.test.ts`
Expected: FAIL — `elkToReactFlow` / `ElkRenderContext` not exported.

- [ ] **Step 3: Add the implementation**

Append to `frontend/src/components/topology/topologyElkGraph.ts`:

```ts
import { MarkerType, type Node, type Edge } from 'reactflow';

/** Full subsystem/dependency data needed to render nodes and edges. */
export interface RenderSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
}
export interface RenderDependency {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
  dependency_type: string;
  direction: string;
  label: string | null;
}
export interface ElkRenderContext {
  currentSystemId: number;
  systemNames: Record<string, string>;
  subsystems: Map<number, RenderSubsystem>;
  dependencies: Map<number, RenderDependency>;
  colorFor: (componentType: string) => string;
}

export function elkToReactFlow(
  result: ElkNode,
  ctx: ElkRenderContext
): { nodes: Node[]; edges: Edge[] } {
  const groupNodes: Node[] = [];
  const childNodes: Node[] = [];

  for (const container of result.children ?? []) {
    const sysId = Number(container.id.replace('group-', ''));
    groupNodes.push({
      id: container.id,
      type: 'systemGroupNode',
      position: { x: container.x ?? 0, y: container.y ?? 0 },
      style: { width: container.width ?? 0, height: container.height ?? 0 },
      data: {
        label: ctx.systemNames[String(sysId)] ?? `System ${sysId}`,
        isCurrent: sysId === ctx.currentSystemId,
      },
      selectable: false,
      draggable: false,
    });

    for (const child of container.children ?? []) {
      const sub = ctx.subsystems.get(Number(child.id));
      if (!sub) continue;
      childNodes.push({
        id: child.id,
        type: 'subsystemNode',
        parentId: container.id,
        position: { x: child.x ?? 0, y: child.y ?? 0 },
        data: { label: sub, color: ctx.colorFor(sub.component_type) },
      });
    }
  }

  const edges: Edge[] = (result.edges ?? []).flatMap((e) => {
    const depId = Number(e.id.replace(/^e/, ''));
    const d = ctx.dependencies.get(depId);
    if (!d) return [];
    return [
      {
        id: String(d.id),
        source: String(d.from_subsystem_id),
        target: String(d.to_subsystem_id),
        type: 'floating',
        label: d.label ?? d.dependency_type,
        markerEnd: { type: MarkerType.ArrowClosed },
        ...(d.direction === 'two_way'
          ? { markerStart: { type: MarkerType.ArrowClosed } }
          : {}),
      },
    ];
  });

  // Group nodes must precede child nodes (React Flow parent-before-child rule).
  return { nodes: [...groupNodes, ...childNodes], edges };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyElkGraph.test.ts`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyElkGraph.ts frontend/src/components/topology/__tests__/topologyElkGraph.test.ts
git commit -m "feat(ui): elkToReactFlow — ELK result to React Flow nodes/edges"
```

---

### Task 4: Wire `SystemTopologyDiagram` to ELK (async layout)

Replace the synchronous dagre `getLayoutedElements` + heuristics with the ELK build/map functions, run async in an effect with a loading state and stale-result guard, and apply selection highlight separately from layout.

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Add imports and a module-level ELK instance**

At the top of `SystemTopologyDiagram.tsx`, remove `import dagre from '@dagrejs/dagre';`, remove the imports of `decideExternalSides` and `positionColumns`/`GroupBox`, and add:

```tsx
import ELK from 'elkjs/lib/elk.bundled.js';
import {
  buildElkGraph,
  elkToReactFlow,
  type ElkRenderContext,
  type RenderSubsystem,
  type RenderDependency,
} from '../../components/topology/topologyElkGraph';
```

Below the imports (module scope, so a single worker/engine is reused), add:

```tsx
const elk = new ELK();
```

- [ ] **Step 2: Delete the dagre layout function**

Remove the entire `getLayoutedElements(...)` function and the `GROUP_GAP` constant and the `interface GroupLayout` — everything that was the dagre + heuristic layout (from `const GROUP_GAP = 80;` through the end of `getLayoutedElements`). Keep `COMPONENT_COLORS`, `NODE_WIDTH`, `NODE_HEIGHT`, `GROUP_PADDING`, `GROUP_LABEL_HEIGHT`, the `SubsystemNode` component, `nodeTypes`, and `edgeTypes`.

- [ ] **Step 3: Replace the layout `useMemo` with an async effect + state**

In the `SystemTopologyDiagram` component, find:

```tsx
  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [], edges: [] };
    return getLayoutedElements(
      data.subsystems,
      data.dependencies,
      data.external_subsystems ?? [],
      data.external_dependencies ?? [],
      data.system_names ?? {},
      systemId,
      selectedDepId
    );
  }, [data, systemId, selectedDepId]);
```

Replace it with layout state + an effect that lays out on `data`/`systemId` only (NOT `selectedDepId`), plus a memo that applies the selection highlight:

```tsx
  const [layout, setLayout] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });
  const [layingOut, setLayingOut] = useState(false);

  useEffect(() => {
    if (!data) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const graph = buildElkGraph({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.external_subsystems ?? [],
      externalDependencies: data.external_dependencies ?? [],
      currentSystemId: systemId,
    });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...data.subsystems, ...(data.external_subsystems ?? [])]) subsystems.set(s.id, s);
    const dependencies = new Map<number, RenderDependency>();
    for (const d of [...data.dependencies, ...(data.external_dependencies ?? [])]) dependencies.set(d.id, d);

    const ctx: ElkRenderContext = {
      currentSystemId: systemId,
      systemNames: data.system_names ?? {},
      subsystems,
      dependencies,
      colorFor: (t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other,
    };

    elk
      .layout(graph)
      .then((res) => {
        if (cancelled) return;
        setLayout(elkToReactFlow(res, ctx));
      })
      .catch(() => {
        if (!cancelled) setLayout({ nodes: [], edges: [] });
      })
      .finally(() => {
        if (!cancelled) setLayingOut(false);
      });

    return () => {
      cancelled = true;
    };
  }, [data, systemId]);

  const nodes = layout.nodes;
  const edges = useMemo(
    () =>
      layout.edges.map((e) =>
        Number(e.id) === selectedDepId
          ? { ...e, style: { stroke: '#1976d2', strokeWidth: 2.5 } }
          : { ...e, style: undefined }
      ),
    [layout.edges, selectedDepId]
  );
```

(`Node`/`Edge` are already imported from `reactflow` at the top of the file; `useEffect`/`useState`/`useMemo` are already imported from `react`.)

- [ ] **Step 4: Show the layout spinner**

Find the existing early-return block:

```tsx
  if (loading)
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
```

Change the condition to also cover the in-flight ELK layout:

```tsx
  if (loading || (layingOut && layout.nodes.length === 0))
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS. If it reports `decideExternalSides`, `positionColumns`, `GroupBox`, `dagre`, `GROUP_GAP`, or `GROUP_PADDING` as unused, remove those now-dead imports/constants (do not remove `GROUP_LABEL_HEIGHT`/`NODE_WIDTH`/`NODE_HEIGHT` — still used). `GROUP_PADDING` is now unused (the old layout used it) — remove it.

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npx vitest run src/`
Expected: PASS. The `externalSidePlacement` and `topologyColumnLayout` suites still exist and pass at this point (removed in Task 5); the new `topologyElkGraph` suite passes.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "feat(ui): lay out system topology with ELK (async)"
```

---

### Task 5: Remove the superseded heuristic modules

**Files:**
- Delete: `frontend/src/components/topology/externalSidePlacement.ts`, `frontend/src/components/topology/__tests__/externalSidePlacement.test.ts`
- Delete: `frontend/src/components/topology/topologyColumnLayout.ts`, `frontend/src/components/topology/__tests__/topologyColumnLayout.test.ts`

- [ ] **Step 1: Confirm nothing else imports them**

Run: `cd frontend && grep -rn "externalSidePlacement\|topologyColumnLayout\|decideExternalSides\|positionColumns" src/`
Expected: no matches (Task 4 removed the imports from `SystemTopologyDiagram.tsx`). If any match remains, fix that reference before deleting.

- [ ] **Step 2: Delete the files**

```bash
cd frontend
git rm src/components/topology/externalSidePlacement.ts \
       src/components/topology/__tests__/externalSidePlacement.test.ts \
       src/components/topology/topologyColumnLayout.ts \
       src/components/topology/__tests__/topologyColumnLayout.test.ts
```

- [ ] **Step 3: Typecheck + tests + build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/ && npm run build`
Expected: all pass. `topologyElkGraph` and `floatingEdgeGeometry` suites remain; the two deleted suites are gone.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(ui): drop side/column topology heuristics (superseded by ELK)"
```

---

### Task 6: Tune ELK options against the Customer example (manual)

The initial spacing/padding values are estimates. Tune them so the Customer topology looks at least as good as the heuristic version (Mortgage + Env Manager fan cleanly into Customer API Server, labels not overlapping nodes, systems clearly boxed).

**Files:**
- Modify: `frontend/src/components/topology/topologyElkGraph.ts` (only `ROOT_OPTIONS` / `CONTAINER_OPTIONS` values)

- [ ] **Step 1: Run the app**

Start the frontend (`cd frontend && npm run dev`) and backend per `CLAUDE.md`; log in `admin`/`admin123` (tenant `demo`); open **Systems → Customer → Topology** tab.

- [ ] **Step 2: Verify and adjust**

Confirm: the loading spinner appears then the diagram renders; Mortgage + Env Manager sit left of Customer and both links fan into Customer API Server without crossing any component box; API Server → database is clean; system labels sit above their boxes without overlapping nodes; selecting an edge highlights it and opens the detail pane **without** a relayout flicker.

If spacing is too tight/loose or labels overlap, adjust the numeric values in `ROOT_OPTIONS` (`nodeNodeBetweenLayers`, `spacing.nodeNode`) and `CONTAINER_OPTIONS` (`elk.padding` top value vs `GROUP_LABEL_HEIGHT`). Re-check after each change.

- [ ] **Step 3: Commit any tuning**

```bash
git add frontend/src/components/topology/topologyElkGraph.ts
git commit -m "fix(ui): tune ELK spacing/padding for topology"
```

(If no change was needed, skip this commit.)

---

## Self-Review

**Spec coverage:** Library add (Task 1); ELK graph model = `buildElkGraph` (Task 2); ELK→RF mapping = `elkToReactFlow` (Task 3); async data flow + stale guard + loading + separated selection styling (Task 4); remove heuristics, keep floating edges (Tasks 4–5); tuning (Task 6). Unit tests for both pure functions (Tasks 2–3). Manual verification (Task 6). `@dagrejs/dagre` kept because `EnvironmentTopologyDiagram.tsx` still uses it (noted in Key facts + Task 4 Step 1). All spec sections covered.

**Placeholder scan:** none — every code step shows full code; tuning values are concrete with an explicit adjust-and-recheck loop.

**Type consistency:** `ElkGraphInput`/`ElkSubsystem`/`ElkDependency` (Task 2) and `ElkRenderContext`/`RenderSubsystem`/`RenderDependency` (Task 3) are used verbatim in Task 4. `buildElkGraph` returns `ElkNode`; `elkToReactFlow(result: ElkNode, ctx)` consumes it. Edge id scheme is consistent: `buildElkGraph` emits `e<depId>`, `elkToReactFlow` strips the leading `e` to recover the dependency id. `NODE_WIDTH`/`NODE_HEIGHT`/`GROUP_LABEL_HEIGHT` are re-exported from `topologyElkGraph.ts` and match the component's constants (180/70/20).
