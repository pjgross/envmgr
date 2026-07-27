import { describe, expect, it } from 'vitest';
import { buildHostGraph } from '../topologyHostTransform';
import type { VisibilityInput, VisibleSubsystem } from '../topologyVisibility';
import type { EnvSubsystemHostRef } from '../../../types/environment';

const host = (id: number, name: string): EnvSubsystemHostRef => ({
  infrastructure_component_id: id,
  name,
  component_type: 'server',
  role: null,
});
const sub = (
  id: number,
  systemId: number,
  hosts: EnvSubsystemHostRef[] | undefined,
): VisibleSubsystem => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: 'service',
  technology: null,
  is_mocked: false,
  hosts,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way' as const,
  label: null,
});

// A(1) on web-01/web-02, B(2) on web-01, C(3) no hosts, external X(9).
// dep A->B  and external dep X->A.
const input: VisibilityInput = {
  subsystems: [
    sub(1, 100, [host(10, 'web-01'), host(11, 'web-02')]),
    sub(2, 100, [host(10, 'web-01')]),
    sub(3, 100, []),
  ],
  dependencies: [dep(50, 1, 2)],
  externalSubsystems: [sub(9, 200, [])],
  externalDependencies: [dep(60, 9, 1)],
};

describe('buildHostGraph', () => {
  it('expands multi-host subsystems to one node per host', () => {
    const { graph, hostKeyById } = buildHostGraph(input);
    // A×2 + B×1 + C×1 = 4 internal, X×1 external
    expect(graph.subsystems).toHaveLength(4);
    expect(graph.externalSubsystems).toHaveLength(1);
    const keys = graph.subsystems.map((s) => hostKeyById.get(s.id)).sort();
    expect(keys).toEqual(['10', '10', '11', 'unassigned']);
  });

  it('buckets a hostless in-env subsystem under "unassigned" and externals under "external"', () => {
    const { graph, hostKeyById, hostMeta } = buildHostGraph(input);
    const cNode = graph.subsystems.find((s) => s.name === 'n3')!;
    expect(hostKeyById.get(cNode.id)).toBe('unassigned');
    expect(hostMeta.get('unassigned')).toEqual({ name: 'Unassigned', isCurrent: false });
    const xNode = graph.externalSubsystems[0];
    expect(hostKeyById.get(xNode.id)).toBe('external');
    expect(hostMeta.get('external')).toEqual({ name: 'External', isCurrent: false });
  });

  it('labels real host groups by host name and marks them current', () => {
    const { hostMeta } = buildHostGraph(input);
    expect(hostMeta.get('10')).toEqual({ name: 'web-01', isCurrent: true });
    expect(hostMeta.get('11')).toEqual({ name: 'web-02', isCurrent: true });
  });

  it('preserves source rendering fields on synthetic nodes', () => {
    const { graph } = buildHostGraph(input);
    const aInstances = graph.subsystems.filter((s) => s.name === 'n1');
    expect(aInstances).toHaveLength(2);
    expect(aInstances.every((s) => s.component_type === 'service' && s.is_mocked === false)).toBe(true);
  });

  it('fans a dependency out across the cartesian product of instances', () => {
    const { graph, hostKeyById, edgeDepResolver } = buildHostGraph(input);
    // A(2 instances) -> B(1 instance) = 2 edges, all resolving to real dep 50.
    expect(graph.dependencies).toHaveLength(2);
    for (const e of graph.dependencies) {
      expect(edgeDepResolver.get(e.id)).toBe(50);
      expect(hostKeyById.get(e.to_subsystem_id)).toBe('10'); // B is on web-01
      expect(['10', '11']).toContain(hostKeyById.get(e.from_subsystem_id));
    }
    // external dep X(1)->A(2) = 2 external edges, resolving to real dep 60.
    expect(graph.externalDependencies).toHaveLength(2);
    expect(graph.externalDependencies.every((e) => edgeDepResolver.get(e.id) === 60)).toBe(true);
  });

  it('mints node and edge ids in disjoint deterministic sequences', () => {
    const { graph } = buildHostGraph(input);
    const nodeIds = [...graph.subsystems, ...graph.externalSubsystems].map((s) => s.id);
    expect(new Set(nodeIds).size).toBe(nodeIds.length); // unique
    const edgeIds = [...graph.dependencies, ...graph.externalDependencies].map((e) => e.id);
    expect(new Set(edgeIds).size).toBe(edgeIds.length); // unique among edges
  });

  it('yields no edges for a dependency referencing a non-existent endpoint', () => {
    const dangling: VisibilityInput = {
      subsystems: [sub(1, 100, [host(10, 'web-01')])],
      dependencies: [dep(50, 1, 999)], // 999 is not in the input
      externalSubsystems: [],
      externalDependencies: [],
    };
    const { graph } = buildHostGraph(dangling);
    expect(graph.dependencies).toHaveLength(0);
  });

  it('is pure/deterministic: identical input yields structurally identical output', () => {
    expect(buildHostGraph(input).graph).toEqual(buildHostGraph(input).graph);
  });

  it('fans an N-host -> M-host dependency into N*M edges', () => {
    const nm: VisibilityInput = {
      subsystems: [
        sub(1, 100, [host(10, 'web-01'), host(11, 'web-02')]),
        sub(2, 100, [host(20, 'app-01'), host(21, 'app-02')]),
      ],
      dependencies: [dep(50, 1, 2)],
      externalSubsystems: [],
      externalDependencies: [],
    };
    const { graph, edgeDepResolver } = buildHostGraph(nm);
    expect(graph.dependencies).toHaveLength(4);
    expect(graph.dependencies.every((e) => edgeDepResolver.get(e.id) === 50)).toBe(true);
  });
});
