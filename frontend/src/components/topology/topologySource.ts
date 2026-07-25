import type { TopologyResponse } from '../../types/topology';
import type { VisibilityInput } from './topologyVisibility';

/**
 * The single boundary between the raw topology data and the render pipeline.
 *
 * Today the only implementation returns the full graph already held in Redux.
 * This seam exists so a future level-of-detail backend (for ~1000-component
 * graphs) can implement the SAME interface — e.g. returning collapsed-system
 * summaries and fetching component detail lazily on expand — WITHOUT touching
 * anything downstream (`computeVisibleGraph` / `computeCollapseModel` onward).
 * Nothing in the render pipeline may depend on the raw `TopologyResponse` shape;
 * everything it needs — the graph and the system-id→name lookup — comes through
 * this contract.
 */
export interface TopologySource {
  getGraph(): VisibilityInput;
  getSystemNames(): Record<string, string>;
}

/** Full-graph source backed by the current unpaginated topology API response. */
export function fromTopologyResponse(data: TopologyResponse): TopologySource {
  return {
    getGraph: () => ({
      subsystems: data.subsystems,
      dependencies: data.dependencies,
      externalSubsystems: data.external_subsystems ?? [],
      externalDependencies: data.external_dependencies ?? [],
    }),
    getSystemNames: () => data.system_names ?? {},
  };
}
