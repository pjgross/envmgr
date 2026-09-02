import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import EnvironmentGroups, { environmentGroupColumns } from '../EnvironmentGroups';
import EnvironmentGroupDetail from '../EnvironmentGroupDetail';
import environmentGroupReducer from '../../../store/environmentGroupSlice';
import { environmentGroupService } from '../../../services/environmentGroupService';
import { useAllEnvironments } from '../../../hooks/useAllEnvironments';
import { getLastDataGridProps } from '../../../test/dataGridMock';

vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroups: vi.fn(),
    getGroup: vi.fn(),
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
    listMembers: vi.fn(),
    listGroupsForEnvironment: vi.fn(),
    addMember: vi.fn(),
    removeMember: vi.fn(),
    transitionGroup: vi.fn(),
    groupAllowedTransitions: vi.fn(),
  },
}));

// EnvironmentGroupDetail sources its "add environment" picker from the shared
// useAllEnvironments hook (in-flight-coalescing, see hooks/useAllEnvironments)
// rather than any service call the page owns directly — stub the hook itself,
// the way projects.test.tsx does for ProjectDetail.
vi.mock('../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: vi.fn(() => ({
    environments: [
      { id: 9, name: 'staging-a' },
      { id: 10, name: 'staging-b' },
    ],
    loading: false,
    truncated: false,
  })),
}));

// The shared stand-in resolves a cell through both `renderCell` and
// `valueGetter` — see dataGridMock.tsx.
vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  const { createDataGridMock } = await import('../../../test/dataGridMock');
  return { ...actual, ...createDataGridMock() };
});

describe('environmentGroupColumns', () => {
  it('marks every column the backend cannot sort as unsortable', () => {
    const sortable = environmentGroupColumns
      .filter((c) => c.sortable !== false)
      .map((c) => c.field)
      .sort();
    // The whole set, so a NEW column fails this test until someone decides
    // whether the backend can sort it.
    expect(sortable).toEqual(['name']);
  });

  it('never makes the computed member count sortable', () => {
    expect(
      environmentGroupColumns.find((c) => c.field === 'member_count')?.sortable
    ).toBe(false);
  });
});

function renderList(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      environmentGroup: environmentGroupReducer,
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/environment-groups']}>
        <EnvironmentGroups />
      </MemoryRouter>
    </Provider>
  );
}

