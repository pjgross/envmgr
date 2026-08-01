import { configureStore } from '@reduxjs/toolkit';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import infrastructureComponentReducer from '../../store/infrastructureComponentSlice';
import type { InfrastructureComponentResponse } from '../../types/infrastructureComponent';

// No HTTP — this test is about whether the hook reads its own fetch result
// or the shared infrastructureComponent slice, not about what the server returns.
vi.mock('../../services/infrastructureComponentService', () => ({
  infrastructureComponentService: {
    listComponents: vi.fn(),
  },
}));

import { infrastructureComponentService } from '../../services/infrastructureComponentService';
import { useAllHosts } from '../useAllHosts';

const mockList = vi.mocked(infrastructureComponentService.listComponents);

// Real `infrastructureComponentReducer` (not a stub) so that if the hook ever
// regresses to `dispatch(fetchInfrastructureComponents())`, the fulfilled
// action would actually populate `infrastructureComponent.components` and the
// second test would catch it.
const INFRASTRUCTURE_COMPONENT_DEFAULTS = infrastructureComponentReducer(undefined, {
  type: '@@INIT',
});

function makeStore(overrides: {
  infrastructureComponent: Partial<typeof INFRASTRUCTURE_COMPONENT_DEFAULTS>;
}) {
  return configureStore({
    reducer: { infrastructureComponent: infrastructureComponentReducer },
    preloadedState: {
      infrastructureComponent: {
        ...INFRASTRUCTURE_COMPONENT_DEFAULTS,
        ...overrides.infrastructureComponent,
      },
    },
  });
}

function providerFor(store: ReturnType<typeof makeStore>) {
  return ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
}

describe('useAllHosts', () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it('fetches once and returns the hosts', async () => {
    mockList.mockResolvedValue([
      { id: 1, name: 'host-a' },
      { id: 2, name: 'host-b' },
    ] as InfrastructureComponentResponse[]);
    const { result } = renderHook(() => useAllHosts());
    await waitFor(() => expect(result.current.hosts).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared infrastructureComponent slice', async () => {
    // The whole point: InfrastructureComponentList is about to turn
    // state.infrastructureComponent.components into a 25-row page. A picker
    // must not be limited to it, and must not clobber it either.
    mockList.mockResolvedValue([{ id: 1, name: 'host-a' }] as InfrastructureComponentResponse[]);
    const store = makeStore({
      infrastructureComponent: { components: [], loading: false, error: null },
    });
    const { result } = renderHook(() => useAllHosts(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.hosts).toHaveLength(1));
    expect(store.getState().infrastructureComponent.components).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllHosts());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.hosts).toEqual([]);
  });
});
