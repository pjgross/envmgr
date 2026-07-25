# Environment Topology on the Shared Engine (SP3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `EnvironmentTopologyDiagram` on the shared `<TopologyCanvas>` (grouped by system), reaching parity with the systems diagram while preserving mocked-subsystem styling and outside-system framing.

**Architecture:** Two tasks. Task 1 adds a shared colours module, threads an optional `is_mocked` flag through the shared pipeline, and teaches the shared `SubsystemNode` to render mocked styling (systems path unchanged, guarded). Task 2 adds an environment `TopologySource` + `byEnvSystem` grouping and rewrites `EnvironmentTopologyDiagram` as a thin wrapper over `<TopologyCanvas>`.

**Tech Stack:** React 18, TypeScript (strict, `noUnusedLocals`), `reactflow` ^11, Vitest + Testing Library.

**Spec:** [docs/superpowers/specs/2026-07-25-topology-env-page-design.md](../specs/2026-07-25-topology-env-page-design.md)

**Base branch:** `feature/topology-env-page` (already checked out, off `feature/topology-env-groundwork`).

**Commands** (run from `frontend/`): typecheck `npx tsc --noEmit`; topology tests `npx vitest run src/components/topology/`; full unit suite `npx vitest run --exclude 'e2e/**'`. If `npx tsc` prints "This is not the tsc command you are looking for", the shell cwd is wrong — re-run with `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit`.

---

## File Structure

**Create:**
- `frontend/src/components/topology/topologyColors.ts` — shared component-type palette + mock colour.
- `frontend/src/components/topology/environmentTopologySource.ts` — env `TopologySource` + `byEnvSystem` grouping.
- `frontend/src/components/topology/__tests__/subsystemNodeMocked.test.tsx` — mocked-rendering test.
- `frontend/src/components/topology/__tests__/environmentTopologySource.test.ts` — mapping + grouping test.

**Modify:**
- `frontend/src/components/topology/topologyVisibility.ts` — `VisibleSubsystem` gains `is_mocked?: boolean`.
- `frontend/src/components/topology/topologyElkGraph.ts` — `RenderSubsystem` gains `is_mocked?: boolean`.
- `frontend/src/components/topology/SubsystemNode.tsx` — retype `data.label` to `RenderSubsystem`; render mocked styling; use shared colours.
- `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — use shared `colorForComponentType` (drop the inline palette).
- `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx` — rewrite as a thin `<TopologyCanvas>` wrapper.

---

## Task 1: Shared colours + mocked-aware SubsystemNode

**Files:** the colours module, `topologyVisibility.ts`, `topologyElkGraph.ts`, `SubsystemNode.tsx`, `SystemTopologyDiagram.tsx`, and the mocked test.

- [ ] **Step 1: Write the failing mocked-rendering test**

Create `frontend/src/components/topology/__tests__/subsystemNodeMocked.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReactFlowProvider } from 'reactflow';
import SubsystemNode from '../SubsystemNode';
import type { RenderSubsystem } from '../topologyElkGraph';

function renderNode(sub: RenderSubsystem) {
  return render(
    <ReactFlowProvider>
      <SubsystemNode data={{ label: sub, color: '#388e3c' }} />
    </ReactFlowProvider>,
  );
}

const base: RenderSubsystem = {
  id: 1, name: 'billing-api', system_id: 2, component_type: 'web_service', technology: null,
};

