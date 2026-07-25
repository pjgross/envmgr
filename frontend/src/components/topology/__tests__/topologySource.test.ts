import { describe, expect, it } from 'vitest';
import { fromTopologyResponse } from '../topologySource';
import type { TopologyResponse } from '../../../types/topology';

const data = {
  subsystems: [{ id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null }],
  dependencies: [{ id: 8, from_subsystem_id: 5, to_subsystem_id: 6, dependency_type: 'api_call', direction: 'one_way', label: null }],
  external_subsystems: [{ id: 1, name: 'ext', system_id: 1, component_type: 'other', technology: null }],
  external_dependencies: [{ id: 10, from_subsystem_id: 1, to_subsystem_id: 5, dependency_type: 'api_call', direction: 'one_way', label: null }],
  system_names: { '1': 'Mortgage', '2': 'Customer' },
} as unknown as TopologyResponse;

describe('fromTopologyResponse', () => {
  it('maps a TopologyResponse into the pipeline VisibilityInput shape', () => {
    const graph = fromTopologyResponse(data).getGraph();
    expect(graph.subsystems.map((s) => s.id)).toEqual([5]);
    expect(graph.dependencies.map((d) => d.id)).toEqual([8]);
    expect(graph.externalSubsystems.map((s) => s.id)).toEqual([1]);
    expect(graph.externalDependencies.map((d) => d.id)).toEqual([10]);
  });

  it('defaults missing external arrays to empty', () => {
    const graph = fromTopologyResponse({ ...data, external_subsystems: undefined, external_dependencies: undefined } as unknown as TopologyResponse).getGraph();
    expect(graph.externalSubsystems).toEqual([]);
    expect(graph.externalDependencies).toEqual([]);
  });
});
