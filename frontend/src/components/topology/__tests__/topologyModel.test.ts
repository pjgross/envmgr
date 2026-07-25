import { describe, expect, it } from 'vitest';
import { computeCollapseModel, bySystem, type CollapseContext } from '../topologyModel';
import type { VisibilityInput } from '../topologyVisibility';

const sub = (id: number, systemId: number, type = 'other') => ({
  id, name: `n${id}`, system_id: systemId, component_type: type, technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id, from_subsystem_id: from, to_subsystem_id: to,
  dependency_type: 'api_call', direction: 'one_way' as const, label: null,
});

// Customer(2): API(5) -> db(6). Mortgage(1): m(1) -> 5. EnvMgr(3): e(19) -> 5.
const input: VisibilityInput = {
  subsystems: [sub(5, 2), sub(6, 2)],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1), sub(19, 3)],
  externalDependencies: [dep(10, 1, 5), dep(11, 19, 5)],
};
const ctx = (collapsed: string[]): CollapseContext => ({
  collapsedGroups: new Set(collapsed),
  grouping: bySystem({ '1': 'Mortgage', '2': 'Customer', '3': 'Env Manager' }, 2),
});

describe('computeCollapseModel', () => {
  it('with nothing collapsed: one expanded system per system, edges 1:1', () => {
    const m = computeCollapseModel(input, ctx([]));
    expect(m.groups.map((g) => g.groupId).sort()).toEqual(['1', '2', '3']);
    expect(m.groups.every((g) => !g.collapsed)).toBe(true);
    const customer = m.groups.find((g) => g.groupId === '2')!;
    expect(customer.components.map((c) => c.id).sort()).toEqual([5, 6]);
    expect(customer.isCurrent).toBe(true);
    expect(m.edges.map((e) => e.id).sort()).toEqual(['10', '11', '8']);
    expect(m.edges.every((e) => e.aggregatedCount === 1)).toBe(true);
  });

  it('collapsing a system empties its components and sets the count', () => {
    const m = computeCollapseModel(input, ctx(['1']));
    const mort = m.groups.find((g) => g.groupId === '1')!;
    expect(mort.collapsed).toBe(true);
    expect(mort.components).toEqual([]);
    expect(mort.componentCount).toBe(1);
  });

  it('re-points a collapsed system\'s boundary edge to sys-<id>', () => {
    const m = computeCollapseModel(input, ctx(['1']));
    const e = m.edges.find((x) => x.dependencyId === 10)!; // 1 -> 5
    expect(e.source).toBe('sys-1');
    expect(e.target).toBe('5');
  });

  it('drops an edge internal to a collapsed system', () => {
    const m = computeCollapseModel(input, ctx(['2']));
    expect(m.edges.some((e) => e.dependencyId === 8)).toBe(false);
  });

  it('aggregates multiple boundary edges into one with a count', () => {
    const agg: VisibilityInput = {
      subsystems: [sub(5, 2)],
      dependencies: [],
      externalSubsystems: [sub(1, 1), sub(2, 1)],
      externalDependencies: [dep(20, 1, 5), dep(21, 2, 5)],
    };
    const m = computeCollapseModel(agg, ctx(['1']));
    const aggEdge = m.edges.find((e) => e.source === 'sys-1' && e.target === '5')!;
    expect(aggEdge.aggregatedCount).toBe(2);
    expect(aggEdge.dependencyId).toBeNull();
    expect(aggEdge.id).toBe('agg:sys-1->5');
    expect(aggEdge.label).toBe('2×');
  });
});
