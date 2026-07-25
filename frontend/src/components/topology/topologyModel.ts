import type { DependencyDirection } from '../../types/dependency';
import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface ModelSystem {
  systemId: number;
  name: string;
  isCurrent: boolean;
  collapsed: boolean;
  componentCount: number;
  components: VisibleSubsystem[]; // [] when collapsed
}

export interface ModelEdge {
  id: string; // real dep id (String) when single; `agg:${source}->${target}` when aggregated
  source: string; // component id (String) or `sys-${systemId}`
  target: string;
  label: string;
  aggregatedCount: number;
  dependencyId: number | null;
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

export function computeCollapseModel(
  input: VisibilityInput,
  ctx: CollapseContext
): TopologyModel {
  const allSubs = [...input.subsystems, ...input.externalSubsystems];
  const allDeps = [...input.dependencies, ...input.externalDependencies];

  const systemOf = new Map<number, number>();
  for (const s of allSubs) systemOf.set(s.id, s.system_id);

  const bySystem = new Map<number, VisibleSubsystem[]>();
  for (const s of allSubs) {
    if (!bySystem.has(s.system_id)) bySystem.set(s.system_id, []);
    bySystem.get(s.system_id)!.push(s);
  }

  const systems: ModelSystem[] = [...bySystem.entries()].map(([systemId, comps]) => {
    const collapsed = ctx.collapsedSystems.has(systemId);
    return {
      systemId,
      name: ctx.systemNames[String(systemId)] ?? `System ${systemId}`,
      isCurrent: systemId === ctx.currentSystemId,
      collapsed,
      componentCount: comps.length,
      components: collapsed ? [] : comps,
    };
  });

  const displayNode = (componentId: number): string => {
    const sysId = systemOf.get(componentId);
    return sysId !== undefined && ctx.collapsedSystems.has(sysId)
      ? `sys-${sysId}`
      : String(componentId);
  };

  const buckets = new Map<string, VisibleDependency[]>();
  for (const d of allDeps) {
    const source = displayNode(d.from_subsystem_id);
    const target = displayNode(d.to_subsystem_id);
    if (source === target) continue; // internal to a collapsed system
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

  return { systems, edges };
}
