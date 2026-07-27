# Group-by-System / Group-by-Host Toggle (SP4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a client-side "Group by: System / Host" toggle to the environment topology diagram, regrouping subsystems by the infrastructure host they deploy on.

**Architecture:** A pure upstream transform (`buildHostGraph`) expands each multi-host subsystem into synthetic per-host nodes and fans dependencies out across host instances, minting its own synthetic node/edge ids and returning closure maps (`hostKeyById`, `hostMeta`, `edgeDepResolver`). A `byHost(...)` grouping closes over those maps. The shared `<TopologyCanvas>` core (model/ELK/visibility/collapse) is untouched; only the env wrapper switches graph + grouping + detail-pane resolver by mode. Backend is unchanged (SP2 already returns `hosts`).

**Tech Stack:** React 18 + TypeScript (strict), MUI, React Flow, Vitest. Frontend-only.

**Spec:** `docs/superpowers/specs/2026-07-27-topology-group-by-host-design.md`

---

## File Structure

**Create:**
- `frontend/src/components/topology/topologyHostTransform.ts` — `buildHostGraph`, `HostGraph`, `HostGroupMeta`
- `frontend/src/components/topology/__tests__/topologyHostTransform.test.ts` — transform + `byHost` grouping tests

**Modify:**
- `frontend/src/types/environment.ts` — `EnvSubsystemHostRef`, `hosts` on `EnvSubsystemNode`
- `frontend/src/components/topology/topologyVisibility.ts` — optional `hosts?` on `VisibleSubsystem`
- `frontend/src/components/topology/environmentTopologySource.ts` — `byHost(...)` grouping
- `frontend/src/components/topology/TopologyCanvas.tsx` — `headerControls?` prop rendered in the toolbar row
- `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx` — `groupBy` state, `<ToggleButtonGroup>`, host-mode wiring

All `npx …` commands run from `frontend/`.

---

## Task 1: Thread host data through the frontend types

**Files:**
- Modify: `frontend/src/types/environment.ts`
- Modify: `frontend/src/components/topology/topologyVisibility.ts`

Type-only change (no runtime behavior yet), verified by the type-checker.

- [ ] **Step 1: Add the host-ref type and `hosts` field in `environment.ts`**

Add above `EnvSubsystemNode` (currently near line 92):

```ts
export interface EnvSubsystemHostRef {
  infrastructure_component_id: number;
  name: string;
  component_type: string;
  role: string | null;
}
```

Then add `hosts` to `EnvSubsystemNode` (keep existing fields):

```ts
export interface EnvSubsystemNode {
  id: number;
  name: string;
  component_type: string;
  technology: string | null;
  system_id: number;
  is_mocked: boolean;
  hosts: EnvSubsystemHostRef[]; // [] for outside subsystems
}
```

- [ ] **Step 2: Add optional `hosts?` to `VisibleSubsystem` in `topologyVisibility.ts`**

Import the ref type at the top:

```ts
import type { EnvSubsystemHostRef } from '../../types/environment';
```

Add the field to `VisibleSubsystem` (keep existing fields):

```ts
export interface VisibleSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
  is_mocked?: boolean;
  hosts?: EnvSubsystemHostRef[]; // present only for environment subsystems
}
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: PASS (no errors). `EnvSubsystemNode` is structurally assignable to `VisibleSubsystem`, so `fromEnvironmentTopologyResponse` still compiles and `hosts` now flows through the graph.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/environment.ts frontend/src/components/topology/topologyVisibility.ts
git commit -m "feat(topology): thread env host data through frontend types (SP4)"
```

---

## Task 2: `buildHostGraph` transform (TDD)

