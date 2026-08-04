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
import whitelists from '../../../constants/sortWhitelists.json';

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

function renderPage() {
  const store = configureStore({ reducer: { userGroup: userGroupReducer } });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/tenant/groups']}>
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

  it('marks every column the backend cannot sort as unsortable', () => {
    // The contract docs/pagination.md describes: a sortable header whose field
    // the backend does not whitelist looks clickable and 422s on click.
    // member_count and environment_count are correlated subqueries, not
    // columns, so they can never be whitelisted.
    const sortable = new Set(whitelists['tenant-groups'].sortable as string[]);
    userGroupColumns.forEach((col) => {
      if (col.sortable !== false) {
        expect(sortable.has(col.field)).toBe(true);
      }
    });
    const byField = Object.fromEntries(userGroupColumns.map((c) => [c.field, c]));
    expect(byField.member_count.sortable).toBe(false);
    expect(byField.environment_count.sortable).toBe(false);
  });

  it('renders the counts that came with the row', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
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
});
