import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentRequestList, { environmentRequestColumns } from '../EnvironmentRequestList';
import environmentRequestReducer from '../../../store/environmentRequestSlice';
import { environmentRequestService } from '../../../services/environmentRequestService';
import type { EnvironmentRequestResponse } from '../../../types/environmentRequest';

vi.mock('../../../services/environmentRequestService', () => ({
  environmentRequestService: {
    listRequests: vi.fn(),
  },
}));

// See userGroups.test.tsx / environmentListServerGrid.test.tsx: the real
// DataGrid virtualizes columns by container width and jsdom reports zero
// width, so this stand-in renders every column's cell for every row using
// the column's own renderCell/valueGetter — the `target` column below is
// valueGetter-only (see EnvironmentRequestList's environmentRequestColumns),
// so the fallback must cover that case too, not just renderCell.
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
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        valueGetter?: (params: any) => unknown;
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
                      : col.valueGetter
                        ? String(col.valueGetter({ row }))
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

const ACCESS_REQUEST: EnvironmentRequestResponse = {
  id: 1,
  tenant_id: 1,
  kind: 'access',
  status: 'submitted',
  lifecycle_id: 1,
  requested_by: 2,
  requester_username: 'alice',
  justification: 'Need to verify a fix',
  needed_by: null,
  environment_id: 5,
  environment_name: 'Mortgage SIT',
  proposed_name: null,
  tier_id: null,
  tier_name: null,
  expires_at: null,
  operations_group_id: null,
  operations_group_name: null,
  created_environment_id: null,
  custom_fields: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const NEW_ENVIRONMENT_REQUEST: EnvironmentRequestResponse = {
  id: 2,
  tenant_id: 1,
  kind: 'new_environment',
  status: 'draft',
  lifecycle_id: 1,
  requested_by: 3,
  requester_username: 'bob',
  justification: 'Need a dedicated perf environment',
  needed_by: null,
  environment_id: null,
  environment_name: null,
  proposed_name: 'Mortgage PERF',
  tier_id: 4,
  tier_name: 'Performance',
  expires_at: '2026-09-01T00:00:00Z',
  operations_group_id: null,
  operations_group_name: null,
  created_environment_id: null,
  custom_fields: null,
  created_at: '2026-01-02T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

function renderList(url = '/environment-requests') {
  const store = configureStore({
    reducer: { environmentRequest: environmentRequestReducer },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <EnvironmentRequestList />
      </MemoryRouter>
    </Provider>
  );
}

describe('EnvironmentRequestList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentRequestService.listRequests).mockResolvedValue({
      rows: [ACCESS_REQUEST, NEW_ENVIRONMENT_REQUEST],
      total: 2,
    });
  });

  it('marks every column the backend cannot sort as unsortable', () => {
    // The whitelist is status, kind, needed_by, created_at. environment_name,
    // requester_username and proposed_name are joined or mode-dependent
    // columns the backend does not sort — a sortable header 422s on click.
    const sortable = new Set(['status', 'kind', 'needed_by', 'created_at']);
    environmentRequestColumns.forEach((col) => {
      if (col.sortable !== false) {
        expect(sortable.has(col.field as string)).toBe(true);
      }
    });
  });

  it('shows the target for both kinds in one column', async () => {
    // An access request shows the environment; a new-environment request
    // shows the proposed name. A single "Target" column with a mode-aware
    // valueGetter, so the grid does not need two half-empty columns.
    renderList();
    await waitFor(() => expect(screen.getByText('Mortgage SIT')).toBeInTheDocument());
    expect(screen.getByText('Mortgage PERF (new)')).toBeInTheDocument();
  });

  it('the For my team chip sends actionable=true', async () => {
    renderList();
    await waitFor(() => expect(screen.getByText('Mortgage SIT')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /for my team/i }));
    await waitFor(() =>
      expect(environmentRequestService.listRequests).toHaveBeenCalledWith(
        expect.objectContaining({ actionable: true })
      )
    );
  });

  it('the Mine chip sends mine=true', async () => {
    renderList();
    await waitFor(() => expect(screen.getByText('Mortgage SIT')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /^mine$/i }));
    await waitFor(() =>
      expect(environmentRequestService.listRequests).toHaveBeenCalledWith(
        expect.objectContaining({ mine: true })
      )
    );
  });

  it('reads the For my team filter back out of the URL on mount, not just writes it', async () => {
    // A filter that only writes to the URL and never hydrates from it looks
    // correct in a click-through and breaks on refresh — this reproduces a
    // fresh mount against a URL that already carries the filter, the way a
    // page reload or a shared link would.
    renderList('/environment-requests?queue=team');
    await waitFor(() =>
      expect(environmentRequestService.listRequests).toHaveBeenCalledWith(
        expect.objectContaining({ actionable: true })
      )
    );
    const calls = vi.mocked(environmentRequestService.listRequests).mock.calls;
    const lastCall = calls[calls.length - 1]?.[0];
    // Never the raw URL spelling, and never both filters at once.
    expect(lastCall).not.toHaveProperty('queue');
    expect(lastCall).not.toHaveProperty('mine');
  });
});
