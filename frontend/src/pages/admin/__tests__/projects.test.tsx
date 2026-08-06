import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import Projects, { projectColumns } from '../Projects';
import ProjectDetail from '../ProjectDetail';
import projectReducer from '../../../store/projectSlice';
import userGroupReducer from '../../../store/userGroupSlice';
import { projectService } from '../../../services/projectService';
import { userGroupService } from '../../../services/userGroupService';

vi.mock('../../../services/projectService', () => ({
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

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn(),
    getGroup: vi.fn(),
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
  },
}));

// ProjectDetail sources its environment picker from the shared
// useAllEnvironments hook (in-flight-coalescing, see hooks/useAllEnvironments)
// rather than any service call the page owns directly — stub the hook itself.
vi.mock('../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: () => ({
    environments: [{ id: 9, name: 'staging-a' }],
    loading: false,
    truncated: false,
  }),
}));

// The shared stand-in resolves a cell through both `renderCell` and
// `valueGetter` — see dataGridMock.tsx. Used rather than a local
// renderCell-only copy per the task brief.
vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  const { createDataGridMock } = await import('../../../test/dataGridMock');
  return { ...actual, ...createDataGridMock() };
});

describe('projectColumns', () => {
  it('marks every column the backend cannot sort as unsortable', () => {
    const sortable = projectColumns
      .filter((c) => c.sortable !== false)
      .map((c) => c.field)
      .sort();
    // Exactly the whitelist. Asserting the whole set — rather than checking a
    // few columns individually — is what makes a NEW column fail this test
    // until someone decides whether the backend can sort it.
    expect(sortable).toEqual(['code', 'name']);
  });

  it('never makes the joined and computed columns sortable', () => {
    // team_group_name comes from an outer join and environment_count from a
    // correlated subquery. Neither is backed by a single column, so neither
    // can ever be whitelisted — this is permanent, not a gap to fill later.
    for (const field of ['team_group_name', 'environment_count']) {
      expect(projectColumns.find((c) => c.field === field)?.sortable).toBe(false);
    }
  });

  it('renders a missing team as prose rather than a blank cell', () => {
    const column = projectColumns.find((c) => c.field === 'team_group_name');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rendered = column?.renderCell?.({ value: null } as any);
    expect(rendered).toBe('— no team');
  });
});

function renderPage(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      project: projectReducer,
      userGroup: userGroupReducer,
      // Minimal stand-in — the page only reads `state.auth.user`.
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/tenant/projects']}>
        <Projects />
      </MemoryRouter>
    </Provider>
  );
}

describe('Projects', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(projectService.listProjects).mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'Mortgage',
          code: 'MTG',
          description: 'Mortgage origination platform',
          team_group_id: 5,
          team_group_name: 'Platform Ops',
          environment_count: 4,
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
    vi.mocked(userGroupService.listGroups).mockResolvedValue({
      rows: [
        {
          id: 5,
          tenant_id: 1,
          name: 'Platform Ops',
          description: null,
          member_count: 3,
          environment_count: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
  });

  it('renders the team name and environment count from the row the API returned', async () => {
    // Neither value is looked up against a separately-fetched collection —
    // both travel with the row, the way ReleaseSystemRead carries system_name.
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(screen.getByText('Platform Ops')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
  });

  it('links the environment count to the project-filtered environments list', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: '4' });
    expect(link).toHaveAttribute('href', '/environments?project_id=1');
  });

  it('surfaces the server reason when a create is refused, not the axios status line', async () => {
    // A plain `Error` carrying the final text would pass against broken code
    // that reads `result.error.message`, because miniSerializeError keeps
    // `.message` — this rejection is shaped like the real AxiosError instead.
    vi.mocked(projectService.createProject).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "A project named 'Mortgage' already exists in this tenant" },
      },
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /new project/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'Mortgage');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() =>
      expect(screen.getByText(/already exists/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('shows the list but not the write controls for a non-admin', async () => {
    renderPage('Member');
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /new project/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it('shows the write controls for an admin', async () => {
    renderPage('Admin');
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /new project/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument();
  });
});

function renderDetail(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      project: projectReducer,
      userGroup: userGroupReducer,
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/tenant/projects/1']}>
        <Routes>
          <Route path="/tenant/projects/:id" element={<ProjectDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

describe('ProjectDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(projectService.getProject).mockResolvedValue({
      id: 1,
      tenant_id: 1,
      name: 'Mortgage',
      code: 'MTG',
      description: 'Mortgage origination platform',
      team_group_id: 5,
      team_group_name: 'Platform Ops',
      environment_count: 1,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [],
      total: 0,
    });
  });

  it('states the usage agreements section is a record, not an enforced rule', async () => {
    // Nothing in A1 stops this project booking an environment it has no
    // agreement for — enforcement is sub-project A3. Without this line the
    // first person to see the section will assume it is already enforced.
    renderDetail();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(
      screen.getByText(/is a record .* not a rule|nothing here stops/i)
    ).toBeInTheDocument();
  });
});
