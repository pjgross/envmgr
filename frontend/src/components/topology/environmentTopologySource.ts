import type { EnvironmentTopologyData } from '../../types/environment';
import type { VisibilityInput } from './topologyVisibility';
import type { Grouping } from './topologyModel';
import type { TopologySource } from './topologySource';
import type { HostGroupMeta } from './topologyHostTransform';

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

/**
 * Environment grouping by deployment host. Keys come from `buildHostGraph`'s
 * `hostKeyById` (synthetic node id -> host key); labels/current-ness from `hostMeta`.
 * Unknown nodes fall back to the "unassigned" bucket.
 */
export function byHost(
  hostKeyById: Map<number, string>,
  hostMeta: Map<string, HostGroupMeta>,
): Grouping {
  return {
    keyOf: (s) => hostKeyById.get(s.id) ?? 'unassigned',
    meta: (key) => hostMeta.get(key) ?? { name: key, isCurrent: false },
  };
}
