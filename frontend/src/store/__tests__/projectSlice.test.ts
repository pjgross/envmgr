import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import projectReducer, { createProject, fetchProjects } from '../projectSlice';
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
});
