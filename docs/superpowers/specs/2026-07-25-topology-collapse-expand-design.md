# Topology Readability 2b-ii — Collapse / Expand Systems — Design

**Date:** 2026-07-25
**Status:** Approved (design), pending spec review
**Scope:** Frontend-only. Let a user collapse a system in the topology diagram into a single node (name + component count) with its edges **aggregated**, and expand it again. Extends the existing filter/ELK pipeline. No backend/API change.

> Sub-project 2 (readability), final increment **2b-ii of 2b** (2b-i = filter by type, shipped). Prior increments: 1 (ELK layout), 2a (focus + search), 2b-i (filter). This is the last readability lever.

Decisions locked in brainstorming: **any system is collapsible** (including the current one); **all systems expanded by default** (user collapses manually); **trigger = a collapse chevron on an expanded system's box + click a collapsed node to expand**.

---

## Problem

Even with layout, focus, search, and type-filtering, a topology with many *systems* is cluttered — every system's internal components are always shown. There's no way to fold a system you don't currently care about down to a single node while keeping its connections visible.

## Goal

Collapse any system to a single node showing its name and visible-component count; aggregate the edges that crossed its boundary onto that node; expand it back on demand. Compose cleanly with type-filtering (2b-i), focus (2a), and search (2a). When nothing is collapsed, the diagram is byte-for-byte what it is today.

Non-goals (deferred): collapse persisted across navigation; searching *into* a collapsed system; per-underlying-dependency detail for an aggregated edge; performance hardening (sub-project 3).

---

## Architecture

### Pipeline

Today: `data → computeVisibleGraph(filter) → buildElkGraph → ELK → elkToReactFlow → React Flow`.

New: insert a collapse/aggregate step and thread a **model** through build + map:

```
data
  → computeVisibleGraph(data, { hiddenTypes })            // 2b-i, unchanged (type filter)
  → computeCollapseModel(visibleGraph, { collapsedSystems, systemNames, currentSystemId })  // NEW
  → buildElkGraph(model)                                  // rewritten to consume the model
  → elk.layout()
  → elkToReactFlow(result, model, ctx)                    // rewritten to consume the model
  → React Flow
```

`computeVisibleGraph` (2b-i) is untouched. The new `computeCollapseModel` is the only place aggregation lives. `buildElkGraph`/`elkToReactFlow` are reworked to take the model, and **must produce identical output to today when `collapsedSystems` is empty** (regression-safety: the existing ELK/focus/filter tests must stay green).

### The model — `frontend/src/components/topology/topologyModel.ts`

```ts
import type { DependencyDirection } from '../../types/dependency';
import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface ModelSystem {
  systemId: number;
  name: string;
  isCurrent: boolean;
  collapsed: boolean;
  componentCount: number;         // count of VISIBLE components
  components: VisibleSubsystem[];  // visible components; [] when collapsed
}

export interface ModelEdge {
  id: string;              // real dep id (String) when single; `agg:${source}->${target}` when aggregated
  source: string;          // component id (String) or `sys-${systemId}` for a collapsed system
  target: string;
  label: string;
  aggregatedCount: number; // 1 for a single dependency; >1 for an aggregate
  dependencyId: number | null; // the real dependency id when aggregatedCount === 1, else null
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

export function computeCollapseModel(input: VisibilityInput, ctx: CollapseContext): TopologyModel;
```

**`computeCollapseModel` logic:**
1. `allSubs = [...input.subsystems, ...input.externalSubsystems]`; `allDeps = [...input.dependencies, ...input.externalDependencies]`. Build `systemOf: Map<number, number>` (component id → system_id).
2. Group `allSubs` by `system_id`. For each group with ≥1 component, emit a `ModelSystem`: `collapsed = ctx.collapsedSystems.has(systemId)`, `componentCount = group.length`, `components = collapsed ? [] : group`, `name = ctx.systemNames[String(systemId)] ?? \`System ${systemId}\``, `isCurrent = systemId === ctx.currentSystemId`. Groups with 0 components don't occur (input is already type-filtered), so every emitted system has ≥1 component. (A system entirely type-filtered simply isn't in `allSubs`, so it's absent — vanishes, per 2b-i.)
3. **Endpoint resolver:** `displayNode(componentId) = ctx.collapsedSystems.has(systemOf.get(componentId)!) ? \`sys-${systemOf.get(componentId)}\` : String(componentId)`.
4. For each dependency in `allDeps`: `src = displayNode(from)`, `tgt = displayNode(to)`. If `src === tgt` (both endpoints inside the same collapsed system) → **drop**. Else accumulate under the ordered key `\`${src}->${tgt}\``, collecting the underlying dependencies.
5. Build `edges`: for each key group — if it has exactly one dependency `d`: `{ id: String(d.id), source: src, target: tgt, label: d.label ?? d.dependency_type, aggregatedCount: 1, dependencyId: d.id, direction: d.direction }`. If it has N > 1: `{ id: \`agg:${src}->${tgt}\`, source: src, target: tgt, label: \`${N}×\`, aggregatedCount: N, dependencyId: null, direction: 'one_way' }`. (Aggregates render a one-way arrow and a count; two-way distinctions within an aggregate are not preserved — acceptable for v1.)

