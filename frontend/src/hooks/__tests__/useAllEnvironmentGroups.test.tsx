import { configureStore } from '@reduxjs/toolkit';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import environmentGroupReducer from '../../store/environmentGroupSlice';
import type { EnvironmentGroupResponse } from '../../types/environmentGroup';

// No HTTP — this test is about whether the hook reads its own fetch result
// or the shared environmentGroup slice, not about what the server returns.
vi.mock('../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroups: vi.fn(),
  },
}));

import { environmentGroupService } from '../../services/environmentGroupService';
import { useAllEnvironmentGroups } from '../useAllEnvironmentGroups';

const mockList = vi.mocked(environmentGroupService.listGroups);

// Real `environmentGroupReducer` (not a stub) so that if the hook ever
// regresses to `dispatch(fetchEnvironmentGroups())`, the fulfilled action
// would actually populate `environmentGroup.groups` and the second test
// would catch it.
const ENV_GROUP_DEFAULTS = environmentGroupReducer(undefined, { type: '@@INIT' });

function makeStore(overrides: { environmentGroup: Partial<typeof ENV_GROUP_DEFAULTS> }) {
  return configureStore({
    reducer: { environmentGroup: environmentGroupReducer },
    preloadedState: {
      environmentGroup: { ...ENV_GROUP_DEFAULTS, ...overrides.environmentGroup },
    },
  });
}

function providerFor(store: ReturnType<typeof makeStore>) {
  return ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
}

describe('useAllEnvironmentGroups', () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it('fetches once and returns the groups', async () => {
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'Payments squad' },
        { id: 2, name: 'Data squad' },
      ] as EnvironmentGroupResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllEnvironmentGroups());
    await waitFor(() => expect(result.current.groups).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared environmentGroup slice', async () => {
    // The whole point: state.environmentGroup.groups is the admin page's
    // current server-paged filter slice, not every group. A picker must not
    // be limited to it, and must not clobber it either.
    mockList.mockResolvedValue({
      rows: [{ id: 1, name: 'Payments squad' }] as EnvironmentGroupResponse[],
      total: 1,
    });
    const store = makeStore({
      environmentGroup: {
        groups: [],
        total: 0,
        current: null,
        members: [],
        memberTotal: 0,
        loading: false,
        error: null,
      },
    });
    const { result } = renderHook(() => useAllEnvironmentGroups(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.groups).toHaveLength(1));
    expect(store.getState().environmentGroup.groups).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllEnvironmentGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.groups).toEqual([]);
  });

  it('reports truncated when the server has more rows than were fetched', async () => {
    mockList.mockResolvedValue({
      rows: [{ id: 1, name: 'Payments squad' }] as EnvironmentGroupResponse[],
      total: 5,
    });
    const { result } = renderHook(() => useAllEnvironmentGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(true);
  });

  it('reports not truncated when every row was fetched', async () => {
    // Discriminates against the rejected `rows.length === LIMIT` proxy: the
    // row count here doesn't happen to equal the request limit, it equals
    // the server's total, which is the only thing that should matter.
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'Payments squad' },
        { id: 2, name: 'Data squad' },
      ] as EnvironmentGroupResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllEnvironmentGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(false);
  });

  // Every consumer of this hook is a picker or filter, never a form
  // preserving an existing archived value. Dropping `is_active: true` here
  // would not be caught by any of the tests above, since none inspects the
  // call params.
  it('fetches only active groups', async () => {
    mockList.mockResolvedValue({ rows: [], total: 0 });
    renderHook(() => useAllEnvironmentGroups());
    await waitFor(() =>
      expect(mockList).toHaveBeenCalledWith(expect.objectContaining({ is_active: true }))
    );
  });
});
