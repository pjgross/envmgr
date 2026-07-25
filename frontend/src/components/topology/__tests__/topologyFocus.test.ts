import { describe, expect, it } from 'vitest';
import {
  computeFocusSet,
  matchComponents,
  type FocusDep,
  type SearchableComponent,
} from '../topologyFocus';

const deps: FocusDep[] = [
  { id: 8, from_subsystem_id: 5, to_subsystem_id: 6 }, // 5 -> 6
  { id: 1, from_subsystem_id: 1, to_subsystem_id: 5 }, // 1 -> 5
  { id: 9, from_subsystem_id: 19, to_subsystem_id: 5 }, // 19 -> 5
  { id: 3, from_subsystem_id: 100, to_subsystem_id: 200 }, // unrelated
];

describe('computeFocusSet', () => {
  it('includes the focused node, its out- and in-neighbours, and incident edges', () => {
    const f = computeFocusSet('5', deps);
    expect([...f.nodeIds].sort()).toEqual(['1', '19', '5', '6']);
    expect([...f.edgeIds].sort()).toEqual(['1', '8', '9']);
  });

  it('excludes unrelated nodes and edges', () => {
    const f = computeFocusSet('5', deps);
    expect(f.nodeIds.has('100')).toBe(false);
    expect(f.edgeIds.has('3')).toBe(false);
  });

  it('returns just the node itself when it has no dependencies', () => {
    const f = computeFocusSet('42', deps);
    expect([...f.nodeIds]).toEqual(['42']);
    expect(f.edgeIds.size).toBe(0);
  });
});

const comps: SearchableComponent[] = [
  { id: 5, name: 'Customer API Server', systemName: 'Customer' },
  { id: 6, name: 'Customer database', systemName: 'Customer' },
  { id: 1, name: 'Mortage Server', systemName: 'Mortgage' },
];

describe('matchComponents', () => {
  it('matches case-insensitively on name', () => {
    expect(matchComponents('mort', comps).map((c) => c.id)).toEqual([1]);
    expect(matchComponents('CUSTOMER', comps).map((c) => c.id)).toEqual([5, 6]);
  });

  it('returns [] for an empty or whitespace query', () => {
    expect(matchComponents('', comps)).toEqual([]);
    expect(matchComponents('   ', comps)).toEqual([]);
  });

  it('preserves input order', () => {
    expect(matchComponents('server', comps).map((c) => c.id)).toEqual([5, 1]);
  });
});
