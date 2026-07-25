# Topology Focus Mode + Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add focus mode (click a component → highlight it + its direct neighbours, dim the rest) and a search box (find a component by name → focus + centre it) to the system topology diagram, as pure overlays on the existing ELK layout.

**Architecture:** A single `focusedId` state drives both features. Pure helpers (`computeFocusSet`, `matchComponents`) live in `topologyFocus.ts`. A presentational `TopologyToolbar` provides the search box. `SystemTopologyDiagram.tsx` folds focus dimming into the nodes/edges arrays (no re-layout) and pans to a searched node via a React Flow instance ref.

**Tech Stack:** React 18 + TypeScript strict + React Flow 11.11.4 + MUI + Vitest / React Testing Library.

**Spec:** `docs/superpowers/specs/2026-07-25-topology-focus-search-design.md`

---

## Key facts (verified against current code)

- `SystemTopologyDiagram.tsx` constants: `NODE_WIDTH = 180`, `NODE_HEIGHT = 70` (module scope).
- `SubsystemNode` (in that file, ~line 45) is `function SubsystemNode({ data }: { data: { label: SubSystemResponse; color: string } })`, renders an outer MUI `<Box sx={{ ..., cursor: 'default' }}>` with name/chip/technology and two hidden `<Handle>`s.
- `SystemGroupNode` (`src/components/topology/SystemGroupNode.tsx`) takes `data: { label: string; isCurrent: boolean }`, renders a dashed `<Box>` with `pointerEvents: 'none'`.
- `FloatingEdge` (`src/components/topology/FloatingEdge.tsx`) receives `EdgeProps` incl. `style`, spreads `style` onto `<BaseEdge>`, and renders the label via `<EdgeLabelRenderer>` in a `<div style={{...}}>`.
- The component derives `const nodes = layout.nodes;` (line 171) and an `edges` `useMemo` (lines 172–180) that applies the blue selection highlight for `selectedDepId`.
- Render (lines 202–238): outer `<Box>` (flex row, height 500) → diagram `<Box sx={{ flex:1, minWidth:'60%', position:'relative' }}>` wrapping `<ReactFlow nodes edges nodeTypes edgeTypes fitView fitViewOptions nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} onEdgeClick={handleEdgeClick}>` with `<Background/><Controls/><MiniMap/>`, then a conditional `<DependencyDetailPane>`.
- `data` (redux `state.topology`) shape: `{ subsystems, dependencies, external_subsystems, external_dependencies, system_names }`. `SubSystemResponse` has `{ id, name, system_id, component_type, technology }`. `ComponentDependencyResponse` has `{ id, from_subsystem_id, to_subsystem_id, ... }`.

---

## File Structure

- **Create** `frontend/src/components/topology/topologyFocus.ts` — pure `computeFocusSet` + `matchComponents` (+ `FocusDep`, `FocusSet`, `SearchableComponent` types).
- **Create** `frontend/src/components/topology/__tests__/topologyFocus.test.ts` — unit tests for both.
- **Create** `frontend/src/components/topology/TopologyToolbar.tsx` — presentational search box + typeahead.
- **Create** `frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx` — RTL test.
- **Modify** `frontend/src/components/topology/SystemGroupNode.tsx` — honour a `dimmed` flag.
- **Modify** `frontend/src/components/topology/FloatingEdge.tsx` — dim the label with `style.opacity`.
- **Modify** `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — `focusedId` state, node/pane click, dim styling, toolbar + `setCenter`, `SubsystemNode` dim + pointer cursor.

---

### Task 1: Pure focus/search helpers (`topologyFocus.ts`, TDD)

**Files:**
- Create: `frontend/src/components/topology/topologyFocus.ts`
- Test: `frontend/src/components/topology/__tests__/topologyFocus.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/topology/__tests__/topologyFocus.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  computeFocusSet,
  matchComponents,
  type FocusDep,
  type SearchableComponent,
} from '../topologyFocus';

const deps: FocusDep[] = [
  { id: 8, from_subsystem_id: 5, to_subsystem_id: 6 }, // 5 -> 6
  { id: 1, from_subsystem_id: 1, to_subsystem_id: 5 }, // 1 -> 5
  { id: 9, from_subsystem_id: 19, to_subsystem_id: 5 }, // 19 -> 5
  { id: 3, from_subsystem_id: 100, to_subsystem_id: 200 }, // unrelated
];