**Files:**
- Create: `frontend/src/components/topology/topologyHostTransform.ts`
- Test: `frontend/src/components/topology/__tests__/topologyHostTransform.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/topology/__tests__/topologyHostTransform.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { buildHostGraph } from '../topologyHostTransform';
import type { VisibilityInput, VisibleSubsystem } from '../topologyVisibility';
import type { EnvSubsystemHostRef } from '../../../types/environment';

const host = (id: number, name: string): EnvSubsystemHostRef => ({
  infrastructure_component_id: id,
  name,
  component_type: 'server',
  role: null,
});
const sub = (
  id: number,
  systemId: number,
  hosts: EnvSubsystemHostRef[] | undefined,
): VisibleSubsystem => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: 'service',
  technology: null,
  is_mocked: false,
  hosts,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way' as const,
  label: null,
});

// A(1) on web-01/web-02, B(2) on web-01, C(3) no hosts, external X(9).
// dep A->B  and external dep X->A.
const input: VisibilityInput = {
  subsystems: [
    sub(1, 100, [host(10, 'web-01'), host(11, 'web-02')]),
    sub(2, 100, [host(10, 'web-01')]),
    sub(3, 100, []),
  ],
  dependencies: [dep(50, 1, 2)],
  externalSubsystems: [sub(9, 200, [])],
  externalDependencies: [dep(60, 9, 1)],
};

describe('buildHostGraph', () => {
  it('expands multi-host subsystems to one node per host', () => {
    const { graph, hostKeyById } = buildHostGraph(input);
    // A×2 + B×1 + C×1 = 4 internal, X×1 external
    expect(graph.subsystems).toHaveLength(4);
    expect(graph.externalSubsystems).toHaveLength(1);
    const keys = graph.subsystems.map((s) => hostKeyById.get(s.id)).sort();
    expect(keys).toEqual(['10', '10', '11', 'unassigned']);
  });

  it('buckets a hostless in-env subsystem under "unassigned" and externals under "external"', () => {
    const { graph, hostKeyById, hostMeta } = buildHostGraph(input);
    const cNode = graph.subsystems.find((s) => s.name === 'n3')!;
    expect(hostKeyById.get(cNode.id)).toBe('unassigned');
    expect(hostMeta.get('unassigned')).toEqual({ name: 'Unassigned', isCurrent: false });
    const xNode = graph.externalSubsystems[0];
    expect(hostKeyById.get(xNode.id)).toBe('external');
    expect(hostMeta.get('external')).toEqual({ name: 'External', isCurrent: false });
  });

  it('labels real host groups by host name and marks them current', () => {
    const { hostMeta } = buildHostGraph(input);
    expect(hostMeta.get('10')).toEqual({ name: 'web-01', isCurrent: true });
    expect(hostMeta.get('11')).toEqual({ name: 'web-02', isCurrent: true });
  });

  it('preserves source rendering fields on synthetic nodes', () => {
    const { graph } = buildHostGraph(input);
    const aInstances = graph.subsystems.filter((s) => s.name === 'n1');
    expect(aInstances).toHaveLength(2);
    expect(aInstances.every((s) => s.component_type === 'service' && s.is_mocked === false)).toBe(true);
  });

  it('fans a dependency out across the cartesian product of instances', () => {
    const { graph, hostKeyById, edgeDepResolver } = buildHostGraph(input);
    // A(2 instances) -> B(1 instance) = 2 edges, all resolving to real dep 50.
    expect(graph.dependencies).toHaveLength(2);
    for (const e of graph.dependencies) {
      expect(edgeDepResolver.get(e.id)).toBe(50);
      expect(hostKeyById.get(e.to_subsystem_id)).toBe('10'); // B is on web-01
      expect(['10', '11']).toContain(hostKeyById.get(e.from_subsystem_id));
    }
    // external dep X(1)->A(2) = 2 external edges, resolving to real dep 60.
    expect(graph.externalDependencies).toHaveLength(2);
    expect(graph.externalDependencies.every((e) => edgeDepResolver.get(e.id) === 60)).toBe(true);
  });

  it('mints node and edge ids in disjoint deterministic sequences', () => {
    const { graph } = buildHostGraph(input);
    const nodeIds = [...graph.subsystems, ...graph.externalSubsystems].map((s) => s.id);
    expect(new Set(nodeIds).size).toBe(nodeIds.length); // unique
    const edgeIds = [...graph.dependencies, ...graph.externalDependencies].map((e) => e.id);
    expect(new Set(edgeIds).size).toBe(edgeIds.length); // unique among edges
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/components/topology/__tests__/topologyHostTransform.test.ts`
Expected: FAIL — cannot resolve `../topologyHostTransform`.

- [ ] **Step 3: Implement the transform**

Create `frontend/src/components/topology/topologyHostTransform.ts`:

