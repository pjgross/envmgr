import { describe, expect, it } from 'vitest';
import { buildElkGraph, type ElkGraphInput } from '../topologyElkGraph';

const sub = (id: number, systemId: number) => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: 'other',
  technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way',
  label: null,
});

// Customer(2): API(5)->db(6). External Mortgage(1) sys1 ->5; EnvMgr(19) sys3 ->5.
const input: ElkGraphInput = {
  subsystems: [sub(5, 2), sub(6, 2)],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1), sub(19, 3)],
  externalDependencies: [dep(1, 1, 5), dep(9, 19, 5)],
  currentSystemId: 2,
};

describe('buildElkGraph', () => {
  it('creates one container per system', () => {
    const g = buildElkGraph(input);
    const ids = (g.children ?? []).map((c) => c.id).sort();
    expect(ids).toEqual(['group-1', 'group-2', 'group-3']);
  });

  it('nests each component under its system container', () => {
    const g = buildElkGraph(input);
    const byId = new Map((g.children ?? []).map((c) => [c.id, c]));
    expect((byId.get('group-2')!.children ?? []).map((c) => c.id).sort()).toEqual(['5', '6']);
    expect((byId.get('group-1')!.children ?? []).map((c) => c.id)).toEqual(['1']);
    expect((byId.get('group-3')!.children ?? []).map((c) => c.id)).toEqual(['19']);
  });

  it('emits one edge per dependency (internal + external) with correct endpoints', () => {
    const g = buildElkGraph(input);
    const edges = (g.edges ?? []).map((e) => `${e.sources[0]}->${e.targets[0]}`).sort();
    expect(edges).toEqual(['1->5', '19->5', '5->6']);
  });

  it('gives every component node fixed width/height', () => {
    const g = buildElkGraph(input);
    const child = (g.children ?? [])
      .flatMap((c) => c.children ?? [])
      .find((c) => c.id === '5')!;
    expect(child.width).toBe(180);
    expect(child.height).toBe(70);
  });

  it('sets the layered algorithm, RIGHT direction and INCLUDE_CHILDREN on the root', () => {
    const g = buildElkGraph(input);
    expect(g.layoutOptions?.['elk.algorithm']).toBe('layered');
    expect(g.layoutOptions?.['elk.direction']).toBe('RIGHT');
    expect(g.layoutOptions?.['elk.hierarchyHandling']).toBe('INCLUDE_CHILDREN');
  });
});
