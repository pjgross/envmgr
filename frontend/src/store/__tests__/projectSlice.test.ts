import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import projectReducer, {
  createProject,
  fetchProject,
  fetchProjects,
} from '../projectSlice';
import { projectService } from '../../services/projectService';

vi.mock('../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn(),
    getProject: vi.fn(),
    createProject: vi.fn(),
    updateProject: vi.fn(),
    deleteProject: vi.fn(),
    listAgreementsForProject: vi.fn(),
    listAgreementsForEnvironment: vi.fn(),
    createAgreement: vi.fn(),
    deleteAgreement: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { project: projectReducer } });
}

describe('projectSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores the server total, not the row count', async () => {
    // The total is what tells a paged grid there is more; deriving it from
    // rows.length would report the page size as the whole set.
    vi.mocked(projectService.listProjects).mockResolvedValue({
      rows: [{ id: 1, name: 'Mortgage' }] as never,
      total: 42,
    });
    const store = makeStore();
    await store.dispatch(fetchProjects({}));
    expect(store.getState().project.projects).toHaveLength(1);
    expect(store.getState().project.total).toBe(42);
  });

  it('surfaces the server reason when a create is refused', async () => {
    // AxiosError SHAPE: generic text on .message, the reason only at
    // response.data.detail. A plain Error carrying the final text would pass
    // against broken code, because miniSerializeError keeps .message.
    vi.mocked(projectService.createProject).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "A project named 'Mortgage' already exists in this tenant" },
      },
    });
    const store = makeStore();
    const result = await store.dispatch(createProject({ name: 'Mortgage' }));
    expect(createProject.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('already exists');
  });

  it('leaves the paged list alone when a create succeeds', async () => {
    // The list is a server-paged window. Splicing the new row in locally
    // desynchronises the page from its total and from the sort order the
    // server applied — pages refetch instead. Enforced only by a comment until
    // this test existed: adding a createProject.fulfilled handler that pushed
    // onto state.projects broke nothing.
    vi.mocked(projectService.listProjects).mockResolvedValue({
      rows: [{ id: 1, name: 'Mortgage' }] as never,
      total: 42,
    });
    vi.mocked(projectService.createProject).mockResolvedValue({
      id: 2,
      name: 'Savings',
    } as never);
    const store = makeStore();
    await store.dispatch(fetchProjects({}));

    await store.dispatch(createProject({ name: 'Savings' }));

    expect(store.getState().project.projects).toHaveLength(1);
    expect(store.getState().project.total).toBe(42);
  });

  it('clears a stale error banner once a fetch succeeds', async () => {
    // Without the reset, a failed load leaves its message on screen through
    // every later successful one, so the page reads as broken while working.
    //
    // Note only the READ thunks touch state.error. A refused create or delete
    // returns its reason through rejectWithValue for the dialog that caused it
    // to render — a mutation error does not belong in the page banner.
    vi.mocked(projectService.getProject)
      .mockRejectedValueOnce({
        isAxiosError: true,
        message: 'Request failed with status code 500',
        response: { status: 500, data: { detail: 'boom' } },
      })
      .mockResolvedValueOnce({ id: 1, name: 'Mortgage' } as never);
    const store = makeStore();
    await store.dispatch(fetchProject(1));
    expect(store.getState().project.error).toBeTruthy();

    await store.dispatch(fetchProject(1));

    expect(store.getState().project.error).toBeNull();
  });
});