Pure and fully unit-testable.

### `buildElkGraph(model)` (rewrite)

Consumes `TopologyModel`:
- Each **expanded** `ModelSystem` → an ELK container node `group-${systemId}` (same padding/label options as today) with children = its `components` (leaf nodes `String(component.id)`, `width: NODE_WIDTH, height: NODE_HEIGHT`).
- Each **collapsed** `ModelSystem` → a top-level ELK **leaf** node `sys-${systemId}` sized `COLLAPSED_WIDTH × COLLAPSED_HEIGHT` (a component-sized box).
- Edges = `model.edges` mapped to ELK edges: `{ id: modelEdge.id, sources: [modelEdge.source], targets: [modelEdge.target] }`.
- Root layout options unchanged (`layered`, `RIGHT`, `INCLUDE_CHILDREN`, the tuned spacing).

When `collapsedSystems` is empty, every system is expanded → output is structurally identical to today's `buildElkGraph(visibleGraph)`.

### `elkToReactFlow(result, model, ctx)` (rewrite)

- ELK node id `group-<sysId>` → React Flow `systemGroupNode` (data gains `systemId` + `onCollapse` — see interaction); its ELK children → `subsystemNode`s (unchanged data: `{ label: component, color }`), positioned relative to the group.
- ELK node id `sys-<sysId>` → a new `collapsedSystemNode` (data `{ systemId, name, componentCount, isCurrent, onExpand }`), positioned top-level.
- Edges: map `model.edges` → floating edges `{ id, source, target, type: 'floating', label, markerEnd: ArrowClosed, markerStart when direction==='two_way' && aggregatedCount===1 }`. Group-before-children ordering preserved (group + collapsed leaf nodes first, then component children).
- `ctx` still provides `colorFor` + the component/dependency lookups needed to build `subsystemNode` data; it no longer needs the dependency map for edges (the model already carries edge label/id).

### New node component — `frontend/src/components/topology/CollapsedSystemNode.tsx`

A solid (non-dashed) box, current-system accent when `isCurrent`, showing the system name and `${componentCount} components`, with a subtle expand affordance (e.g. an `UnfoldMoreIcon`). The whole node is clickable → calls `data.onExpand(data.systemId)`. Has hidden source/target handles (like `SubsystemNode`) so floating edges attach.

### Collapse control on `SystemGroupNode`

`SystemGroupNode` (currently `pointerEvents: 'none'`) gains a small **collapse chevron** button in its header label area. The button itself is `pointerEvents: 'auto'` and calls `data.onCollapse(data.systemId)`; the rest of the box stays non-interactive. `data` gains `systemId` and `onCollapse`.

### Diagram wiring — `SystemTopologyDiagram.tsx`

- `const [collapsedSystems, setCollapsedSystems] = useState<Set<number>>(new Set())` (empty = all expanded).
- Replace the `visibleGraph → buildElkGraph` step with: `model = computeCollapseModel(visibleGraph, { collapsedSystems, systemNames, currentSystemId })`, then `buildElkGraph(model)` and `elkToReactFlow(res, model, ctx)`. The ELK effect deps gain `collapsedSystems` (a new Set each toggle → re-layout).
- `collapse(systemId)` = add to the set; `expand(systemId)` = remove. Both passed into node `data` (`onCollapse` on group nodes, `onExpand` on collapsed nodes) via `elkToReactFlow` — the handlers are stable `useCallback`s threaded through `ctx`.
- Reset `collapsedSystems` to empty on system switch (alongside the existing `focusedId`/`selectedDepId` reset).

---

## Interplay (locked in brainstorming)