```ts
import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface HostGroupMeta {
  name: string;
  isCurrent: boolean;
}

export interface HostGraph {
  /** Synthetic graph: per-host subsystem instances + fanned-out dependencies. */
  graph: VisibilityInput;
  /** synthetic node id -> host group key */
  hostKeyById: Map<number, string>;
  /** host group key -> display metadata */
  hostMeta: Map<string, HostGroupMeta>;
  /** synthetic edge id -> real dependency id (for the detail pane) */
  edgeDepResolver: Map<number, number>;
}

const UNASSIGNED = 'unassigned';
const EXTERNAL = 'external';

/**
 * Regroup an environment topology by deployment host. Each subsystem is duplicated
 * into one synthetic node per host it runs on; dependencies fan out across the
 * cartesian product of their endpoints' instances. Node ids and edge ids are freshly
 * minted (disjoint counters) so the numeric-keyed core pipeline stays valid, and the
 * returned maps resolve synthetic ids back to host groups and real dependencies.
 */
export function buildHostGraph(input: VisibilityInput): HostGraph {
  const hostKeyById = new Map<number, string>();
  const hostMeta = new Map<string, HostGroupMeta>();
  const edgeDepResolver = new Map<number, number>();
  const instancesOf = new Map<number, VisibleSubsystem[]>();

  let nodeSeq = 1;
  let edgeSeq = 1;

  const addInstance = (src: VisibleSubsystem, hostKey: string, out: VisibleSubsystem[]) => {
    const node: VisibleSubsystem = { ...src, id: nodeSeq++ };
    hostKeyById.set(node.id, hostKey);
    if (!instancesOf.has(src.id)) instancesOf.set(src.id, []);
    instancesOf.get(src.id)!.push(node);
    out.push(node);
  };

  const subsystems: VisibleSubsystem[] = [];
  for (const s of input.subsystems) {
    const hosts = s.hosts ?? [];
    if (hosts.length === 0) {
      hostMeta.set(UNASSIGNED, { name: 'Unassigned', isCurrent: false });
      addInstance(s, UNASSIGNED, subsystems);
    } else {
      for (const h of hosts) {
        const key = String(h.infrastructure_component_id);
        hostMeta.set(key, { name: h.name, isCurrent: true });
        addInstance(s, key, subsystems);
      }
    }
  }

  const externalSubsystems: VisibleSubsystem[] = [];
  for (const s of input.externalSubsystems) {
    hostMeta.set(EXTERNAL, { name: 'External', isCurrent: false });
    addInstance(s, EXTERNAL, externalSubsystems);
  }

  const fanOut = (deps: VisibleDependency[], out: VisibleDependency[]) => {
    for (const d of deps) {
      const sources = instancesOf.get(d.from_subsystem_id) ?? [];
      const targets = instancesOf.get(d.to_subsystem_id) ?? [];
      for (const src of sources) {
        for (const tgt of targets) {
          const id = edgeSeq++;
          edgeDepResolver.set(id, d.id);
          out.push({ ...d, id, from_subsystem_id: src.id, to_subsystem_id: tgt.id });
        }
      }
    }
  };

  const dependencies: VisibleDependency[] = [];
  fanOut(input.dependencies, dependencies);
  const externalDependencies: VisibleDependency[] = [];
  fanOut(input.externalDependencies, externalDependencies);

  return {
    graph: { subsystems, externalSubsystems, dependencies, externalDependencies },
    hostKeyById,
    hostMeta,
    edgeDepResolver,
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/components/topology/__tests__/topologyHostTransform.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyHostTransform.ts frontend/src/components/topology/__tests__/topologyHostTransform.test.ts
git commit -m "feat(topology): buildHostGraph host-regrouping transform (SP4)"
```

---

## Task 3: `byHost` grouping (TDD)

**Files:**
- Modify: `frontend/src/components/topology/environmentTopologySource.ts`
- Test: `frontend/src/components/topology/__tests__/topologyHostTransform.test.ts` (extend)

- [ ] **Step 1: Add the failing test (append to the existing test file)**

Add these imports at the top of `topologyHostTransform.test.ts`:

```ts
import { byHost } from '../environmentTopologySource';
import { computeCollapseModel } from '../topologyModel';
```

Append this describe block:

```ts
describe('byHost grouping', () => {
  it('keys synthetic nodes to their host group and resolves meta', () => {
    const { graph, hostKeyById, hostMeta } = buildHostGraph(input);
    const grouping = byHost(hostKeyById, hostMeta);
    const bNode = graph.subsystems.find((s) => s.name === 'n2')!; // B on web-01 (id 10)
    expect(grouping.keyOf(bNode)).toBe('10');
    expect(grouping.meta('10')).toEqual({ name: 'web-01', isCurrent: true });
    expect(grouping.meta('unassigned')).toEqual({ name: 'Unassigned', isCurrent: false });
  });

  it('falls back to unassigned / raw key for unknown nodes', () => {
    const grouping = byHost(new Map(), new Map());
    const orphan = { id: 999, name: 'x', system_id: 1, component_type: 'service', technology: null };
    expect(grouping.keyOf(orphan)).toBe('unassigned');
    expect(grouping.meta('zzz')).toEqual({ name: 'zzz', isCurrent: false });
  });

  it('feeds computeCollapseModel: groups by host and aggregates a collapsed host group', () => {
    const { graph, hostKeyById, hostMeta } = buildHostGraph(input);
    const grouping = byHost(hostKeyById, hostMeta);
    const model = computeCollapseModel(graph, { collapsedGroups: new Set(['10']), grouping });
    const groupIds = model.groups.map((g) => g.groupId).sort();
    expect(groupIds).toEqual(['10', '11', 'external', 'unassigned']);
    const web01 = model.groups.find((g) => g.groupId === '10')!;
    expect(web01.collapsed).toBe(true);
    // edges into the collapsed web-01 group re-point to sys-10.
    expect(model.edges.some((e) => e.source === 'sys-10' || e.target === 'sys-10')).toBe(true);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/components/topology/__tests__/topologyHostTransform.test.ts`
