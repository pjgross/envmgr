import { describe, expect, it } from 'vitest';
import { fromEnvironmentTopologyResponse, byEnvSystem } from '../environmentTopologySource';
import type { EnvironmentTopologyData } from '../../../types/environment';

const data = {
  environment_id: 9,
  subsystems: [
    { id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null, is_mocked: false },
    { id: 6, name: 'db', system_id: 2, component_type: 'database', technology: null, is_mocked: true },
  ],
  dependencies: [
    { id: 8, from_subsystem_id: 5, to_subsystem_id: 6, dependency_type: 'database', direction: 'one_way', label: null },
  ],
  system_names: { '2': 'Customer', '3': 'Mortgage' },
  outside_subsystems: [
    { id: 1, name: 'ext', system_id: 3, component_type: 'other', technology: null, is_mocked: false },
  ],
  outside_dependencies: [
    { id: 10, from_subsystem_id: 5, to_subsystem_id: 1, dependency_type: 'api_call', direction: 'one_way', label: null },
  ],
} as unknown as EnvironmentTopologyData;

describe('fromEnvironmentTopologyResponse', () => {
  it('maps outside_* to external* and carries is_mocked + system names', () => {
    const src = fromEnvironmentTopologyResponse(data);
    const g = src.getGraph();
    expect(g.subsystems.map((s) => s.id)).toEqual([5, 6]);
    expect(g.subsystems.find((s) => s.id === 6)!.is_mocked).toBe(true);
    expect(g.dependencies.map((d) => d.id)).toEqual([8]);
    expect(g.externalSubsystems.map((s) => s.id)).toEqual([1]);
    expect(g.externalDependencies.map((d) => d.id)).toEqual([10]);
    expect(src.getSystemNames()).toEqual({ '2': 'Customer', '3': 'Mortgage' });
  });

  it('defaults missing outside arrays to empty', () => {
    const g = fromEnvironmentTopologyResponse({
      ...data, outside_subsystems: undefined, outside_dependencies: undefined,
    } as unknown as EnvironmentTopologyData).getGraph();
    expect(g.externalSubsystems).toEqual([]);
    expect(g.externalDependencies).toEqual([]);
  });
});

describe('byEnvSystem', () => {
  const grouping = byEnvSystem({ '2': 'Customer', '3': 'Mortgage' }, new Set([2]));

  it('groups by system id', () => {
    expect(grouping.keyOf({ id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null })).toBe('2');
  });

  it('marks in-env systems current with their plain name', () => {
    expect(grouping.meta('2')).toEqual({ name: 'Customer', isCurrent: true });
  });

  it('labels outside systems and marks them not current', () => {
    expect(grouping.meta('3')).toEqual({ name: 'Mortgage — not in environment', isCurrent: false });
  });

  it('falls back to System <id> for unknown names', () => {
    expect(grouping.meta('7')).toEqual({ name: 'System 7 — not in environment', isCurrent: false });
  });
});
