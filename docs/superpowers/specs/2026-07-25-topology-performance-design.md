# Topology Diagram — Sub-Project 3: Performance

**Date:** 2026-07-25
**Status:** Design approved, ready for implementation plan
**Programme:** System topology diagram scalability/readability (sub-projects 1 & 2 shipped, PRs #3–#8)

## Goal

Make the system topology diagram (`Systems → <system> → Topology` tab) usable at a
few hundred densely-linked components without freezing the UI, and **architect the
data boundary so scaling to ~1000 components later does not force a rewrite** once
there are live users.

- **Deliver for:** ~300 components / ~600 dependencies across ~6–8 systems.
- **Architect for:** ~1000 components (LOD-readiness seam only; no backend change now).

## Non-Goals

- Backend pagination or level-of-detail (LOD) endpoints — **out of scope**; increment 4
  only prepares a seam so this can be added later without touching the render pipeline.
- Automated CI performance-gate tests — rejected as environment-sensitive/flaky.
  Measurement is dev instrumentation + a manual protocol (below).
- Any change to topology *features* (focus/search, filter, collapse/expand) — this
  sub-project is purely performance.

## Current State (baseline architecture)

Pipeline (all client-side, ELK on the **main thread**):

```
fetchTopology (Redux)
  → computeVisibleGraph(hiddenTypes)      topologyVisibility.ts
  → computeCollapseModel(collapsedSystems) topologyModel.ts
  → buildElkGraph(model)                   topologyElkGraph.ts
  → elk.layout()   ← elk.bundled.js, MAIN THREAD (blocks UI)
  → elkToReactFlow(result, model, ctx)     topologyElkGraph.ts
  → <ReactFlow>                            SystemTopologyDiagram.tsx
```

Confirmed performance gaps:

- **ELK runs on the main thread** (`import ELK from 'elkjs/lib/elk.bundled.js'`).
  `elk-worker.min.js` ships in the package but is unused. Layout of hundreds of nodes
  blocks the UI thread.
- **No `React.memo`** on `SubsystemNode`, `SystemGroupNode`, `CollapsedSystemNode` —
  every diagram render re-renders all nodes.
- **No viewport culling** — `onlyRenderVisibleElements` is not set on `<ReactFlow>`.
- **No zoom clamps** — default `minZoom`/`maxZoom`.
- Backend `GET /systems/{id}/topology` returns everything unpaginated (acceptable at
  300; the LOD seam in increment 4 prepares for the day it isn't).

## Approach

Profile-first, then layered increments (matches sub-projects 1/2 workflow): seed +
instrumentation land first so every later increment is measured against a real
baseline. Four increments, each its own branch → PR → cumulative `main`.

The **pipeline shape is unchanged.** Increment 2 changes only *where* `elk.layout()`
runs; increment 4 changes only *how* `data` enters the pipeline.

| # | Increment | Primary lever | Merge artifact |
|---|-----------|---------------|----------------|
| 1 | Seed + instrumentation | Reproducible worst case + measurement | `seed_large_topology.py`, dev timing hooks, baseline numbers |
| 2 | Worker offload | ELK off main thread | `topologyLayout.ts` worker wrapper |
| 3 | Render wins | `React.memo` + culling + zoom clamps | memo'd nodes, `<ReactFlow>` props |
| 4 | LOD-readiness seam | Future-proof data→model boundary | refactor + documented contract |

---

## Increment 1 — Seed + instrumentation

### Backend seed

`backend/scripts/seed_large_topology.py`, mirroring `scripts/seed_master_admin.py`
conventions: async, reads `DATABASE_URL`/`PYTHONPATH` from env, idempotent (safe to
re-run — clears/reuses its own demo data rather than duplicating).

Creates a multi-system topology in the `demo` tenant:

- **~6–8 systems** with the ~300 components distributed across them, component types
  drawn across the full `COMPONENT_COLORS` palette (realistic mix).
- **~600 dependencies**, split:
  - **intra-system** (dense linking within each system) — the bulk, ~450.
  - **cross-system** (component in system A → component in system B) — ~150, so the
    viewed system shows a rich set of `external_subsystems` + `external_dependencies`
    and `computeCollapseModel`'s edge aggregation gets a real workout.
- One designated **"hub" system** with the most cross-system edges — this is the
  system we benchmark from, so a single topology view stresses both intra-system
  layout *and* external fan-in.
- Parameterized via CLI args: `--systems`, `--components`, `--deps` — so the same
  script scales to ~1000 later without edits.

### Frontend instrumentation

Dev-only (guarded by `import.meta.env.DEV`), logged with a stable prefix (e.g.
`[topo-perf]`) for console filtering:

- `elk.layout()` / `layoutTopology()` wall-clock ms (wrap the call in the diagram effect).
- node / edge counts fed to React Flow.
- render-count per node type (a dev-only `useRef` tick inside each node component).

### Deliverable

Baseline numbers recorded in the **Measurement Log** table below at 300/600, before
any optimization.

---

## Increment 2 — Worker offload

Extract layout into `frontend/src/components/topology/topologyLayout.ts` — a thin
module owning the ELK instance and exposing:

```ts
export function layoutTopology(model: TopologyModel): Promise<{ nodes: Node[]; edges: Edge[] }>
```

Internally it constructs ELK with a Vite-resolved worker:

```ts
new ELK({
  workerFactory: () =>
    new Worker(new URL('elkjs/lib/elk-worker.min.js', import.meta.url), { type: 'module' }),
})
```

- `buildElkGraph` runs to produce the ELK graph; `elk.layout()` runs **in the worker**;
  `elkToReactFlow` runs cheaply on the main thread after geometry returns.
- The diagram effect's `elk.layout(...).then(...)` becomes `layoutTopology(model).then(...)`
  — same Promise shape, same `cancelled` flag, so `SystemTopologyDiagram.tsx` logic
  barely moves.
- **Fallback:** if worker construction/execution fails, fall back to main-thread layout
  so the diagram never hard-breaks. Fallback path is logged (dev) once.

---

## Increment 3 — Render wins

Three cheap, independent changes:

- Wrap `SubsystemNode`, `SystemGroupNode`, `CollapsedSystemNode` in `React.memo`. Their
  `data` objects are rebuilt only inside the `nodes` `useMemo`, so referential stability
  holds except when something actually changed. Verify callback identities
  (`onCollapse`/`onExpand`) stay stable (already `useCallback`'d).
- `onlyRenderVisibleElements` on `<ReactFlow>` — culls off-viewport nodes/edges.
- `minZoom` / `maxZoom` clamps so users can't zoom to a level that renders thousands of
  DOM nodes or loses all context.

---

## Increment 4 — LOD-readiness seam

No behavior change — insurance against a costly rewrite when live users hit ~1000.

Introduce a single typed boundary — a `TopologySource` shape — that today returns the
full graph from Redux, but is written so a future paginated / summary-detail backend
can implement the same interface without touching anything downstream in the pipeline.

- Document the contract in this spec (below) and in a code comment at the seam.
- Describe how 1000-node LOD would plug in: e.g. backend returns collapsed-system
  summaries + on-demand component detail; the source fetches detail lazily on
  expand; `computeVisibleGraph`/`computeCollapseModel` consume the same model shape.

### Contract sketch

```ts
interface TopologySource {
  // Current impl: returns the full graph already in Redux state.
  // Future impl: may return summaries only, fetching component detail on expand.
  getGraph(): VisibleGraphInput;
}
```

The pipeline downstream of `getGraph()` (`computeVisibleGraph` onward) must depend only
on this shape, never on the raw Redux `data` object, so the source can be swapped.

---

## Measurement protocol

Manual, dev instrumentation only (no CI gate). For each increment, on the hub system
of the seeded 300/600 dataset:

1. Hard-reload the Topology tab; record `[topo-perf]` layout ms and node/edge counts.
2. Note first-paint feel and whether the UI froze during layout.
3. Pan and zoom across the full graph; note subjective smoothness and per-node render
   counts from the instrumentation.
4. Record numbers in the log below. Compare against the increment-1 baseline.

### Measurement Log

| Increment | Layout ms | Nodes / Edges | UI froze? | Pan/zoom feel | Notes |
|-----------|-----------|---------------|-----------|---------------|-------|
| 1 baseline | _TBD (captured during impl)_ | | | | |
| 2 worker | | | | | |
| 3 render wins | | | | | |
| 4 seam | | | | | (expect no change) |

> The _TBD_ cells are filled with live numbers during implementation — they are the
> deliverable of each increment, not a spec gap.

## Testing strategy

- **Unit tests** per increment following the existing `__tests__/` pattern:
  - Increment 2: `topologyLayout` returns the same node/edge structure as the current
    inline path for a known model (worker mocked); fallback path is exercised.
  - Increment 3: node components memoize (re-render only on relevant `data` change).
  - Increment 4: `TopologySource` returns the expected `VisibleGraphInput` shape; the
    pipeline produces identical output through the seam.
- **Manual browser walkthrough** on the seeded dataset per the measurement protocol.
  (Note: browser automation has been flaky — see the automation-flakiness reference;
  fall back to asking the user to eyeball if synthetic clicks stall.)

## Risks

- **Vite worker resolution** (`new URL(..., import.meta.url)`) can behave differently
  in dev vs. build — verify both; the main-thread fallback covers hard failures.
- **`React.memo` false stability** — if any `data` field is a freshly-built object each
  render, memo won't help. Confirm with the render-count instrumentation from
  increment 1.
- **Seed idempotency** — re-running must not duplicate; scope all created rows to a
  recognizable demo system name and clear them first.
