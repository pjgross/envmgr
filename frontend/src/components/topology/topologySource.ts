import type { TopologyResponse } from '../../types/topology';
import type { VisibilityInput } from './topologyVisibility';

/**
 * The single boundary between the raw topology data and the render pipeline.
 *
 * Today the only implementation returns the full graph already held in Redux.
 * This seam exists so a future level-of-detail backend (for ~1000-component
 * graphs) can implement the SAME interface — e.g. returning collapsed-system
 * summaries and fetching component detail lazily on expand — WITHOUT touching
 * anything downstream (`computeVisibleGraph` onward). Nothing past `getGraph()`
 * may depend on the raw `TopologyResponse` shape.
 */
export interface TopologySource {
  getGraph(): VisibilityInput;
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
  };
}
