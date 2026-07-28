# Group-by-System / Group-by-Host Toggle (Sub-Project 4)

**Date:** 2026-07-27
**Status:** Design approved, ready for implementation plan
**Programme:** Environment topology parity with systems topology + group-by-system/host
**Base branch:** `main` (SP1–SP3 all merged; `main` tip `e456aca`)

## Context

The environment topology diagram (`Environments → <env> → Topology`) now runs on the
shared `<TopologyCanvas>` engine with ELK layout, focus/search, filter, and
collapse/expand (SP1–SP3, PRs #9 + #10). Subsystems are grouped **by owning system**
via the `byEnvSystem(...)` grouping.

SP2 added host assignments to the environment topology API: each in-environment
subsystem node carries `hosts: [{ infrastructure_component_id, name, component_type,
role }]` (a subsystem can span multiple hosts via the `EnvironmentSubSystemHost`
many-to-many junction); outside/external subsystems carry `hosts: []`.

SP4 is the final sub-project: add a **Group by: System / Host** toggle to the
environment diagram. In host mode, subsystems are grouped by the infrastructure
component (host) they are deployed on instead of by owning system.

This is a **frontend-only** change — the backend already returns everything needed
(SP2). The toggle is **client-side**: the API response is re-grouped in the browser
when the user flips the switch; no refetch.

## Goal

Let a user switch the environment topology between grouping by system (today) and
grouping by host, entirely client-side, reusing the shared engine's layout, focus,
filter, collapse, and detail-pane behavior in both modes.

## Non-Goals

- No systems-page changes — the systems diagram has no hosts and no toggle.
- No backend changes — SP2 already returns host data.
- No "primary host" concept — a multi-host subsystem is shown on **all** its hosts.
- No new node-detail pane for hosts — clicking a node still only focuses it; the
  detail pane remains dependency-only (unchanged from today).
- No persistence of the toggle across sessions/navigation — it is component-local
  state, defaulting to **system** on every mount.

## Key architectural decision: identity via closure maps

The core pipeline (`computeVisibleGraph` → `computeCollapseModel` → ELK →
`elkToReactFlow`) keys everything by a **numeric** subsystem `id` and assumes each
non-aggregated edge's `id` equals `String(dependency.id)` and is unique across the
graph. Host-mode duplication breaks both assumptions:

- A subsystem on N hosts appears N times → needs N distinct node ids.
- A dependency A→B where A is on hosts `[h1, h2]` and B on `[h3]` fans out to
  `A@h1→B@h3` and `A@h2→B@h3` — two edges that would otherwise share the real
  dependency id, colliding on React Flow's edge key.

Rather than widen the core's id types (a wide ripple through model/ELK/visibility),
the **host transform mints its own synthetic numeric ids** for the duplicated nodes
and fanned-out edges, and hands back **closure maps** so the grouping and the detail
pane can resolve synthetic ids to their real meaning. The core model, ELK, and
visibility code are **untouched**. This mirrors SP1's principle: "host-mode
duplication is handled *upstream* as a data transform; the core stays single-group."

## Design

### 1. Thread host data through the frontend types (additive)

Host data currently stops at the backend — the frontend `EnvSubsystemNode` and
`VisibleSubsystem` types do not carry `hosts` (SP2 was backend-only).

**`frontend/src/types/environment.ts`:**

```ts
export interface EnvSubsystemHostRef {
  infrastructure_component_id: number;
  name: string;
  component_type: string;
  role: string | null;
}

export interface EnvSubsystemNode {
  id: number;
  name: string;
  component_type: string;
  technology: string | null;
  system_id: number;
  is_mocked: boolean;
  hosts: EnvSubsystemHostRef[]; // NEW — [] for outside subsystems
}
```

**`frontend/src/components/topology/topologyVisibility.ts`:** add an optional
`hosts?: EnvSubsystemHostRef[]` field to `VisibleSubsystem`. It passes through
`computeVisibleGraph` untouched; the systems source never sets it.
`fromEnvironmentTopologyResponse` already spreads `data.subsystems` into the graph, so
`hosts` flows through automatically once the type carries it.

### 2. `buildHostGraph` — the upstream transform (`topologyHostTransform.ts`, new)

```ts
export interface HostGraph {
  graph: VisibilityInput;                    // synthetic per-host nodes + fanned-out edges
  hostKeyById: Map<number, string>;          // synthetic node id → host group key
  hostMeta: Map<string, { name: string; isCurrent: boolean }>;
  edgeDepResolver: Map<number, number>;      // synthetic edge id → real dependency id
}

export function buildHostGraph(input: VisibilityInput): HostGraph;
```

**Node expansion** (over `input.subsystems` then `input.externalSubsystems`):

- **In-env subsystem with `hosts.length > 0`:** one synthetic `VisibleSubsystem` per
  host. `host_key = String(host.infrastructure_component_id)`;
  `hostMeta[key] = { name: host.name, isCurrent: true }`.
- **In-env subsystem with `hosts` empty/undefined:** one synthetic node in the
  `"unassigned"` bucket. `hostMeta["unassigned"] = { name: "Unassigned", isCurrent: false }`.
- **External subsystem** (from `externalSubsystems`, regardless of `hosts`): one
  synthetic node in the `"external"` bucket.
  `hostMeta["external"] = { name: "External", isCurrent: false }`.

Each synthetic node is a shallow copy of the source subsystem (`name`,
`component_type`, `technology`, `is_mocked` preserved for rendering/mock-styling) with
a **freshly minted numeric `id`** from a counter. Build:

- `instancesOf: Map<realSubsystemId, syntheticNode[]>` — every instance a real
  subsystem expanded to (used for edge fan-out).
- `hostKeyById: Map<syntheticId, hostKey>` — for the grouping.

Internal subsystems keep their `subsystems` vs external `externalSubsystems`
placement in the output `VisibilityInput` (so the External bucket is driven by list
membership, not by an empty `hosts` array — an in-env subsystem with no host is
"Unassigned", not "External").

**Edge fan-out** (over `input.dependencies` then `input.externalDependencies`):

- For each real dependency `d`, take `instancesOf[d.from_subsystem_id]` ×
  `instancesOf[d.to_subsystem_id]` (cartesian product). Emit one synthetic
  `VisibleDependency` per pair with a minted numeric `id`, `from_subsystem_id`/
  `to_subsystem_id` set to the synthetic instance ids, and `label`/`dependency_type`/
  `direction` copied from `d`. Record `edgeDepResolver[syntheticEdgeId] = d.id`.
- If either endpoint expanded to zero instances (e.g. a dependency to a
  filtered-away subsystem — should not happen post-`computeVisibleGraph`, but guard),
  the product is empty and the dependency contributes no edges.
- Internal vs external placement follows the source list (so external dependencies
  stay in `externalDependencies`).

Synthetic node ids and synthetic edge ids live in disjoint namespaces (nodes vs
edges) and never mix, so **two independent counters** are fine — node ids need only
be unique among nodes, edge ids unique among edges. Ids are assigned in deterministic
input order, so the transform is pure and testable.

### 3. `byHost(...)` grouping (`environmentTopologySource.ts`, beside `byEnvSystem`)

```ts
export function byHost(
  hostKeyById: Map<number, string>,
  hostMeta: Map<string, { name: string; isCurrent: boolean }>,
): Grouping {
  return {
    keyOf: (s) => hostKeyById.get(s.id) ?? 'unassigned',
    meta: (key) => hostMeta.get(key) ?? { name: key, isCurrent: false },
  };
}
```

The grouping closes over the transform's maps — no `host_key` field on
`VisibleSubsystem`, no core-type change. Cartesian fan-out is **tamed by the existing
collapse-aggregation**: collapsing a host group rolls all its inter-group edges into
`agg:${source}->${target}` edges exactly as collapsing a system does today
(`computeCollapseModel`, unchanged).

### 4. `TopologyCanvas` gains a `headerControls` slot

Add one optional prop:

```ts
interface TopologyCanvasProps {
  // ...existing...
  headerControls?: React.ReactNode; // rendered inline in the toolbar row; default none
}
```

The canvas renders `headerControls` in the toolbar row alongside search/filter (see
current toolbar layout in `TopologyCanvas.tsx`). When omitted (systems page), the
toolbar renders exactly as today — **zero behavior change** for the systems diagram.

### 5. `EnvironmentTopologyDiagram` wrapper wiring

Add component-local `groupBy: 'system' | 'host'` state (default `'system'`) and a MUI
`<ToggleButtonGroup>` ("System" / "Host") passed as `headerControls`. The wrapper
computes `graph`, `grouping`, and `findDependency` per mode:

- **System mode (unchanged):** `graph = source.getGraph()`,
  `grouping = byEnvSystem(systemNames, envSystemIds)`, `findDependency` over
  `data.dependencies` + `data.outside_dependencies` by real dep id.
- **Host mode:** `const hg = buildHostGraph(source.getGraph())` (memoized on `data`);
  `graph = hg.graph`; `grouping = byHost(hg.hostKeyById, hg.hostMeta)`;
  `findDependency = (syntheticEdgeId) => realDep`, resolving via
  `hg.edgeDepResolver` then looking the real dependency up in the same
  `data.dependencies` + `data.outside_dependencies` list.

Both `buildHostGraph` and the two `findDependency` variants are memoized so flipping
the toggle re-runs only the necessary work. Switching modes resets nothing else —
focus/filter/collapse state lives in the canvas keyed by node id; because node ids
differ between modes, a fresh mode starts with an uncollapsed, unfiltered view, which
is the desired behavior. (If React Flow retains stale internal state across the id
change, remount the canvas with a `key={groupBy}` — decide during implementation
based on observed behavior.)

## Files

**Create:**
- `frontend/src/components/topology/topologyHostTransform.ts` — `buildHostGraph`, `HostGraph`
- `frontend/src/components/topology/__tests__/topologyHostTransform.test.ts`

**Modify:**
- `frontend/src/types/environment.ts` — `EnvSubsystemHostRef`, `hosts` on `EnvSubsystemNode`
- `frontend/src/components/topology/topologyVisibility.ts` — optional `hosts?` on `VisibleSubsystem`
- `frontend/src/components/topology/environmentTopologySource.ts` — `byHost(...)` grouping (+ a `byHost` grouping test, either here or in the transform test file)
- `frontend/src/components/topology/TopologyCanvas.tsx` — `headerControls?` prop rendered in the toolbar row
- `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx` — `groupBy` state, `<ToggleButtonGroup>`, host-mode wiring

## Testing

**New `topologyHostTransform.test.ts`:**
- Single-host subsystem → one node, keyed by that host.
- Multi-host subsystem (2 hosts) → two nodes, one per host key; both carry the source
  `name`/`component_type`/`is_mocked`.
- In-env subsystem with `hosts: []` → one node in `"unassigned"`; `hostMeta` label "Unassigned".
- External subsystem → one node in `"external"`; `hostMeta` label "External".
- Cartesian fan-out: dep A(2 hosts)→B(1 host) yields **2** synthetic edges; each
  `edgeDepResolver` entry maps back to the real dep id.
- `byHost` grouping keys synthetic nodes to the right group; a collapsed host group
  aggregates its edges (drive `computeCollapseModel` with `byHost` + a `collapsedGroups`
  set and assert an `agg:` edge results).

**Regression / parity:**
- All existing topology tests pass unchanged (system mode is byte-identical — the
  wrapper's system path and `TopologyCanvas` without `headerControls` are unchanged).
- `tsc --noEmit` clean; full `vitest run --exclude 'e2e/**'` green.

**Manual eyeball** (env Topology tab, on `main` after merge — the automation-flakiness
caveat applies, so this is a human check):
- Toggle defaults to System; the diagram matches SP3.
- Flip to Host: subsystems regroup under host boxes; a multi-host subsystem appears
  under each of its hosts; "Unassigned" and "External" buckets appear when applicable.
- Fan-out edges render; collapsing a host box aggregates them; expanding restores.
- Clicking a fanned-out edge opens the correct real dependency in the detail pane.
- Flip back to System: returns to the SP3 view.

## Risks

- **Cartesian edge blow-up.** A dependency between two subsystems each on many hosts
  produces `m × n` edges. Real deployments have few hosts per subsystem, and
  collapse-aggregation tames the dense case, but the seeded large-topology script
  (`seed_large_topology.py`) is worth a glance in host mode during the manual check.
- **Detail-pane resolution in host mode.** The synthetic edge id must resolve through
  `edgeDepResolver` before the real-dep lookup — a wrong wiring shows the wrong (or
  no) dependency. Covered by the resolver test and the manual edge-click check.
- **Stale React Flow state across mode flips.** Node ids differ between modes; if RF
  retains internal selection/viewport oddly, a `key={groupBy}` remount on the canvas
  is the fallback (noted in §5).
- **Group-node click interception (SP-wide gotcha).** Any group node covering an area
  intercepts clicks on edges beneath it unless its wrapper is `pointer-events:none`
  with interactive children re-enabling `auto`. Host groups reuse the same
  `systemGroupNode`/`elkToReactFlow` path already fixed on `main` (commit `043b7be`),
  so this is inherited, not re-introduced — but re-verify intra-host-group edge clicks
  in the manual pass.