Expected: FAIL — `byHost` is not exported from `environmentTopologySource`.

- [ ] **Step 3: Implement `byHost` in `environmentTopologySource.ts`**

Add the import for the meta type at the top:

```ts
import type { HostGroupMeta } from './topologyHostTransform';
```

Append below `byEnvSystem`:

```ts
/**
 * Environment grouping by deployment host. Keys come from `buildHostGraph`'s
 * `hostKeyById` (synthetic node id -> host key); labels/current-ness from `hostMeta`.
 * Unknown nodes fall back to the "unassigned" bucket.
 */
export function byHost(
  hostKeyById: Map<number, string>,
  hostMeta: Map<string, HostGroupMeta>,
): Grouping {
  return {
    keyOf: (s) => hostKeyById.get(s.id) ?? 'unassigned',
    meta: (key) => hostMeta.get(key) ?? { name: key, isCurrent: false },
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/components/topology/__tests__/topologyHostTransform.test.ts`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/environmentTopologySource.ts frontend/src/components/topology/__tests__/topologyHostTransform.test.ts
git commit -m "feat(topology): byHost grouping over host transform maps (SP4)"
```

---

## Task 4: `headerControls` slot on `TopologyCanvas`

**Files:**
- Modify: `frontend/src/components/topology/TopologyCanvas.tsx`

Additive prop; omitting it (systems page) preserves current behavior exactly.

- [ ] **Step 1: Add the prop to the interface**

In `TopologyCanvasProps` (near line 26), add after `emptyMessage?`:

```ts
  headerControls?: React.ReactNode; // rendered inline beside the toolbar; default none
```

- [ ] **Step 2: Destructure it**

In the component signature (near line 38), add `headerControls,` to the destructured props.

- [ ] **Step 3: Render it in the toolbar row**

Replace the existing `<TopologyToolbar … />` block (lines ~255-261) with:

```tsx
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <TopologyToolbar
              components={searchable}
              onSelect={handleSearchSelect}
              availableTypes={availableTypes}
              hiddenTypes={hiddenTypes}
              onToggleType={toggleType}
            />
          </Box>
          {headerControls}
        </Box>
```

- [ ] **Step 4: Type-check and run the topology test suite**

Run: `npx tsc --noEmit`
Expected: PASS.

Run: `npx vitest run src/components/topology`
Expected: PASS (all existing topology tests still green — systems path unchanged).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/TopologyCanvas.tsx
git commit -m "feat(topology): optional headerControls toolbar slot on TopologyCanvas (SP4)"
```

---

## Task 5: Wire the toggle into `EnvironmentTopologyDiagram`

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx`

- [ ] **Step 1: Add imports**

Add to the existing imports:

```tsx
import { ToggleButton, ToggleButtonGroup } from '@mui/material';
import { byEnvSystem, byHost, fromEnvironmentTopologyResponse } from '../../components/topology/environmentTopologySource';
import { buildHostGraph } from '../../components/topology/topologyHostTransform';
```

(Adjust the existing `environmentTopologySource` import line so it also brings in `byHost` rather than duplicating it.)

- [ ] **Step 2: Add `groupBy` state and the host graph**

Inside the component, after the existing `source`/`graph`/`envSystemIds` memos, add:

```tsx
  const [groupBy, setGroupBy] = useState<'system' | 'host'>('system');

  const hostGraph = useMemo(
    () => (source && groupBy === 'host' ? buildHostGraph(source.getGraph()) : null),
    [source, groupBy],
  );
