import type { DependencyDirection } from '../../types/dependency';
import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface ModelGroup {
  groupId: string;
  name: string;
  isCurrent: boolean;
  collapsed: boolean;
  componentCount: number;
  components: VisibleSubsystem[]; // [] when collapsed
}

export interface ModelEdge {
  id: string; // real dep id (String) when single; `agg:${source}->${target}` when aggregated
  source: string; // component id (String) or `sys-${groupId}`
  target: string;
  label: string;
  aggregatedCount: number;
  dependencyId: number | null;
  direction: DependencyDirection;
}

export interface TopologyModel {
  groups: ModelGroup[];
  edges: ModelEdge[];
}

/** Pluggable grouping: which group a subsystem belongs to, and that group's display metadata. */
export interface Grouping {
  keyOf(sub: VisibleSubsystem): string;
  meta(key: string): { name: string; isCurrent: boolean };
}

export interface CollapseContext {
  collapsedGroups: Set<string>;
  grouping: Grouping;
}

/** Grouping by owning system — the systems-diagram grouping. groupId === String(system_id). */
export function bySystem(systemNames: Record<string, string>, currentSystemId: number): Grouping {
  return {
    keyOf: (s) => String(s.system_id),
    meta: (key) => ({
      name: systemNames[key] ?? `System ${key}`,
      isCurrent: Number(key) === currentSystemId,
    }),
  };
}

export function computeCollapseModel(
  input: VisibilityInput,
  ctx: CollapseContext
): TopologyModel {
  const { grouping, collapsedGroups } = ctx;
  const allSubs = [...input.subsystems, ...input.externalSubsystems];
  const allDeps = [...input.dependencies, ...input.externalDependencies];

  const groupOf = new Map<number, string>();
  for (const s of allSubs) groupOf.set(s.id, grouping.keyOf(s));

  const byGroup = new Map<string, VisibleSubsystem[]>();
  for (const s of allSubs) {
    const key = grouping.keyOf(s);
    if (!byGroup.has(key)) byGroup.set(key, []);
    byGroup.get(key)!.push(s);
  }

  const groups: ModelGroup[] = [...byGroup.entries()].map(([groupId, comps]) => {
    const collapsed = collapsedGroups.has(groupId);
    const meta = grouping.meta(groupId);
    return {
      groupId,
      name: meta.name,
      isCurrent: meta.isCurrent,
      collapsed,
      componentCount: comps.length,
      components: collapsed ? [] : comps,
    };
  });

  const displayNode = (componentId: number): string => {
    const key = groupOf.get(componentId);
    return key !== undefined && collapsedGroups.has(key) ? `sys-${key}` : String(componentId);
  };

  const buckets = new Map<string, VisibleDependency[]>();
  for (const d of allDeps) {
    const source = displayNode(d.from_subsystem_id);
    const target = displayNode(d.to_subsystem_id);
    if (source === target) continue; // both endpoints in one collapsed group (or a self-loop) — nothing to draw
    const key = `${source}->${target}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(d);
  }

  const edges: ModelEdge[] = [...buckets.entries()].map(([key, deps]) => {
    const arrowIdx = key.indexOf('->');
    const source = key.slice(0, arrowIdx);
    const target = key.slice(arrowIdx + 2);
    if (deps.length === 1) {
      const d = deps[0];
      return {
        id: String(d.id),
        source,
        target,
        label: d.label ?? d.dependency_type,
        aggregatedCount: 1,
        dependencyId: d.id,
        direction: d.direction,
      };
    }
    return {
      id: `agg:${key}`,
      source,
      target,
      label: `${deps.length}×`,
      aggregatedCount: deps.length,
      dependencyId: null,
      direction: 'one_way', // aggregates always render one-way (per-dep direction not preserved — v1)
    };
  });

  return { groups, edges };
}
