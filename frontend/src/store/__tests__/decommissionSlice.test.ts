import { configureStore } from '@reduxjs/toolkit';
import { AxiosError } from 'axios';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import decommissionReducer, {
  cancelDecommission,
  fetchDecommission,
  fetchDecommissionWorklist,
  tearDown,
} from '../decommissionSlice';
import { decommissionService } from '../../services/decommissionService';
import type { Decommission, DecommissionWorklistRow } from '../../types/decommission';

vi.mock('../../services/decommissionService', () => ({
  decommissionService: {
    getForEnvironment: vi.fn(),
    initiate: vi.fn(),
    requestExtension: vi.fn(),
    decideExtension: vi.fn(),
    signAttestation: vi.fn(),
    tearDown: vi.fn(),
    cancel: vi.fn(),
    listWorklist: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { decommission: decommissionReducer } });
}

const DECOMMISSION: Decommission = {
  id: 1,
  environment_id: 9,
  reason: 'End of project',
  warned_at: '2026-08-01T00:00:00Z',
  scheduled_teardown_at: '2026-08-15T00:00:00Z',
  initiated_by: 3,
  extension_requested_at: null,
  extension_reason: null,
  extension_until: null,
  extension_decided_at: null,
  extension_granted: null,
  torn_down_at: null,
  cancelled_at: null,
  cancel_reason: null,
  state: 'due',
  // Required, not optional — nothing has been signed yet, which is the
  // honest value, not a placeholder standing in for an omitted field.
  attestations: [],
};

describe('decommissionSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  // THE MOST IMPORTANT TEST IN THIS FILE. RTK's default miniSerializeError
  // copies only name/message/stack/code, and a real AxiosError's `.message`
  // is the generic "Request failed with status code 422" — the server's
  // reason, at response.data.detail, is dropped unless the thunk goes
  // through rejectWithValue(formatApiError(...)). A test that instead
  // rejects with a plain Error carrying the final text would pass while the
  // app is broken, which is why this constructs a real AxiosError shape.
  it('surfaces the server reason, not the HTTP status, when teardown is refused', async () => {
    const err = new AxiosError('Request failed with status code 422');
    err.response = {
      data: { detail: 'Sign these first: final_backup, teardown' },
      status: 422,
      statusText: 'Unprocessable Entity',
      headers: {},
      config: {} as never,
    } as never;
    vi.mocked(decommissionService.tearDown).mockRejectedValueOnce(err);

    const store = makeStore();
    const result = await store.dispatch(tearDown(1));

    expect(tearDown.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('final_backup');
    expect(result.payload).toContain('teardown');
  });

  it('surfaces the server reason when a cancel is refused too', async () => {
    vi.mocked(decommissionService.cancel).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This decommission has already been cancelled' },
      },
    });

    const store = makeStore();
    const result = await store.dispatch(
      cancelDecommission({ decommissionId: 1, data: { reason: 'Mistake' } })
    );

    expect(cancelDecommission.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('already been cancelled');
  });

  it('keeps the worklist total from X-Total-Count, not the row count', async () => {
    const rows: DecommissionWorklistRow[] = [
      {
        ...DECOMMISSION,
        environment_name: 'staging-a',
        initiated_by_username: 'alice',
        owner_username: 'bob',
      },
    ];
    vi.mocked(decommissionService.listWorklist).mockResolvedValueOnce({ rows, total: 37 });

    const store = makeStore();
    await store.dispatch(fetchDecommissionWorklist({ page: 0, pageSize: 25 }));

    expect(store.getState().decommission.worklist).toHaveLength(1);
    expect(store.getState().decommission.worklistTotal).toBe(37);
  });

  it('converts a 0-based page/pageSize into limit/offset for the wire', async () => {
    vi.mocked(decommissionService.listWorklist).mockResolvedValueOnce({ rows: [], total: 0 });

    const store = makeStore();
    await store.dispatch(fetchDecommissionWorklist({ page: 2, pageSize: 25 }));

    expect(decommissionService.listWorklist).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 25, offset: 50 })
    );
  });

  it('clears a stale error banner once a fetch succeeds', async () => {
    vi.mocked(decommissionService.getForEnvironment)
      .mockRejectedValueOnce({
        isAxiosError: true,
        message: 'Request failed with status code 500',
        response: { status: 500, data: { detail: 'boom' } },
      })
      .mockResolvedValueOnce(DECOMMISSION);

    const store = makeStore();
    await store.dispatch(fetchDecommission(9));
    expect(store.getState().decommission.error).toBeTruthy();

    await store.dispatch(fetchDecommission(9));
    expect(store.getState().decommission.error).toBeNull();
    expect(store.getState().decommission.current).toEqual(DECOMMISSION);
  });

  it('updates `current` in place when a teardown resolves the same decommission', async () => {
    vi.mocked(decommissionService.getForEnvironment).mockResolvedValueOnce(DECOMMISSION);
    const store = makeStore();
    await store.dispatch(fetchDecommission(9));

    const remaining = [
      { id: 55, start_date: '2026-09-01T00:00:00Z', end_date: '2026-09-02T00:00:00Z', status: 'approved' },
    ];
    vi.mocked(decommissionService.tearDown).mockResolvedValueOnce({
      ...DECOMMISSION,
      state: 'torn_down',
      torn_down_at: '2026-08-15T00:00:00Z',
      remaining_bookings: remaining,
    });

    await store.dispatch(tearDown(1));

    expect(store.getState().decommission.current?.state).toBe('torn_down');
    expect(store.getState().decommission.remainingBookings).toEqual(remaining);
  });
});
