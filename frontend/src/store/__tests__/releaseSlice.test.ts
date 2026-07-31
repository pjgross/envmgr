import { describe, expect, it } from 'vitest';
import reducer, { fetchReleases, createRelease, deleteRelease } from '../releaseSlice';
import type { ReleaseListItemResponse, ReleaseResponse } from '../../types/release';

const listRow = (id: number): ReleaseListItemResponse =>
  ({
    id,
    tenant_id: 1,
    name: `Release ${id}`,
    description: null,
    release_type: 'project',
    release_kind: 'project',
    parent_release_id: null,
    template_id: null,
    lifecycle_template_id: 1,
    status: 'draft',
    target_date: null,
    actual_date: null,
    scope_deadline: null,
    custom_fields: null,
    raised_by: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    phase_count: 0,
    scope_count: 0,
    blocker_count: 0,
    overdue_criterion_count: 0,
    scope_additions_count: 0,
    scope_removals_count: 0,
    scope_change_count: 0,
    scope_creep_count: 0,
    window_status: 'no_cutoff',
    days_to_cutoff: null,
    systems: [],
  }) as ReleaseListItemResponse;

const newRelease = (id: number): ReleaseResponse =>
  ({
    id,
    tenant_id: 1,
    name: `Release ${id}`,
    description: null,
    release_type: 'project',
    release_kind: 'project',
    parent_release_id: null,
    template_id: null,
    lifecycle_template_id: 1,
    status: 'draft',
    target_date: null,
    actual_date: null,
    scope_deadline: null,
    custom_fields: null,
    raised_by: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }) as ReleaseResponse;

describe('releaseSlice — total tracking', () => {
  it('increments total when a release is created, alongside unshifting the row', () => {
    const afterList = reducer(undefined, {
      type: fetchReleases.fulfilled.type,
      payload: { rows: [listRow(1), listRow(2)], total: 2 },
    });

    const afterCreate = reducer(afterList, {
      type: createRelease.fulfilled.type,
      payload: newRelease(3),
    });

    expect(afterCreate.total).toBe(3);
    expect(afterCreate.list).toHaveLength(3);
    expect(afterCreate.list[0].id).toBe(3);
  });

  it('decrements total when a release is deleted, alongside removing the row', () => {
    const afterList = reducer(undefined, {
      type: fetchReleases.fulfilled.type,
      payload: { rows: [listRow(1), listRow(2)], total: 2 },
    });

    const afterDelete = reducer(afterList, {
      type: deleteRelease.fulfilled.type,
      payload: 1,
    });

    expect(afterDelete.total).toBe(1);
    expect(afterDelete.list.map((r) => r.id)).toEqual([2]);
  });

  it('does not let total go negative when a delete lands with total already at 0', () => {
    const afterList = reducer(undefined, {
      type: fetchReleases.fulfilled.type,
      payload: { rows: [], total: 0 },
    });

    const afterDelete = reducer(afterList, {
      type: deleteRelease.fulfilled.type,
      payload: 1,
    });

    expect(afterDelete.total).toBe(0);
  });
});

describe('releaseSlice — aborted fetches', () => {
  // useServerGrid aborts a superseded request rather than merely ignoring its
  // reply. RTK dispatches `pending` for the new request synchronously, then
  // `rejected` (with `meta.aborted: true`) for the aborted one on a
  // microtask — landing *after* the new request's own `pending`. Without a
  // guard, that late `rejected` would flip `loading` back to false while the
  // real request is still in flight, and stamp `error` with 'Aborted'.
  it('leaves loading and error untouched when a fetch is aborted', () => {
    const midFlight = reducer(undefined, { type: fetchReleases.pending.type });
    expect(midFlight.loading).toBe(true);

    const afterAbort = reducer(midFlight, {
      type: fetchReleases.rejected.type,
      error: { message: 'Aborted' },
      meta: { aborted: true },
    });

    expect(afterAbort.loading).toBe(true);
    expect(afterAbort.error).toBeNull();
  });

  it('still records loading/error for a genuine (non-aborted) failure', () => {
    const midFlight = reducer(undefined, { type: fetchReleases.pending.type });

    const afterFailure = reducer(midFlight, {
      type: fetchReleases.rejected.type,
      error: { message: 'Network error' },
      meta: { aborted: false },
    });

    expect(afterFailure.loading).toBe(false);
    expect(afterFailure.error).toBe('Network error');
  });
});
