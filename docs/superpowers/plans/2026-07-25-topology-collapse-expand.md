# Topology Collapse / Expand Systems Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user collapse any system in the topology diagram to a single node (name + component count) with its boundary edges aggregated, and expand it again — composing with type-filtering, focus, and search.

**Architecture:** A new pure `computeCollapseModel` turns the (type-filtered) graph + a `collapsedSystems` set into a `TopologyModel` (systems marked collapsed/expanded + resolved, deduped edges). `buildElkGraph`/`elkToReactFlow` are reworked to consume the model — identical output to today when nothing is collapsed. A new `CollapsedSystemNode` renders a collapsed system; a chevron on `SystemGroupNode` collapses; clicking a collapsed node expands.

**Tech Stack:** React 18 + TypeScript strict + React Flow 11.11.4 + elkjs + MUI + Vitest.

**Spec:** `docs/superpowers/specs/2026-07-25-topology-collapse-expand-design.md`

---

## Key facts (verified against current code)

- `topologyElkGraph.ts` currently: `buildElkGraph(input: ElkGraphInput)` groups `[...subsystems, ...externalSubsystems]` by `system_id` into ELK containers `group-<sysId>` with children `String(id)` (`NODE_WIDTH=180 × NODE_HEIGHT=70`), edges `{ id: 'e'+d.id, sources:[String(from)], targets:[String(to)] }`. `elkToReactFlow(result, ctx)` maps containers → `systemGroupNode` + `subsystemNode` children, and edges by looking up `ctx.dependencies` (strips the `e` prefix). Constants `NODE_WIDTH/NODE_HEIGHT/GROUP_LABEL_HEIGHT`, `ROOT_OPTIONS`, `CONTAINER_OPTIONS`, `LAYER_SPACING` are module-level. `RenderSubsystem`/`RenderDependency`/`ElkRenderContext` exported.
- `SystemGroupNode.tsx`: `data: { label: string; isCurrent: boolean; dimmed?: boolean }`; renders a dashed `<Box pointerEvents:'none'>` with a label chip near top-left (`top:-11, left:14`).
- `topologyVisibility.ts` (2b-i): `VisibilityInput = { subsystems: VisibleSubsystem[]; dependencies: VisibleDependency[]; externalSubsystems; externalDependencies }`; `VisibleSubsystem = { id, name, system_id, component_type, technology }`; `VisibleDependency = { id, from_subsystem_id, to_subsystem_id, dependency_type, direction: DependencyDirection, label }`.
- `SystemTopologyDiagram.tsx` (post-2b-i): builds `visibleGraph = computeVisibleGraph(...)`, then the ELK effect does `buildElkGraph(visibleGraph)` + ctx maps + `elkToReactFlow(res, ctx)`, deps `[visibleGraph, systemId, data]`. Has `focusedId`, `selectedDepId`, `hiddenTypes` state; a `[data]` effect resets `selectedDepId`+`focusedId`; a focus-clear effect on `[focusedId, visibleIds]`; `nodes` memo applies focus dimming; `handleNodeClick` ignores `group-` ids; `handleEdgeClick` does `parseInt(edge.id,10)`; `nodeTypes = { subsystemNode, systemGroupNode }`.

---

## File Structure

- **Create** `frontend/src/components/topology/topologyModel.ts` — `computeCollapseModel` + `TopologyModel`/`ModelSystem`/`ModelEdge`/`CollapseContext` types. Pure aggregation.
- **Create** `frontend/src/components/topology/__tests__/topologyModel.test.ts`.
- **Create** `frontend/src/components/topology/CollapsedSystemNode.tsx` — collapsed-system node.
- **Modify** `frontend/src/components/topology/SystemGroupNode.tsx` — optional collapse chevron.
- **Modify** `frontend/src/components/topology/topologyElkGraph.ts` — `buildElkGraph`/`elkToReactFlow` consume `TopologyModel`.
- **Modify** `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts` — updated for the model.
- **Modify** `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — model pipeline + collapse/expand state & interaction.

---

### Task 1: `computeCollapseModel` (pure aggregation, TDD)

**Files:**
- Create: `frontend/src/components/topology/topologyModel.ts`
- Test: `frontend/src/components/topology/__tests__/topologyModel.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/topology/__tests__/topologyModel.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { computeCollapseModel, type CollapseContext } from '../topologyModel';
import type { VisibilityInput } from '../topologyVisibility';

