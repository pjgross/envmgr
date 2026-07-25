# Topology Readability 2a — Focus Mode + Search — Design

**Date:** 2026-07-25
**Status:** Approved (design), pending spec review
**Scope:** Frontend-only. Add **focus mode** (click a component → highlight it + its direct neighbours, dim the rest) and **search/find** (locate a component by name, then focus + centre it) to the system topology diagram. Pure styling + viewport changes over the existing ELK layout — **no re-layout, no graph change**. No backend/API change.

> Sub-project 2 (readability at scale) of the topology programme, increment **2a of 2**:
> - **2a (this spec)** — Focus mode + Search. Pure overlay; no layout change.
> - **2b (later)** — Collapse/expand systems + Filter by type. Changes the visible graph → re-runs ELK.
>
> Prior increments: sub-project 1 (ELK layout) shipped. See `docs/superpowers/specs/2026-07-24-scalable-topology-elk-design.md`.

---

## Problem

The topology diagram now lays out hundreds of densely-linked components correctly (ELK), but with that many nodes on screen it's hard to answer "what is *this* component connected to?" or "where is component X?". There is no way to isolate a component's relationships or jump to one by name.

## Goal

Two readability overlays driven by a single `focusedId` state:
1. **Focus mode** — clicking a component highlights it and its directly-connected components/edges and dims everything else, so its relationships stand out. Instant (restyle only, no layout).
2. **Search** — a toolbar search finds a component by name across all systems; selecting it focuses that component and pans/zooms the viewport to it.

Non-goals (deferred): collapse/expand systems, filter by type (2b); performance hardening — worker offload, viewport culling (sub-project 3); multi-hop focus depth (1 hop only); persisting focus across navigation.

---

## Architecture

A single state value, `focusedId: string | null` (a component node id), owns both features. When null the diagram renders exactly as today. When set:
- `computeFocusSet(focusedId, dependencies)` yields the set of node ids and edge ids to keep bright.
- The nodes/edges arrays passed to React Flow are restyled: anything **not** in the focus set is dimmed (reduced opacity). No `elk.layout()` call — positions are untouched.

Search is a thin producer of `focusedId`: it filters components by name and, on selection, sets `focusedId` and calls `setCenter` on the React Flow instance to bring that node into view.

### Pure helpers — `frontend/src/components/topology/topologyFocus.ts`

```ts
export interface FocusDep {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
}

export interface FocusSet {
  nodeIds: Set<string>; // focused node + direct neighbours (both directions), as String(id)
  edgeIds: Set<string>; // dependency ids (String) incident to the focused node
}

/** Focused component + everything directly linked to/from it, and the incident edges. */
export function computeFocusSet(focusedId: string, dependencies: FocusDep[]): FocusSet;

export interface SearchableComponent {
  id: number;
  name: string;
  systemName: string;
}

/** Case-insensitive substring match on component name; empty/whitespace query → []. */
export function matchComponents(
  query: string,
  components: SearchableComponent[]
): SearchableComponent[];
```

- `computeFocusSet`: seed `nodeIds` with `focusedId`; for each dependency where `String(from) === focusedId` add `String(to)` to `nodeIds` and `String(id)` to `edgeIds`; where `String(to) === focusedId` add `String(from)` and the edge id. A component with no dependencies yields `{ nodeIds: {focusedId}, edgeIds: {} }`.
- `matchComponents`: trim the query; if empty return `[]`; otherwise return components whose `name.toLowerCase().includes(query.toLowerCase())`, preserving input order. (Result-count capping for very large lists is a rendering concern handled in the toolbar, not here.)

### Search toolbar — `frontend/src/components/topology/TopologyToolbar.tsx`

Presentational. Props: `components: SearchableComponent[]`, `onSelect: (componentId: number) => void`. Renders a search `TextField` in a thin strip; as the user types it shows a typeahead list (component name + system name, using display names per the project convention — never `#id`). Selecting an item (click or Enter on the highlighted row) calls `onSelect(id)` and clears/closes the list. Escape closes the list. No Redux; state is local (`query`, open/highlight index). Uses `matchComponents` for filtering; caps the visible list (e.g. first 20) with a "+N more — refine search" hint when truncated so it stays responsive at hundreds of components.

