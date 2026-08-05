import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import userGroupReducer, {
  deleteUserGroup,
  fetchGroupMembers,
  fetchUserGroup,
  fetchUserGroups,
} from '../userGroupSlice';
import { userGroupService } from '../../services/userGroupService';

vi.mock('../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn(),
    deleteGroup: vi.fn(),
    getGroup: vi.fn(),
    listMembers: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { userGroup: userGroupReducer } });
}

describe('userGroupSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores the rows and the server total, not the row count', async () => {
    // The total is what tells a paged grid there is more; deriving it from
    // rows.length would report the page size as the whole set.
    vi.mocked(userGroupService.listGroups).mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'Platform Ops',
          description: null,
          member_count: 3,
          environment_count: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 42,
    });

    const store = makeStore();
    await store.dispatch(fetchUserGroups({}));

    expect(store.getState().userGroup.groups).toHaveLength(1);
    expect(store.getState().userGroup.total).toBe(42);
  });

  it('surfaces the server reason when a delete is refused', async () => {
    // Shaped like a real AxiosError: `.message` is the generic HTTP-status
    // text, and the reason lives only at `response.data.detail`. Redux
    // Toolkit's miniSerializeError drops `response`, so a thunk that let the
    // error escape could only ever yield the generic string.
    vi.mocked(userGroupService.deleteGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This group operates Mortgage SIT. Reassign them before deleting it.' },
      },
    });

    const store = makeStore();
    const result = await store.dispatch(deleteUserGroup(1));

    expect(deleteUserGroup.rejected.match(result)).toBe(true);
    expect(result.payload).toBe(
      'This group operates Mortgage SIT. Reassign them before deleting it.'
    );
  });

  it('clears a stale error banner once fetchUserGroup succeeds', async () => {
    // Neither fetchUserGroup nor fetchGroupMembers has a pending handler, so
    // without an explicit clear on `fulfilled` a failed load's error banner
    // survives a later successful one — it just sits on the detail page.
    vi.mocked(userGroupService.getGroup).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'db unavailable' } },
    });
    const store = makeStore();
    await store.dispatch(fetchUserGroup(1));
    expect(store.getState().userGroup.error).toBe('db unavailable');

    vi.mocked(userGroupService.getGroup).mockResolvedValueOnce({
      id: 1,
      tenant_id: 1,
      name: 'Platform Ops',
      description: null,
      member_count: 0,
      environment_count: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    await store.dispatch(fetchUserGroup(1));
    expect(store.getState().userGroup.error).toBeNull();
  });

  it('clears a stale error banner once fetchGroupMembers succeeds', async () => {
    vi.mocked(userGroupService.listMembers).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'db unavailable' } },
    });
    const store = makeStore();
    await store.dispatch(fetchGroupMembers(1));
    expect(store.getState().userGroup.error).toBe('db unavailable');

    vi.mocked(userGroupService.listMembers).mockResolvedValueOnce({ rows: [], total: 0 });
    await store.dispatch(fetchGroupMembers(1));
    expect(store.getState().userGroup.error).toBeNull();
  });
});
