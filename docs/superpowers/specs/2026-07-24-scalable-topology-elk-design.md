# Scalable Topology Layout with ELK — Design

**Date:** 2026-07-24
**Status:** Approved (design), pending spec review
**Scope:** Frontend-only. Replace the heuristic topology layout (per-system dagre + side-placement + vertical columns) with an ELK (`elkjs`) hierarchical layout, so a system's topology diagram lays out correctly at hundreds of densely-linked components. No backend/API change.

> This is **sub-project 1 of 3** in the "scale the topology diagram" programme:
> 1. **Scalable layout engine (this spec)** — correct positioning at scale.
> 2. Readability at scale — collapse/expand systems, focus-on-neighbours, search/filter.
> 3. Performance — memoisation, viewport culling, web-worker offload.

---

## Problem

The current topology diagram (`SystemTopologyDiagram.tsx`) positions nodes with a chain of heuristics:
- per-system dagre (internal edges only) for intra-system layout,
- `decideExternalSides` to pick which side each external system goes,
- `positionColumns` to stack same-side external systems vertically.

These heuristics each fixed a specific case but keep breaking as connectivity grows (e.g. two systems linking to one component required the vertical-column fix). They have no general answer for **hundreds of components** or **components linked to many others** (dense many-to-many). Customer examples reportedly have hundreds of components with high fan-in/fan-out.

Additional issues found in the current implementation:
- Layout is recomputed on every `selectedDepId` change (edge selection), not just on data change — wasteful at scale (`SystemTopologyDiagram.tsx` `useMemo` deps `[data, systemId, selectedDepId]`).
- No pagination anywhere; the backend returns all subsystems + dependencies, so the frontend must lay out whatever it receives.

## Goal

Replace the heuristics with a real hierarchical graph-layout engine (ELK) that positions systems (as containers) and their components (as children) considering **all** dependencies at once, producing a correct, crossing-minimised layout for arbitrary connectivity and scale. Preserve the good behaviours we already have (clean system boxes; the Mortgage + Env-Manager fan-into-Customer-API result).

Non-goals for this sub-project (explicitly deferred):
- Orthogonal edge routing via ELK bend points (fast-follow; floating edges are kept).
- Readability interactions: collapse/expand, focus mode, search/filter (sub-project 2).
- Performance hardening: web-worker offload, `onlyRenderVisibleElements`, node memoisation, min/max zoom (sub-project 3).

---

## Approach

### Library

Add **`elkjs`** (Eclipse Layout Kernel, JS port). ELK models a graph as nested containers with children, which maps directly onto systems (containers) and components (children). It provides the `layered` algorithm with hierarchy handling and cross-container edge support — built for large, dense, hierarchical graphs.

`elk.layout(graph)` returns a **Promise**, so layout becomes asynchronous.

### ELK graph model

Build one ELK graph per topology response:

- **Root graph**: `layoutOptions` set the algorithm and global spacing.
- **Container node per system** (`group-<systemId>`): holds `children` = that system's component nodes; carries `layoutOptions` for padding (to leave room for the system label) and node placement.
- **Child node per component** (`<subsystemId>`): fixed `width: NODE_WIDTH`, `height: NODE_HEIGHT`.
- **Edges**: one ELK edge per dependency (internal + external), referencing component node ids by `sources`/`targets`. Cross-system edges are handled by `elk.hierarchyHandling: 'INCLUDE_CHILDREN'`.

Root `layoutOptions` (initial values; tunable during implementation):
```
'elk.algorithm': 'layered'
'elk.direction': 'RIGHT'                       // preserve today's left-to-right flow
'elk.hierarchyHandling': 'INCLUDE_CHILDREN'    // edges between children of different systems
'elk.layered.spacing.nodeNodeBetweenLayers': '80'
'elk.spacing.nodeNode': '40'
'elk.spacing.edgeNode': '20'
```
Container `layoutOptions`:
```
'elk.padding': '[top=36,left=12,bottom=12,right=12]'   // room for the system label (GROUP_LABEL_HEIGHT)
```

### Mapping ELK output → React Flow

ELK returns each node with `x, y, width, height`. Container children coordinates are **relative to their container**, which is exactly what React Flow wants for `parentId` children.

- Each ELK container → RF node `{ id: 'group-<sysId>', type: 'systemGroupNode', position: {x,y}, style: {width,height}, data: {label, isCurrent}, selectable:false, draggable:false }`.
- Each ELK child → RF node `{ id: '<subId>', type: 'subsystemNode', parentId: 'group-<sysId>', position: {x,y} /* relative, from ELK */, data: {label, color} }`.
- Group nodes must appear before their children in the nodes array (React Flow requirement) — preserved.
- Edges map 1:1 from dependencies as today (`type: 'floating'`, `markerEnd`, optional `markerStart` for two-way, `label`). No `sourceHandle`/`targetHandle` (floating edges compute attachment).