- **Filter + collapse compose** — both feed the pipeline (filter first, then collapse). A system whose components are all type-filtered is already absent (2b-i); `componentCount` counts only visible components.
- **Focus** stays component-level. If the focused component's system collapses, its node disappears → clear focus (reuse the existing "focused node no longer visible" effect, extended to also fire when a system collapses — i.e. keyed off the model's visible component ids). Clicking a collapsed node **expands**, it does not focus.
- **Search** stays scoped to **visible (expanded, unfiltered) components** — components inside a collapsed system aren't searchable until expanded. `searchable` is built from the model's expanded systems' components.
- **Edge selection / detail** — a single-underlying-dependency edge keeps its real id, so edge-click still opens the Link Details pane exactly as today. An **aggregated** edge (`aggregatedCount > 1`, id `agg:...`) is **not** individually detailed: `handleEdgeClick` ignores ids that aren't a plain integer (guard `Number.isNaN(parseInt(id,10))` or the `agg:` prefix); it shows the `${N}×` label so the user sees the multiplicity.

---

## Testing

### Unit (Vitest)
`computeCollapseModel` (`topologyModel.ts`):
- No collapse → one `ModelSystem` per system, all `collapsed:false`, `components` = all visible, edges 1:1 with dependencies (ids = `String(dep.id)`, `aggregatedCount:1`). (Regression-parity with today.)
- Collapse one system → that system `collapsed:true`, `components:[]`, `componentCount` correct; edges from its components to outside re-pointed to `sys-<id>`.
- Internal edge (both endpoints in the collapsed system) is dropped.
- Two dependencies from different internal components to the same outside node → **one** aggregated edge, `aggregatedCount:2`, id `agg:...`, `dependencyId:null`.
- A single cross-boundary dependency stays non-aggregated (keeps real dep id, `dependencyId` set).

`buildElkGraph(model)`:
- Expanded system → container with component children; collapsed system → a top-level `sys-<id>` leaf (no children); edges use the model edge ids/endpoints. Empty-collapse output matches the pre-existing shape (containers + children).

`elkToReactFlow(result, model, ctx)`:
- `group-` → `systemGroupNode` (+ children); `sys-` → `collapsedSystemNode` with `{ name, componentCount, systemId }`; group/leaf nodes precede component children; aggregated edge → floating edge with the `${N}×` label and no `markerStart`.

### Manual / live verification (Customer topology)
- Collapse an external system (Env Manager) via its box chevron → it becomes one node "Env Manager · 1 component"; its `api_call` edge to Customer API Server re-points to the collapsed node; layout reflows. Click the collapsed node → it expands back.
- Collapse the current system (Customer) → Customer becomes one node; edges from Mortgage/Env Manager aggregate onto it.
- (Seed/confirm an aggregate: two components in one system both linking to a single outside component collapse to one `2×` edge.)
- Filter + collapse together (hide a type, collapse a system) both hold. Focus a component, then collapse its system → focus clears. Edge-click still opens Link Details for a non-aggregated edge; an aggregated edge shows `N×` and opens no pane.
- With nothing collapsed, the diagram is unchanged from today (focus/search/filter all still work).

---

## Files
- **Create** `topologyModel.ts` (`computeCollapseModel` + model types) — pure, unit-tested.
- **Create** `CollapsedSystemNode.tsx` — the collapsed-system node component.
- **Modify** `topologyElkGraph.ts` — `buildElkGraph`/`elkToReactFlow` consume `TopologyModel` (collapsed leaves + expanded containers + model edges); update their tests.
- **Modify** `SystemGroupNode.tsx` — collapse chevron (interactive) + `systemId`/`onCollapse` data.
- **Modify** `SystemTopologyDiagram.tsx` — `collapsedSystems` state, collapse/expand handlers, model pipeline, register `collapsedSystemNode` in `nodeTypes`, reset on system switch, aggregated-edge click guard.

## Risks & Mitigations
- **Regression to the core ELK pipeline:** the biggest risk. Mitigate by keeping the empty-collapse path structurally identical to today and requiring all pre-existing ELK/focus/filter/search tests to stay green; verify live that an un-collapsed diagram is unchanged.
- **Interactive control inside a React Flow node:** the chevron/expand click must not be swallowed by pane/node pan handlers — use `stopPropagation` in the handlers and `pointerEvents:'auto'` only on the control.
- **Aggregated two-way edges:** direction detail is lost in an aggregate (rendered one-way). Accepted for v1; documented.
- **Focus/search into collapsed systems:** deliberately unsupported for v1; expanding restores full focus/search on those components.
