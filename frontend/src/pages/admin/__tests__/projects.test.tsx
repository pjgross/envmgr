import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import Projects, { projectColumns } from '../Projects';
import ProjectDetail, { gapBookingsHref } from '../ProjectDetail';
import projectReducer from '../../../store/projectSlice';
import userGroupReducer from '../../../store/userGroupSlice';
import { bookingService } from '../../../services/bookingService';
import { projectService } from '../../../services/projectService';
import { userGroupService } from '../../../services/userGroupService';
import { getLastDataGridProps } from '../../../test/dataGridMock';

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

// ProjectDetail's usage-agreement gap rollup (Phase 7 A3) counts through
// `GET /bookings` — there is no count endpoint, and A3 added no backend at
// all. `listBookings` reads `X-Total-Count`, so `limit: 1` buys the number
// without the rows.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn(),
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

  it('links the environment count to the project detail page, not a filter GET /environments does not support (Finding I2)', async () => {
    // GET /environments has no project_id filter — FastAPI silently drops
    // unknown query params, so that link used to show the whole unfiltered
    // estate. The project's own detail page's usage-agreements table is
    // exactly what this count counts.
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: '4' });
    expect(link).toHaveAttribute('href', '/tenant/projects/1');
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

  it('clears a previous create failure when the dialog is reopened (Finding 1)', async () => {
    // Trigger a 409, Cancel, wait for the dialog to unmount, reopen — the
    // fresh, untouched form must not carry the previous attempt's message.
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
    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /new project/i }));
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument();
  });

  it('surfaces the server reason when an edit is refused, not the axios status line', async () => {
    vi.mocked(projectService.updateProject).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "A project named 'Mortgage' already exists in this tenant" },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('surfaces the server reason when a delete is refused, not the axios status line', async () => {
    vi.mocked(projectService.deleteProject).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'Cannot delete a project with active usage agreements' },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    // MUI's Modal marks background content aria-hidden while the dialog is
    // open, so this second query resolves to the dialog's own Delete button
    // even though the (now-hidden) row button shares its accessible name.
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(screen.getByText(/active usage agreements/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('does not offer a per-column filter menu on the grid (docs/pagination.md)', async () => {
    // A raw DataGrid still offers a Filter menu on unsortable columns, which
    // would silently filter only the fetched window rather than the
    // server-paged set. The shared mock does not interpret this prop itself,
    // so this reads it back from the actual props the grid was rendered with.
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(getLastDataGridProps()?.disableColumnFilter).toBe(true);
  });

  it('refetches the list after a successful create rather than splicing the row in', async () => {
    vi.mocked(projectService.createProject).mockResolvedValue({
      id: 2,
      tenant_id: 1,
      name: 'New Project',
      code: null,
      description: null,
      team_group_id: null,
      team_group_name: null,
      environment_count: 0,
      is_active: true,
      created_at: '2026-01-02T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(projectService.listProjects).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /new project/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'New Project');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));

    // The list is a server-paged window: a fulfilled create has no reducer
    // handler (see projectSlice.ts), so the only way the new row appears is
    // a refetch of the whole page.
    await waitFor(() => expect(projectService.listProjects).toHaveBeenCalledTimes(2));
  });
});

function makeDetailStore(role: 'Admin' | 'Member' = 'Admin') {
  return configureStore({
    reducer: {
      project: projectReducer,
      userGroup: userGroupReducer,
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
}

/**
 * `store` and `projectId` are options rather than fixtures so a test can mount
 * the page TWICE against ONE store — the shape a mount-only test cannot see.
 * Redux state outlives an unmount, so whatever the first project left behind is
 * exactly what the second project's page starts from.
 */
function renderDetail(
  role: 'Admin' | 'Member' = 'Admin',
  options: {
    projectId?: number | string;
    store?: ReturnType<typeof makeDetailStore>;
  } = {}
) {
  const store = options.store ?? makeDetailStore(role);
  const projectId = options.projectId ?? 1;
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/tenant/projects/${projectId}`]}>
        <Routes>
          <Route path="/tenant/projects/:id" element={<ProjectDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

const AGREEMENT = {
  id: 10,
  tenant_id: 1,
  project_id: 1,
  project_name: 'Mortgage',
  environment_id: 9,
  environment_name: 'staging-a',
  starts_at: null,
  ends_at: null,
  notes: null,
  created_at: '2026-01-01T00:00:00Z',
};

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
    // The gap rollup's default: two of this project's bookings are in gap.
    // `rows` is deliberately empty — the page reads the total, never the rows.
    vi.mocked(bookingService.listBookings).mockResolvedValue({ rows: [], total: 2 });
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

  it('shows the add-agreement form and Remove buttons for an admin (Finding 2)', async () => {
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [AGREEMENT],
      total: 1,
    });
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(screen.getByRole('combobox', { name: 'Environment' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^add$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^remove$/i })).toBeInTheDocument();
    // Reads are open to any tenant member — an admin must see them too.
    expect(screen.getByText('staging-a')).toBeInTheDocument();
  });

  it('hides the add-agreement form and Remove buttons for a non-admin, who can still read the table (Finding 2)', async () => {
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [AGREEMENT],
      total: 1,
    });
    renderDetail('Member');
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(screen.queryByRole('combobox', { name: 'Environment' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^add$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^remove$/i })).not.toBeInTheDocument();
    // The read/write split is deliberate: GET is open to any tenant member,
    // only POST/DELETE are Admin-gated (see the module docblock).
    expect(screen.getByText('staging-a')).toBeInTheDocument();
  });

  it('surfaces the server reason when adding a usage agreement is refused, not the axios status line', async () => {
    vi.mocked(projectService.createAgreement).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This environment already has an agreement with this project' },
      },
    });
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('combobox', { name: 'Environment' }));
    await userEvent.click(await screen.findByRole('option', { name: 'staging-a' }));
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(screen.getByText(/already has an agreement/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('counts the bookings in gap from the filtered total, not from a page of rows', async () => {
    // `X-Total-Count` describes the whole filtered set; `rows` is one row's
    // worth of window. The mock returns an EMPTY rows array with total 2, so
    // a component that counted `rows.length` renders "No bookings in gap" and
    // fails here.
    renderDetail();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(await screen.findByText('2 bookings in gap')).toBeInTheDocument();
    expect(bookingService.listBookings).toHaveBeenCalledWith({
      project_id: 1,
      agreement_gap: true,
      limit: 1,
    });
  });

  it('asks for the same filtered set its link points at', async () => {
    // The count and the list the user lands on must be ONE query. Derived
    // from the link the page actually rendered rather than from a literal, so
    // changing one side without the other fails here.
    renderDetail();
    const link = await screen.findByRole('link', { name: /in gap/i });
    const href = link.getAttribute('href') ?? '';
    const url = new URL(href, 'http://localhost');
    expect(url.pathname).toBe('/bookings/list');
    expect(url.searchParams.get('project_id')).toBe('1');
    expect(url.searchParams.get('agreement_gap')).toBe('true');
    // And the request carries the same two values the URL does.
    const params = vi.mocked(bookingService.listBookings).mock.calls[0][0];
    expect(String(params?.project_id)).toBe(url.searchParams.get('project_id'));
    expect(String(params?.agreement_gap)).toBe(url.searchParams.get('agreement_gap'));
  });

  it('renders the rollup as a link even when nothing is in gap', async () => {
    vi.mocked(bookingService.listBookings).mockResolvedValue({ rows: [], total: 0 });
    renderDetail();
    const link = await screen.findByRole('link', { name: 'No bookings in gap' });
    expect(link).toHaveAttribute('href', gapBookingsHref(1));
  });

  it('says the count is unavailable when it could not be loaded, rather than showing no gaps', async () => {
    // A rollup nobody could compute must not read as a clean bill of health —
    // the partial-read rule the drift dialog already broke once. A component
    // falling back to 0 renders "No bookings in gap" and fails the second
    // assertion here.
    vi.mocked(bookingService.listBookings).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'Booking index unavailable' } },
    });
    renderDetail();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    expect(await screen.findByText(/bookings in gap: unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/^No bookings in gap$/)).not.toBeInTheDocument();
    // The server's reason, not the axios status line — the rollup goes through
    // a thunk, so `rejectWithValue(formatApiError(...))` is what carries it.
    expect(screen.getByText(/booking index unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('re-counts after an agreement is added, because recording one is what closes a gap', async () => {
    // A test that only ever mounts would pass against a page that fetches the
    // count once and never again — leaving the rollup reporting the gap the
    // user has just fixed, on the page they fixed it on.
    vi.mocked(bookingService.listBookings)
      .mockResolvedValueOnce({ rows: [], total: 2 })
      .mockResolvedValue({ rows: [], total: 1 });
    vi.mocked(projectService.createAgreement).mockResolvedValue(AGREEMENT);
    renderDetail('Admin');
    expect(await screen.findByText('2 bookings in gap')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('combobox', { name: 'Environment' }));
    await userEvent.click(await screen.findByRole('option', { name: 'staging-a' }));
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    expect(await screen.findByText('1 booking in gap')).toBeInTheDocument();
  });

  it('re-counts after an agreement is removed, because removing one can open a gap', async () => {
    // The mirror of the add path, and the one the reviewer found unguarded:
    // deleting the refetch on this path left every test in this directory
    // green (70 at the time). Removing an agreement can only ever OPEN gaps,
    // so a rollup left alone here under-reports on the very page that caused
    // it.
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [AGREEMENT],
      total: 1,
    });
    vi.mocked(projectService.deleteAgreement).mockResolvedValue(undefined);
    vi.mocked(bookingService.listBookings)
      .mockResolvedValueOnce({ rows: [], total: 1 })
      .mockResolvedValue({ rows: [], total: 3 });
    renderDetail('Admin');
    expect(await screen.findByText('1 booking in gap')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^remove$/i }));

    expect(await screen.findByText('3 bookings in gap')).toBeInTheDocument();
  });

  it('drops the previous project’s count while the next project’s is in flight (Finding I2)', async () => {
    // Two mounts, ONE store. Redux state outlives the unmount, so without the
    // thunk's `pending` handler project A's count is still sitting in the slice
    // when project B's page renders — and B's request failing leaves it there.
    // The page would then show A's number, under B's name, linking to B, on the
    // same line as "unavailable". Two contradictory answers, one of them
    // attributed to the wrong project.
    const store = makeDetailStore('Admin');
    const first = renderDetail('Admin', { store, projectId: 1 });
    expect(await screen.findByText('2 bookings in gap')).toBeInTheDocument();
    first.unmount();

    vi.mocked(projectService.getProject).mockResolvedValue({
      id: 2,
      tenant_id: 1,
      name: 'Pensions',
      code: 'PEN',
      description: null,
      team_group_id: null,
      team_group_name: null,
      environment_count: 0,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    vi.mocked(bookingService.listBookings).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'Booking index unavailable' } },
    });
    renderDetail('Admin', { store, projectId: 2 });

    expect(await screen.findByText('Pensions')).toBeInTheDocument();
    expect(await screen.findByText(/bookings in gap: unavailable/i)).toBeInTheDocument();
    // The stale number must be GONE, not merely accompanied by the caption.
    expect(screen.queryByRole('link', { name: /in gap/i })).not.toBeInTheDocument();
  });

  it('says the count spans every lifecycle status, not just live bookings', async () => {
    // `gap_clause` never looks at `Booking.status`, so "12 bookings in gap" on
    // a project with two live bookings and ten closed ones is literally true
    // and reads as current exposure. The admin guide says so; so must the page.
    renderDetail();
    expect(await screen.findByText('2 bookings in gap')).toBeInTheDocument();
    expect(screen.getByText(/any status .* closed included/i)).toBeInTheDocument();
  });

  it('refuses to render a rollup for an address that does not name a project (Finding M5)', async () => {
    // Same two-mount shape: nothing is dispatched for `Number('nope')`, so
    // every number on screen would belong to the project last viewed — beside a
    // link carrying `project_id=NaN`.
    const store = makeDetailStore('Admin');
    const first = renderDetail('Admin', { store, projectId: 1 });
    expect(await screen.findByText('2 bookings in gap')).toBeInTheDocument();
    first.unmount();

    renderDetail('Admin', { store, projectId: 'nope' });

    expect(await screen.findByText(/does not name a project/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /in gap/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Mortgage')).not.toBeInTheDocument();
    // And nothing was asked of the server on this second mount.
    expect(bookingService.listBookings).toHaveBeenCalledTimes(1);
    expect(projectService.getProject).toHaveBeenCalledTimes(1);
  });

  it('refuses to render a rollup for a project that could not be loaded (Finding I3)', async () => {
    // The valid-but-soft-deleted sibling of the test above: `Number.isInteger`
    // passes, the id is real, and `GET /projects/{id}` still 404s because
    // `get_project` filters `deleted_at`. Found by the browser pass, not by any
    // test — `/tenant/projects/1` rendered "Project not found" and, beneath it,
    // "0 agreements · 1 booking in gap" with a live link. The count is
    // CORRECT (a request still points at the deleted project, which is why that
    // booking is in gap), which makes it more convincing, not less.
    //
    // `listBookings` deliberately RESOLVES here: the count endpoint knows
    // nothing about the project being deleted, so the rollup would render
    // happily. Suppressing it has to come from the page.
    const notFound = {
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Project not found' } },
    };
    vi.mocked(projectService.getProject).mockRejectedValue(notFound);
    vi.mocked(projectService.listAgreementsForProject).mockRejectedValue(notFound);
    vi.mocked(bookingService.listBookings).mockResolvedValue({ rows: [], total: 1 });

    renderDetail('Admin');

    expect(await screen.findByText(/project not found/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /in gap/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/1 booking in gap/)).not.toBeInTheDocument();
    // Nor the rest of the section the number sits in — an Add form for a
    // project that does not exist is the same mistake one control along.
    expect(screen.queryByText('Usage Agreements')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^add$/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/agreements$/)).not.toBeInTheDocument();
  });

  it('keeps the not-found page suppressed even when a later load nulls the shared error (Finding I3)', async () => {
    // `projectSlice.error` is shared: `fetchProjectAgreements.fulfilled` sets it
    // to null, so a page that gated on the banner would come BACK once the
    // agreements request succeeded — rollup and all, with nothing left on
    // screen to say the project is missing. Gating on `current` is what makes
    // that impossible, and this is the test that tells the two gates apart.
    vi.mocked(projectService.getProject).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Project not found' } },
    });
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [AGREEMENT],
      total: 1,
    });
    vi.mocked(bookingService.listBookings).mockResolvedValue({ rows: [], total: 1 });

    renderDetail('Admin');

    await waitFor(() => expect(projectService.listAgreementsForProject).toHaveBeenCalled());
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    expect(screen.queryByRole('link', { name: /in gap/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Usage Agreements')).not.toBeInTheDocument();
    // The agreement row itself must not render either: it belongs to a project
    // this address could not resolve.
    expect(screen.queryByText('staging-a')).not.toBeInTheDocument();
  });

  it('states plainly that a gap warns and never blocks', async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());
    // The old copy promised enforcement was "a separate, later piece of work";
    // A3 shipped the warning, so that sentence became false. What must stay
    // true and stated: the booking is still created.
    expect(screen.getByText(/the booking is still created/i)).toBeInTheDocument();
    expect(screen.queryByText(/separate, later piece of work/i)).not.toBeInTheDocument();
  });

  it('surfaces the server reason when removing a usage agreement is refused, not the axios status line', async () => {
    vi.mocked(projectService.listAgreementsForProject).mockResolvedValue({
      rows: [AGREEMENT],
      total: 1,
    });
    vi.mocked(projectService.deleteAgreement).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'Cannot remove: a booking already exists for this environment' },
      },
    });
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Mortgage')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^remove$/i }));

    await waitFor(() =>
      expect(screen.getByText(/booking already exists/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