describe('SubsystemNode mocked styling', () => {
  it('shows a "mocked" caption when the subsystem is mocked', () => {
    renderNode({ ...base, is_mocked: true });
    expect(screen.getByText('mocked')).toBeInTheDocument();
  });

  it('omits the "mocked" caption for a normal subsystem', () => {
    renderNode({ ...base, is_mocked: false });
    expect(screen.queryByText('mocked')).not.toBeInTheDocument();
  });

  it('omits the "mocked" caption when is_mocked is absent (systems path)', () => {
    renderNode(base);
    expect(screen.queryByText('mocked')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npx vitest run src/components/topology/__tests__/subsystemNodeMocked.test.tsx`
Expected: FAIL — no "mocked" text (and `RenderSubsystem` has no `is_mocked`, so a type error may surface too).

- [ ] **Step 3: Create the shared colours module**

Create `frontend/src/components/topology/topologyColors.ts`:

```ts
// Shared component-type palette used by both the systems and environment diagrams.
export const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2', // blue
  cache: '#f57c00', // amber
  message_queue: '#7b1fa2', // purple
  web_service: '#388e3c', // green
  api_gateway: '#00796b', // teal
  worker: '#e64a19', // orange
  frontend: '#303f9f', // indigo
  other: '#616161', // grey
};

/** Colour for a mocked subsystem, regardless of its component type. */
export const MOCK_COLOR = '#9e9e9e';

export const colorForComponentType = (t: string): string =>
  COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other;
```

- [ ] **Step 4: Add `is_mocked?` to the pipeline subsystem shapes**

In `frontend/src/components/topology/topologyVisibility.ts`, add the field to `VisibleSubsystem`:

```ts
export interface VisibleSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
  is_mocked?: boolean;
}
```

In `frontend/src/components/topology/topologyElkGraph.ts`, add the same field to `RenderSubsystem`:

```ts
export interface RenderSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
  is_mocked?: boolean;
}
```

- [ ] **Step 5: Make `SubsystemNode` render mocked styling**

Replace the contents of `frontend/src/components/topology/SubsystemNode.tsx` with:

```tsx
import { memo } from 'react';
import { Box, Chip, Typography } from '@mui/material';
import { Handle, Position } from 'reactflow';
import type { RenderSubsystem } from './topologyElkGraph';
import { MOCK_COLOR } from './topologyColors';
import { useRenderCount } from './topologyPerf';

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 70;

interface SubsystemNodeProps {
  data: { label: RenderSubsystem; color: string; dimmed?: boolean };
}

function SubsystemNode({ data }: SubsystemNodeProps) {
  useRenderCount('SubsystemNode');
  const s = data.label;
  const mocked = s.is_mocked ?? false;
  const color = mocked ? MOCK_COLOR : data.color;
  return (
    <Box
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px ${mocked ? 'dashed' : 'solid'} ${color}`,
        borderRadius: 1,
        bgcolor: mocked ? 'rgba(158,158,158,0.06)' : 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: 'pointer',
        opacity: data.dimmed ? 0.25 : mocked ? 0.75 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {s.technology && (
        <Typography variant="caption" color="text.secondary" noWrap>
          {s.technology}
        </Typography>
      )}
      {mocked && (
        <Typography variant="caption" sx={{ color: MOCK_COLOR, fontSize: '0.6rem' }}>
          mocked
        </Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}

export default memo(SubsystemNode);
```

- [ ] **Step 6: Run the mocked test — expect PASS**

Run: `npx vitest run src/components/topology/__tests__/subsystemNodeMocked.test.tsx`
Expected: PASS (3 passed).

- [ ] **Step 7: DRY the systems page onto the shared palette**

In `frontend/src/pages/systems/SystemTopologyDiagram.tsx`, delete the inline `COMPONENT_COLORS` const and the local `colorFor`, and import the shared helper:

```ts
import { colorForComponentType } from '../../components/topology/topologyColors';
```

Change the `<TopologyCanvas>` prop to `colorFor={colorForComponentType}`. (If any other reference to the removed `COMPONENT_COLORS`/`colorFor` remains, `tsc`/eslint will flag it — update it to `colorForComponentType`.)

- [ ] **Step 8: Typecheck + full topology suite**

Run: `npx tsc --noEmit`
Expected: clean.
Run: `npx vitest run src/components/topology/`
Expected: all pass (mocked test + all existing topology tests, incl. `nodeMemo`).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/topology/topologyColors.ts \
        frontend/src/components/topology/topologyVisibility.ts \
        frontend/src/components/topology/topologyElkGraph.ts \
        frontend/src/components/topology/SubsystemNode.tsx \
        frontend/src/components/topology/__tests__/subsystemNodeMocked.test.tsx \
        frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "feat(topology): mocked-subsystem styling + shared colours module"
```

---

## Task 2: Environment source + rewrite the env diagram as a wrapper

**Files:** `environmentTopologySource.ts` (+ test), `EnvironmentTopologyDiagram.tsx`.

- [ ] **Step 1: Write the failing env-source test**

Create `frontend/src/components/topology/__tests__/environmentTopologySource.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { fromEnvironmentTopologyResponse, byEnvSystem } from '../environmentTopologySource';
import type { EnvironmentTopologyData } from '../../../types/environment';

const data = {
  environment_id: 9,
  subsystems: [
    { id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null, is_mocked: false },
    { id: 6, name: 'db', system_id: 2, component_type: 'database', technology: null, is_mocked: true },
  ],
  dependencies: [
    { id: 8, from_subsystem_id: 5, to_subsystem_id: 6, dependency_type: 'database', direction: 'one_way', label: null },
  ],
  system_names: { '2': 'Customer', '3': 'Mortgage' },
  outside_subsystems: [
    { id: 1, name: 'ext', system_id: 3, component_type: 'other', technology: null, is_mocked: false },
  ],
  outside_dependencies: [
    { id: 10, from_subsystem_id: 5, to_subsystem_id: 1, dependency_type: 'api_call', direction: 'one_way', label: null },
  ],
} as unknown as EnvironmentTopologyData;

describe('fromEnvironmentTopologyResponse', () => {
  it('maps outside_* to external* and carries is_mocked + system names', () => {
    const src = fromEnvironmentTopologyResponse(data);
    const g = src.getGraph();
    expect(g.subsystems.map((s) => s.id)).toEqual([5, 6]);
    expect(g.subsystems.find((s) => s.id === 6)!.is_mocked).toBe(true);
    expect(g.dependencies.map((d) => d.id)).toEqual([8]);
    expect(g.externalSubsystems.map((s) => s.id)).toEqual([1]);
    expect(g.externalDependencies.map((d) => d.id)).toEqual([10]);
    expect(src.getSystemNames()).toEqual({ '2': 'Customer', '3': 'Mortgage' });
  });

  it('defaults missing outside arrays to empty', () => {
    const g = fromEnvironmentTopologyResponse({
      ...data, outside_subsystems: undefined, outside_dependencies: undefined,
    } as unknown as EnvironmentTopologyData).getGraph();
    expect(g.externalSubsystems).toEqual([]);
    expect(g.externalDependencies).toEqual([]);
  });
});

describe('byEnvSystem', () => {
  const grouping = byEnvSystem({ '2': 'Customer', '3': 'Mortgage' }, new Set([2]));

  it('groups by system id', () => {
    expect(grouping.keyOf({ id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null })).toBe('2');
  });

  it('marks in-env systems current with their plain name', () => {
    expect(grouping.meta('2')).toEqual({ name: 'Customer', isCurrent: true });
  });

  it('labels outside systems and marks them not current', () => {
    expect(grouping.meta('3')).toEqual({ name: 'Mortgage — not in environment', isCurrent: false });
  });

  it('falls back to System <id> for unknown names', () => {
    expect(grouping.meta('7')).toEqual({ name: 'System 7 — not in environment', isCurrent: false });
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npx vitest run src/components/topology/__tests__/environmentTopologySource.test.ts`
Expected: FAIL — module/exports don't exist yet.

- [ ] **Step 3: Create the environment source module**

Create `frontend/src/components/topology/environmentTopologySource.ts`:

```ts
import type { EnvironmentTopologyData } from '../../types/environment';
import type { VisibilityInput } from './topologyVisibility';
import type { Grouping } from './topologyModel';
import type { TopologySource } from './topologySource';

/** Full-graph source backed by the environment topology API response. */
export function fromEnvironmentTopologyResponse(data: EnvironmentTopologyData): TopologySource {
  return {
    getGraph: (): VisibilityInput => ({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.outside_subsystems ?? [],
      externalDependencies: data.outside_dependencies ?? [],
    }),
    getSystemNames: () => data.system_names ?? {},
  };
}

/**
 * Environment grouping by owning system: systems deployed in this environment are
 * "current"; systems referenced only by cross-environment dependencies are labelled
 * "— not in environment" and rendered as non-current.
 */
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

- [ ] **Step 4: Run the env-source test — expect PASS**

Run: `npx vitest run src/components/topology/__tests__/environmentTopologySource.test.ts`
Expected: PASS (6 passed).

- [ ] **Step 5: Rewrite `EnvironmentTopologyDiagram` as a thin wrapper**

Replace the entire contents of `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx` with:

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import SubsystemNode from '../../components/topology/SubsystemNode';
import SystemGroupNode from '../../components/topology/SystemGroupNode';
import CollapsedSystemNode from '../../components/topology/CollapsedSystemNode';
import TopologyCanvas from '../../components/topology/TopologyCanvas';
import { colorForComponentType } from '../../components/topology/topologyColors';
import {
  fromEnvironmentTopologyResponse,
  byEnvSystem,
} from '../../components/topology/environmentTopologySource';
import { environmentService } from '../../services/environmentService';
import type { EnvironmentTopologyData } from '../../types/environment';

const nodeTypes = {
  subsystemNode: SubsystemNode,
  systemGroupNode: SystemGroupNode,
  collapsedSystemNode: CollapsedSystemNode,
};

interface Props {
  envId: number;
}

export default function EnvironmentTopologyDiagram({ envId }: Props) {
  const [data, setData] = useState<EnvironmentTopologyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    environmentService
      .getEnvironmentTopology(envId)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message ?? 'Failed to load topology');
        setLoading(false);
      });
  }, [envId]);

  const source = useMemo(() => (data ? fromEnvironmentTopologyResponse(data) : null), [data]);
  const graph = useMemo(() => source?.getGraph() ?? null, [source]);
  const envSystemIds = useMemo(
    () => new Set((data?.subsystems ?? []).map((s) => s.system_id)),
    [data],
  );
  const grouping = useMemo(
    () => byEnvSystem(source?.getSystemNames() ?? {}, envSystemIds),
    [source, envSystemIds],
  );
  const findDependency = useCallback(
    (id: number) =>
      [...(data?.dependencies ?? []), ...(data?.outside_dependencies ?? [])].find(
        (d) => d.id === id,
      ) ?? null,
    [data],
  );

  return (
    <TopologyCanvas
      graph={graph}
      grouping={grouping}
      loading={loading}
      error={error}
      colorFor={colorForComponentType}
      nodeTypes={nodeTypes}
      findDependency={findDependency}
      emptyMessage="No subsystems configured. Add systems with subsystems to see the topology."
    />
  );
}
```

- [ ] **Step 6: Typecheck + full unit suite**

Run: `npx tsc --noEmit`
Expected: clean (the old `dagre`, inline node, and `EnvSubsystemNode`/`ComponentDependencyResponse` imports are gone; if `noUnusedLocals` flags a leftover import, remove it).
Run: `npx vitest run --exclude 'e2e/**'`
Expected: all pass.

- [ ] **Step 7: Manual parity + feature check**

Start the app if needed (`npm run dev`), open an environment's **Topology** tab. Confirm: ELK layout renders; search centers a component; filter-by-type hides/shows; collapse chevron collapses a system and clicking a collapsed node expands it; clicking an edge opens the dependency detail pane; focus dims non-neighbours; **mocked** subsystems show dashed grey + "mocked"; **outside** systems show greyed group boxes labelled "— not in environment". (Browser automation has been flaky — eyeball or ask the user if synthetic clicks stall.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/topology/environmentTopologySource.ts \
        frontend/src/components/topology/__tests__/environmentTopologySource.test.ts \
        frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx
git commit -m "feat(topology): environment diagram on the shared TopologyCanvas"
```

---

## Done Criteria

- `EnvironmentTopologyDiagram` is a thin wrapper over `<TopologyCanvas>`; the dagre layout and inline node are gone.
- Mocked subsystems render distinctly via the shared `SubsystemNode`; the systems path is unchanged (guarded by `subsystemNodeMocked` test).
- Outside systems render as greyed, non-current groups labelled "— not in environment" via `byEnvSystem`.
- The env diagram gains ELK layout, floating edges, focus/search, filter-by-type, and collapse/expand.
- `tsc --noEmit` clean; `vitest run --exclude 'e2e/**'` green; env Topology tab verified manually.
- No group-by-host / toggle (SP4); no backend changes.