### Diagram wiring — `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- Add `const [focusedId, setFocusedId] = useState<string | null>(null)`.
- Capture the React Flow instance: add `onInit={(inst) => { rfRef.current = inst; }}` where `rfRef = useRef<ReactFlowInstance | null>(null)`.
- **Node click** → focus/toggle: `onNodeClick={(_, node) => setFocusedId((cur) => (cur === node.id ? null : node.id))}`. (Only component nodes are clickable targets in practice; group nodes are `selectable:false` and non-interactive, but guard by ignoring ids starting with `group-`.)
- **Pane click** → clear: `onPaneClick={() => setFocusedId(null)}`.
- **Apply dim styling** in the existing derived `nodes`/`edges` (currently `nodes = layout.nodes` and the `edges` useMemo that applies selection highlight). Extend both to fold in focus:
  - Compute `focusSet = useMemo(() => focusedId ? computeFocusSet(focusedId, allDeps) : null, [focusedId, layout.edges/deps])`. Source dependencies from `data` (internal + external) — the same list used to build the graph.
  - `nodes`: when `focusSet` is set, map `layout.nodes` to add `data: { ...n.data, dimmed: !focusSet.nodeIds.has(n.id) }` for subsystem nodes; for group nodes, `dimmed: true` when none of the group's children are in `focusSet.nodeIds` (keeps a focused component's own system box bright). When `focusSet` is null, pass `layout.nodes` through unchanged (stable reference).
  - `edges`: extend the current selection-highlight map so each edge's `style` combines: base `{ opacity: focusSet && !focusSet.edgeIds.has(e.id) ? 0.12 : 1 }` merged with the selection stroke (`selectedDepId`) when applicable. Selection colour wins on stroke; opacity is independent.
- **Search:** render `<TopologyToolbar components={searchable} onSelect={handleSearchSelect} />` above the React Flow container. Build `searchable` from `data` (all subsystems, with `systemName` from `data.system_names`). `handleSearchSelect(id)`: `setFocusedId(String(id))`, then compute the node's absolute position from `layout.nodes` (subsystem node position is relative to its parent group, so `absX = group.position.x + node.position.x`, same for y) and call `rfRef.current?.setCenter(absX + NODE_WIDTH/2, absY + NODE_HEIGHT/2, { zoom: 1.2, duration: 400 })`. If the node isn't found (shouldn't happen), just set focus.

### Node/edge dimming

- `SubsystemNode` (defined in `SystemTopologyDiagram.tsx`): read `data.dimmed`; when true set the outer `Box` `sx.opacity` to ~`0.25` (transition for smoothness). Bright (default) otherwise.
- `SystemGroupNode`: accept `data.dimmed`; when true reduce opacity of the box/label similarly. (Its `data` currently is `{ label, isCurrent }`; add optional `dimmed?: boolean`.)
- Edges: dimming is applied via `style.opacity` in the diagram's `edges` mapping; `FloatingEdge` already spreads `style` onto `BaseEdge`, so **no `FloatingEdge` change** is needed. (The edge label is rendered separately in `FloatingEdge` via `EdgeLabelRenderer`; dimming the label too is desirable — `FloatingEdge` can read `style?.opacity` and apply it to the label wrapper. This is the only `FloatingEdge` tweak.)

---

## Interaction summary

| Action | Result |
|---|---|
| Click a component | Focus it: highlight it + direct neighbours + incident edges; dim the rest. Click again → clear. |
| Click empty canvas | Clear focus. |
| Click an edge | Unchanged — highlight it + open Link Details pane. Coexists with focus. |
| Type in search | Typeahead list of matching components (name + system). |
| Select a search result | Focus that component and pan/zoom the viewport to it. |

---

## Testing

### Unit (Vitest) — `topologyFocus.ts`
`computeFocusSet`:
- Focused node with outgoing + incoming deps → `nodeIds` contains itself and both neighbours; `edgeIds` contains both incident dependency ids; a non-incident dependency's nodes/edge are excluded.
- Isolated component (no deps) → `nodeIds = {focusedId}`, `edgeIds` empty.
- Both directions counted (a dep pointing *into* the focused node still adds the source neighbour).

`matchComponents`:
- Case-insensitive substring match; empty/whitespace query → `[]`.
- Matches across systems; preserves input order.

### Manual / live verification (Customer topology)
- Click "Customer API Server" → it + Mortgage + Env Manager + database stay bright with their edges; unrelated nodes/edges dim. Click it again (or empty canvas) → all bright again.
- Edge-click still highlights the edge and opens Link Details, with focus active and inactive.
- Search "mort" → shows "Mortage Server (Mortgage)"; selecting it focuses it and centres the view on it.
- Confirm no layout shift/flicker when focusing or clearing (positions unchanged).

---

## Risks & Mitigations
- **Node-click not firing** with `elementsSelectable={false}`: React Flow fires `onNodeClick` independently of selectability; verify in manual testing. If it doesn't, set `nodesFocusable`/`elementsSelectable` appropriately without enabling drag.
- **`setCenter` before instance ready**: guard with `rfRef.current?.` — the toolbar can only be used after the diagram (and `onInit`) has mounted.
- **Absolute-position math for child nodes**: subsystem positions are parent-relative; must add the group origin. Covered explicitly in `handleSearchSelect`.
- **Large typeahead lists**: cap rendered results (first 20 + "refine" hint) so hundreds of components don't render a giant dropdown.
- **Stable references when unfocused**: when `focusedId` is null, pass `layout.nodes` through unchanged to avoid needless React Flow node diffing.