const GROUP = {
  id: 1,
  tenant_id: 1,
  name: 'Payments regression',
  description: 'Environments used for the payments regression suite',
  member_count: 3,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('EnvironmentGroups', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentGroupService.listGroups).mockResolvedValue({
      rows: [GROUP],
      total: 1,
    });
  });

  it('renders the member count from the row the API returned', async () => {
    // Not resolved against a separately-fetched collection — travels with the
    // row, the way ReleaseSystemRead carries system_name.
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('surfaces the server reason when a create is refused, not the axios status line', async () => {
    // A plain `Error` carrying the final text would pass against broken code
    // that reads `result.error.message`, because miniSerializeError keeps
    // `.message` — this rejection is shaped like the real AxiosError instead.
    vi.mocked(environmentGroupService.createGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "An environment group named 'Payments regression' already exists" },
      },
    });
    renderList();

    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /new group/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'Payments regression');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() =>
      expect(screen.getByText(/already exists/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('clears a previous create failure when the dialog is reopened', async () => {
    // Trigger a 409, Cancel, wait for the dialog to unmount, reopen — the
    // fresh, untouched form must not carry the previous attempt's message.
    // Projects.tsx was fixed for exactly this; UserGroups.tsx still has the bug.
    vi.mocked(environmentGroupService.createGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "An environment group named 'Payments regression' already exists" },
      },
    });
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /new group/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'Payments regression');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /new group/i }));
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument();
  });

  it('surfaces the server reason when an edit is refused, not the axios status line', async () => {
    vi.mocked(environmentGroupService.updateGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "An environment group named 'Payments regression' already exists" },
      },
    });
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('surfaces the server reason when a delete is refused, not the axios status line', async () => {
    vi.mocked(environmentGroupService.deleteGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'Cannot delete a group with active bookings' },
      },
    });
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    // MUI's Modal marks background content aria-hidden while the dialog is
    // open, so this second query resolves to the dialog's own Delete button
    // even though the (now-hidden) row button shares its accessible name.
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(screen.getByText(/active bookings/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('shows the list but not the write controls for a non-admin', async () => {
    renderList('Member');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /new group/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it('shows the write controls for an admin', async () => {
    renderList('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /new group/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument();
  });

  it('does not offer a per-column filter menu on the grid (docs/pagination.md)', async () => {
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(getLastDataGridProps()?.disableColumnFilter).toBe(true);
  });

  it('refetches the list after a successful create rather than splicing the row in', async () => {
    vi.mocked(environmentGroupService.createGroup).mockResolvedValue({
      id: 2,
      tenant_id: 1,
      name: 'New group',
      description: null,
      member_count: 0,
      is_active: true,
      created_at: '2026-01-02T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    });
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(environmentGroupService.listGroups).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /new group/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'New group');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));

    // The slice deliberately has no fulfilled handler for create (see
    // environmentGroupSlice.ts) — the only way the new row appears is a
    // refetch of the whole list.
    await waitFor(() => expect(environmentGroupService.listGroups).toHaveBeenCalledTimes(2));
  });

  it('refetches the list after a successful edit rather than splicing the row in', async () => {
    vi.mocked(environmentGroupService.updateGroup).mockResolvedValue({
      ...GROUP,
      name: 'Payments regression (renamed)',
    });
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(environmentGroupService.listGroups).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    // The slice deliberately has no fulfilled handler for update (see
    // environmentGroupSlice.ts) — the only way a rename appears is a
    // refetch of the whole list.
    await waitFor(() => expect(environmentGroupService.listGroups).toHaveBeenCalledTimes(2));
  });

  it('refetches the list after a successful delete rather than splicing the row out', async () => {
    vi.mocked(environmentGroupService.deleteGroup).mockResolvedValue(undefined);
    renderList();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(environmentGroupService.listGroups).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    // MUI's Modal marks background content aria-hidden while the dialog is
    // open, so this second query resolves to the dialog's own Delete button.
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    // The slice deliberately has no fulfilled handler for delete (see
    // environmentGroupSlice.ts) — the only way the row disappears is a
    // refetch of the whole list.
    await waitFor(() => expect(environmentGroupService.listGroups).toHaveBeenCalledTimes(2));
  });
});

function renderDetail(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      environmentGroup: environmentGroupReducer,
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/environment-groups/1']}>
        <Routes>
          <Route path="/environment-groups/:id" element={<EnvironmentGroupDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

const MEMBER = {
  id: 20,
  tenant_id: 1,
  group_id: 1,
  group_name: 'Payments regression',
  environment_id: 9,
  environment_name: 'staging-a',
  created_at: '2026-01-01T00:00:00Z',
};

describe('EnvironmentGroupDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentGroupService.getGroup).mockResolvedValue(GROUP);
    vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
      rows: [],
      total: 0,
    });
  });

  // `mockReturnValue` (not `Once`) sticks around across renders within a test, but
  // that also means it leaks into every test that runs after this one unless something
  // puts the default back — restore it here, mirroring EnvironmentCompare.test.tsx.
  afterEach(() => {
    vi.mocked(useAllEnvironments).mockReturnValue({
      environments: [
        { id: 9, name: 'staging-a' },
        { id: 10, name: 'staging-b' },
      ],
      loading: false,
      truncated: false,
    } as ReturnType<typeof useAllEnvironments>);
  });

  it('states that changing membership does not affect existing bookings', async () => {
    // Membership is frozen at booking time. Without this line an admin
    // removing an environment will reasonably assume they have cancelled its
    // bookings — this is exactly the kind of copy a later tidy-up drops.
    renderDetail();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(
      screen.getByText(/does not affect existing bookings/i)
    ).toBeInTheDocument();
  });

  it('renders environment names from the member rows the API returned, not a resolved collection', async () => {
    // environment_id 99 is deliberately absent from useAllEnvironments' mocked
    // list (ids 9/10) — if the table resolved names via `.find()` against
    // that capped collection instead of reading environment_name off the
    // row, this environment would render `—`, not its real name.
    vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
      rows: [{ ...MEMBER, environment_id: 99, environment_name: 'prod-eu' }],
      total: 1,
    });
    renderDetail();
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(screen.getByText('prod-eu')).toBeInTheDocument();
  });

  it('shows the add-environment form and Remove buttons for an admin, and the members table for anyone', async () => {
    // environment_id 77 is deliberately absent from useAllEnvironments' mocked
    // list (ids 9/10) — MEMBER's own environment_id (9) coincides with that
    // list, which would let a `.find()`-against-the-picker-collection bug pass
    // this test undetected. See the dedicated coincidence test below for why.
    vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
      rows: [{ ...MEMBER, environment_id: 77, environment_name: 'canary' }],
      total: 1,
    });
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(screen.getByRole('combobox', { name: 'Environment' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^add$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^remove$/i })).toBeInTheDocument();
    expect(screen.getByText('canary')).toBeInTheDocument();
  });

  it('hides the add-environment form and Remove buttons for a non-admin, who can still read the members table', async () => {
    // Same coincidence risk as the admin test above — environment_id 77 is
    // absent from the mocked environments list, so this stays a real test of
    // reading `environment_name` off the row.
    vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
      rows: [{ ...MEMBER, environment_id: 77, environment_name: 'canary' }],
      total: 1,
    });
    renderDetail('Member');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(screen.queryByRole('combobox', { name: 'Environment' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^add$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^remove$/i })).not.toBeInTheDocument();
    // The read/write split is deliberate: GET is open to any tenant member,
    // only POST/DELETE are Admin-gated.
    expect(screen.getByText('canary')).toBeInTheDocument();
  });

  it('surfaces the server reason when adding a member is refused, not the axios status line', async () => {
    vi.mocked(environmentGroupService.addMember).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This environment is already a member of this group' },
      },
    });
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('combobox', { name: 'Environment' }));
    await userEvent.click(await screen.findByRole('option', { name: 'staging-a' }));
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(screen.getByText(/already a member/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('surfaces the server reason when removing a member is refused, not the axios status line', async () => {
    vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
      rows: [MEMBER],
      total: 1,
    });
    vi.mocked(environmentGroupService.removeMember).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'Cannot remove: an active booking references this membership' },
      },
    });
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^remove$/i }));

    await waitFor(() =>
      expect(screen.getByText(/active booking references/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('refetches members after a successful add rather than splicing the row in', async () => {
    vi.mocked(environmentGroupService.addMember).mockResolvedValue(MEMBER);
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(environmentGroupService.listMembers).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('combobox', { name: 'Environment' }));
    await userEvent.click(await screen.findByRole('option', { name: 'staging-a' }));
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    // The slice deliberately has no fulfilled handler for addMember (see
    // environmentGroupSlice.ts) — the only way the new row appears is a
    // refetch of the members list.
    await waitFor(() => expect(environmentGroupService.listMembers).toHaveBeenCalledTimes(2));
  });

  it('refetches members after a successful remove rather than splicing the row out', async () => {
    vi.mocked(environmentGroupService.listMembers).mockResolvedValue({
      rows: [MEMBER],
      total: 1,
    });
    vi.mocked(environmentGroupService.removeMember).mockResolvedValue(undefined);
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());
    expect(environmentGroupService.listMembers).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /^remove$/i }));

    // The slice deliberately has no fulfilled handler for removeMember (see
    // environmentGroupSlice.ts) — the only way the row disappears is a
    // refetch of the members list.
    await waitFor(() => expect(environmentGroupService.listMembers).toHaveBeenCalledTimes(2));
  });

  it('surfaces a truncated environment picker list, because a missing option is silent', async () => {
    // Mirrors EnvironmentCompare.test.tsx: `mockReturnValueOnce` is consumed
    // per-call, not per-test, so use `mockReturnValue` and restore it in
    // `afterEach` above rather than leaking into later tests.
    vi.mocked(useAllEnvironments).mockReturnValue({
      environments: [{ id: 9, name: 'staging-a' }],
      loading: false,
      truncated: true,
    } as ReturnType<typeof useAllEnvironments>);
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    expect(screen.getByText(/only the first/i)).toBeInTheDocument();
  });

  it('does not show a truncation notice when the environment list is not truncated', async () => {
    renderDetail('Admin');
    await waitFor(() => expect(screen.getByText('Payments regression')).toBeInTheDocument());

    expect(screen.queryByText(/only the first/i)).not.toBeInTheDocument();
  });
});
