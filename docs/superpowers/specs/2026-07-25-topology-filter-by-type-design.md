# Topology Readability 2b-i — Filter by Component Type — Design

**Date:** 2026-07-25
**Status:** Approved (design), pending spec review
**Scope:** Frontend-only. Add a **filter by component type** control to the system topology diagram: hide components of unchecked types (and their edges), recompute a visible subset of the graph, and re-run the existing ELK layout. No backend/API change.

> Sub-project 2 (readability), increment **2b-i of 2b**:
> - **2b-i (this spec)** — Filter by component type. Establishes the `computeVisibleGraph` (visible-subset → ELK) pipeline.
> - **2b-ii (later)** — Collapse/expand systems. Extends `computeVisibleGraph` with system collapse + edge aggregation.
>
> Prior increments shipped: 1 (ELK layout), 2a (focus + search). This builds on the 2a toolbar (`TopologyToolbar.tsx`) and the ELK pipeline (`topologyElkGraph.ts`, `SystemTopologyDiagram.tsx`).

---

## Problem

At hundreds of components a topology is unreadable even with good layout. Focus mode (2a) isolates *one* component's neighbourhood, but there is no way to reduce the graph to just the *kinds* of components you care about (e.g. "show only the databases and gateways"). Filtering by component type is the primary lever for cutting node count.

## Goal

A toolbar control to hide/show components by `component_type`. Hidden types' components and any dependency touching them are removed from the graph, which then re-lays out via ELK. Unlike focus mode (which dims), filtering **removes** nodes — that is the scale win.

Non-goals (deferred): collapse/expand systems (2b-ii); dependency-type filtering (out of scope — component type only); performance hardening (sub-project 3); persisting filter state across navigation.

---

## Architecture

### Pure helper — `frontend/src/components/topology/topologyVisibility.ts`

```ts
import type { SubSystemResponse } from '../../types/system';
import type { ComponentDependencyResponse } from '../../types/dependency';

export interface VisibilityInput {
  subsystems: SubSystemResponse[];
  dependencies: ComponentDependencyResponse[];
  externalSubsystems: SubSystemResponse[];
  externalDependencies: ComponentDependencyResponse[];
}

export interface VisibilityOptions {
  hiddenTypes: Set<string>; // component_type values to hide
}

/** The graph after applying visibility options, same shape as the input. */
export function computeVisibleGraph(
  input: VisibilityInput,
  options: VisibilityOptions
): VisibilityInput;

/** Distinct component_type values across all (internal + external) subsystems, sorted. */
export function availableComponentTypes(input: VisibilityInput): string[];
```

- `computeVisibleGraph`:
  - Keep a subsystem iff `!hiddenTypes.has(s.component_type)`. Apply to both `subsystems` and `externalSubsystems`.
  - Build the set of surviving subsystem ids. Keep a dependency iff **both** its `from_subsystem_id` and `to_subsystem_id` are in the surviving set. Apply to both `dependencies` and `externalDependencies`.
  - Return the four filtered arrays. A system whose components are all hidden contributes no subsystems, so `buildElkGraph` (which groups by surviving subsystems) produces no container for it — empty systems vanish automatically, no special-casing.
  - `hiddenTypes` empty → returns arrays equal in content to the input (a pure filter pass).
- `availableComponentTypes`: collect `component_type` from `[...subsystems, ...externalSubsystems]`, dedupe, sort ascending.

This helper is the seam 2b-ii will extend (adding collapse options); keep `VisibilityOptions` an object so new options are additive.

