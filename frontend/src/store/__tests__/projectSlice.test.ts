import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import projectReducer, {
  createProject,
  fetchEnvironmentAgreements,
  fetchProject,
  fetchProjectAgreements,
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

  // ── Finding I3: state.agreements and state.current are shared between
  // call sites one click apart, and neither thunk had a `pending` handler ──

  it('does not bleed agreements from the project direction into the environment direction', async () => {
    // fetchProjectAgreements (ProjectDetail) and fetchEnvironmentAgreements
    // (EnvironmentProjectsPanel) both write state.agreements. Reproduced:
    // dispatch fetchProjectAgreements(7) returning rows for OTHER
    // environments, then start fetchEnvironmentAgreements(3) — without a
    // `pending` handler, environment 3's panel would render project 7's
    // agreements for environments that are not environment 3, for the
    // whole time the second request is in flight.
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [
        { id: 1, environment_id: 9, environment_name: 'env-9' },
        { id: 2, environment_id: 10, environment_name: 'env-10' },
      ] as never,
      total: 2,
    });
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [],
      total: 0,
    });
    const store = makeStore();
    await store.dispatch(fetchProjectAgreements(7));
    expect(store.getState().project.agreements).toHaveLength(2);

    const inFlight = store.dispatch(fetchEnvironmentAgreements(3));
    // The pending handler must clear the stale rows synchronously, before
    // the mocked request for environment 3 has any chance to resolve.
    expect(store.getState().project.agreements).toEqual([]);
    await inFlight;
  });

  it('does not leave a stale table rendered under a failed reload', async () => {
    // EnvironmentProjectsPanel gates only its EMPTY message on a local
    // `loading` flag; the table itself renders whenever agreements.length >
    // 0. Without clearing agreements on `pending`, a failed reload left the
    // previous successful load's rows in state — so the error Alert
    // rendered with the stale table still below it, persistently, not as a
    // flash.
    vi.mocked(projectService.listAgreementsForEnvironment)
      .mockResolvedValueOnce({ rows: [{ id: 1 } as never], total: 1 })
      .mockRejectedValueOnce({
        isAxiosError: true,
        message: 'Request failed with status code 500',
        response: { status: 500, data: { detail: 'Could not load usage agreements' } },
      });
    const store = makeStore();
    await store.dispatch(fetchEnvironmentAgreements(3));
    expect(store.getState().project.agreements).toHaveLength(1);

    await store.dispatch(fetchEnvironmentAgreements(3));

    expect(store.getState().project.agreements).toEqual([]);
    expect(store.getState().project.error).toBeTruthy();
  });

  it('clears the previous project before the next one loads', async () => {
    // state.project.current has the same shape as the agreements bleed:
    // navigating project A -> project B must not momentarily show A's name,
    // code, team and status chip while B's fetch is in flight.
    vi.mocked(projectService.getProject)
      .mockResolvedValueOnce({ id: 1, name: 'Project A' } as never)
      .mockResolvedValueOnce({ id: 2, name: 'Project B' } as never);
    const store = makeStore();
    await store.dispatch(fetchProject(1));
    expect(store.getState().project.current?.name).toBe('Project A');

    const inFlight = store.dispatch(fetchProject(2));
    expect(store.getState().project.current).toBeNull();
    await inFlight;
    expect(store.getState().project.current?.name).toBe('Project B');
  });
});