```

- [ ] **Step 3: Make `graph`, `grouping`, and `findDependency` mode-aware**

Replace the existing `graph`, `grouping`, and `findDependency` memos with:

```tsx
  const graph = useMemo(
    () => (groupBy === 'host' ? hostGraph?.graph ?? null : source?.getGraph() ?? null),
    [groupBy, hostGraph, source],
  );

  const grouping = useMemo(
    () =>
      groupBy === 'host'
        ? byHost(hostGraph?.hostKeyById ?? new Map(), hostGraph?.hostMeta ?? new Map())
        : byEnvSystem(source?.getSystemNames() ?? {}, envSystemIds),
    [groupBy, hostGraph, source, envSystemIds],
  );

  const findDependency = useCallback(
    (id: number) => {
      const realId = groupBy === 'host' ? hostGraph?.edgeDepResolver.get(id) ?? null : id;
      if (realId === null) return null;
      return (
        [...(data?.dependencies ?? []), ...(data?.outside_dependencies ?? [])].find(
          (d) => d.id === realId,
        ) ?? null
      );
    },
    [groupBy, hostGraph, data],
  );
```

- [ ] **Step 4: Build the toggle and pass it as `headerControls`**

Before the `return`, add:

```tsx
  const headerControls = (
    <ToggleButtonGroup
      size="small"
      exclusive
      value={groupBy}
      onChange={(_e, value: 'system' | 'host' | null) => value && setGroupBy(value)}
      aria-label="Group topology by"
    >
      <ToggleButton value="system">System</ToggleButton>
      <ToggleButton value="host">Host</ToggleButton>
    </ToggleButtonGroup>
  );
```

Then add `headerControls={headerControls}` to the `<TopologyCanvas … />` props.

- [ ] **Step 5: Type-check and build**

Run: `npx tsc --noEmit`
Expected: PASS.

Run: `npx vitest run src/components/topology`
Expected: PASS (no regressions).

Run: `npx vitest run` (full suite, excluding e2e per project convention)
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx
git commit -m "feat(topology): group-by-system/host toggle on environment diagram (SP4)"
```

---

## Task 6: Manual verification (human eyeball)

> Browser automation is flaky in this project (see the automation-flakiness note) — this is a human check, not an automated one. If you are an agent, hand this checklist to the user.

**Files:** none (verification only).

- [ ] **Step 1: Start the app and open an environment with host assignments**

Ensure an environment has subsystems assigned to infrastructure components (hosts), ideally one subsystem on 2+ hosts. Navigate to `Environments → <env> → Topology`.

- [ ] **Step 2: Verify system mode (default)**

The toggle shows **System** selected; the diagram matches the SP3 view (systems as group boxes, ELK layout, focus/search/filter/collapse all work).

- [ ] **Step 3: Flip to Host and verify grouping**

Click **Host**. Subsystems regroup under host boxes labelled by host name. A multi-host subsystem appears under **each** of its hosts. An in-env subsystem with no host appears under **Unassigned**; cross-environment (outside) subsystems appear under **External**.

- [ ] **Step 4: Verify fan-out edges, collapse, and detail pane**

Fanned-out dependency edges render between host groups. Collapsing a host box aggregates its edges (`N×`); expanding restores them. Clicking a single (non-aggregated) fanned-out edge opens the **correct** dependency in the detail pane. Verify an edge **between two components inside the same host box** still opens on click (the inherited `pointer-events` group-node fix).

- [ ] **Step 5: Flip back to System**

Returns to the SP3 view; focus/filter/collapse reset cleanly.

- [ ] **Step 6 (only if Step 3–5 show stale React Flow state across flips):** Add `key={groupBy}` to the `<TopologyCanvas … />` element in `EnvironmentTopologyDiagram.tsx` to force a clean remount on mode change, then re-verify and commit:

```bash
git add frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx
git commit -m "fix(topology): remount canvas on group-by mode change (SP4)"
```

---

## Self-Review Notes

- **Spec coverage:** types threading (Task 1) ✓; `buildHostGraph` with per-host duplication, Unassigned + External buckets, cartesian fan-out, closure maps (Task 2) ✓; `byHost` grouping + collapse aggregation (Task 3) ✓; `headerControls` toolbar slot (Task 4) ✓; wrapper toggle + mode-aware graph/grouping/findDependency (Task 5) ✓; manual eyeball incl. risks (Task 6) ✓. Backend explicitly out of scope (SP2 shipped it).
- **Type consistency:** `HostGraph`/`HostGroupMeta`, `hostKeyById`/`hostMeta`/`edgeDepResolver`, and `byHost(hostKeyById, hostMeta)` signatures match across Tasks 2, 3, and 5. `findDependency` receives the model edge id (`parseInt(edge.id)` in `TopologyCanvas.handleEdgeClick`), which in host mode is the synthetic edge id resolved via `edgeDepResolver` — consistent with the transform's output.
- **No backend/migration work** — this plan is entirely under `frontend/`.
