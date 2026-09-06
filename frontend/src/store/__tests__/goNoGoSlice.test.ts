/**
 * `closeCondition.fulfilled`'s find/replace-by-id reducer had zero test
 * coverage anywhere as of Task 7 — it would not have acquired any until some
 * later UI test happened to exercise it through a mocked service. This
 * programme has already shipped a missing-`pending`-handler bug that a
 * fully green suite missed (see A3's rollup thunk), so this is a DIRECT
 * slice test rather than one riding on a component's behaviour.
 */
import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import goNoGoReducer, {
  closeCondition,
  fetchDecisions,
  fetchPerspectives,
  createPerspective,
  updatePerspective,
} from '../goNoGoSlice';
import { goNoGoService } from '../../services/goNoGoService';
import type {
  GoNoGoConditionRead,
  GoNoGoDecisionRead,
  GoNoGoPerspectiveRead,
} from '../../types/goNoGo';

vi.mock('../../services/goNoGoService', () => ({
  goNoGoService: {
    list: vi.fn(),
    record: vi.fn(),
    closeCondition: vi.fn(),
    listPerspectives: vi.fn(),
    createPerspective: vi.fn(),
    updatePerspective: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { goNoGo: goNoGoReducer } });
}

function condition(over: Partial<GoNoGoConditionRead> = {}): GoNoGoConditionRead {
  return {
    id: 10,
    decision_id: 1,
    text: 'Confirm backup',
    owner_user_id: null,
    owner_username: null,
    due_date: null,
    met_at: null,
    met_by_user_id: null,
    met_by_username: null,
    ...over,
  };
}

function decision(over: Partial<GoNoGoDecisionRead> = {}): GoNoGoDecisionRead {
  return {
    id: 1,
    tenant_id: 1,
    release_id: 42,
    outcome: 'go',
    rationale: '',
    decided_at: '2026-09-01T10:00:00Z',
    chaired_by_user_id: 1,
    chaired_by_username: 'alice',
    attendees: [],
    attendee_usernames: [],
    snapshot_ok: true,
    snapshot_blockers: [],
    snapshot_warnings: [],
    snapshot_reversibility: null,
    snapshot_rehearsal_state: null,
    signoffs: [],
    conditions: [condition({ id: 10, decision_id: 1 }), condition({ id: 11, decision_id: 1 })],
    unmet_condition_count: 2,
    ...over,
  };
}

// Two decisions, each with its own condition ids, so a mis-scoped reducer
// (e.g. one that searched every decision's conditions rather than the one
// named by `decision_id`) would show up as the WRONG decision's array
// mutating instead of the right one's.
async function loadTwoDecisions() {
  const store = makeStore();
  vi.mocked(goNoGoService.list).mockResolvedValueOnce({
    rows: [
      decision({ id: 1, conditions: [condition({ id: 10, decision_id: 1 }), condition({ id: 11, decision_id: 1 })] }),
      decision({ id: 2, conditions: [condition({ id: 20, decision_id: 2 })] }),
    ],
    total: 2,
  });
  await store.dispatch(fetchDecisions({ releaseId: 42, params: {} }));
  return store;
}

describe('goNoGoSlice — closeCondition.fulfilled', () => {
  beforeEach(() => vi.clearAllMocks());

  it('finds the right decision and replaces the right condition, in place', async () => {
    const store = await loadTwoDecisions();

    const updated = condition({
      id: 11,
      decision_id: 1,
      met_at: '2026-09-05T00:00:00Z',
      met_by_user_id: 7,
      met_by_username: 'bob',
    });
    vi.mocked(goNoGoService.closeCondition).mockResolvedValueOnce(updated);

    const result = await store.dispatch(closeCondition({ conditionId: 11, met: true }));
    expect(closeCondition.fulfilled.match(result)).toBe(true);

    const state = store.getState().goNoGo;
    const d1 = state.decisions.find((d) => d.id === 1)!;
    const d2 = state.decisions.find((d) => d.id === 2)!;

    // The named condition was replaced with the server's version...
    expect(d1.conditions.find((c) => c.id === 11)).toEqual(updated);
    // ...its sibling on the SAME decision was left untouched...
    expect(d1.conditions.find((c) => c.id === 10)!.met_at).toBeNull();
    // ...and the OTHER decision's conditions were never touched at all.
    expect(d2.conditions).toEqual([condition({ id: 20, decision_id: 2 })]);
  });

  it('no-ops when the payload names a decision that is not loaded', async () => {
    const store = await loadTwoDecisions();
    const before = store.getState().goNoGo.decisions;

    // decision_id 999 does not exist in the loaded page — a stale response
    // for a decision that has since scrolled off, say.
    vi.mocked(goNoGoService.closeCondition).mockResolvedValueOnce(
      condition({ id: 10, decision_id: 999, met_at: '2026-09-05T00:00:00Z' })
    );
    const result = await store.dispatch(closeCondition({ conditionId: 10, met: true }));
    expect(closeCondition.fulfilled.match(result)).toBe(true);

    // Nothing in the loaded decisions changed — in particular, condition 10
    // on decision 1 (a different row entirely, sharing only the numeric id)
    // must not have been mistakenly patched.
    expect(store.getState().goNoGo.decisions).toEqual(before);
  });

  it('no-ops when the condition id is not found on its named decision', async () => {
    const store = await loadTwoDecisions();
    const before = store.getState().goNoGo.decisions.find((d) => d.id === 1)!.conditions;

    // decision_id 1 IS loaded, but condition id 999 does not belong to it.
    vi.mocked(goNoGoService.closeCondition).mockResolvedValueOnce(
      condition({ id: 999, decision_id: 1, met_at: '2026-09-05T00:00:00Z' })
    );
    const result = await store.dispatch(closeCondition({ conditionId: 999, met: true }));
    expect(closeCondition.fulfilled.match(result)).toBe(true);

    expect(store.getState().goNoGo.decisions.find((d) => d.id === 1)!.conditions).toEqual(before);
  });
});

function perspective(over: Partial<GoNoGoPerspectiveRead> = {}): GoNoGoPerspectiveRead {
  return {
    id: 1,
    tenant_id: 1,
    name: 'Quality',
    description: null,
    sort_order: 10,
    is_active: true,
    ...over,
  };
}

describe('goNoGoSlice — createPerspective / updatePerspective', () => {
  beforeEach(() => vi.clearAllMocks());

  it('createPerspective.rejected carries formatApiError\'s message into action.payload', async () => {
    // The 409 case Task 7's brief called "the whole point": a real AxiosError
    // shape, so a regression back to `action.error.message` (the default
    // serializer, which drops response.data.detail) would fail this test
    // rather than passing an entire green suite.
    vi.mocked(goNoGoService.createPerspective).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'A perspective named Quality already exists' },
      },
    });

    const store = makeStore();
    const result = await store.dispatch(
      createPerspective({ name: 'Quality', description: null, sort_order: 10, is_active: true })
    );

    expect(createPerspective.rejected.match(result)).toBe(true);
    expect(result.payload).toBe('A perspective named Quality already exists');
    expect(result.payload).not.toMatch(/status code/i);
  });

  it('updatePerspective.fulfilled replaces the right perspective, leaving its siblings untouched', async () => {
    const store = makeStore();
    vi.mocked(goNoGoService.listPerspectives).mockResolvedValueOnce([
      perspective({ id: 1, name: 'Quality', sort_order: 10 }),
      perspective({ id: 2, name: 'Process', sort_order: 20 }),
    ]);
    await store.dispatch(fetchPerspectives(true));

    const updated = perspective({ id: 2, name: 'Process', sort_order: 20, is_active: false });
    vi.mocked(goNoGoService.updatePerspective).mockResolvedValueOnce(updated);

    const result = await store.dispatch(
      updatePerspective({ id: 2, data: { is_active: false } })
    );
    expect(updatePerspective.fulfilled.match(result)).toBe(true);

    const { perspectives } = store.getState().goNoGo;
    expect(perspectives).toHaveLength(2);
    // The named perspective was replaced with the server's version...
    expect(perspectives.find((p) => p.id === 2)).toEqual(updated);
    // ...and its sibling was neither appended to nor overwritten.
    expect(perspectives.find((p) => p.id === 1)).toEqual(perspective({ id: 1, name: 'Quality', sort_order: 10 }));
  });
});

