# Environment Topology on the Shared Engine (Sub-Project 3)

**Date:** 2026-07-25
**Status:** Design approved, ready for implementation plan
**Programme:** Environment topology parity + group-by-system/host (SP3 of 4)

## Context

SP1 extracted a reusable `<TopologyCanvas>` and made grouping pluggable
(`Grouping`); SP2 added per-subsystem host data to the environment topology API.
The **environment** topology diagram (`Environments → <env> → Topology`,
`EnvironmentTopologyDiagram.tsx`) is still the old style: **dagre** layout, its own
inline node, plain edges, and no focus/search/filter/collapse/perf.

This sub-project rebuilds `EnvironmentTopologyDiagram` on top of `<TopologyCanvas>`,
grouped by system — reaching full parity with the systems diagram (ELK layout,
floating edges, focus/search, filter-by-type, collapse/expand, worker-offloaded
layout) while preserving the two environment-specific behaviors:

1. **Mocked subsystems** render distinctly (dashed grey border, grey chip, "mocked"
   caption, dimmed) — driven by `EnvSubsystemNode.is_mocked`.
2. **Outside systems** (systems referenced by cross-environment dependencies but not
   deployed in this env) render as non-current groups labelled
   "{name} — not in environment".

Group-by-host is **not** part of this sub-project (SP4). The `hosts` field SP2 added
is carried in the response but ignored here.

## Goal

`EnvironmentTopologyDiagram` becomes a thin wrapper over `<TopologyCanvas>`, grouped
by system, with mocked-subsystem styling and outside-system framing preserved. Net
effect: the env diagram gains everything the systems diagram has.

## Non-Goals

- No group-by-host / grouping toggle (SP4).
- No backend changes (SP2 already shipped the data).
- No change to the systems diagram's behavior (shared-code changes are additive and
  guarded).

## Design

### 1. Shared colours module (`components/topology/topologyColors.ts`) — new

Promote the duplicated palette out of the page components so systems and environments
share one source:

```ts
export const COMPONENT_COLORS: Record<string, string> = { /* database…other, as today */ };
export const MOCK_COLOR = '#9e9e9e';
export const colorForComponentType = (t: string): string =>
  COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other;
```

`SystemTopologyDiagram` and `SubsystemNode` import from here instead of defining their
own copies (DRY; no behavior change).

### 2. Thread `is_mocked` through the shared pipeline (Approach A)

- `VisibleSubsystem` (`topologyVisibility.ts`) and `RenderSubsystem`
  (`topologyElkGraph.ts`) each gain an optional `is_mocked?: boolean`. Both interfaces
  keep the same field set, so `VisibleSubsystem` remains assignable to
  `RenderSubsystem` (the `TopologyCanvas` builds `Map<number, RenderSubsystem>` from
  visible subsystems).
- `computeVisibleGraph` / `computeCollapseModel` / `elkToReactFlow` are unchanged in
  logic — the flag rides along on the subsystem objects they already pass through.
  `elkToReactFlow` still sets `color: ctx.colorFor(sub.component_type)`; the node
  decides the mocked override.
- `SubsystemNode` renders mocked styling when `data.label.is_mocked`:
  dashed border in `MOCK_COLOR`, grey chip, `bgcolor: rgba(158,158,158,0.06)`, a
  "mocked" caption, and lower opacity (composed with the existing `dimmed` opacity).
  When `is_mocked` is falsy (all systems-diagram nodes), rendering is exactly as today
  — zero systems change.

### 3. Environment topology source (`components/topology/environmentTopologySource.ts`) — new

Mirrors `topologySource.ts` (systems), adapting the env response shape:

```ts
export function fromEnvironmentTopologyResponse(data: EnvironmentTopologyData): TopologySource {
  return {
    getGraph: () => ({
      subsystems: data.subsystems,            // carry is_mocked
      dependencies: data.dependencies,
      externalSubsystems: data.outside_subsystems ?? [],   // outside_* → external*
      externalDependencies: data.outside_dependencies ?? [],
    }),
    getSystemNames: () => data.system_names ?? {},
  };
}

/** Env grouping: in-env systems are "current"; outside systems are labelled and greyed. */
export function byEnvSystem(
  systemNames: Record<string, string>,
  envSystemIds: Set<number>,
): Grouping {
  return {
    keyOf: (s) => String(s.system_id),
    meta: (key) => {
      const inEnv = envSystemIds.has(Number(key));
      const name = systemNames[key] ?? `System ${key}`;
      return { name: inEnv ? name : `${name} — not in environment`, isCurrent: inEnv };
    },
  };
}
```

`envSystemIds` is the set of `system_id`s of the environment's own subsystems
(`data.subsystems`), matching how the current diagram distinguishes in-env vs outside
groups.

### 4. `EnvironmentTopologyDiagram` becomes a thin wrapper