describe('computeFocusSet', () => {
  it('includes the focused node, its out- and in-neighbours, and incident edges', () => {
    const f = computeFocusSet('5', deps);
    expect([...f.nodeIds].sort()).toEqual(['1', '19', '5', '6']);
    expect([...f.edgeIds].sort()).toEqual(['1', '8', '9']);
  });

  it('excludes unrelated nodes and edges', () => {
    const f = computeFocusSet('5', deps);
    expect(f.nodeIds.has('100')).toBe(false);
    expect(f.edgeIds.has('3')).toBe(false);
  });

  it('returns just the node itself when it has no dependencies', () => {
    const f = computeFocusSet('42', deps);
    expect([...f.nodeIds]).toEqual(['42']);
    expect(f.edgeIds.size).toBe(0);
  });
});

const comps: SearchableComponent[] = [
  { id: 5, name: 'Customer API Server', systemName: 'Customer' },
  { id: 6, name: 'Customer database', systemName: 'Customer' },
  { id: 1, name: 'Mortage Server', systemName: 'Mortgage' },
];

describe('matchComponents', () => {
  it('matches case-insensitively on name', () => {
    expect(matchComponents('mort', comps).map((c) => c.id)).toEqual([1]);
    expect(matchComponents('CUSTOMER', comps).map((c) => c.id)).toEqual([5, 6]);
  });

  it('returns [] for an empty or whitespace query', () => {
    expect(matchComponents('', comps)).toEqual([]);
    expect(matchComponents('   ', comps)).toEqual([]);
  });

  it('preserves input order', () => {
    expect(matchComponents('server', comps).map((c) => c.id)).toEqual([5, 1]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyFocus.test.ts`
Expected: FAIL — cannot resolve `../topologyFocus`.

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/topology/topologyFocus.ts`:

```ts
export interface FocusDep {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
}

export interface FocusSet {
  nodeIds: Set<string>;
  edgeIds: Set<string>;
}

/** Focused component + everything directly linked to/from it, and the incident edges. */
export function computeFocusSet(focusedId: string, dependencies: FocusDep[]): FocusSet {
  const nodeIds = new Set<string>([focusedId]);
  const edgeIds = new Set<string>();
  for (const d of dependencies) {
    const from = String(d.from_subsystem_id);
    const to = String(d.to_subsystem_id);
    if (from === focusedId) {
      nodeIds.add(to);
      edgeIds.add(String(d.id));
    } else if (to === focusedId) {
      nodeIds.add(from);
      edgeIds.add(String(d.id));
    }
  }
  return { nodeIds, edgeIds };
}

export interface SearchableComponent {
  id: number;
  name: string;
  systemName: string;
}

/** Case-insensitive substring match on component name; empty/whitespace query → []. */
export function matchComponents(
  query: string,
  components: SearchableComponent[]
): SearchableComponent[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return components.filter((c) => c.name.toLowerCase().includes(q));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/topologyFocus.test.ts`
Expected: PASS (6 tests). Then `npx tsc --noEmit` — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/topologyFocus.ts frontend/src/components/topology/__tests__/topologyFocus.test.ts
git commit -m "feat(ui): topology focus-set + component-match helpers"
```

---

### Task 2: Search toolbar (`TopologyToolbar.tsx`, TDD with RTL)

**Files:**
- Create: `frontend/src/components/topology/TopologyToolbar.tsx`
- Test: `frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import TopologyToolbar from '../TopologyToolbar';
import type { SearchableComponent } from '../topologyFocus';

const comps: SearchableComponent[] = [
  { id: 5, name: 'Customer API Server', systemName: 'Customer' },
  { id: 1, name: 'Mortage Server', systemName: 'Mortgage' },
];

describe('TopologyToolbar', () => {
  it('shows matching components as the user types and calls onSelect on click', async () => {
    const onSelect = vi.fn();
    render(<TopologyToolbar components={comps} onSelect={onSelect} />);
    await userEvent.type(screen.getByPlaceholderText(/search component/i), 'mort');
    const option = await screen.findByText('Mortage Server');
    expect(screen.queryByText('Customer API Server')).not.toBeInTheDocument();
    await userEvent.click(option);
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('shows no result list for an empty query', () => {
    render(<TopologyToolbar components={comps} onSelect={vi.fn()} />);
    expect(screen.queryByText('Mortage Server')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/TopologyToolbar.test.tsx`
Expected: FAIL — cannot resolve `../TopologyToolbar`.

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/topology/TopologyToolbar.tsx`:

```tsx
import { useMemo, useState } from 'react';
import {
  Box,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  TextField,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import { matchComponents, type SearchableComponent } from './topologyFocus';

const MAX_RESULTS = 20;

interface Props {
  components: SearchableComponent[];
  onSelect: (componentId: number) => void;
}

export default function TopologyToolbar({ components, onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);

  const matches = useMemo(() => matchComponents(query, components), [query, components]);
  const visible = matches.slice(0, MAX_RESULTS);
  const overflow = matches.length - visible.length;

  const choose = (id: number) => {
    onSelect(id);
    setQuery('');
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (!open || visible.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, visible.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(visible[highlight].id);
    }
  };

  return (
    <Box sx={{ position: 'relative', p: 1, borderBottom: 1, borderColor: 'divider' }}>
      <TextField
        size="small"
        fullWidth
        placeholder="Search component…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onFocus={() => query && setOpen(true)}
        onKeyDown={onKeyDown}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
        }}
      />
      {open && visible.length > 0 && (
        <Paper
          sx={{ position: 'absolute', top: '100%', left: 8, right: 8, zIndex: 5, maxHeight: 260, overflow: 'auto' }}
        >
          <List dense disablePadding>
            {visible.map((c, i) => (
              <ListItemButton key={c.id} selected={i === highlight} onClick={() => choose(c.id)}>
                <ListItemText primary={c.name} secondary={c.systemName} />
              </ListItemButton>
            ))}
          </List>
          {overflow > 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', px: 2, py: 0.5 }}>
              +{overflow} more — refine search
            </Typography>
          )}
        </Paper>
      )}
    </Box>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/topology/__tests__/TopologyToolbar.test.tsx`
Expected: PASS (2 tests). Then `npx tsc --noEmit` — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/TopologyToolbar.tsx frontend/src/components/topology/__tests__/TopologyToolbar.test.tsx
git commit -m "feat(ui): topology search toolbar with typeahead"
```

---

### Task 3: Focus mode in the diagram (node/pane click + dimming)

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`
- Modify: `frontend/src/components/topology/SystemGroupNode.tsx`
- Modify: `frontend/src/components/topology/FloatingEdge.tsx`

- [ ] **Step 1: `SubsystemNode` honours `dimmed` + pointer cursor**

In `SystemTopologyDiagram.tsx`, change the `SubsystemNode` signature and its outer `Box` `sx`:

```tsx
function SubsystemNode({
  data,
}: {
  data: { label: SubSystemResponse; color: string; dimmed?: boolean };
}) {
  const s = data.label;
  return (
    <Box
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px solid ${data.color}`,
        borderRadius: 1,
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: 'pointer',
        opacity: data.dimmed ? 0.25 : 1,
        transition: 'opacity 0.2s',
      }}
    >
```

(Leave the rest of `SubsystemNode` — name, chip, technology, handles — unchanged.)

- [ ] **Step 2: `SystemGroupNode` honours `dimmed`**

In `frontend/src/components/topology/SystemGroupNode.tsx`, extend the props type and add opacity. Change:

```tsx
interface SystemGroupNodeProps {
  data: { label: string; isCurrent: boolean };
}
```

to:

```tsx
interface SystemGroupNodeProps {
  data: { label: string; isCurrent: boolean; dimmed?: boolean };
}
```

and on the outermost `<Box sx={{ ... }}>` add `opacity: data.dimmed ? 0.3 : 1, transition: 'opacity 0.2s',` to the `sx`.

- [ ] **Step 3: `FloatingEdge` dims its label with `style.opacity`**

In `frontend/src/components/topology/FloatingEdge.tsx`, the label is rendered inside `<EdgeLabelRenderer>` in a `<div style={{...}}>`. Add `opacity: (style as React.CSSProperties | undefined)?.opacity` to that div's inline style object so the label fades with its edge. (The `BaseEdge` already receives `style` and fades the line; this only adds the same opacity to the label div.) If `style` is already typed as `React.CSSProperties`, use `style?.opacity` directly.

- [ ] **Step 4: Add `focusedId` state, focusSet, and focus-aware nodes/edges**

In `SystemTopologyDiagram.tsx`, add the import at the top (with the other topology imports):

```tsx
import { computeFocusSet } from '../../components/topology/topologyFocus';
```

Add state near the other `useState` calls:

```tsx
  const [focusedId, setFocusedId] = useState<string | null>(null);
```

Replace `const nodes = layout.nodes;` (line ~171) and the existing `edges` `useMemo` (lines ~172–180) with:

```tsx
  const focusSet = useMemo(() => {
    if (!focusedId || !data) return null;
    const deps = [...data.dependencies, ...(data.external_dependencies ?? [])];
    return computeFocusSet(focusedId, deps);
  }, [focusedId, data]);

  const nodes = useMemo(() => {
    if (!focusSet) return layout.nodes;
    const brightGroups = new Set<string>();
    for (const n of layout.nodes) {
      if (n.parentId && focusSet.nodeIds.has(n.id)) brightGroups.add(n.parentId);
    }
    return layout.nodes.map((n) =>
      n.type === 'systemGroupNode'
        ? { ...n, data: { ...n.data, dimmed: !brightGroups.has(n.id) } }
        : { ...n, data: { ...n.data, dimmed: !focusSet.nodeIds.has(n.id) } }
    );
  }, [layout.nodes, focusSet]);

  const edges = useMemo(
    () =>
      layout.edges.map((e) => {
        const dimmed = focusSet ? !focusSet.edgeIds.has(e.id) : false;
        const selected = Number(e.id) === selectedDepId;
        const style: React.CSSProperties = {
          opacity: dimmed ? 0.12 : 1,
          ...(selected ? { stroke: '#1976d2', strokeWidth: 2.5 } : {}),
        };
        return { ...e, style };
      }),
    [layout.edges, selectedDepId, focusSet]
  );
```

- [ ] **Step 5: Add node/pane click handlers**

Add near `handleEdgeClick`:

```tsx
  const handleNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    if (node.id.startsWith('group-')) return; // ignore system boxes
    setFocusedId((cur) => (cur === node.id ? null : node.id));
  }, []);

  const handlePaneClick = useCallback(() => setFocusedId(null), []);
```

Wire them onto `<ReactFlow>` (add these two props alongside `onEdgeClick`):

```tsx
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
```

- [ ] **Step 6: Typecheck + tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/`
Expected: clean typecheck; all tests pass (existing + topologyFocus + TopologyToolbar).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx frontend/src/components/topology/SystemGroupNode.tsx frontend/src/components/topology/FloatingEdge.tsx
git commit -m "feat(ui): focus mode — highlight a component's neighbours, dim the rest"
```

---

### Task 4: Wire the search toolbar + centre-on-select

**Files:**
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

- [ ] **Step 1: Imports and instance ref**

Add imports at the top of `SystemTopologyDiagram.tsx`:

```tsx
import { useRef } from 'react';
import type { ReactFlowInstance } from 'reactflow';
import TopologyToolbar from '../../components/topology/TopologyToolbar';
import { computeFocusSet, type SearchableComponent } from '../../components/topology/topologyFocus';
```

(`useRef` joins the existing `react` import; `computeFocusSet` is already imported from Task 3 — merge `SearchableComponent` into that existing import line rather than duplicating it.)

Add the ref near the other hooks:

```tsx
  const rfRef = useRef<ReactFlowInstance | null>(null);
```

- [ ] **Step 2: Build the searchable list and the select handler**

Add after the `nodes`/`edges` memos:

```tsx
  const searchable = useMemo<SearchableComponent[]>(() => {
    if (!data) return [];
    const names = data.system_names ?? {};
    return [...data.subsystems, ...(data.external_subsystems ?? [])].map((s) => ({
      id: s.id,
      name: s.name,
      systemName: names[String(s.system_id)] ?? `System ${s.system_id}`,
    }));
  }, [data]);

  const handleSearchSelect = useCallback(
    (id: number) => {
      setFocusedId(String(id));
      const node = layout.nodes.find((n) => n.id === String(id));
      if (node?.parentId) {
        const group = layout.nodes.find((n) => n.id === node.parentId);
        const absX = (group?.position.x ?? 0) + node.position.x;
        const absY = (group?.position.y ?? 0) + node.position.y;
        rfRef.current?.setCenter(absX + NODE_WIDTH / 2, absY + NODE_HEIGHT / 2, {
          zoom: 1.2,
          duration: 400,
        });
      }
    },
    [layout.nodes]
  );
```

- [ ] **Step 3: Capture the instance and render the toolbar**

Add `onInit` to `<ReactFlow>`:

```tsx
          onInit={(inst) => {
            rfRef.current = inst;
          }}
```

Restructure the diagram `<Box>` (currently `sx={{ flex: 1, minWidth: '60%', position: 'relative' }}` wrapping `<ReactFlow>`) into a column with the toolbar on top and the canvas below. Replace that diagram `<Box>...</Box>` with:

```tsx
      {/* Diagram column: search toolbar above, canvas below */}
      <Box sx={{ flex: 1, minWidth: '60%', display: 'flex', flexDirection: 'column' }}>
        <TopologyToolbar components={searchable} onSelect={handleSearchSelect} />
        <Box sx={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onEdgeClick={handleEdgeClick}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            onInit={(inst) => {
              rfRef.current = inst;
            }}
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </Box>
      </Box>
```

(The `<ReactFlow>` still needs a sized parent — the inner `<Box sx={{ flex: 1, position: 'relative' }}>` provides it. The outer diagram column and the `<DependencyDetailPane>` sibling are unchanged in their relationship.)

- [ ] **Step 4: Typecheck + tests + build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/ && npm run build`
Expected: clean typecheck; all tests pass; build succeeds. If tsc flags a duplicate `computeFocusSet`/`SearchableComponent` import, merge them into one import line from `../../components/topology/topologyFocus`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "feat(ui): topology search — find a component and centre + focus it"
```

---

### Task 5: Manual verification (live)

**Files:** none (verification only).

- [ ] **Step 1: Run the app**

Start backend (per `CLAUDE.md`) and `cd frontend && npm run dev`. Log in `admin`/`admin123` (tenant `demo`). Open **Systems → Customer → Topology**.

- [ ] **Step 2: Verify focus mode**

- Click "Customer API Server": it, Mortage Server, envManager_Server, and Customer database stay bright with their connecting edges; nothing else here to dim in the small example — confirm the dim style engages by clicking "Customer database" instead (only API Server + the api_call edge stay bright; Mortgage/Env Manager and their edges dim).
- Click the focused node again → all bright. Click empty canvas → all bright.
- Click an edge → Link Details still opens and the edge highlights, both with and without a focus active.
- Confirm **no layout shift** when focusing/clearing.

- [ ] **Step 3: Verify search**

- Type "mort" in the toolbar → "Mortage Server (Mortgage)" appears; click it → view centres on it and it becomes focused (neighbours bright, rest dim). Type a non-match → no list. Press Escape → list closes.

- [ ] **Step 4 (optional): open a PR** — handled by the finishing-a-development-branch step after review.

---

## Self-Review

**Spec coverage:** `focusedId` single-state model (Task 3); `computeFocusSet` + `matchComponents` pure helpers + tests (Task 1); focus dimming of nodes/edges incl. group-node brightness rule and edge opacity composed with selection (Task 3); `SubsystemNode`/`SystemGroupNode`/`FloatingEdge` dim handling (Task 3); node-click focus/toggle + pane-click clear, edge-click unchanged (Task 3); search toolbar above canvas with typeahead + cap (Task 2); `setCenter` via `onInit` ref with parent-relative→absolute math (Task 4); manual verification (Task 5). All spec sections covered.

**Placeholder scan:** none — every code step is complete; opacity/zoom/cap values are concrete.

**Type consistency:** `FocusDep`/`FocusSet`/`SearchableComponent` (Task 1) are consumed unchanged in Tasks 2–4. `computeFocusSet(focusedId: string, deps: FocusDep[])` called in Task 3 with `[...dependencies, ...external]` (each a `ComponentDependencyResponse`, structurally a `FocusDep`). `matchComponents` used inside `TopologyToolbar` (Task 2). `data.dimmed?: boolean` added to `SubsystemNode` (Task 3) and `SystemGroupNode` (Task 3) props, set by the `nodes` memo (Task 3). `NODE_WIDTH`/`NODE_HEIGHT` reused for centring (Task 4). `rfRef: ReactFlowInstance | null` set in `onInit` and read in `handleSearchSelect` (Task 4). Import of `computeFocusSet` is added in Task 3 and extended (not duplicated) in Task 4 — flagged in both tasks.