const sub = (id: number, systemId: number, type = 'other') => ({
  id, name: `n${id}`, system_id: systemId, component_type: type, technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id, from_subsystem_id: from, to_subsystem_id: to,
  dependency_type: 'api_call', direction: 'one_way' as const, label: null,
});

// Customer(2): API(5) -> db(6). Mortgage(1): m(1) -> 5. EnvMgr(3): e(19) -> 5.
const input: VisibilityInput = {
  subsystems: [sub(5, 2), sub(6, 2)],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1), sub(19, 3)],
  externalDependencies: [dep(10, 1, 5), dep(11, 19, 5)],
};
const ctx = (collapsed: number[]): CollapseContext => ({
  collapsedSystems: new Set(collapsed),
  systemNames: { '1': 'Mortgage', '2': 'Customer', '3': 'Env Manager' },
  currentSystemId: 2,
});

describe('computeCollapseModel', () => {
  it('with nothing collapsed: one expanded system per system, edges 1:1', () => {
    const m = computeCollapseModel(input, ctx([]));
    expect(m.systems.map((s) => s.systemId).sort()).toEqual([1, 2, 3]);
    expect(m.systems.every((s) => !s.collapsed)).toBe(true);
    const customer = m.systems.find((s) => s.systemId === 2)!;
    expect(customer.components.map((c) => c.id).sort()).toEqual([5, 6]);
    expect(customer.isCurrent).toBe(true);
    expect(m.edges.map((e) => e.id).sort()).toEqual(['10', '11', '8']);
    expect(m.edges.every((e) => e.aggregatedCount === 1)).toBe(true);
  });

  it('collapsing a system empties its components and sets the count', () => {
    const m = computeCollapseModel(input, ctx([1]));
    const mort = m.systems.find((s) => s.systemId === 1)!;
    expect(mort.collapsed).toBe(true);
    expect(mort.components).toEqual([]);
    expect(mort.componentCount).toBe(1);
  });

  it('re-points a collapsed system’s boundary edge to sys-<id>', () => {
    const m = computeCollapseModel(input, ctx([1]));
    const e = m.edges.find((x) => x.dependencyId === 10)!; // 1 -> 5
    expect(e.source).toBe('sys-1');
    expect(e.target).toBe('5');
  });

  it('drops an edge internal to a collapsed system', () => {
    // Collapse Customer(2): its internal dep 8 (5->6) becomes sys-2 -> sys-2 → dropped.
    const m = computeCollapseModel(input, ctx([2]));
    expect(m.edges.some((e) => e.dependencyId === 8)).toBe(false);
  });

  it('aggregates multiple boundary edges into one with a count', () => {
    // Two deps into API server 5 from two different collapsed systems is NOT an aggregate
    // (different sources). Build a case: two components of Mortgage(1) both -> 5.
    const agg: VisibilityInput = {
      subsystems: [sub(5, 2)],
      dependencies: [],
      externalSubsystems: [sub(1, 1), sub(2, 1)],
      externalDependencies: [dep(20, 1, 5), dep(21, 2, 5)],
    };
    const m = computeCollapseModel(agg, ctx([1]));
    const aggEdge = m.edges.find((e) => e.source === 'sys-1' && e.target === '5')!;
    expect(aggEdge.aggregatedCount).toBe(2);
    expect(aggEdge.dependencyId).toBeNull();
    expect(aggEdge.id).toBe('agg:sys-1->5');
    expect(aggEdge.label).toBe('2×');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyModel.test.ts`
Expected: FAIL — cannot resolve `../topologyModel`.

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/topology/topologyModel.ts`:

```ts
import type { DependencyDirection } from '../../types/dependency';
import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface ModelSystem {
  systemId: number;
  name: string;
  isCurrent: boolean;
  collapsed: boolean;
  componentCount: number;
  components: VisibleSubsystem[]; // [] when collapsed
}

export interface ModelEdge {
  id: string; // real dep id (String) when single; `agg:${source}->${target}` when aggregated
  source: string; // component id (String) or `sys-${systemId}`
  target: string;
  label: string;
  aggregatedCount: number;
  dependencyId: number | null;
  direction: DependencyDirection;
}

export interface TopologyModel {
  systems: ModelSystem[];
  edges: ModelEdge[];
}

export interface CollapseContext {
  collapsedSystems: Set<number>;
  systemNames: Record<string, string>;
  currentSystemId: number;
}

export function computeCollapseModel(
  input: VisibilityInput,
  ctx: CollapseContext
): TopologyModel {
  const allSubs = [...input.subsystems, ...input.externalSubsystems];
  const allDeps = [...input.dependencies, ...input.externalDependencies];

  const systemOf = new Map<number, number>();
  for (const s of allSubs) systemOf.set(s.id, s.system_id);

  // Group components by system (first-seen order).
  const bySystem = new Map<number, VisibleSubsystem[]>();
  for (const s of allSubs) {
    if (!bySystem.has(s.system_id)) bySystem.set(s.system_id, []);
    bySystem.get(s.system_id)!.push(s);
  }

  const systems: ModelSystem[] = [...bySystem.entries()].map(([systemId, comps]) => {
    const collapsed = ctx.collapsedSystems.has(systemId);
    return {
      systemId,
      name: ctx.systemNames[String(systemId)] ?? `System ${systemId}`,
      isCurrent: systemId === ctx.currentSystemId,
      collapsed,
      componentCount: comps.length,
      components: collapsed ? [] : comps,
    };
  });

  const displayNode = (componentId: number): string => {
    const sysId = systemOf.get(componentId);
    return sysId !== undefined && ctx.collapsedSystems.has(sysId)
      ? `sys-${sysId}`
      : String(componentId);
  };

  // Bucket dependencies by resolved (source,target); drop same-collapsed-system edges.
  const buckets = new Map<string, VisibleDependency[]>();
  for (const d of allDeps) {
    const source = displayNode(d.from_subsystem_id);
    const target = displayNode(d.to_subsystem_id);
    if (source === target) continue; // internal to a collapsed system
    const key = `${source}->${target}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(d);
  }

  const edges: ModelEdge[] = [...buckets.entries()].map(([key, deps]) => {
    const [source, target] = key.split('->');
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
      direction: 'one_way',
    };
  });

  return { systems, edges };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyModel.test.ts`
Expected: PASS (5 tests). Then `npx tsc --noEmit` — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyModel.ts frontend/src/components/topology/__tests__/topologyModel.test.ts
git commit -m "feat(ui): computeCollapseModel — system collapse + edge aggregation"
```

---

### Task 2: `CollapsedSystemNode` + `SystemGroupNode` collapse chevron

Both changes are inert until Task 4 wires the handlers, so the build stays green.

**Files:**
- Create: `frontend/src/components/topology/CollapsedSystemNode.tsx`
- Modify: `frontend/src/components/topology/SystemGroupNode.tsx`

- [ ] **Step 1: Create `CollapsedSystemNode.tsx`**

```tsx
import { Box, Typography } from '@mui/material';
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore';
import { Handle, Position } from 'reactflow';

interface CollapsedSystemNodeProps {
  data: {
    systemId: number;
    name: string;
    componentCount: number;
    isCurrent: boolean;
    dimmed?: boolean;
    onExpand?: (systemId: number) => void;
  };
}

const NODE_WIDTH = 180;
const NODE_HEIGHT = 70;

export default function CollapsedSystemNode({ data }: CollapsedSystemNodeProps) {
  const borderColor = data.isCurrent ? '#1976d2' : '#757575';
  return (
    <Box
      onClick={() => data.onExpand?.(data.systemId)}
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px solid ${borderColor}`,
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
        {data.name}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}>
        <UnfoldMoreIcon sx={{ fontSize: 14, transform: 'rotate(90deg)' }} />
        <Typography variant="caption">
          {data.componentCount} component{data.componentCount === 1 ? '' : 's'}
        </Typography>
      </Box>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}
