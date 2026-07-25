# Shared Topology Engine + Grouping Generalization (Sub-Project 1)

**Date:** 2026-07-25
**Status:** Design approved, ready for implementation plan
**Programme:** Environment topology parity with systems topology + group-by-system/host

## Context

The systems topology diagram (`Systems → <system> → Topology`) was modernized in the
topology-scalability programme (ELK layout, focus/search, filter-by-type,
collapse/expand, floating edges, worker-offloaded perf — PRs #3–#9). The
**environment** topology diagram (`Environments → <env> → Topology`) is still the
older style: dagre layout, grouped by system, `is_mocked` styling, "outside"
subsystems, no focus/search/filter/collapse/perf.

The goal (full effort) is to bring the environment diagram to full parity with the
systems diagram **and** add a **group-by-system / group-by-host** switch. Host data
already exists in the model: `InfrastructureComponent` (a deploy target) and
`EnvironmentSubSystemHost` (a many-to-many junction; a subsystem can span multiple
hosts), but the environment topology API does not yet return host assignments.

Architecture decision (**Approach A**): extract a **shared topology engine** used by
both pages, and generalize the model's grouping so a subsystem can be grouped by
system today and by host later. The full effort is decomposed into four sub-projects:

1. **Shared topology engine + grouping generalization** ← THIS SPEC
2. Backend: host data in the environment topology API
3. Environment topology on the shared engine (group-by-system parity)
4. Group-by-host toggle (host groups, node duplication + fan-out edges, buckets)

Base branch for all four: `feature/topology-perf` (PR #9, not yet merged).

## Goal (this sub-project)

Refactor the systems topology so its pipeline is reusable and its grouping is
pluggable, **with zero change to the systems diagram's behavior or appearance**. This
proves the shared engine against the existing, tested systems page before any
environment or host work begins.

## Non-Goals

- No environment-page changes (sub-project 3).
- No backend changes (sub-project 2).
- No host grouping or the group toggle (sub-project 4).
- **No multi-group / node-duplication machinery in the core.** The core stays
  single-group (each subsystem → exactly one group key). Host-mode duplication is
  deferred to SP4 and handled *upstream* as a data transform (a multi-host subsystem
  becomes N synthetic per-host nodes, each with a single host group; edges fan out
  among the synthetic ids). The core model never needs to know about duplication.

## Current pipeline (unchanged in shape)

```
data (Redux) → TopologySource.getGraph() → computeVisibleGraph(hiddenTypes)
  → computeCollapseModel(collapsedSystems, systemNames, currentSystemId)   ← grouping hardcoded to system_id
  → buildElkGraph(model) → layoutTopology() → elkToReactFlow() → React Flow
```

`computeCollapseModel` (in `topologyModel.ts`) currently hardcodes:
- `systemOf: Map<compId, systemId>` and `bySystem` grouping of subsystems
- `collapsedSystems: Set<number>`, `systemNames: Record<string,string>`, `currentSystemId`
- output `ModelSystem { systemId, name, isCurrent, collapsed, componentCount, components }`
- node/group ids `group-<sysId>` and `sys-<sysId>` (collapsed)

## Design

### 1. Grouping generalization (`topologyModel.ts`)

Introduce a pluggable grouping abstraction:

```ts
export interface Grouping {
  keyOf(sub: VisibleSubsystem): string;             // which group a subsystem belongs to
  meta(key: string): { name: string; isCurrent: boolean };
}
```

Refactor `computeCollapseModel(input, ctx)`:
- `ctx` becomes `{ collapsedGroups: Set<string>; grouping: Grouping }`
- `ModelSystem` → `ModelGroup { groupId: string; name: string; isCurrent: boolean; collapsed: boolean; componentCount: number; components: VisibleSubsystem[] }`
- `TopologyModel` returns `{ groups: ModelGroup[]; edges: ModelEdge[] }`
- internal `systemOf` → `groupOf: Map<compId, string>` built via `grouping.keyOf`
- `displayNode(componentId)` returns `sys-<groupKey>` when that group is collapsed, else `String(componentId)` — unchanged logic, generic key
- node/group ids become `group-<groupId>` / `sys-<groupId>`
- `ModelEdge` shape is unchanged (aggregation keys are built from display-node ids)

Provide the system grouping as a factory beside `computeCollapseModel`:

```ts
export function bySystem(systemNames: Record<string, string>, currentSystemId: number): Grouping {
  return {
    keyOf: (s) => String(s.system_id),
    meta: (key) => ({
      name: systemNames[key] ?? `System ${key}`,
      isCurrent: Number(key) === currentSystemId,
    }),
  };
}
```

**Parity guarantee:** for the system grouping, `groupId === String(system_id)`, so
node ids (`group-2`, `sys-2`), edge ids/aggregation, and all ELK geometry are
identical to today. `buildElkGraph`/`elkToReactFlow` change only in the field they
read (`model.systems`→`model.groups`, `s.systemId`→`s.groupId`).

Downstream field renames:
- `topologyElkGraph.ts`: iterate `model.groups`; read `g.groupId`; the render-context
  and node `data` carry `groupId` instead of `systemId`
- `SystemGroupNode.tsx` / `CollapsedSystemNode.tsx`: `data.systemId` → `data.groupId`,
  `onCollapse(groupId)` / `onExpand(groupId)` take a string; collapse handlers key a
  `Set<string>`

### 2. `<TopologyCanvas>` (new `components/topology/TopologyCanvas.tsx`)

Owns all orchestration currently inside `SystemTopologyDiagram`:
- **State:** `focusedId`, `hiddenTypes`, `collapsedGroups: Set<string>`, `selectedDepId`, `rfRef`
- **Pipeline:** `computeVisibleGraph(graph, {hiddenTypes})` → `computeCollapseModel(visibleGraph, {collapsedGroups, grouping})` → `layoutTopology(model, ctx)` → `computeFocusSet` dimming
- **UI:** `TopologyToolbar`, `<ReactFlow>` (with `onlyRenderVisibleElements`, `minZoom=0.1`, `maxZoom=2`, `Background/Controls/MiniMap`), and `DependencyDetailPane` inside the flex layout
- **Handlers:** search-to-center, edge-click→select, node-click→focus, pane-click, collapse/expand

Props (the seam):

```ts
interface TopologyCanvasProps {
  graph: VisibilityInput | null;                                    // from the page's TopologySource
  grouping: Grouping;                                               // system today; host later
  loading: boolean;
  error: string | null;
  colorFor: (componentType: string) => string;
  nodeTypes: NodeTypes;                                             // page supplies subsystem/group/collapsed nodes
  findDependency: (id: number) => ComponentDependencyResponse | null; // full dep for the detail pane
  height?: number;                                                  // default 500
  emptyMessage?: string;
}
```

The canvas has no knowledge of "systems" vs "environments" — only a graph, a grouping,
and render config. `search`-result group labels come from `grouping.meta(keyOf(sub)).name`.
The detail pane resolves the selected edge id via `findDependency` (the full dependency
objects live in the page's data, not in the minimal `VisibilityInput`).

### 3. `SystemTopologyDiagram` becomes a thin wrapper

Keeps only system-specific concerns: Redux fetch/clear, building the `TopologySource`
and a `bySystem(...)` grouping, `COMPONENT_COLORS`/`colorFor`, `nodeTypes` + the
`SubsystemNode` component, and `findDependency` over the full dependency list. Renders
`<TopologyCanvas>`.

```tsx
export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { data, loading, error } = useSelector((s: RootState) => s.topology);
  useEffect(() => { dispatch(fetchTopology(systemId)); return () => { dispatch(clearTopology()); }; }, [systemId, dispatch]);

  const source = useMemo(() => (data ? fromTopologyResponse(data) : null), [data]);
  const graph = useMemo(() => source?.getGraph() ?? null, [source]);
  const grouping = useMemo(() => bySystem(source?.getSystemNames() ?? {}, systemId), [source, systemId]);
  const findDependency = useCallback(
    (id: number) => [...(data?.dependencies ?? []), ...(data?.external_dependencies ?? [])].find((d) => d.id === id) ?? null,
    [data],
  );

  return (
    <TopologyCanvas
      graph={graph} grouping={grouping} loading={loading} error={error}
      colorFor={(t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other}
      nodeTypes={nodeTypes} findDependency={findDependency}
      emptyMessage="No subsystems yet. Add subsystems to see the topology diagram."
    />
  );
}
```

`COMPONENT_COLORS`, `nodeTypes`, and `SubsystemNode` stay in the systems page for this
sub-project to limit churn; SP3 promotes to a shared module whatever the env page needs.

## Files

**Create:**
- `frontend/src/components/topology/TopologyCanvas.tsx`
- `frontend/src/components/topology/__tests__/topologyGrouping.test.ts` (pluggability test)

**Modify:**
- `frontend/src/components/topology/topologyModel.ts` — `Grouping`, `bySystem()`, generalized `computeCollapseModel`, `ModelGroup`/`groupId`, `{ groups, edges }`
- `frontend/src/components/topology/topologyElkGraph.ts` — read `model.groups`/`groupId`; node `data.groupId`
- `frontend/src/components/topology/SystemGroupNode.tsx` — `data.groupId`, `onCollapse(string)`
- `frontend/src/components/topology/CollapsedSystemNode.tsx` — `data.groupId`, `onExpand(string)`
- `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — slim to wrapper
- Existing tests referencing the old signatures/fields: `topologyModel.test.ts`, `topologyElkGraph.test.ts` (and any others asserting `systemId`/`collapsedSystems`/`model.systems`)

## Testing

- **Update** `topologyModel.test.ts` for the new signature (pass a `bySystem(...)`
  grouping; `collapsedGroups: Set<string>`; assert `model.groups` + `groupId`). Node/
  group id assertions (`group-2`, `sys-2`) are unchanged because `groupId===String(system_id)`.
- **Update** `topologyElkGraph.test.ts` for `model.groups`/`groupId`.
- **New** `topologyGrouping.test.ts`: run `computeCollapseModel` with a non-system
  grouping (group by `component_type`) and assert components land in the correct groups
  and that a collapsed group aggregates its edges — proves the seam is genuinely
  pluggable without needing host data.
- **Parity:** all existing `elk`/`focus`/`visibility`/`toolbar` tests pass unchanged;
  `tsc --noEmit` clean; full `vitest run --exclude 'e2e/**'` green.
- **Manual:** eyeball the systems Topology tab — layout, focus/search, filter,
  collapse/expand, detail pane behave and look identical to before (no
  `SystemTopologyDiagram` component test exists, so this is the parity backstop).

## Risks

- **Wide rename ripple.** `systemId`→`groupId` and `model.systems`→`model.groups` touch
  several files and tests. Mitigated by the parity guarantee (ids/geometry identical)
  and by doing the rename mechanically with the type-checker as a guide.
- **Canvas extraction hiding a behavioral change.** The orchestration moves wholesale;
  the risk is a subtle dependency-array or memo change. Mitigated by keeping the moved
  logic byte-for-byte where possible and the manual parity eyeball.
- **Over-generalizing for host mode now.** Explicitly avoided — core stays single-group;
  host duplication is an upstream transform in SP4.
