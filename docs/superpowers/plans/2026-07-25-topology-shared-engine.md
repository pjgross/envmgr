# Shared Topology Engine + Grouping Generalization (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the systems-topology pipeline reusable (`<TopologyCanvas>`) and its grouping pluggable (`Grouping`, system today / host later), with zero change to the systems diagram's behavior or appearance.

**Architecture:** Two tasks. Task 1 generalizes `computeCollapseModel` from hardcoded system grouping to a pluggable `Grouping` (renaming `ModelSystem`→`ModelGroup`, `collapsedSystems`→`collapsedGroups: Set<string>`, `{systems}`→`{groups}`) and updates its consumers — because `groupId === String(system_id)` for the system grouping, all node/edge ids and ELK geometry stay identical. Task 2 extracts the orchestration into a reusable `<TopologyCanvas>` and slims `SystemTopologyDiagram` to a thin wrapper.

**Tech Stack:** React 18, TypeScript (strict, `noUnusedLocals`), `reactflow` ^11, `elkjs` ^0.12, Vitest + Testing Library.

**Spec:** [docs/superpowers/specs/2026-07-25-topology-shared-engine-design.md](../specs/2026-07-25-topology-shared-engine-design.md)

**Base branch:** `feature/topology-shared-engine` (already checked out, off `feature/topology-perf`).

**Commands** (run from `frontend/`):
- Typecheck: `npx tsc --noEmit`
- Topology tests: `npx vitest run src/components/topology/`
- Full unit suite: `npx vitest run --exclude 'e2e/**'`

---

## File Structure

**Create:**
- `frontend/src/components/topology/TopologyCanvas.tsx` — reusable diagram orchestration (state, layout effect, toolbar, ReactFlow, detail pane). One responsibility: render a topology from a `graph` + `grouping` + render-config, with no knowledge of systems vs environments.
- `frontend/src/components/topology/__tests__/topologyGrouping.test.ts` — proves `computeCollapseModel` works with a non-system `Grouping`.

**Modify:**
- `frontend/src/components/topology/topologyModel.ts` — add `Grouping` + `bySystem()`; generalize `computeCollapseModel` (`ModelGroup`/`groupId`/`collapsedGroups`/`{groups}`).
- `frontend/src/components/topology/topologyElkGraph.ts` — read `model.groups`/`groupId`; string group keys; node `data.groupId`; drop `systemNames` from `ElkRenderContext`.
- `frontend/src/components/topology/SystemGroupNode.tsx` — `data.groupId: string`, `onCollapse(groupId: string)`.
- `frontend/src/components/topology/CollapsedSystemNode.tsx` — `data.groupId: string`, `onExpand(groupId: string)`.
- `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — Task 1: compile against the new model; Task 2: slim to a wrapper.
- `frontend/src/components/topology/__tests__/topologyModel.test.ts` — new signature/field names.
- `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts` — `groups`/`groupId` in the model literal + assertions.
- `frontend/src/components/topology/__tests__/topologyLayout.test.ts` — `groups`/`groupId` in the model literal.

---

## Task 1: Generalize grouping in the topology model

**Files:** as listed above (all except `TopologyCanvas.tsx`).

This is one atomic refactor — the renamed types couple `topologyModel`, `topologyElkGraph`, the two node components, the page, and their tests, so they change together and land in one green commit. Do the steps in order; the type-checker guides you.

- [ ] **Step 1: Add the failing pluggability test**

Create `frontend/src/components/topology/__tests__/topologyGrouping.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { computeCollapseModel, bySystem, type Grouping } from '../topologyModel';
import type { VisibilityInput } from '../topologyVisibility';

const sub = (id: number, systemId: number, type = 'other') => ({
  id, name: `n${id}`, system_id: systemId, component_type: type, technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id, from_subsystem_id: from, to_subsystem_id: to,
  dependency_type: 'api_call', direction: 'one_way' as const, label: null,
});

