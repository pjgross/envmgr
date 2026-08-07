import { configureStore } from '@reduxjs/toolkit';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import projectReducer from '../../store/projectSlice';
import type { ProjectResponse } from '../../types/project';

// No HTTP — this test is about whether the hook reads its own fetch result
// or the shared project slice, not about what the server returns.
vi.mock('../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn(),
  },
}));

import { projectService } from '../../services/projectService';
import { useAllProjects } from '../useAllProjects';

const mockList = vi.mocked(projectService.listProjects);

// Real `projectReducer` (not a stub) so that if the hook ever regresses to
// `dispatch(fetchProjects())`, the fulfilled action would actually populate
// `project.projects` and the second test would catch it.
const PROJECT_DEFAULTS = projectReducer(undefined, { type: '@@INIT' });

function makeStore(overrides: { project: Partial<typeof PROJECT_DEFAULTS> }) {
  return configureStore({
    reducer: { project: projectReducer },
    preloadedState: { project: { ...PROJECT_DEFAULTS, ...overrides.project } },
  });
}

function providerFor(store: ReturnType<typeof makeStore>) {
  return ({ children }: { children: ReactNode }) => <Provider store={store}>{children}</Provider>;
}

describe('useAllProjects', () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it('fetches once and returns the projects', async () => {
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'Project A' },
        { id: 2, name: 'Project B' },
      ] as ProjectResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllProjects());
    await waitFor(() => expect(result.current.projects).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared project slice', async () => {
    // The whole point: state.project.projects is BookingList's/ReleaseList's
    // current server-paged filter slice, not every project. A picker must
    // not be limited to it, and must not clobber it either.
    mockList.mockResolvedValue({ rows: [{ id: 1, name: 'Project A' }] as ProjectResponse[], total: 1 });
    const store = makeStore({
      project: { projects: [], total: 0, current: null, agreements: [], agreementTotal: 0, loading: false, error: null },
    });
    const { result } = renderHook(() => useAllProjects(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    expect(store.getState().project.projects).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllProjects());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.projects).toEqual([]);
  });

  it('reports truncated when the server has more rows than were fetched', async () => {
    mockList.mockResolvedValue({ rows: [{ id: 1, name: 'Project A' }] as ProjectResponse[], total: 5 });
    const { result } = renderHook(() => useAllProjects());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(true);
  });

  it('reports not truncated when every row was fetched', async () => {
    // Discriminates against the rejected `rows.length === LIMIT` proxy: the
    // row count here doesn't happen to equal the request limit, it equals
    // the server's total, which is the only thing that should matter.
    mockList.mockResolvedValue({
      rows: [
        { id: 1, name: 'Project A' },
        { id: 2, name: 'Project B' },
      ] as ProjectResponse[],
      total: 2,
    });
    const { result } = renderHook(() => useAllProjects());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.truncated).toBe(false);
  });

  // Finding 4: fetching every project rather than only active ones would
  // leave archived projects offered as valid choices in every picker and
  // filter this hook feeds. Dropping `is_active: true` here would not be
  // caught by any of the tests above, since none inspects the call params.
  it('fetches only active projects', async () => {
    mockList.mockResolvedValue({ rows: [], total: 0 });
    renderHook(() => useAllProjects());
    await waitFor(() =>
      expect(mockList).toHaveBeenCalledWith(expect.objectContaining({ is_active: true }))
    );
  });
});
