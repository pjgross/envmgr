# Topology Filter by Component Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toolbar "Types" filter to the system topology diagram that hides components of unchecked `component_type` (and their edges), recomputing a visible subset that re-runs through the existing ELK layout.

**Architecture:** A new pure `computeVisibleGraph(input, { hiddenTypes })` filters the topology data to a visible subset; `SystemTopologyDiagram.tsx` derives that subset in a memo, feeds it to the ELK effect (so a filter toggle re-lays out), and scopes search/focus to it. `TopologyToolbar.tsx` gains a "Types" checkbox menu. The helper is the seam that 2b-ii (collapse) will extend.

**Tech Stack:** React 18 + TypeScript strict + React Flow 11.11.4 + elkjs + MUI + Vitest / React Testing Library.

**Spec:** `docs/superpowers/specs/2026-07-25-topology-filter-by-type-design.md`

---

## Key facts (verified against current post-2a code)

- `SystemTopologyDiagram.tsx` imports at top include `computeFocusSet, type SearchableComponent` from `topologyFocus` (line 22) and `TopologyToolbar` (line 23). `useCallback/useEffect/useMemo/useRef/useState` from react (line 1). Constants `NODE_WIDTH`/`NODE_HEIGHT` at module scope; `COMPONENT_COLORS` map too.
- State: `selectedDepId`, `focusedId`, `rfRef` (lines 108-110). An effect at lines 120-123 clears `selectedDepId` + `focusedId` on `[data]` change.
- The ELK effect (lines 137-181) reads `data.subsystems / data.dependencies / data.external_subsystems / data.external_dependencies`, builds the graph + `subsystems`/`dependencies` context maps, runs `elk.layout`, deps `[data, systemId]`.
- `focusSet` memo (183-187) uses `[...data.dependencies, ...(data.external_dependencies ?? [])]`.
- `searchable` memo (216-224) maps `[...data.subsystems, ...(data.external_subsystems ?? [])]` to `SearchableComponent`.
- `TopologyToolbar.tsx` props are `{ components: SearchableComponent[]; onSelect: (id: number) => void }`; it already imports `Box, InputAdornment, List, ListItemButton, ListItemText, Paper, TextField, Typography` from MUI and `SearchIcon`. Root is `<Box sx={{ position: 'relative', p: 1, borderBottom: 1, borderColor: 'divider' }}>` containing a `TextField` and an absolutely-positioned results `Paper`.
- Types: `SubSystemResponse` = `{ id, name, system_id, component_type, technology }`; `ComponentDependencyResponse` has `{ id, from_subsystem_id, to_subsystem_id, ... }`.

---

## File Structure

- **Create** `frontend/src/components/topology/topologyVisibility.ts` — pure `computeVisibleGraph` + `availableComponentTypes` (+ `VisibilityInput`, `VisibilityOptions` types).
- **Create** `frontend/src/components/topology/__tests__/topologyVisibility.test.ts` — unit tests.
- **Modify** `frontend/src/components/topology/TopologyToolbar.tsx` — add the "Types" checkbox menu.
- **Modify** `frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx` — add a filter-menu test.
- **Modify** `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — `hiddenTypes` state, `visibleGraph`/`visibleIds` memos, ELK effect from visible subset, `availableTypes`, search scoped to visible, clear-focus-when-filtered-out, wire toolbar.

---

### Task 1: Pure `computeVisibleGraph` + `availableComponentTypes` (TDD)

**Files:**
- Create: `frontend/src/components/topology/topologyVisibility.ts`
- Test: `frontend/src/components/topology/__tests__/topologyVisibility.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/topology/__tests__/topologyVisibility.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  computeVisibleGraph,
  availableComponentTypes,
  type VisibilityInput,
} from '../topologyVisibility';

const sub = (id: number, systemId: number, type: string) => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: type,
  technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way' as const,
  label: null,
});

