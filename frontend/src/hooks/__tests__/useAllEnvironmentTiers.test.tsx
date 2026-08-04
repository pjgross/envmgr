import { configureStore } from '@reduxjs/toolkit';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import environmentTierReducer from '../../store/environmentTierSlice';
import type { EnvironmentTierResponse } from '../../types/environmentTier';

// No HTTP — this test is about whether the hook reads its own fetch result
// or the shared environmentTier slice, not about what the server returns.
vi.mock('../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn(),
  },
}));

import { environmentTierService } from '../../services/environmentTierService';
import { useAllEnvironmentTiers } from '../useAllEnvironmentTiers';

const mockList = vi.mocked(environmentTierService.listTiers);

// Real `environmentTierReducer` (not a stub) so that if the hook ever
// regresses to `dispatch(fetchEnvironmentTiers())`, the fulfilled action
// would actually populate `environmentTier.tiers` and the second test would
// catch it.
const ENVIRONMENT_TIER_DEFAULTS = environmentTierReducer(undefined, { type: '@@INIT' });

function makeStore(overrides: { environmentTier: Partial<typeof ENVIRONMENT_TIER_DEFAULTS> }) {
  return configureStore({
    reducer: { environmentTier: environmentTierReducer },
    preloadedState: {
      environmentTier: { ...ENVIRONMENT_TIER_DEFAULTS, ...overrides.environmentTier },
    },
  });
}

function providerFor(store: ReturnType<typeof makeStore>) {
  return ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
}

describe('useAllEnvironmentTiers', () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it('fetches once and returns the tiers', async () => {
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'SIT' },
        { id: 2, name: 'UAT' },
      ] as EnvironmentTierResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllEnvironmentTiers());
    await waitFor(() => expect(result.current.tiers).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared environmentTier slice', async () => {
    // The whole point: the admin panel is about to load state.environmentTier
    // .tiers as its own working list. A picker must not be limited to it, and
    // must not clobber it either.
    mockList.mockResolvedValue({
      rows: [{ id: 1, name: 'SIT' }] as EnvironmentTierResponse[],
      total: 1,
    });
    const store = makeStore({ environmentTier: { tiers: [], total: 0, loading: false, error: null } });
    const { result } = renderHook(() => useAllEnvironmentTiers(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.tiers).toHaveLength(1));
    expect(store.getState().environmentTier.tiers).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllEnvironmentTiers());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tiers).toEqual([]);
  });

  it('reports truncated when the server has more rows than were fetched', async () => {
    mockList.mockResolvedValue({
      rows: [{ id: 1, name: 'SIT' }] as EnvironmentTierResponse[],
      total: 5,
    });
    const { result } = renderHook(() => useAllEnvironmentTiers());
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
      ] as EnvironmentTierResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllEnvironmentTiers());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(false);
  });

  it('coalesces two consumers mounting in the same commit into one request', async () => {
    mockList.mockResolvedValue({ rows: [], total: 0 });
    const { result: a } = renderHook(() => useAllEnvironmentTiers());
    const { result: b } = renderHook(() => useAllEnvironmentTiers());
    await waitFor(() => expect(a.current.loading).toBe(false));
    await waitFor(() => expect(b.current.loading).toBe(false));
    expect(mockList).toHaveBeenCalledTimes(1);
  });
});
