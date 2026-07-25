import { describe, expect, it } from 'vitest';
import { computeCollapseModel, bySystem, type Grouping } from '../topologyModel';
import type { VisibilityInput } from '../topologyVisibility';

const sub = (id: number, systemId: number, type = 'other') => ({
  id, name: `n${id}`, system_id: systemId, component_type: type, technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id, from_subsystem_id: from, to_subsystem_id: to,
  dependency_type: 'api_call', direction: 'one_way' as const, label: null,
});

// 5(web_service,sysA), 6(database,sysA), 7(web_service,sysB); deps 5->6, 5->7
const input: VisibilityInput = {
  subsystems: [sub(5, 1, 'web_service'), sub(6, 1, 'database'), sub(7, 2, 'web_service')],
  dependencies: [dep(8, 5, 6), dep(9, 5, 7)],
  externalSubsystems: [],
  externalDependencies: [],
};

// A grouping that is NOT by system — groups by component_type.
const byType: Grouping = {
  keyOf: (s) => s.component_type,
  meta: (key) => ({ name: key.toUpperCase(), isCurrent: false }),
};

describe('computeCollapseModel with a pluggable grouping', () => {
  it('groups components by an arbitrary key (component_type), not just system', () => {
    const m = computeCollapseModel(input, { collapsedGroups: new Set(), grouping: byType });
    expect(m.groups.map((g) => g.groupId).sort()).toEqual(['database', 'web_service']);
    const web = m.groups.find((g) => g.groupId === 'web_service')!;
    expect(web.name).toBe('WEB_SERVICE');
    expect(web.components.map((c) => c.id).sort()).toEqual([5, 7]);
    expect(web.componentCount).toBe(2);
  });

  it('collapsing a non-system group aggregates its edges to the collapsed node', () => {
    const m = computeCollapseModel(input, {
      collapsedGroups: new Set(['web_service']),
      grouping: byType,
    });
    const web = m.groups.find((g) => g.groupId === 'web_service')!;
    expect(web.collapsed).toBe(true);
    expect(web.components).toEqual([]);
    // 5 is now sys-web_service; edge 5->6 becomes sys-web_service -> 6; 5->7 collapses (both ends in group) → dropped
    const e = m.edges.find((x) => x.source === 'sys-web_service' && x.target === '6');
    expect(e).toBeTruthy();
    expect(m.edges.some((x) => x.source === '5' || x.target === '5')).toBe(false);
  });

  it('bySystem grouping keeps ids as String(system_id) (parity)', () => {
    const m = computeCollapseModel(input, {
      collapsedGroups: new Set(),
      grouping: bySystem({ '1': 'Alpha', '2': 'Beta' }, 1),
    });
    expect(m.groups.map((g) => g.groupId).sort()).toEqual(['1', '2']);
    expect(m.groups.find((g) => g.groupId === '1')!.isCurrent).toBe(true);
    expect(m.groups.find((g) => g.groupId === '1')!.name).toBe('Alpha');
  });
});