// Customer(2): API(5, api_gateway) -> db(6, database). External Mortgage(1, web_service) -> 5.
const input: VisibilityInput = {
  subsystems: [sub(5, 2, 'api_gateway'), sub(6, 2, 'database')],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1, 'web_service')],
  externalDependencies: [dep(1, 1, 5)],
};

describe('computeVisibleGraph', () => {
  it('returns everything when no types are hidden', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set() });
    expect(v.subsystems.map((s) => s.id)).toEqual([5, 6]);
    expect(v.externalSubsystems.map((s) => s.id)).toEqual([1]);
    expect(v.dependencies.map((d) => d.id)).toEqual([8]);
    expect(v.externalDependencies.map((d) => d.id)).toEqual([1]);
  });

  it('hides components of a hidden type', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['database']) });
    expect(v.subsystems.map((s) => s.id)).toEqual([5]); // db (6) gone
    expect(v.externalSubsystems.map((s) => s.id)).toEqual([1]);
  });

  it('drops any dependency whose endpoint was hidden', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['database']) });
    expect(v.dependencies.map((d) => d.id)).toEqual([]); // 8 (5->6) gone because 6 hidden
    expect(v.externalDependencies.map((d) => d.id)).toEqual([1]); // 1 (1->5) stays
  });

  it('keeps external deps only when both endpoints survive', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['api_gateway']) });
    expect(v.subsystems.map((s) => s.id)).toEqual([6]); // api gateway (5) gone
    expect(v.externalDependencies.map((d) => d.id)).toEqual([]); // 1->5 gone because 5 hidden
  });

  it('makes a fully-hidden system contribute no subsystems', () => {
    // Hide web_service → external system 1 (Mortgage) has no surviving components.
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['web_service']) });
    expect(v.externalSubsystems).toEqual([]);
    expect(v.externalDependencies).toEqual([]);
  });
});