// 5(web_service,sysA), 6(database,sysA), 7(web_service,sysB); deps 5->6, 5->7
const input: VisibilityInput = {
  subsystems: [sub(5, 1, 'web_service'), sub(6, 1, 'database'), sub(7, 2, 'web_service')],
  dependencies: [dep(8, 5, 6), dep(9, 5, 7)],
  externalSubsystems: [],
  externalDependencies: [],
};

// A grouping that is NOT by system — groups by component_type.
const byType: Grouping = {
  keyOf: (s) => s.component_type,
  meta: (key) => ({ name: key.toUpperCase(), isCurrent: false }),
};

describe('computeCollapseModel with a pluggable grouping', () => {
  it('groups components by an arbitrary key (component_type), not just system', () => {
    const m = computeCollapseModel(input, { collapsedGroups: new Set(), grouping: byType });
    expect(m.groups.map((g) => g.groupId).sort()).toEqual(['database', 'web_service']);
    const web = m.groups.find((g) => g.groupId === 'web_service')!;
    expect(web.name).toBe('WEB_SERVICE');
    expect(web.components.map((c) => c.id).sort()).toEqual([5, 7]);
    expect(web.componentCount).toBe(2);
  });

  it('collapsing a non-system group aggregates its edges to the collapsed node', () => {
    const m = computeCollapseModel(input, {
      collapsedGroups: new Set(['web_service']),
      grouping: byType,
    });
    const web = m.groups.find((g) => g.groupId === 'web_service')!;
    expect(web.collapsed).toBe(true);
    expect(web.components).toEqual([]);
    // 5 is now sys-web_service; edge 5->6 becomes sys-web_service -> 6; 5->7 collapses (both ends in group) → dropped
    const e = m.edges.find((x) => x.source === 'sys-web_service' && x.target === '6');
    expect(e).toBeTruthy();
    expect(m.edges.some((x) => x.source === '5' || x.target === '5')).toBe(false);
  });

  it('bySystem grouping keeps ids as String(system_id) (parity)', () => {
    const m = computeCollapseModel(input, {
      collapsedGroups: new Set(),
      grouping: bySystem({ '1': 'Alpha', '2': 'Beta' }, 1),
    });
    expect(m.groups.map((g) => g.groupId).sort()).toEqual(['1', '2']);
    expect(m.groups.find((g) => g.groupId === '1')!.isCurrent).toBe(true);
    expect(m.groups.find((g) => g.groupId === '1')!.name).toBe('Alpha');
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npx vitest run src/components/topology/__tests__/topologyGrouping.test.ts`
Expected: FAIL — `bySystem`/`Grouping` not exported / `m.groups` undefined.

- [ ] **Step 3: Rewrite `topologyModel.ts` with the generalized model**

Replace the entire contents of `frontend/src/components/topology/topologyModel.ts` with:

```ts
import type { DependencyDirection } from '../../types/dependency';
import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface ModelGroup {
  groupId: string;
  name: string;
  isCurrent: boolean;
  collapsed: boolean;
  componentCount: number;
  components: VisibleSubsystem[]; // [] when collapsed
}

export interface ModelEdge {
  id: string; // real dep id (String) when single; `agg:${source}->${target}` when aggregated
  source: string; // component id (String) or `sys-${groupId}`
  target: string;
  label: string;
  aggregatedCount: number;
  dependencyId: number | null;
  direction: DependencyDirection;
}

export interface TopologyModel {
  groups: ModelGroup[];
  edges: ModelEdge[];
}

/** Pluggable grouping: which group a subsystem belongs to, and that group's display metadata. */
export interface Grouping {
  keyOf(sub: VisibleSubsystem): string;
  meta(key: string): { name: string; isCurrent: boolean };
}

export interface CollapseContext {
  collapsedGroups: Set<string>;
  grouping: Grouping;
}

/** Grouping by owning system — the systems-diagram grouping. groupId === String(system_id). */
export function bySystem(systemNames: Record<string, string>, currentSystemId: number): Grouping {
  return {
    keyOf: (s) => String(s.system_id),
    meta: (key) => ({
      name: systemNames[key] ?? `System ${key}`,
      isCurrent: Number(key) === currentSystemId,
    }),
  };
}

export function computeCollapseModel(
  input: VisibilityInput,
  ctx: CollapseContext
): TopologyModel {
  const { grouping, collapsedGroups } = ctx;
  const allSubs = [...input.subsystems, ...input.externalSubsystems];
  const allDeps = [...input.dependencies, ...input.externalDependencies];

  const groupOf = new Map<number, string>();
  for (const s of allSubs) groupOf.set(s.id, grouping.keyOf(s));

  const byGroup = new Map<string, VisibleSubsystem[]>();
  for (const s of allSubs) {
    const key = grouping.keyOf(s);
    if (!byGroup.has(key)) byGroup.set(key, []);
    byGroup.get(key)!.push(s);
  }

  const groups: ModelGroup[] = [...byGroup.entries()].map(([groupId, comps]) => {
    const collapsed = collapsedGroups.has(groupId);
    const meta = grouping.meta(groupId);
    return {
      groupId,
      name: meta.name,
      isCurrent: meta.isCurrent,
      collapsed,
      componentCount: comps.length,
      components: collapsed ? [] : comps,
    };
  });

  const displayNode = (componentId: number): string => {
    const key = groupOf.get(componentId);
    return key !== undefined && collapsedGroups.has(key) ? `sys-${key}` : String(componentId);
  };

  const buckets = new Map<string, VisibleDependency[]>();
  for (const d of allDeps) {
    const source = displayNode(d.from_subsystem_id);
    const target = displayNode(d.to_subsystem_id);
    if (source === target) continue; // both endpoints in one collapsed group (or a self-loop) — nothing to draw
    const key = `${source}->${target}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(d);
  }

  const edges: ModelEdge[] = [...buckets.entries()].map(([key, deps]) => {
    const arrowIdx = key.indexOf('->');
    const source = key.slice(0, arrowIdx);
    const target = key.slice(arrowIdx + 2);
    if (deps.length === 1) {
      const d = deps[0];
      return {
        id: String(d.id),
        source,
        target,
        label: d.label ?? d.dependency_type,
        aggregatedCount: 1,
        dependencyId: d.id,
        direction: d.direction,
      };
    }
    return {
      id: `agg:${key}`,
      source,
      target,
      label: `${deps.length}×`,
      aggregatedCount: deps.length,
      dependencyId: null,
      direction: 'one_way', // aggregates always render one-way (per-dep direction not preserved — v1)
    };
  });

  return { groups, edges };
}
```

- [ ] **Step 4: Update `topologyElkGraph.ts` to consume `groups`/`groupId`**

In `frontend/src/components/topology/topologyElkGraph.ts`:

Replace the `buildElkGraph` children mapping:

```ts
  const children: ElkNode[] = model.groups.map((g) =>
    g.collapsed
      ? { id: `sys-${g.groupId}`, width: COLLAPSED_WIDTH, height: COLLAPSED_HEIGHT }
      : {
          id: `group-${g.groupId}`,
          layoutOptions: CONTAINER_OPTIONS,
          children: g.components.map((c) => ({
            id: String(c.id),
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
          })),
        }
  );
```

Remove `systemNames` from `ElkRenderContext`:

```ts
export interface ElkRenderContext {
  subsystems: Map<number, RenderSubsystem>;
  colorFor: (componentType: string) => string;
}
```

Replace the `elkToReactFlow` body's group/collapsed handling. Change the map lookup and both branches to use string group ids:

```ts
  const groupById = new Map(model.groups.map((g) => [g.groupId, g]));
  const topNodes: Node[] = [];
  const childNodes: Node[] = [];

  for (const node of result.children ?? []) {
    if (node.id.startsWith('sys-')) {
      const groupId = node.id.replace('sys-', '');
      const g = groupById.get(groupId);
      if (!g) continue;
      topNodes.push({
        id: node.id,
        type: 'collapsedSystemNode',
        position: { x: node.x ?? 0, y: node.y ?? 0 },
        data: { groupId, name: g.name, componentCount: g.componentCount, isCurrent: g.isCurrent },
        selectable: false,
        draggable: false,
      });
      continue;
    }
    const groupId = node.id.replace('group-', '');
    const g = groupById.get(groupId);
    topNodes.push({
      id: node.id,
      type: 'systemGroupNode',
      position: { x: node.x ?? 0, y: node.y ?? 0 },
      style: { width: node.width ?? 0, height: node.height ?? 0 },
      data: {
        label: g?.name ?? `Group ${groupId}`,
        isCurrent: g?.isCurrent ?? false,
        groupId,
      },
      selectable: false,
      draggable: false,
    });
    for (const child of node.children ?? []) {
      const sub = ctx.subsystems.get(Number(child.id));
      if (!sub) continue;
      childNodes.push({
        id: child.id,
        type: 'subsystemNode',
        parentId: node.id,
        position: { x: child.x ?? 0, y: child.y ?? 0 },
        data: { label: sub, color: ctx.colorFor(sub.component_type) },
      });
    }
  }
```

(The `edges` mapping below it — `model.edges.map(...)` — is unchanged.)

- [ ] **Step 5: Update the two node components to `groupId: string`**

In `frontend/src/components/topology/SystemGroupNode.tsx`, change the `data` type and the collapse call:

```ts
  data: {
    label: string;
    isCurrent: boolean;
    dimmed?: boolean;
    groupId?: string;
    onCollapse?: (groupId: string) => void;
  };
```
and in the body replace the guard + click:
```ts
        {data.onCollapse && data.groupId !== undefined && (
          <IconButton
            size="small"
            aria-label={`Collapse ${data.label}`}
            onClick={(e) => {
              e.stopPropagation();
              data.onCollapse!(data.groupId!);
            }}
            sx={{ p: 0.25, ml: 0.5, pointerEvents: 'auto' }}
          >
```

In `frontend/src/components/topology/CollapsedSystemNode.tsx`, change the `data` type and the expand calls:

```ts
  data: {
    groupId: string;
    name: string;
    componentCount: number;
    isCurrent: boolean;
    dimmed?: boolean;
    onExpand?: (groupId: string) => void;
  };
```
and replace `data.systemId` with `data.groupId` in the `onClick` and `onKeyDown` handlers (both call `data.onExpand?.(data.groupId)`).

- [ ] **Step 6: Update `SystemTopologyDiagram.tsx` to compile against the new model**

(This is minimal — Task 2 rewrites this file. Just make it green.) In `frontend/src/pages/systems/SystemTopologyDiagram.tsx`:

Change the import to add `bySystem`:
```ts
import { computeCollapseModel, bySystem } from '../../components/topology/topologyModel';
```

Change the collapsed-state hook to string keys:
```ts
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
```
Update the reset effect (line ~70) `setCollapsedSystems(new Set())` → `setCollapsedGroups(new Set())`.

Update `renderedComponents` (filters collapsed) to key by group — for the system grouping the group key is `String(s.system_id)`:
```ts
  const renderedComponents = useMemo(() => {
    if (!visibleGraph) return [];
    return [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems].filter(
      (s) => !collapsedGroups.has(String(s.system_id))
    );
  }, [visibleGraph, collapsedGroups]);
```

Replace the layout effect's model/ctx construction and deps:
```ts
    const grouping = bySystem(source.getSystemNames(), systemId);
    const model = computeCollapseModel(visibleGraph, { collapsedGroups, grouping });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems]) subsystems.set(s.id, s);

    const ctx: ElkRenderContext = {
      subsystems,
      colorFor: (t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other,
    };
```
and change the effect dependency array from `[visibleGraph, systemId, source, collapsedSystems]` to `[visibleGraph, systemId, source, collapsedGroups]`.

Replace the collapse/expand callbacks:
```ts
  const collapseGroup = useCallback((gid: string) => {
    setCollapsedGroups((prev) => new Set(prev).add(gid));
  }, []);
  const expandGroup = useCallback((gid: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      next.delete(gid);
      return next;
    });
  }, []);
```
and in the `nodes` useMemo replace `onCollapse: collapseSystem` → `onCollapse: collapseGroup`, `onExpand: expandSystem` → `onExpand: expandGroup`, and its dep array `[layout.nodes, focusSet, collapseSystem, expandSystem]` → `[layout.nodes, focusSet, collapseGroup, expandGroup]`.

- [ ] **Step 7: Update the existing model test**

READ `frontend/src/components/topology/__tests__/topologyModel.test.ts` and apply these exact transformations (mechanical; the type-checker + test run will confirm completeness):
- Import `bySystem` alongside `computeCollapseModel`.
- Replace the `ctx` helper with:
  ```ts
  const ctx = (collapsed: string[]): CollapseContext => ({
    collapsedGroups: new Set(collapsed),
    grouping: bySystem({ '1': 'Mortgage', '2': 'Customer', '3': 'Env Manager' }, 2),
  });
  ```
- Every `ctx([...])` call that passed numbers now passes strings: `ctx([])` stays, `ctx([1])` → `ctx(['1'])`, etc.
- `m.systems` → `m.groups`; `s.systemId` (number) → `s.groupId` (string). Any assertion like `.map((s) => s.systemId).sort()).toEqual([1, 2, 3])` becomes `.map((g) => g.groupId).sort()).toEqual(['1', '2', '3'])`; `.find((s) => s.systemId === 2)` → `.find((g) => g.groupId === '2')`.
- Node/group id assertions (`group-2`, `sys-1`, edge ids `'8'`, `'10'`, `agg:...`) are unchanged.

- [ ] **Step 8: Update the elk + layout test model literals**

In `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts` and `frontend/src/components/topology/__tests__/topologyLayout.test.ts`: any `TopologyModel` literal of the form `{ systems: [{ systemId: N, name, isCurrent, collapsed, componentCount, components }], edges: [...] }` becomes `{ groups: [{ groupId: String(N), name, isCurrent, collapsed, componentCount, components }], edges: [...] }`. Any `ElkRenderContext` literal that set `systemNames: {...}` drops that field (keep `subsystems` + `colorFor`). READ each file first and apply; node-id assertions (`group-2` etc.) are unchanged.

- [ ] **Step 9: Typecheck + run the whole topology suite**

Run: `npx tsc --noEmit`
Expected: clean (no errors).
Run: `npx vitest run src/components/topology/`
Expected: all pass (including the new `topologyGrouping.test.ts`).

If `tsc` reports a stray `systemId`/`collapsedSystems`/`model.systems`/`systemNames` reference anywhere, fix it to the new name and re-run.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/topology/topologyModel.ts \
        frontend/src/components/topology/topologyElkGraph.ts \
        frontend/src/components/topology/SystemGroupNode.tsx \
        frontend/src/components/topology/CollapsedSystemNode.tsx \
        frontend/src/pages/systems/SystemTopologyDiagram.tsx \
        frontend/src/components/topology/__tests__/topologyModel.test.ts \
        frontend/src/components/topology/__tests__/topologyElkGraph.test.ts \
        frontend/src/components/topology/__tests__/topologyLayout.test.ts \
        frontend/src/components/topology/__tests__/topologyGrouping.test.ts
git commit -m "refactor(topology): pluggable Grouping in computeCollapseModel"
```

---

## Task 2: Extract `<TopologyCanvas>` and slim the systems page

**Files:**
- Create: `frontend/src/components/topology/TopologyCanvas.tsx`
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

No new unit test (there is no `SystemTopologyDiagram` component test to mirror, and the extraction is a behavior-preserving move verified by the existing pipeline tests + `tsc` + a manual parity eyeball). The canvas is exercised end-to-end by the systems page.

- [ ] **Step 1: Create `TopologyCanvas.tsx`**

Create `frontend/src/components/topology/TopologyCanvas.tsx` with the full orchestration, parameterized by props:

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Box, Typography, CircularProgress, Alert } from '@mui/material';
import { NODE_WIDTH, NODE_HEIGHT } from './SubsystemNode';
import { type ElkRenderContext, type RenderSubsystem } from './topologyElkGraph';
import { computeCollapseModel, type Grouping } from './topologyModel';
import { layoutTopology } from './topologyLayout';
import { computeFocusSet, type SearchableComponent } from './topologyFocus';
import { computeVisibleGraph, availableComponentTypes, type VisibilityInput } from './topologyVisibility';
import TopologyToolbar from './TopologyToolbar';
import FloatingEdge from './FloatingEdge';
import DependencyDetailPane from './DependencyDetailPane';
import type { ComponentDependencyResponse } from '../../types/dependency';

const edgeTypes = { floating: FloatingEdge };

export interface TopologyCanvasProps {
  graph: VisibilityInput | null;
  grouping: Grouping;
  loading: boolean;
  error: string | null;
  colorFor: (componentType: string) => string;
  nodeTypes: NodeTypes;
  findDependency: (id: number) => ComponentDependencyResponse | null;
  height?: number;
  emptyMessage?: string;
}

export default function TopologyCanvas({
  graph,
  grouping,
  loading,
  error,
  colorFor,
  nodeTypes,
  findDependency,
  height = 500,
  emptyMessage = 'No components yet.',
}: TopologyCanvasProps) {
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const rfRef = useRef<ReactFlowInstance | null>(null);

  // Reset transient state when the underlying graph changes (e.g. entity switch).
  useEffect(() => {
    setSelectedDepId(null);
    setFocusedId(null);
    setCollapsedGroups(new Set());
  }, [graph]);

  const selectedDep = useMemo(
    () => (selectedDepId === null ? null : findDependency(selectedDepId)),
    [selectedDepId, findDependency]
  );

  const visibleGraph = useMemo(() => {
    if (!graph) return null;
    return computeVisibleGraph(graph, { hiddenTypes });
  }, [graph, hiddenTypes]);

  const renderedComponents = useMemo(() => {
    if (!visibleGraph) return [];
    return [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems].filter(
      (s) => !collapsedGroups.has(grouping.keyOf(s))
    );
  }, [visibleGraph, collapsedGroups, grouping]);

  const visibleIds = useMemo(
    () => (visibleGraph ? new Set(renderedComponents.map((s) => String(s.id))) : null),
    [visibleGraph, renderedComponents]
  );

  const [layout, setLayout] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });
  const [layingOut, setLayingOut] = useState(false);

  useEffect(() => {
    if (!visibleGraph) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const model = computeCollapseModel(visibleGraph, { collapsedGroups, grouping });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems]) subsystems.set(s.id, s);

    const ctx: ElkRenderContext = { subsystems, colorFor };

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

    return () => {
      cancelled = true;
    };
  }, [visibleGraph, grouping, collapsedGroups, colorFor]);

  const focusSet = useMemo(() => {
    if (!focusedId || !visibleGraph) return null;
    const deps = [...visibleGraph.dependencies, ...visibleGraph.externalDependencies];
    return computeFocusSet(focusedId, deps);
  }, [focusedId, visibleGraph]);

  const collapseGroup = useCallback((gid: string) => {
    setCollapsedGroups((prev) => new Set(prev).add(gid));
  }, []);
  const expandGroup = useCallback((gid: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      next.delete(gid);
      return next;
    });
  }, []);

  const nodes = useMemo(() => {
    const brightGroups = new Set<string>();
    if (focusSet) {
      for (const n of layout.nodes) {
        if (n.parentId && focusSet.nodeIds.has(n.id)) brightGroups.add(n.parentId);
      }
    }
    return layout.nodes.map((n) => {
      const dimmed = focusSet
        ? n.type === 'systemGroupNode' || n.type === 'collapsedSystemNode'
          ? !brightGroups.has(n.id)
          : !focusSet.nodeIds.has(n.id)
        : undefined;
      if (n.type === 'systemGroupNode') {
        return { ...n, data: { ...n.data, dimmed, onCollapse: collapseGroup } };
      }
      if (n.type === 'collapsedSystemNode') {
        return { ...n, data: { ...n.data, dimmed, onExpand: expandGroup } };
      }
      return { ...n, data: { ...n.data, dimmed } };
    });
  }, [layout.nodes, focusSet, collapseGroup, expandGroup]);

  const edges = useMemo(
    () =>
      layout.edges.map((e) => {
        const dimmed = focusSet ? !focusSet.edgeIds.has(e.id) : false;
        const selected = Number(e.id) === selectedDepId;
        const style: React.CSSProperties = {
          opacity: dimmed ? 0.12 : 1,
          ...(selected ? { stroke: '#1976d2', strokeWidth: 2.5 } : {}),
        };
        return { ...e, style };
      }),
    [layout.edges, selectedDepId, focusSet]
  );

  const searchable = useMemo<SearchableComponent[]>(
    () =>
      renderedComponents.map((s) => ({
        id: s.id,
        name: s.name,
        systemName: grouping.meta(grouping.keyOf(s)).name,
      })),
    [renderedComponents, grouping]
  );

  const availableTypes = useMemo(() => (graph ? availableComponentTypes(graph) : []), [graph]);

  const toggleType = useCallback((t: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }, []);

  useEffect(() => {
    if (focusedId && visibleIds && !visibleIds.has(focusedId)) setFocusedId(null);
  }, [focusedId, visibleIds]);

  const handleSearchSelect = useCallback(
    (id: number) => {
      setFocusedId(String(id));
      const node = layout.nodes.find((n) => n.id === String(id));
      if (node?.parentId) {
        const group = layout.nodes.find((n) => n.id === node.parentId);
        const absX = (group?.position.x ?? 0) + node.position.x;
        const absY = (group?.position.y ?? 0) + node.position.y;
        rfRef.current?.setCenter(absX + NODE_WIDTH / 2, absY + NODE_HEIGHT / 2, {
          zoom: 1.2,
          duration: 400,
        });
      }
    },
    [layout.nodes]
  );

  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    const id = parseInt(edge.id, 10);
    if (Number.isNaN(id)) return; // aggregated edge — no single dependency to show
    setSelectedDepId((prev) => (prev === id ? null : id));
  }, []);

  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    // group node ids are prefixed "group-", collapsed group nodes "sys-"; only components are focusable
    if (node.id.startsWith('group-') || node.id.startsWith('sys-')) return;
    setFocusedId((cur) => (cur === node.id ? null : node.id));
  }, []);

  const handlePaneClick = useCallback(() => setFocusedId(null), []);

  if (loading || (layingOut && layout.nodes.length === 0))
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!graph || graph.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>{emptyMessage}</Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        height,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        overflow: 'hidden',
      }}
    >
      <Box sx={{ flex: 1, minWidth: '60%', display: 'flex', flexDirection: 'column' }}>
        <TopologyToolbar
          components={searchable}
          onSelect={handleSearchSelect}
          availableTypes={availableTypes}
          hiddenTypes={hiddenTypes}
          onToggleType={toggleType}
        />
        <Box sx={{ flex: 1, position: 'relative' }}>
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
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </Box>
      </Box>

      {selectedDep && (
        <DependencyDetailPane dep={selectedDep} onClose={() => setSelectedDepId(null)} />
      )}
    </Box>
  );
}
```

- [ ] **Step 2: (No change) `availableComponentTypes` already takes `VisibilityInput`**

Confirmed: `availableComponentTypes(input: VisibilityInput): string[]` in `topologyVisibility.ts`. The canvas calls it with `graph` (a `VisibilityInput`) directly. No edit needed — this step is just a note so you don't second-guess the call site.

- [ ] **Step 3: Rewrite `SystemTopologyDiagram.tsx` as a thin wrapper**

Replace the entire contents of `frontend/src/pages/systems/SystemTopologyDiagram.tsx` with:

```tsx
import { useCallback, useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import SubsystemNode from '../../components/topology/SubsystemNode';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import TopologyCanvas from '../../components/topology/TopologyCanvas';
import { bySystem } from '../../components/topology/topologyModel';
import { fromTopologyResponse } from '../../components/topology/topologySource';
import type { AppDispatch, RootState } from '../../store';
import { fetchTopology, clearTopology } from '../../store/topologySlice';

const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2',
  cache: '#f57c00',
  message_queue: '#7b1fa2',
  web_service: '#388e3c',
  api_gateway: '#00796b',
  worker: '#e64a19',
  frontend: '#303f9f',
  other: '#616161',
};

const nodeTypes = {
  subsystemNode: SubsystemNode,
  systemGroupNode: SystemGroupNode,
  collapsedSystemNode: CollapsedSystemNode,
};

const colorFor = (t: string) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other;

interface Props {
  systemId: number;
}

export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { data, loading, error } = useSelector((state: RootState) => state.topology);

  useEffect(() => {
    dispatch(fetchTopology(systemId));
    return () => {
      dispatch(clearTopology());
    };
  }, [systemId, dispatch]);

  const source = useMemo(() => (data ? fromTopologyResponse(data) : null), [data]);
  const graph = useMemo(() => source?.getGraph() ?? null, [source]);
  const grouping = useMemo(
    () => bySystem(source?.getSystemNames() ?? {}, systemId),
    [source, systemId]
  );

  const findDependency = useCallback(
    (id: number) =>
      [...(data?.dependencies ?? []), ...(data?.external_dependencies ?? [])].find(
        (d) => d.id === id
      ) ?? null,
    [data]
  );

  return (
    <TopologyCanvas
      graph={graph}
      grouping={grouping}
      loading={loading}
      error={error}
      colorFor={colorFor}
      nodeTypes={nodeTypes}
      findDependency={findDependency}
      emptyMessage="No subsystems yet. Add subsystems to see the topology diagram."
    />
  );
}
```

- [ ] **Step 4: Typecheck + full topology suite**

Run: `npx tsc --noEmit`
Expected: clean.
Run: `npx vitest run src/components/topology/`
Expected: all pass.

- [ ] **Step 5: Full unit suite (guard against wider breakage)**

Run: `npx vitest run --exclude 'e2e/**'`
Expected: all pass (same count as before this sub-project; the 3 Playwright e2e specs remain excluded).

- [ ] **Step 6: Manual parity check**

Start the app if not running (`npm run dev`), open a system's Topology tab. Confirm identical behavior to before: ELK layout renders, search centers a component, filter-by-type hides/shows, collapse chevron collapses a system and clicking a collapsed node expands it, clicking an edge opens the detail pane, focus dims non-neighbors. (Browser automation has been flaky — eyeball or ask the user if synthetic clicks stall.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/topology/TopologyCanvas.tsx \
        frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "refactor(topology): extract reusable TopologyCanvas; systems page is a thin wrapper"
```

---

## Done Criteria

- `computeCollapseModel` takes a pluggable `Grouping`; `bySystem()` reproduces the current behavior with `groupId === String(system_id)`.
- A non-system grouping is proven by `topologyGrouping.test.ts`.
- `<TopologyCanvas>` owns all orchestration; `SystemTopologyDiagram` is a thin wrapper supplying data + grouping + render config.
- `npx tsc --noEmit` clean; `npx vitest run --exclude 'e2e/**'` green; systems Topology tab behaves/looks identical (manual).
- No environment, backend, or host code touched (deferred to SP2–SP4).
```
