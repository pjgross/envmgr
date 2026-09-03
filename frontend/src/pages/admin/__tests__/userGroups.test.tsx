import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UserGroups, { userGroupColumns } from '../UserGroups';
import userGroupReducer from '../../../store/userGroupSlice';
import { userGroupService } from '../../../services/userGroupService';

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn(),
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
  },
}));

// See environmentTiersPanel.test.tsx: the real DataGrid virtualizes columns by
// container width and jsdom reports zero width, so the actions column never
// mounts. This stand-in renders every column's cell.
vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  return {
    ...actual,
    DataGrid: (props: Record<string, unknown>) => {
      const rows = props.rows as Array<Record<string, unknown>>;
      const columns = props.columns as Array<{
        field: string;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        renderCell?: (params: any) => ReactNode;
      }>;
      return (
        <table>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)}>
                {columns.map((col) => (
                  <td key={col.field}>
                    {col.renderCell
                      ? col.renderCell({ row, value: row[col.field], id: row.id })
                      : String(row[col.field] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    },
  };
});

function renderPage(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      userGroup: userGroupReducer,
      // Minimal stand-in — the page only reads `state.auth.user`.
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/admin/user-groups']}>
        <UserGroups />
      </MemoryRouter>
    </Provider>
  );
}

describe('UserGroups', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(userGroupService.listGroups).mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'Platform Ops',
          description: 'Runs the SIT estate',
          member_count: 3,
          environment_count: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
  });

  it('leaves member_count and environment_count sortable', () => {
    // This grid has no sortingMode="server" / paginationMode="server" (see
    // UserGroups.tsx) — every sort happens against the rows already in the
    // browser, so it never reaches the backend's USER_GROUP_SORTS whitelist.
    // member_count and environment_count are correlated subqueries the
    // backend could never whitelist for a server-side sort, but that
    // restriction doesn't apply client-side: disabling them here would give
    // up a capability that works. `tenant-groups` is deliberately absent from
    // sortWhitelists.json for the same reason (docs/pagination.md's ‡
    // footnote convention).
    const byField = Object.fromEntries(userGroupColumns.map((c) => [c.field, c]));
    expect(byField.member_count.sortable).not.toBe(false);
    expect(byField.environment_count.sortable).not.toBe(false);
    // description stays unsortable: it's an ordinary column the backend
    // never whitelisted, unrelated to the client/server-sort distinction.
    expect(byField.description.sortable).toBe(false);
  });

  it('renders the counts that came with the row', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('links the environment count to the filtered environments list', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: '2' });
    expect(link).toHaveAttribute('href', '/environments?operations_group_id=1');
  });

  it('names the blocking environments when a delete is refused', async () => {
    // The whole value of this 409 is *which* environments block it. An admin
    // told only "in use" has to go hunting.
    vi.mocked(userGroupService.deleteGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: {
          detail: 'This group operates Mortgage SIT. Reassign them before deleting it.',
        },
      },
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(screen.getByText(/This group operates Mortgage SIT/)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('shows the list but not the write controls for a non-admin', async () => {
    // Finding 1: GET /tenant/groups is readable by any tenant member (see
    // app/api/v1/user_groups.py), so the route must not be Admin-gated — but
    // the write actions still are.
    renderPage('Member');
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /new group/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it('shows the write controls for an admin', async () => {
    renderPage('Admin');
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /new group/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeInTheDocument();
  });

  it('clears a previous create failure when the dialog is reopened', async () => {
    // handleCreate resets createError at SUBMIT time, which is too late: after
    // a failed create and a Cancel, reopening showed the previous attempt's
    // message on a fresh, untouched, empty form — the page reading as broken
    // before the user had typed anything.
    //
    // The identical bug was fixed in Projects.tsx, which was modelled on this
    // file; a review found it here too. Both dialogs now reset at open, the
    // way openEdit and the delete flow already did.
    vi.mocked(userGroupService.createGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "A group named 'Platform Ops' already exists in this tenant" },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /new group/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'Platform Ops');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole('button', { name: /new group/i }));
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument();
  });
});