```

- [ ] **Step 2: Add the collapse chevron to `SystemGroupNode.tsx`**

Read the current file. Extend the `data` type and add an interactive chevron button in the label area (the label is at `top:-11, left:14`). Change the props type to:

```tsx
interface SystemGroupNodeProps {
  data: {
    label: string;
    isCurrent: boolean;
    dimmed?: boolean;
    systemId?: number;
    onCollapse?: (systemId: number) => void;
  };
}
```

Inside the label `<Box>` (the one positioned at `top:-11, left:14` that contains the system name), render — AFTER the label `Typography` — a collapse control that only appears when a handler is provided:

```tsx
        {data.onCollapse && data.systemId !== undefined && (
          <IconButton
            size="small"
            aria-label={`Collapse ${data.label}`}
            onClick={(e) => {
              e.stopPropagation();
              data.onCollapse!(data.systemId!);
            }}
            sx={{ p: 0.25, ml: 0.5, pointerEvents: 'auto' }}
          >
            <UnfoldLessIcon sx={{ fontSize: 16, transform: 'rotate(90deg)' }} />
          </IconButton>
        )}
```

Add the imports at the top of `SystemGroupNode.tsx`: `IconButton` from `@mui/material` (extend the existing MUI import) and `import UnfoldLessIcon from '@mui/icons-material/UnfoldLess';`. Ensure the label container `<Box>` lays its children in a row (`display: 'flex', alignItems: 'center'`) so the chevron sits beside the label; the label Box currently wraps only the name — set its `sx` to include `display:'flex', alignItems:'center'`. Keep the outer dashed box `pointerEvents: 'none'`; the `IconButton`'s `pointerEvents:'auto'` re-enables just the control.

- [ ] **Step 3: Typecheck + tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/`
Expected: clean typecheck; all existing tests pass (these two changes are additive/inert — `CollapsedSystemNode` is not yet referenced, `SystemGroupNode`'s chevron renders only when `onCollapse` is passed, which it isn't yet).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/topology/CollapsedSystemNode.tsx frontend/src/components/topology/SystemGroupNode.tsx
git commit -m "feat(ui): collapsed-system node + collapse chevron (inert until wired)"
```

---

### Task 3: Rework `buildElkGraph`/`elkToReactFlow` to the model + rewire the diagram (behavior-preserving)

This changes the two core functions' signatures and updates the single caller in the same task so the build stays green. With `collapsedSystems` empty (still the case after this task), the rendered diagram is identical to today.

**Files:**
- Modify: `frontend/src/components/topology/topologyElkGraph.ts`
- Modify: `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts`
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Rewrite `buildElkGraph` to take a `TopologyModel`**

In `topologyElkGraph.ts`, add `import type { TopologyModel } from './topologyModel';` and add collapsed-node size constants near the others:

```ts
export const COLLAPSED_WIDTH = 180;
export const COLLAPSED_HEIGHT = 70;
```

Replace `buildElkGraph` (and remove the now-unused `ElkSubsystem`/`ElkDependency`/`ElkGraphInput` interfaces) with:

```ts
export function buildElkGraph(model: TopologyModel): ElkNode {
  const children: ElkNode[] = model.systems.map((s) =>
    s.collapsed
      ? { id: `sys-${s.systemId}`, width: COLLAPSED_WIDTH, height: COLLAPSED_HEIGHT }
      : {
          id: `group-${s.systemId}`,
          layoutOptions: CONTAINER_OPTIONS,
          children: s.components.map((c) => ({
            id: String(c.id),
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
          })),
        }
  );

  const edges: ElkExtendedEdge[] = model.edges.map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));

  return { id: 'root', layoutOptions: ROOT_OPTIONS, children, edges };
}
```

- [ ] **Step 2: Rewrite `elkToReactFlow` to take `(result, model, ctx)`**

Replace `elkToReactFlow` with a version that maps collapsed leaves + expanded containers and builds edges from the model. Change `ElkRenderContext` to drop the now-unneeded `dependencies` map (edges come from the model):

```ts
export interface ElkRenderContext {
  systemNames: Record<string, string>;
  subsystems: Map<number, RenderSubsystem>;
  colorFor: (componentType: string) => string;
}

