import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import environmentGroupReducer, {
  createEnvironmentGroup,
  fetchEnvironmentGroup,
  fetchEnvironmentGroups,
  fetchGroupMembers,
  fetchGroupsForEnvironment,
} from '../environmentGroupSlice';
import { environmentGroupService } from '../../services/environmentGroupService';
import type { MemberResponse } from '../../types/environmentGroup';

// A promise this test resolves by hand, so it can control which of two
// in-flight requests settles first — the whole point of the races below.
// `Promise.resolve().then(...)`-style sequential mocks (as the rest of this
// file uses) can only ever resolve in dispatch order, which is exactly why
// the review finding on Task 10 survived the original suite.
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

vi.mock('../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroups: vi.fn(),
    getGroup: vi.fn(),
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
    listMembers: vi.fn(),
    listGroupsForEnvironment: vi.fn(),
    addMember: vi.fn(),
    removeMember: vi.fn(),
    transitionGroup: vi.fn(),
    groupAllowedTransitions: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { environmentGroup: environmentGroupReducer } });
}

describe('environmentGroupSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores the server total, not the row count', async () => {
    // The total is what tells a paged grid there is more; deriving it from
    // rows.length would report the page size as the whole set.
    vi.mocked(environmentGroupService.listGroups).mockResolvedValue({
      rows: [{ id: 1, name: 'Payments squad' }] as never,
      total: 42,
    });
    const store = makeStore();
    await store.dispatch(fetchEnvironmentGroups({}));
    expect(store.getState().environmentGroup.groups).toHaveLength(1);
    expect(store.getState().environmentGroup.total).toBe(42);
  });

  it('surfaces the server reason when a create is refused', async () => {
    // AxiosError SHAPE: generic text on .message, the reason only at
    // response.data.detail. A plain Error carrying the final text would pass
    // against broken code, because miniSerializeError keeps .message.
    vi.mocked(environmentGroupService.createGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "A group named 'Payments squad' already exists in this tenant" },
      },
    });
    const store = makeStore();
    const result = await store.dispatch(createEnvironmentGroup({ name: 'Payments squad' }));
    expect(createEnvironmentGroup.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('already exists');
  });

  it('leaves the paged list alone when a create succeeds', async () => {
    // The list is a server-paged window. Splicing the new row in locally
    // desynchronises the page from its total and from the sort order the
    // server applied — pages refetch instead.
    vi.mocked(environmentGroupService.listGroups).mockResolvedValue({
      rows: [{ id: 1, name: 'Payments squad' }] as never,
      total: 42,
    });
    vi.mocked(environmentGroupService.createGroup).mockResolvedValue({
      id: 2,
      name: 'Data squad',
    } as never);
    const store = makeStore();
    await store.dispatch(fetchEnvironmentGroups({}));

    await store.dispatch(createEnvironmentGroup({ name: 'Data squad' }));

    expect(store.getState().environmentGroup.groups).toHaveLength(1);
    expect(store.getState().environmentGroup.total).toBe(42);
  });

  it('clears a stale error banner once a fetch succeeds', async () => {
    // Without the reset, a failed load leaves its message on screen through
    // every later successful one, so the page reads as broken while working.
    //
    // Note only the READ thunks touch state.error. A refused create or delete
    // returns its reason through rejectWithValue for the dialog that caused it
    // to render — a mutation error does not belong in the page banner. Driven
    // with a failed FETCH here, not a failed create, per the same rule.
    vi.mocked(environmentGroupService.getGroup)
      .mockRejectedValueOnce({
        isAxiosError: true,
        message: 'Request failed with status code 500',
        response: { status: 500, data: { detail: 'boom' } },
      })
      .mockResolvedValueOnce({ id: 1, name: 'Payments squad' } as never);
    const store = makeStore();
    await store.dispatch(fetchEnvironmentGroup(1));
    expect(store.getState().environmentGroup.error).toBeTruthy();

    await store.dispatch(fetchEnvironmentGroup(1));

    expect(store.getState().environmentGroup.error).toBeNull();
  });

  // Task 10 review finding: EnvironmentGroupsPanel's effect had no request
  // sequencing, so an out-of-order response could silently overwrite fresher
  // data. Both races below resolve requests OUT OF ORDER on purpose — the
  // existing suite only ever resolved sequentially, which is why this
  // survived review once already.
  describe('request races (Task 10 review finding)', () => {
    const envGroupA: MemberResponse = {
      id: 101,
      tenant_id: 1,
      group_id: 5,
      group_name: 'Payments Squad',
      environment_id: 3,
      environment_name: 'UAT-1',
      created_at: '2026-08-06T00:00:00Z',
    };
    const envGroupB: MemberResponse = {
      id: 102,
      tenant_id: 1,
      group_id: 9,
      group_name: 'Data Squad',
      environment_id: 4,
      environment_name: 'UAT-2',
      created_at: '2026-08-06T00:00:00Z',
    };
    const groupMember: MemberResponse = {
      id: 20,
      tenant_id: 1,
      group_id: 1,
      group_name: 'Payments regression',
      environment_id: 9,
      environment_name: 'staging-a',
      created_at: '2026-01-01T00:00:00Z',
    };

    it('discards a stale fetchGroupsForEnvironment response when a newer request for a different environment resolves first (same-component race)', async () => {
      // Simulates environmentId changing mid-flight (3 -> 4): the FIRST
      // dispatch (environment 3) is the one that resolves LAST.
      const forEnv3 = deferred<{ rows: MemberResponse[]; total: number }>();
      const forEnv4 = deferred<{ rows: MemberResponse[]; total: number }>();
      vi.mocked(environmentGroupService.listGroupsForEnvironment)
        .mockReturnValueOnce(forEnv3.promise)
        .mockReturnValueOnce(forEnv4.promise);

      const store = makeStore();
      const p1 = store.dispatch(fetchGroupsForEnvironment(3));
      const p2 = store.dispatch(fetchGroupsForEnvironment(4));

      // Newer request (environment 4) lands FIRST.
      forEnv4.resolve({ rows: [envGroupB], total: 1 });
      await p2;
      expect(store.getState().environmentGroup.environmentGroups).toEqual([envGroupB]);

      // Older request (environment 3) lands LAST — without the requestId
      // guard this overwrites environment 4's data with environment 3's.
      forEnv3.resolve({ rows: [envGroupA], total: 1 });
      await p1;

      expect(store.getState().environmentGroup.environmentGroups).toEqual([envGroupB]);
      expect(store.getState().environmentGroup.environmentGroupsTotal).toBe(1);
    });

    it('keeps a group-detail members read in its own slot, unaffected by a slower environment-direction read resolving after it (cross-page race)', async () => {
      // Simulates the EnvironmentGroupsPanel request still being in flight
      // when the user has already navigated to the group's own detail page
      // (whose fetchGroupMembers completes first, then the environment
      // response lands last).
      const forEnvironment = deferred<{ rows: MemberResponse[]; total: number }>();
      vi.mocked(environmentGroupService.listGroupsForEnvironment).mockReturnValue(
        forEnvironment.promise
      );
      vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
        rows: [groupMember],
        total: 1,
      });

      const store = makeStore();
      const environmentRequest = store.dispatch(fetchGroupsForEnvironment(3));

      // Group detail's own read completes while the environment panel's
      // request is still pending.
      await store.dispatch(fetchGroupMembers(1));
      expect(store.getState().environmentGroup.members).toEqual([groupMember]);
      expect(store.getState().environmentGroup.memberTotal).toBe(1);

      // The environment-direction response lands last.
      forEnvironment.resolve({ rows: [envGroupA], total: 1 });
      await environmentRequest;

      // Group detail's slot is untouched by the later-landing response...
      expect(store.getState().environmentGroup.members).toEqual([groupMember]);
      expect(store.getState().environmentGroup.memberTotal).toBe(1);
      // ...which instead landed in its own field.
      expect(store.getState().environmentGroup.environmentGroups).toEqual([envGroupA]);
    });
  });
});
