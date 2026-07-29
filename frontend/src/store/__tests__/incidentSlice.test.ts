import { describe, expect, it } from 'vitest';
import reducer, { fetchIncidents } from '../incidentSlice';
import type { IncidentListRow } from '../../types/incident';

describe('incidentSlice', () => {
  it('has an empty initial state', () => {
    const s = reducer(undefined, { type: '@@INIT' });
    expect(s.list).toEqual([]);
    expect(s.loading).toBe(false);
  });
  it('stores incidents on fulfilled', () => {
    const rows = [
      { id: 1, title: 'x', severity: 'P1', status: 'new' },
    ] as unknown as IncidentListRow[];
    const s = reducer(undefined, { type: fetchIncidents.fulfilled.type, payload: rows });
    expect(s.list).toHaveLength(1);
  });
  it('sets loading on pending', () => {
    const s = reducer(undefined, { type: fetchIncidents.pending.type });
    expect(s.loading).toBe(true);
  });
});
