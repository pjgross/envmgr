import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import environmentGroupReducer, {
  createEnvironmentGroup,
  fetchEnvironmentGroup,
  fetchEnvironmentGroups,
} from '../environmentGroupSlice';
import { environmentGroupService } from '../../services/environmentGroupService';

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
});
