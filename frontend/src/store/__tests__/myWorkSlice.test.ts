import { describe, expect, it } from 'vitest';
import reducer, { fetchMyWork, selectMyWorkTotal } from '../myWorkSlice';
import type { MyWorkState } from '../myWorkSlice';
import type { MyWorkResponse } from '../../types/myWork';

/**
 * `selectMyWorkTotal` runs on EVERY route via `AppLayout` -> `useMyWork` (the
 * nav badge), not just on `/my-work` — see the selector's own comment.
 * Finding 4 of the PR 3 whole-branch review: a `/me/work` 200 whose body
 * does not match `MyWorkResponse` used to throw here (`Object.values` on a
 * non-object, or on `undefined`), dropping every route in the app to the
 * root `ErrorBoundary`. These tests call the selector directly with exactly
 * the malformed shapes a wrong-but-200 response could carry.
 */
function stateWith(data: MyWorkState['data']): { myWork: MyWorkState } {
  return { myWork: { data, loading: false, error: null } };
}

describe('selectMyWorkTotal', () => {
  const okQueue = { count: 0, items: [], failed: false };

  it('sums every queue’s count', () => {
    const state = stateWith({
      as_of: '2026-09-04T00:00:00Z',
      queues: {
        environment_requests: { ...okQueue, count: 2 },
        contentions: { ...okQueue, count: 1 },
        decommissions: okQueue,
        pir_actions: { ...okQueue, count: 3 },
        incidents: okQueue,
      },
    });
    expect(selectMyWorkTotal(state)).toBe(6);
  });

  it('is 0 before any fetch has landed', () => {
    expect(selectMyWorkTotal(stateWith(null))).toBe(0);
  });

  it('does not throw when `queues` is missing entirely', () => {
    const state = stateWith({ as_of: 'x' } as unknown as MyWorkResponse);
    expect(() => selectMyWorkTotal(state)).not.toThrow();
    expect(selectMyWorkTotal(state)).toBe(0);
  });

  it('does not throw when `queues` is an array instead of an object', () => {
    const state = stateWith({ as_of: 'x', queues: [] } as unknown as MyWorkResponse);
    expect(() => selectMyWorkTotal(state)).not.toThrow();
    expect(selectMyWorkTotal(state)).toBe(0);
  });

  it('does not throw when `queues` is null', () => {
    const state = stateWith({ as_of: 'x', queues: null } as unknown as MyWorkResponse);
    expect(() => selectMyWorkTotal(state)).not.toThrow();
    expect(selectMyWorkTotal(state)).toBe(0);
  });

  it('ignores a queue entry whose own `count` is not a number', () => {
    const state = stateWith({
      as_of: 'x',
      queues: {
        environment_requests: { count: 4, items: [], failed: false },
        contentions: 'not-a-queue',
      },
    } as unknown as MyWorkResponse);
    expect(() => selectMyWorkTotal(state)).not.toThrow();
    expect(selectMyWorkTotal(state)).toBe(4);
  });
});

describe('myWorkSlice reducer', () => {
  it('does not blank a previous success on a later transport-level failure', () => {
    const afterSuccess = reducer(undefined, {
      type: fetchMyWork.fulfilled.type,
      payload: { as_of: 'x', queues: {} },
    });
    const afterFailure = reducer(afterSuccess, {
      type: fetchMyWork.rejected.type,
      payload: 'network down',
    });
    expect(afterFailure.data).toEqual({ as_of: 'x', queues: {} });
    expect(afterFailure.error).toBe('network down');
  });
});