describe('availableComponentTypes', () => {
  it('returns distinct types across internal + external, sorted', () => {
    expect(availableComponentTypes(input)).toEqual(['api_gateway', 'database', 'web_service']);
  });

  it('dedupes repeated types', () => {
    const dupes: VisibilityInput = {
      subsystems: [sub(1, 1, 'database'), sub(2, 1, 'database')],
      dependencies: [],
      externalSubsystems: [],
      externalDependencies: [],
    };
    expect(availableComponentTypes(dupes)).toEqual(['database']);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyVisibility.test.ts`
Expected: FAIL — cannot resolve `../topologyVisibility`.

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/topology/topologyVisibility.ts`:

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
  hiddenTypes: Set<string>;
}

/** The graph after applying visibility options (same shape as the input). */
export function computeVisibleGraph(
  input: VisibilityInput,
  options: VisibilityOptions
): VisibilityInput {
  const visible = (s: SubSystemResponse) => !options.hiddenTypes.has(s.component_type);
  const subsystems = input.subsystems.filter(visible);
  const externalSubsystems = input.externalSubsystems.filter(visible);

  const survivingIds = new Set<number>([
    ...subsystems.map((s) => s.id),
    ...externalSubsystems.map((s) => s.id),
  ]);
  const bothSurvive = (d: ComponentDependencyResponse) =>
    survivingIds.has(d.from_subsystem_id) && survivingIds.has(d.to_subsystem_id);

  return {
    subsystems,
    externalSubsystems,
    dependencies: input.dependencies.filter(bothSurvive),
    externalDependencies: input.externalDependencies.filter(bothSurvive),
  };
}

/** Distinct component_type values across all (internal + external) subsystems, sorted. */
export function availableComponentTypes(input: VisibilityInput): string[] {
  const types = new Set<string>();
  for (const s of [...input.subsystems, ...input.externalSubsystems]) types.add(s.component_type);
  return [...types].sort();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyVisibility.test.ts`
Expected: PASS (7 tests). Then `npx tsc --noEmit` — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyVisibility.ts frontend/src/components/topology/__tests__/topologyVisibility.test.ts
git commit -m "feat(ui): computeVisibleGraph + availableComponentTypes helpers"
```

---

### Task 2: "Types" filter menu in the toolbar

**Files:**
- Modify: `frontend/src/components/topology/TopologyToolbar.tsx`
- Test: `frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx`

- [ ] **Step 1: Add the failing test**

Append to `frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx` (inside the existing top-level `describe('TopologyToolbar', ...)` block, after the last test). Also the existing render calls in the OTHER tests will now be missing the three new required props — update the shared `render(<TopologyToolbar .../>)` calls in this file to pass `availableTypes={[]} hiddenTypes={new Set()} onToggleType={() => {}}` so they keep compiling (the new props are required). Add this test:

```tsx
  it('opens the Types menu and toggles a type', async () => {
    const onToggleType = vi.fn();
    render(
      <TopologyToolbar
        components={comps}
        onSelect={vi.fn()}
        availableTypes={['api_gateway', 'database']}
        hiddenTypes={new Set()}
        onToggleType={onToggleType}
      />
    );
    await userEvent.click(screen.getByRole('button', { name: /types/i }));
    const dbRow = await screen.findByText('database');
    await userEvent.click(dbRow);
    expect(onToggleType).toHaveBeenCalledWith('database');
  });
```

(`comps`, `render`, `screen`, `userEvent`, `vi` are already imported/defined at the top of this test file from Task-2-of-2a.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/TopologyToolbar.test.tsx`
Expected: FAIL — TS/prop errors (new props not accepted) and/or no "Types" button.

- [ ] **Step 3: Implement the menu**

In `frontend/src/components/topology/TopologyToolbar.tsx`:

1. Extend the MUI import to add `Button, Checkbox, Menu, MenuItem`:
```tsx
import {
  Box,
  Button,
  Checkbox,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
  TextField,
  Typography,
} from '@mui/material';
```
and add the filter icon import next to `SearchIcon`:
```tsx
import FilterListIcon from '@mui/icons-material/FilterList';
```

2. Extend the `Props` interface:
```tsx
interface Props {
  components: SearchableComponent[];
  onSelect: (componentId: number) => void;
  availableTypes: string[];
  hiddenTypes: Set<string>;
  onToggleType: (type: string) => void;
}
```
and destructure the new props:
```tsx
export default function TopologyToolbar({
  components,
  onSelect,
  availableTypes,
  hiddenTypes,
  onToggleType,
}: Props) {
```

3. Add menu state near the existing `useState` calls:
```tsx
  const [typeAnchor, setTypeAnchor] = useState<null | HTMLElement>(null);
```

4. Change the root `<Box>` to a flex row and add the Types button + menu. Replace the root `<Box sx={{ position: 'relative', p: 1, borderBottom: 1, borderColor: 'divider' }}>` opening tag with:
```tsx
    <Box
      sx={{
        position: 'relative',
        p: 1,
        borderBottom: 1,
        borderColor: 'divider',
        display: 'flex',
        gap: 1,
        alignItems: 'flex-start',
      }}
    >
```
Give the existing `<TextField>` `sx={{ flex: 1 }}` (add the sx prop; keep `fullWidth`). Then, immediately AFTER the closing tag of the results `Paper` block (i.e. after the `{open && visible.length > 0 && ( ... )}` expression, still inside the root Box), add:
```tsx
      {availableTypes.length > 0 && (
        <>
          <Button
            size="small"
            variant="outlined"
            startIcon={<FilterListIcon />}
            onClick={(e) => setTypeAnchor(e.currentTarget)}
            sx={{ flexShrink: 0, whiteSpace: 'nowrap', mt: 0.25 }}
          >
            {hiddenTypes.size > 0 ? `Types · ${hiddenTypes.size} hidden` : 'Types'}
          </Button>
          <Menu anchorEl={typeAnchor} open={Boolean(typeAnchor)} onClose={() => setTypeAnchor(null)}>
            {availableTypes.map((t) => (
              <MenuItem key={t} dense onClick={() => onToggleType(t)}>
                <Checkbox
                  edge="start"
                  size="small"
                  checked={!hiddenTypes.has(t)}
                  tabIndex={-1}
                  disableRipple
                />
                <ListItemText primary={t.replace(/_/g, ' ')} />
              </MenuItem>
            ))}
          </Menu>
        </>
      )}
```
The `MenuItem onClick` toggles but does NOT close the menu, so the user can flip several types; the menu closes on backdrop click (`onClose`).

- [ ] **Step 4: Run test + typecheck**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/TopologyToolbar.test.tsx`
Expected: PASS (all prior tests + the new one). Then `npx tsc --noEmit` — clean (if it complains the other `render(<TopologyToolbar .../>)` calls miss props, ensure Step 1's prop additions were applied to them).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/TopologyToolbar.tsx frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx
git commit -m "feat(ui): topology toolbar Types filter menu"
```

---

### Task 3: Wire filtering into the diagram

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Import the helpers and add filter state**

Add to the topology imports:
```tsx
import { computeVisibleGraph, availableComponentTypes } from '../../components/topology/topologyVisibility';
```
Add state near `focusedId`:
```tsx
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
```

- [ ] **Step 2: Derive the visible graph + visible id set**

Add these memos ABOVE the ELK `useEffect` (after the `selectedDep` memo, before `const [layout, ...]`):
```tsx
  const visibleGraph = useMemo(() => {
    if (!data) return null;
    return computeVisibleGraph(
      {
        subsystems: data.subsystems,
        dependencies: data.dependencies,
        externalSubsystems: data.external_subsystems ?? [],
        externalDependencies: data.external_dependencies ?? [],
      },
      { hiddenTypes }
    );
  }, [data, hiddenTypes]);

  const visibleIds = useMemo(() => {
    if (!visibleGraph) return null;
    return new Set(
      [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems].map((s) => String(s.id))
    );
  }, [visibleGraph]);
```

- [ ] **Step 3: Feed the visible graph into the ELK effect**

Replace the ELK `useEffect` body's graph/context construction so it uses `visibleGraph` instead of `data.*`, and change its dependency array. The new effect:
```tsx
  useEffect(() => {
    if (!visibleGraph || !data) {
      setLayout({ nodes: [], edges: [] });
      return;
    }
    let cancelled = false;
    setLayingOut(true);

    const graph = buildElkGraph(visibleGraph);

    const subsystems = new Map<number, RenderSubsystem>();
    for (const s of [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems]) subsystems.set(s.id, s);
    const dependencies = new Map<number, RenderDependency>();
    for (const d of [...visibleGraph.dependencies, ...visibleGraph.externalDependencies]) dependencies.set(d.id, d);

    const ctx: ElkRenderContext = {
      currentSystemId: systemId,
      systemNames: data.system_names ?? {},
      subsystems,
      dependencies,
      colorFor: (t) => COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other,
    };

    elk
      .layout(graph)
      .then((res) => {
        if (cancelled) return;
        setLayout(elkToReactFlow(res, ctx));
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
  }, [visibleGraph, systemId, data]);
```

- [ ] **Step 4: Scope focusSet + searchable to the visible graph; add availableTypes**

Change the `focusSet` memo to use the visible dependencies:
```tsx
  const focusSet = useMemo(() => {
    if (!focusedId || !visibleGraph) return null;
    const deps = [...visibleGraph.dependencies, ...visibleGraph.externalDependencies];
    return computeFocusSet(focusedId, deps);
  }, [focusedId, visibleGraph]);
```

Change the `searchable` memo to build from the visible subsystems:
```tsx
  const searchable = useMemo<SearchableComponent[]>(() => {
    if (!visibleGraph || !data) return [];
    const names = data.system_names ?? {};
    return [...visibleGraph.subsystems, ...visibleGraph.externalSubsystems].map((s) => ({
      id: s.id,
      name: s.name,
      systemName: names[String(s.system_id)] ?? `System ${s.system_id}`,
    }));
  }, [visibleGraph, data]);
```

Add `availableTypes` (from the FULL data, so hidden types remain toggleable) after `searchable`:
```tsx
  const availableTypes = useMemo(() => {
    if (!data) return [];
    return availableComponentTypes({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.external_subsystems ?? [],
      externalDependencies: data.external_dependencies ?? [],
    });
  }, [data]);

  const toggleType = useCallback((t: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }, []);
```

- [ ] **Step 5: Clear focus when the focused node is filtered out**

Add an effect after the memos:
```tsx
  useEffect(() => {
    if (focusedId && visibleIds && !visibleIds.has(focusedId)) setFocusedId(null);
  }, [focusedId, visibleIds]);
```

- [ ] **Step 6: Pass the filter props to the toolbar**

Find the `<TopologyToolbar components={searchable} onSelect={handleSearchSelect} />` in the render and replace with:
```tsx
        <TopologyToolbar
          components={searchable}
          onSelect={handleSearchSelect}
          availableTypes={availableTypes}
          hiddenTypes={hiddenTypes}
          onToggleType={toggleType}
        />
```

- [ ] **Step 7: Typecheck + tests + build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/ && npm run build`
Expected: clean typecheck; all tests pass; build succeeds. If `data` is flagged unused-in-deps or similar, keep `data` in the ELK effect deps (it is read for `system_names`).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "feat(ui): filter topology by component type (hide + re-layout)"
```

---

### Task 4: Manual verification (live)

**Files:** none (verification only).

- [ ] **Step 1: Run the app**

Start backend (per `CLAUDE.md`) and `cd frontend && npm run dev`. Log in `admin`/`admin123` (tenant `demo`). Open **Systems → Customer → Topology**.

- [ ] **Step 2: Verify filtering**

- Click the **Types** button → a menu lists api_gateway, database, web_service (all checked). Uncheck **database** → "Customer database" and the `api_call` edge from Customer API Server disappear; the diagram re-lays out; the button reads "Types · 1 hidden".
- Re-check **database** → it returns and re-lays out.
- Uncheck **web_service** → "Mortage Server" (and the MORTGAGE box, and the Mortgage→API edge) disappear (a system left with no components vanishes).

- [ ] **Step 3: Verify interplay with search + focus**

- With **database** hidden, type "database" in search → no result.
- Re-show all types. Focus "Customer database" (click it), then hide **database** → focus clears (nothing stays highlighted-bright); everything visible renders normally.

- [ ] **Step 4 (optional): open a PR** — handled by finishing-a-development-branch after review.

---

## Self-Review

**Spec coverage:** `computeVisibleGraph` + `availableComponentTypes` pure helpers + tests (Task 1); Types checkbox menu with hidden-count label (Task 2); `hiddenTypes` state feeding the ELK effect for re-layout, `availableTypes` from full data, search + focusSet scoped to the visible subset, clear-focus-when-filtered-out, toggle handler, toolbar wiring (Task 3); manual verification incl. empty-system-vanishes and search/focus interplay (Task 4). All spec sections covered.

**Placeholder scan:** none — every code step is complete; the menu, filter logic, and effect wiring are fully specified.

**Type consistency:** `VisibilityInput`/`VisibilityOptions` (Task 1) are consumed verbatim in Task 3's `computeVisibleGraph`/`availableComponentTypes` calls. Toolbar `Props` gains `availableTypes: string[]`, `hiddenTypes: Set<string>`, `onToggleType: (type: string) => void` (Task 2), passed exactly by Task 3 Step 6. `hiddenTypes` is always replaced with a new `Set` in `toggleType` (Task 3 Step 4) so the `visibleGraph` memo + ELK effect re-fire on toggle. `visibleGraph` is `VisibilityInput | null`; `buildElkGraph` accepts `VisibilityInput`'s shape (it already takes `{ subsystems, dependencies, externalSubsystems, externalDependencies }`). Test files: Task 1 creates `topologyVisibility.test.ts`; Task 2 extends the existing `TopologyToolbar.test.tsx` and updates its other `render()` calls for the new required props.