Keeps only env-specific concerns: the `environmentService.getEnvironmentTopology`
fetch (local `data`/`loading`/`error` state — **not** Redux), building the
`TopologySource`, the `graph`, `byEnvSystem(...)` grouping, and `findDependency` over
`data.dependencies` + `data.outside_dependencies`. Renders `<TopologyCanvas>` with the
shared `nodeTypes` (`subsystemNode`/`systemGroupNode`/`collapsedSystemNode`),
`colorForComponentType`, and `emptyMessage`
"No subsystems configured. Add systems with subsystems to see the topology."

```tsx
export default function EnvironmentTopologyDiagram({ envId }: { envId: number }) {
  const [data, setData] = useState<EnvironmentTopologyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    environmentService.getEnvironmentTopology(envId)
      .then((d) => { setData(d); setLoading(false); })
      .catch((e: Error) => { setError(e.message ?? 'Failed to load topology'); setLoading(false); });
  }, [envId]);

  const source = useMemo(() => (data ? fromEnvironmentTopologyResponse(data) : null), [data]);
  const graph = useMemo(() => source?.getGraph() ?? null, [source]);
  const envSystemIds = useMemo(
    () => new Set((data?.subsystems ?? []).map((s) => s.system_id)), [data]);
  const grouping = useMemo(
    () => byEnvSystem(source?.getSystemNames() ?? {}, envSystemIds), [source, envSystemIds]);
  const findDependency = useCallback(
    (id: number) => [...(data?.dependencies ?? []), ...(data?.outside_dependencies ?? [])]
      .find((d) => d.id === id) ?? null, [data]);

  return (
    <TopologyCanvas
      graph={graph} grouping={grouping} loading={loading} error={error}
      colorFor={colorForComponentType} nodeTypes={nodeTypes} findDependency={findDependency}
      emptyMessage="No subsystems configured. Add systems with subsystems to see the topology."
    />
  );
}
```

The old `getLayoutedElements` (dagre), the inline `SubsystemNode`, and the manual
ReactFlow/detail-pane wiring are deleted.

### 5. Frontend type (deferred)

The frontend `EnvSubsystemNode` type is left unchanged in SP3. The `hosts` field that
SP2 added to the API response is not consumed here, so — per YAGNI — the matching
frontend type (and a `hosts` field) is added in SP4 when the group-by-host toggle
actually reads it.

## Data flow

```
env Topology tab
  → environmentService.getEnvironmentTopology(envId)         (local state, not Redux)
  → fromEnvironmentTopologyResponse(data) → TopologySource
  → TopologyCanvas: getGraph() → computeVisibleGraph → computeCollapseModel(byEnvSystem)
      → buildElkGraph → layoutTopology → elkToReactFlow → React Flow
  → SubsystemNode renders mocked styling from is_mocked; group nodes show
    "— not in environment" for outside systems
```

## Testing

- **New `environmentTopologySource.test.ts`:** `fromEnvironmentTopologyResponse` maps
  `outside_*` → `external*`, carries `is_mocked`, defaults missing arrays; `byEnvSystem`
  returns `isCurrent:true`/plain name for in-env systems and
  `isCurrent:false`/"— not in environment" for outside systems.
- **New `subsystemNodeMocked.test.tsx`:** `SubsystemNode` renders the "mocked" caption
  when `data.label.is_mocked` is true and omits it when false/absent (guards the
  systems no-change path).
- **Parity:** existing topology tests (`topologyModel`, `topologyElkGraph`,
  `topologyGrouping`, `nodeMemo`, `topologyLayout`, `topologyVisibility`,
  `TopologyToolbar`, `topologyFocus`, `topologySource`) still pass unchanged;
  `tsc --noEmit` clean; full `vitest run --exclude 'e2e/**'` green.
- **Manual:** open an environment's Topology tab — ELK layout, search-to-center,
  filter-by-type, collapse/expand, edge detail pane, and focus dimming all work;
  mocked subsystems show dashed grey + "mocked"; outside systems show greyed groups
  labelled "— not in environment". (Browser automation has been flaky — eyeball or ask
  the user.)

## Risks

- **`is_mocked` assignability:** `VisibleSubsystem` must stay assignable to
  `RenderSubsystem` after both gain `is_mocked?` — keep the field sets aligned; `tsc`
  catches a mismatch.
- **Grouping identity churn:** `byEnvSystem` must be memoized in the wrapper (stable
  across renders) so the canvas's layout effect doesn't thrash — covered by the
  `useMemo` on `[source, envSystemIds]`.
- **Behavioral drift vs the old diagram:** ELK replaces dagre, so exact positions
  change (expected/desired). The preserved semantics are mocked styling, outside
  framing, edge-click detail, and grouping — verified by tests + manual eyeball.
- **Shared-node change touches the systems path:** mitigated by the `is_mocked` guard
  and the `subsystemNodeMocked` test asserting the false/absent case is unchanged.