### Async data flow

Replace the synchronous `useMemo` layout with:

```
data (redux) --build--> ELK graph --await elk.layout()--> ELK result --map--> RF nodes/edges (state)
```

- A single ELK instance is created once (module-level `new ELK()`), reused across layouts.
- An effect runs when `data` (and `systemId`) changes: build graph → `await elk.layout()` → on resolve, if not stale, `setLaidOut({nodes, edges})`.
- **Stale-result guard**: capture a local `cancelled` flag / request id in the effect; ignore a resolved layout if a newer effect has started (data changed) or the component unmounted.
- **Loading state**: show the existing `CircularProgress` while the first layout for the current data is in flight (reuse the existing loading UI pattern).

### Selection styling separated from layout

Edge selection highlight must **not** trigger relayout. Lay out edges without selection styling; then derive the rendered edges by mapping the laid-out edges and applying the highlight style for `selectedDepId` (cheap, synchronous, memoised on `[laidOutEdges, selectedDepId]`). This fixes the current relayout-on-selection waste.

### Files

- **Create** `frontend/src/components/topology/topologyElkGraph.ts`
  - `buildElkGraph(input): ElkNode` — pure; turns systems/subsystems/dependencies into the ELK graph JSON (containers, children, edges, layout options). Input is a small explicit shape (subsystems, external subsystems, dependencies, external dependencies, systemNames, currentSystemId), not the raw redux type, to keep it testable.
  - `elkToReactFlow(result, ctx): { nodes: Node[]; edges: Edge[] }` — pure; maps a laid-out ELK graph back to React Flow nodes (groups before children, relative child positions) and edges. `ctx` carries per-subsystem data needed for node rendering (component object + colour) and per-dependency data for edges (label, direction, id).
- **Create** `frontend/src/components/topology/__tests__/topologyElkGraph.test.ts` — unit tests for both pure functions (see Testing).
- **Modify** `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — async layout effect + loading + stale guard; separated selection styling; use `buildElkGraph`/`elkToReactFlow`; keep `edgeTypes`/`nodeTypes`, `FloatingEdge`, `DependencyDetailPane`, `onEdgeClick`.
- **Remove** `frontend/src/components/topology/externalSidePlacement.ts` + its test, and `frontend/src/components/topology/topologyColumnLayout.ts` + its test — superseded by ELK. (Also removes the direct `dagre` import from `SystemTopologyDiagram.tsx`; leave the `@dagrejs/dagre` package in `package.json` unless nothing else uses it — verify with a grep before removing the dependency.)
- **Keep** `floatingEdgeGeometry.ts`, `FloatingEdge.tsx`, `SystemGroupNode.tsx`, `DependencyDetailPane.tsx`.

### Dependency

Add `elkjs` to `frontend/package.json` (`npm install elkjs`). Main-thread build for now; web-worker offload is a sub-project-3 concern.

---

## Testing

### Unit (Vitest) — pure functions, no live layout

`buildElkGraph`:
- Produces one container per system and one child per component, nested correctly (children under the right container).
- Emits one edge per dependency (internal + external), with correct source/target ids.
- Sets `hierarchyHandling` and the algorithm/direction options on the root; padding on containers; fixed width/height on children.
- The current-system container is marked (via data) as current.

`elkToReactFlow` (fed a hand-authored ELK result object):
- Returns group nodes before child nodes.
- Child node `position` equals the ELK child `x/y` (relative to parent) and `parentId` is the right container.
- Group node `style.width/height` and `position` come from the ELK container.
- Edges map 1:1 with correct `type: 'floating'`, `markerEnd`, `markerStart` only when two-way, and `label`.

(Note: we do not assert ELK's actual coordinates — that's ELK's job. We assert our graph construction and our result mapping.)

### Manual / live verification

- Customer topology renders with ELK: Mortgage + Env Manager still fan cleanly into Customer API Server (no regression from the heuristic result), API Server → database intact, no links crossing component boxes.
- Edge selection still highlights + opens `DependencyDetailPane`, and does **not** cause a relayout fl/flicker.
- Loading spinner shows briefly then the diagram appears.
- If a denser system can be seeded (many components, high fan-in), confirm it lays out without the heuristic failures (no lines through unrelated boxes; crossings minimised).

---

## Risks & Mitigations

- **Async races**: guard against stale layouts with a per-run cancellation flag; ignore resolved layouts after data change/unmount.
- **ELK option tuning**: initial spacing/padding values are estimates; adjust during implementation against the Customer example until spacing matches or improves on the current look.
- **Group label space**: container padding must reserve `GROUP_LABEL_HEIGHT` at the top so labels don't overlap child nodes; verify visually.
- **`@dagrejs/dagre` removal**: only remove the package if no other file imports it (grep first); otherwise just drop the import from the topology component.
- **Bundle size**: `elkjs` is added; acceptable for the capability. Worker offload deferred to sub-project 3.