### Diagram wiring — `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- Add `const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())`.
- In the ELK `useEffect`, replace the direct reads of `data.subsystems`/`data.dependencies`/`data.external_subsystems`/`data.external_dependencies` with the output of `computeVisibleGraph({ subsystems: data.subsystems, dependencies: data.dependencies, externalSubsystems: data.external_subsystems ?? [], externalDependencies: data.external_dependencies ?? [] }, { hiddenTypes })`. Feed the visible arrays into `buildElkGraph` and into the `subsystems`/`dependencies` context maps for `elkToReactFlow`. Add `hiddenTypes` to the effect's dependency array so a filter toggle re-lays out.
- `availableTypes = useMemo(() => availableComponentTypes({ subsystems, dependencies, externalSubsystems, externalDependencies }), [data])` — from the **full** data (so a hidden type still appears in the menu to be re-enabled).
- `searchable` (from 2a) is rebuilt from the **visible** subsystems only, so search reflects the current filter. Compute the visible subsystem list once (reuse the `computeVisibleGraph` result or recompute a visible id set) and filter `searchable` to those ids.
- **Focus interplay:** when `hiddenTypes` changes such that the focused component is no longer visible, clear focus. Implement as an effect: `useEffect(() => { if (focusedId && visibleIds && !visibleIds.has(focusedId)) setFocusedId(null); }, [hiddenTypes, ...])` where `visibleIds` is the set of surviving subsystem id strings. (Keep it simple and correct — clear only when the focused node actually left the visible set.)
- **Toggle handler:** `const toggleType = useCallback((t: string) => setHiddenTypes((prev) => { const next = new Set(prev); next.has(t) ? next.delete(t) : next.add(t); return next; }), [])`.

### Toolbar UI — `frontend/src/components/topology/TopologyToolbar.tsx`

Extend the existing toolbar (currently just the search field). New props:

```ts
interface Props {
  components: SearchableComponent[];
  onSelect: (componentId: number) => void;
  availableTypes: string[];
  hiddenTypes: Set<string>;
  onToggleType: (type: string) => void;
}
```

- Lay the toolbar row as: the search `TextField` (flex-grow) + a **"Types" button** on the right that opens an MUI `Menu` of checkbox rows, one per `availableTypes` value (label = `type.replace(/_/g, ' ')`), checked when **not** in `hiddenTypes`. Toggling a row calls `onToggleType(type)`.
- The button shows the hidden count when any are hidden: label `Types` with a small count/badge like `Types · 2 hidden` (or a `Chip`), so the filtered state is visible at a glance. When nothing is hidden, just `Types`.
- Use a filter icon (`FilterListIcon`) on the button for affordance.
- If `availableTypes` is empty (no data), the button may be omitted or disabled — render nothing for the menu.
- The search typeahead behaviour from 2a is unchanged.

---

## Interaction summary

| Action | Result |
|---|---|
| Open "Types" menu, uncheck "database" | All database components and every edge touching one disappear; the diagram re-lays out. System boxes with no remaining components vanish. |
| Re-check "database" | Those components/edges reappear; re-layout. |
| Search while filtered | Typeahead lists only currently-visible components. |
| Focus a component, then hide its type | Focus clears (the node is gone). |
| Hide a type, then click a still-visible component | Focus mode works normally on the visible subset. |

---

## Testing

### Unit (Vitest) — `topologyVisibility.ts`
`computeVisibleGraph`:
- Hiding a type removes its components from both `subsystems` and `externalSubsystems`.
- Removes any dependency with either endpoint hidden (from both `dependencies` and `externalDependencies`); keeps deps whose both endpoints survive.
- Empty `hiddenTypes` returns all input components/deps unchanged (by content).
- A system whose only components are all hidden contributes zero surviving subsystems (verified by asserting none of its ids remain).

`availableComponentTypes`:
- Returns distinct types across internal + external subsystems, sorted; no duplicates.

### Manual / live verification (Customer topology)
- Open "Types", uncheck **database** → "Customer database" and the `api_call` edge from Customer API Server disappear; layout reflows. Button shows "1 hidden".
- Re-check database → it returns.
- Uncheck **api_gateway** and **web_service** → confirm the appropriate components vanish and any system left empty disappears.
- With database hidden, type "database" in search → no result. Focus "Customer API Server", then hide **api_gateway** → focus clears.
- No console errors; re-layout is smooth (loading spinner only on first layout, per the ELK async design).

---

## Risks & Mitigations
- **Re-layout churn:** every filter toggle re-runs ELK. Acceptable — filtering is deliberate and infrequent, and ELK is fast at these sizes; heavy-scale perf is sub-project 3. The existing loading-spinner-only-on-first-layout behaviour means toggles won't flash a spinner over an existing diagram.
- **Focus/search staleness:** handled explicitly (clear focus when focused node filtered out; search scoped to visible).
- **`Set` identity in effect deps:** `hiddenTypes` is replaced with a new `Set` on every toggle (the handler returns a new set), so referential-equality dep checks fire correctly; never mutate the existing set in place.
- **Menu at scale:** if a tenant has many component types the menu is a simple scrollable list — acceptable; the fixed enum of component types is small in practice.
