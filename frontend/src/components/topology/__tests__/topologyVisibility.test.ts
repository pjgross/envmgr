import { describe, expect, it } from 'vitest';
import {
  computeVisibleGraph,
  availableComponentTypes,
  type VisibilityInput,
} from '../topologyVisibility';

const sub = (id: number, systemId: number, type: string) => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: type,
  technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way' as const,
  label: null,
});

// Customer(2): API(5, api_gateway) -> db(6, database). External Mortgage(1, web_service) -> 5.
const input: VisibilityInput = {
  subsystems: [sub(5, 2, 'api_gateway'), sub(6, 2, 'database')],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1, 'web_service')],
  externalDependencies: [dep(1, 1, 5)],
};

describe('computeVisibleGraph', () => {
  it('returns everything when no types are hidden', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set() });
    expect(v.subsystems.map((s) => s.id)).toEqual([5, 6]);
    expect(v.externalSubsystems.map((s) => s.id)).toEqual([1]);
    expect(v.dependencies.map((d) => d.id)).toEqual([8]);
    expect(v.externalDependencies.map((d) => d.id)).toEqual([1]);
  });

  it('hides components of a hidden type', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['database']) });
    expect(v.subsystems.map((s) => s.id)).toEqual([5]); // db (6) gone
    expect(v.externalSubsystems.map((s) => s.id)).toEqual([1]);
  });

  it('drops any dependency whose endpoint was hidden', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['database']) });
    expect(v.dependencies.map((d) => d.id)).toEqual([]); // 8 (5->6) gone because 6 hidden
    expect(v.externalDependencies.map((d) => d.id)).toEqual([1]); // 1 (1->5) stays
  });

  it('keeps external deps only when both endpoints survive', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['api_gateway']) });
    expect(v.subsystems.map((s) => s.id)).toEqual([6]); // api gateway (5) gone
    expect(v.externalDependencies.map((d) => d.id)).toEqual([]); // 1->5 gone because 5 hidden
  });

  it('makes a fully-hidden system contribute no subsystems', () => {
    const v = computeVisibleGraph(input, { hiddenTypes: new Set(['web_service']) });
    expect(v.externalSubsystems).toEqual([]);
    expect(v.externalDependencies).toEqual([]);
  });
});

describe('availableComponentTypes', () => {
  it('returns distinct types across internal + external, sorted', () => {
    expect(availableComponentTypes(input)).toEqual(['api_gateway', 'database', 'web_service']);
  });

  it('dedupes repeated types', () => {
    const dupes: VisibilityInput = {
      subsystems: [sub(1, 1, 'database'), sub(2, 1, 'database')],
      dependencies: [],
      externalSubsystems: [],
      externalDependencies: [],
    };
    expect(availableComponentTypes(dupes)).toEqual(['database']);
  });
});