export function elkToReactFlow(
  result: ElkNode,
  model: TopologyModel,
  ctx: ElkRenderContext
): { nodes: Node[]; edges: Edge[] } {
  const systemById = new Map(model.systems.map((s) => [s.systemId, s]));
  const topNodes: Node[] = [];
  const childNodes: Node[] = [];

  for (const node of result.children ?? []) {
    if (node.id.startsWith('sys-')) {
      const sysId = Number(node.id.replace('sys-', ''));
      const s = systemById.get(sysId);
      if (!s) continue;
      topNodes.push({
        id: node.id,
        type: 'collapsedSystemNode',
        position: { x: node.x ?? 0, y: node.y ?? 0 },
        data: { systemId: sysId, name: s.name, componentCount: s.componentCount, isCurrent: s.isCurrent },
        selectable: false,
        draggable: false,
      });
      continue;
    }
    const sysId = Number(node.id.replace('group-', ''));
    const s = systemById.get(sysId);
    topNodes.push({
      id: node.id,
      type: 'systemGroupNode',
      position: { x: node.x ?? 0, y: node.y ?? 0 },
      style: { width: node.width ?? 0, height: node.height ?? 0 },
      data: {
        label: s?.name ?? ctx.systemNames[String(sysId)] ?? `System ${sysId}`,
        isCurrent: s?.isCurrent ?? false,
        systemId: sysId,
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

  const edges: Edge[] = model.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: 'floating',
    label: e.label,
    markerEnd: { type: MarkerType.ArrowClosed },
    ...(e.direction === 'two_way' && e.aggregatedCount === 1
      ? { markerStart: { type: MarkerType.ArrowClosed } }
      : {}),
  }));

  return { nodes: [...topNodes, ...childNodes], edges };
}
```

- [ ] **Step 3: Update `topologyElkGraph.test.ts`**

Read the current test. Its `buildElkGraph`/`elkToReactFlow` tests pass the old `ElkGraphInput`/`ctx` shapes. Rewrite them to build a `TopologyModel` and pass `(result, model, ctx)`. Replace the whole test file with:

```ts
import { describe, expect, it } from 'vitest';
import { buildElkGraph, elkToReactFlow, type ElkRenderContext, type RenderSubsystem } from '../topologyElkGraph';
import type { TopologyModel } from '../topologyModel';
import type { ElkNode } from 'elkjs/lib/elk-api';

const comp = (id: number, systemId: number): RenderSubsystem => ({
  id, name: `n${id}`, system_id: systemId, component_type: 'other', technology: null,
});

const model: TopologyModel = {
  systems: [
    { systemId: 2, name: 'Customer', isCurrent: true, collapsed: false, componentCount: 2, components: [comp(5, 2), comp(6, 2)] },
    { systemId: 1, name: 'Mortgage', isCurrent: false, collapsed: true, componentCount: 1, components: [] },
  ],
  edges: [
    { id: '8', source: '5', target: '6', label: 'api_call', aggregatedCount: 1, dependencyId: 8, direction: 'one_way' },
    { id: 'sys-1->5', source: 'sys-1', target: '5', label: 'api_call', aggregatedCount: 1, dependencyId: 10, direction: 'one_way' },
  ],
};

describe('buildElkGraph', () => {
  it('emits a container for an expanded system and a leaf for a collapsed one', () => {
    const g = buildElkGraph(model);
    const ids = (g.children ?? []).map((c) => c.id).sort();
    expect(ids).toEqual(['group-2', 'sys-1']);
    const group = (g.children ?? []).find((c) => c.id === 'group-2')!;
    expect((group.children ?? []).map((c) => c.id).sort()).toEqual(['5', '6']);
    const leaf = (g.children ?? []).find((c) => c.id === 'sys-1')!;
    expect(leaf.children).toBeUndefined();
    expect(leaf.width).toBe(180);
  });

  it('emits one edge per model edge, using resolved endpoints', () => {
    const g = buildElkGraph(model);
    expect((g.edges ?? []).map((e) => `${e.sources[0]}->${e.targets[0]}`).sort()).toEqual([
      '5->6',
      'sys-1->5',
    ]);
  });
});

const laidOut: ElkNode = {
  id: 'root',
  children: [
    { id: 'group-2', x: 300, y: 0, width: 240, height: 140, children: [{ id: '5', x: 12, y: 40, width: 180, height: 70 }, { id: '6', x: 12, y: 40, width: 180, height: 70 }] },
    { id: 'sys-1', x: 0, y: 0, width: 180, height: 70 },
  ],
};
const ctx: ElkRenderContext = {
  systemNames: { '1': 'Mortgage', '2': 'Customer' },
  subsystems: new Map([[5, comp(5, 2)], [6, comp(6, 2)]]),
  colorFor: () => '#616161',
};

describe('elkToReactFlow', () => {
  it('maps a collapsed leaf to a collapsedSystemNode with name + count', () => {
    const { nodes } = elkToReactFlow(laidOut, model, ctx);
    const collapsed = nodes.find((n) => n.id === 'sys-1')!;
    expect(collapsed.type).toBe('collapsedSystemNode');
    expect(collapsed.data).toMatchObject({ systemId: 1, name: 'Mortgage', componentCount: 1 });
  });

  it('maps an expanded container to a group node with its children after it', () => {
    const { nodes } = elkToReactFlow(laidOut, model, ctx);
    const g = nodes.find((n) => n.id === 'group-2')!;
    expect(g.type).toBe('systemGroupNode');
    expect(g.data).toMatchObject({ systemId: 2, isCurrent: true });
    const child = nodes.find((n) => n.id === '5')!;
    expect(child.parentId).toBe('group-2');
    expect(nodes.indexOf(g)).toBeLessThan(nodes.indexOf(child));
  });

  it('builds floating edges from the model', () => {
    const { edges } = elkToReactFlow(laidOut, model, ctx);
    expect(edges.map((e) => e.id).sort()).toEqual(['8', 'sys-1->5']);
    expect(edges.every((e) => e.type === 'floating')).toBe(true);
  });
});
```

- [ ] **Step 4: Rewire the diagram's ELK effect to the model pipeline**

In `SystemTopologyDiagram.tsx`: add imports:
```tsx
import { computeCollapseModel } from '../../components/topology/topologyModel';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
```
Register the new node type:
```tsx
const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode, collapsedSystemNode: CollapsedSystemNode };
```
Replace the ELK effect body's graph/ctx construction and `elkToReactFlow` call. The effect currently builds `buildElkGraph(visibleGraph)` + a `subsystems` map + a `dependencies` map + `elkToReactFlow(res, ctx)`. Replace with a model-based version (note: the `dependencies` map is no longer needed):

```tsx
  useEffect(() => {
    if (!visibleGraph || !data) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const model = computeCollapseModel(visibleGraph, {
      collapsedSystems,
      systemNames: data.system_names ?? {},
      currentSystemId: systemId,
    });

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems]) subsystems.set(s.id, s);

    const ctx: ElkRenderContext = {
      systemNames: data.system_names ?? {},
      subsystems,
      colorFor: (t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other,
    };

    elk
      .layout(buildElkGraph(model))
      .then((res) => {
        if (cancelled) return;
        setLayout(elkToReactFlow(res, model, ctx));
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
  }, [visibleGraph, systemId, data, collapsedSystems]);
```

Add the `collapsedSystems` state near `hiddenTypes` (empty set = all expanded), so the effect compiles:
```tsx
  const [collapsedSystems, setCollapsedSystems] = useState<Set<number>>(new Set());
```
So the setter is used in this task (avoids a `noUnusedLocals` error before Task 4), extend the existing `[data]` reset effect to also clear collapse — change it to:
```tsx
  useEffect(() => {
    setSelectedDepId(null);
    setFocusedId(null);
    setCollapsedSystems(new Set());
  }, [data]);
```
Remove the now-unused `RenderDependency` import if tsc flags it (edges no longer use the dependencies map). Keep `RenderSubsystem`.

- [ ] **Step 5: Typecheck + tests + build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/ && npm run build`
Expected: clean; all tests pass (topologyModel + rewritten topologyElkGraph + focus/filter/toolbar suites); build succeeds. Both `collapsedSystems` (read in the effect) and `setCollapsedSystems` (used in the reset effect) are referenced, so `noUnusedLocals` is satisfied.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/topology/topologyElkGraph.ts frontend/src/components/topology/__tests__/topologyElkGraph.test.ts frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "refactor(ui): topology build/map consume a TopologyModel (collapse-ready)"
```

---

### Task 4: Collapse/expand interaction

Now `collapsedSystems` actually gets toggled and the handlers thread into node data.

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Collapse/expand handlers**

Add stable handlers near the other `useCallback`s (the `[data]` reset effect already clears `collapsedSystems` from Task 3):
```tsx
  const collapseSystem = useCallback((sid: number) => {
    setCollapsedSystems((prev) => new Set(prev).add(sid));
  }, []);
  const expandSystem = useCallback((sid: number) => {
    setCollapsedSystems((prev) => {
      const next = new Set(prev);
      next.delete(sid);
      return next;
    });
  }, []);
```

- [ ] **Step 2: Thread `onCollapse`/`onExpand` into node data via the `nodes` memo**

The `nodes` memo currently maps `layout.nodes` for focus dimming. Extend each branch to also inject the handlers by node type. Replace the `nodes` memo with:
```tsx
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
        return { ...n, data: { ...n.data, dimmed, onCollapse: collapseSystem } };
      }
      if (n.type === 'collapsedSystemNode') {
        return { ...n, data: { ...n.data, dimmed, onExpand: expandSystem } };
      }
      return { ...n, data: { ...n.data, dimmed } };
    });
  }, [layout.nodes, focusSet, collapseSystem, expandSystem]);
