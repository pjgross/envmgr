import { configureStore } from '@reduxjs/toolkit';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import environmentReducer from '../../store/environmentSlice';
import type { EnvironmentResponse } from '../../types/environment';

// No HTTP — this test is about whether the hook reads its own fetch result
// or the shared environment slice, not about what the server returns.
vi.mock('../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn(),
  },
}));

import { environmentService } from '../../services/environmentService';
import { useAllEnvironments } from '../useAllEnvironments';

const mockList = vi.mocked(environmentService.listEnvironments);

// Real `environmentReducer` (not a stub) so that if the hook ever regresses
// to `dispatch(fetchEnvironments())`, the fulfilled action would actually
// populate `environment.environments` and the second test would catch it.
const ENVIRONMENT_DEFAULTS = environmentReducer(undefined, { type: '@@INIT' });

function makeStore(overrides: { environment: Partial<typeof ENVIRONMENT_DEFAULTS> }) {
  return configureStore({
    reducer: { environment: environmentReducer },
    preloadedState: { environment: { ...ENVIRONMENT_DEFAULTS, ...overrides.environment } },
  });
}

function providerFor(store: ReturnType<typeof makeStore>) {
  return ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
}

describe('useAllEnvironments', () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it('fetches once and returns the environments', async () => {
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'SIT' },
        { id: 2, name: 'UAT' },
      ] as EnvironmentResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllEnvironments());
    await waitFor(() => expect(result.current.environments).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared environment slice', async () => {
    // The whole point: EnvironmentList is about to turn state.environment
    // .environments into a 25-row page. A picker must not be limited to it,
    // and must not clobber it either.
    mockList.mockResolvedValue({ rows: [{ id: 1, name: 'SIT' }] as EnvironmentResponse[], total: 1 });
    const store = makeStore({ environment: { environments: [], loading: false, error: null } });
    const { result } = renderHook(() => useAllEnvironments(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.environments).toHaveLength(1));
    expect(store.getState().environment.environments).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllEnvironments());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.environments).toEqual([]);
  });

  it('reports truncated when the server has more rows than were fetched', async () => {
    mockList.mockResolvedValue({ rows: [{ id: 1, name: 'SIT' }] as EnvironmentResponse[], total: 5 });
    const { result } = renderHook(() => useAllEnvironments());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(true);
  });

  it('reports not truncated when every row was fetched', async () => {
    // Discriminates against the rejected `rows.length === LIMIT` proxy: the
    // row count here doesn't happen to equal the request limit, it equals
    // the server's total, which is the only thing that should matter.
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'SIT' },
        { id: 2, name: 'UAT' },
      ] as EnvironmentResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllEnvironments());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(false);
  });
});
