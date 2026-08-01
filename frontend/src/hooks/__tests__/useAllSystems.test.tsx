import { configureStore } from '@reduxjs/toolkit';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import systemReducer from '../../store/systemSlice';
import type { SystemResponse } from '../../types/system';

// No HTTP — this test is about whether the hook reads its own fetch result
// or the shared system slice, not about what the server returns.
vi.mock('../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn(),
  },
}));

import { systemService } from '../../services/systemService';
import { useAllSystems } from '../useAllSystems';

const mockList = vi.mocked(systemService.listSystems);

// Real `systemReducer` (not a stub) so that if the hook ever regresses to
// `dispatch(fetchSystems())`, the fulfilled action would actually populate
// `system.systems` and the second test would catch it.
const SYSTEM_DEFAULTS = systemReducer(undefined, { type: '@@INIT' });

function makeStore(overrides: { system: Partial<typeof SYSTEM_DEFAULTS> }) {
  return configureStore({
    reducer: { system: systemReducer },
    preloadedState: { system: { ...SYSTEM_DEFAULTS, ...overrides.system } },
  });
}

function providerFor(store: ReturnType<typeof makeStore>) {
  return ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
}

describe('useAllSystems', () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it('fetches once and returns the systems', async () => {
    mockList.mockResolvedValue([
      { id: 1, name: 'System A' },
      { id: 2, name: 'System B' },
    ] as SystemResponse[]);
    const { result } = renderHook(() => useAllSystems());
    await waitFor(() => expect(result.current.systems).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared system slice', async () => {
    // The whole point: a later task turns state.system.systems into a 25-row
    // page. A picker must not be limited to it, and must not clobber it either.
    mockList.mockResolvedValue([{ id: 1, name: 'System A' }] as SystemResponse[]);
    const store = makeStore({
      system: { systems: [], currentSystem: null, subsystems: [], currentSubSystem: null, loading: false, error: null },
    });
    const { result } = renderHook(() => useAllSystems(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.systems).toHaveLength(1));
    expect(store.getState().system.systems).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllSystems());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.systems).toEqual([]);
  });
});