// Fix round 1: the Go/No-Go tab never loaded its history in the running app
// — a permanent "Unable to load go/no-go decisions." Alert, on first mount
// and every remount, even though a direct API call returned 200 with
// X-Total-Count: 0. Root cause: useServerGrid deliberately aborts the
// previous in-flight request (frontend/src/hooks/useServerGrid.ts:308-321),
// and React StrictMode's double effect fires that abort on first mount. RTK
// dispatches `pending` for the new request synchronously, then `rejected`
// (meta.aborted: true) for the aborted one on a microtask, which — with no
// guard — stamped `error` with a false failure while the real request was
// still in flight. `fetchPerspectives` is exposed to the identical trap: it
// is dispatched from the record-decision dialog on mount. Two sibling
// slices already carry this guard and its comment: buildSlice.
// fetchBuilds.rejected and bookingSlice.fetchBookings.rejected;
// releaseSlice's own `describe('releaseSlice — aborted fetches', ...)` is
// the direct-reducer test style this block follows.
describe('goNoGoSlice — aborted fetches', () => {
  it('fetchDecisions: leaves error null and the loaded page untouched when aborted', () => {
    const loaded = goNoGoReducer(undefined, {
      type: fetchDecisions.fulfilled.type,
      payload: { rows: [decision()], total: 1 },
    });
    expect(loaded.error).toBeNull();

    const midFlight = goNoGoReducer(loaded, { type: fetchDecisions.pending.type });
    expect(midFlight.loading).toBe(true);

    const afterAbort = goNoGoReducer(midFlight, {
      type: fetchDecisions.rejected.type,
      error: { message: 'Aborted' },
      meta: { aborted: true },
    });

    // Still mid-flight for the SUPERSEDING request — the stale abort must
    // not flip this back to false.
    expect(afterAbort.loading).toBe(true);
    expect(afterAbort.error).toBeNull();
    expect(afterAbort.decisions).toEqual([decision()]);
    expect(afterAbort.total).toBe(1);
  });

  it('fetchDecisions: still records a genuine (non-aborted) failure', () => {
    const midFlight = goNoGoReducer(undefined, { type: fetchDecisions.pending.type });

    const afterFailure = goNoGoReducer(midFlight, {
      type: fetchDecisions.rejected.type,
      error: { message: 'Network error' },
      meta: { aborted: false },
    });

    expect(afterFailure.loading).toBe(false);
    expect(afterFailure.error).toBe('Network error');
  });

  it('fetchPerspectives: leaves error null and the loaded list untouched when aborted', () => {
    const loaded = goNoGoReducer(undefined, {
      type: fetchPerspectives.fulfilled.type,
      payload: [perspective()],
    });
    expect(loaded.error).toBeNull();

    const midFlight = goNoGoReducer(loaded, { type: fetchPerspectives.pending.type });

    const afterAbort = goNoGoReducer(midFlight, {
      type: fetchPerspectives.rejected.type,
      error: { message: 'Aborted' },
      meta: { aborted: true },
    });

    expect(afterAbort.loading).toBe(true);
    expect(afterAbort.error).toBeNull();
    expect(afterAbort.perspectives).toEqual([perspective()]);
  });

  it('fetchPerspectives: still records a genuine (non-aborted) failure', () => {
    const midFlight = goNoGoReducer(undefined, { type: fetchPerspectives.pending.type });

    const afterFailure = goNoGoReducer(midFlight, {
      type: fetchPerspectives.rejected.type,
      error: { message: 'Network error' },
      meta: { aborted: false },
    });

    expect(afterFailure.loading).toBe(false);
    expect(afterFailure.error).toBe('Network error');
  });
});