```
(This preserves the prior behaviour: when `focusSet` is null, `dimmed` is `undefined` on every node — the node components treat falsy `dimmed` as not-dimmed. The collapsed-node brightness follows the same group rule via its own id in `brightGroups`; a collapsed system is bright when in the focus set is moot since its components aren't rendered — it simply never dims unless focus is active, which is acceptable.)

- [ ] **Step 3: Guard node-click and edge-click for the new ids**

`handleNodeClick` must ignore collapsed-system nodes (they expand via their own onClick, not focus). Update its guard:
```tsx
  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    if (node.id.startsWith('group-') || node.id.startsWith('sys-')) return;
    setFocusedId((cur) => (cur === node.id ? null : node.id));
  }, []);
```
`handleEdgeClick` must ignore aggregated edges (id like `agg:...`, not an integer). Update it:
```tsx
  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    const id = parseInt(edge.id, 10);
    if (Number.isNaN(id)) return; // aggregated edge — no single dependency to show
    setSelectedDepId((prev) => (prev === id ? null : id));
  }, []);
```

- [ ] **Step 4: Typecheck + tests + build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/ && npm run build`
Expected: clean; all pass; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "feat(ui): collapse/expand systems interaction (chevron + click)"
```

---

### Task 5: Manual verification (live)

**Files:** none (verification only).

- [ ] **Step 1: Run the app**

Start backend (per `CLAUDE.md`) and `cd frontend && npm run dev`. Log in `admin`/`admin123` (tenant `demo`). Open **Systems → Customer → Topology**.

- [ ] **Step 2: Verify no regression (nothing collapsed)**

The diagram looks exactly as before: Env Manager + Mortgage fan into Customer API Server; API Server → database; labels legible. Focus (click a component), search, and the Types filter all still work.

- [ ] **Step 3: Verify collapse/expand**

- Hover the **Env Manager** box → a collapse chevron shows on its header; click it → Env Manager becomes a single node "Env Manager · 1 component"; its `api_call` edge re-points to that node; the diagram reflows.
- Click the collapsed "Env Manager" node → it expands back to the box with its component.
- Collapse **Customer** (the current system) → it becomes one node; the Mortgage/Env-Manager edges aggregate onto it.

- [ ] **Step 4: Verify interplay**

- Collapse a system, then open **Types** and hide a type → both hold; the collapsed count reflects visible components.
- Focus "Customer database", then collapse **Customer** → focus clears.
- Click a normal (non-aggregated) edge → Link Details still opens. If an aggregated `N×` edge exists, clicking it does nothing (no pane) — the `N×` label shows the multiplicity.

- [ ] **Step 5 (optional): open a PR** — handled by finishing-a-development-branch after review.

---

## Self-Review

**Spec coverage:** `computeCollapseModel` + aggregation (Task 1); `CollapsedSystemNode` + collapse chevron (Task 2); model-driven `buildElkGraph`/`elkToReactFlow` with behavior-preserving rewire (Task 3); collapse/expand state, handlers, reset-on-switch, focus/edge-click guards (Task 4); manual verification incl. regression, collapse/expand, interplay (Task 5). All spec sections covered.

**Placeholder scan:** none — full code in every step; the empty-collapse regression-safety is enforced by keeping the existing focus/filter/search test suites green in Task 3 Step 5.

**Type consistency:** `TopologyModel`/`ModelSystem`/`ModelEdge`/`CollapseContext` (Task 1) are consumed verbatim by `buildElkGraph(model)`/`elkToReactFlow(result, model, ctx)` (Task 3) and `computeCollapseModel(...)` in the diagram (Task 3 Step 4). `ElkRenderContext` loses its `dependencies` map (Task 3 Step 2) — the diagram stops building that map (Task 3 Step 4) and drops the `RenderDependency` import. Node data contracts line up: `systemGroupNode` data gains `systemId` (Task 3 Step 2) which the chevron (Task 2 Step 2) reads and the `nodes` memo sets `onCollapse` on (Task 4 Step 2); `collapsedSystemNode` data (`systemId,name,componentCount,isCurrent`) from Task 3 Step 2 matches `CollapsedSystemNode`'s props (Task 2 Step 1) plus `onExpand` injected in Task 4 Step 2. `collapsedSystems` state is added in Task 3 Step 4 and consumed by the effect there; its setter is used in Task 4. Collapsed node id scheme `sys-<id>` is emitted by `buildElkGraph` (Task 3 Step 1), mapped by `elkToReactFlow` (Task 3 Step 2), and guarded in `handleNodeClick` (Task 4 Step 3). Aggregated edge id `agg:...` from Task 1 is guarded in `handleEdgeClick` (Task 4 Step 3).
