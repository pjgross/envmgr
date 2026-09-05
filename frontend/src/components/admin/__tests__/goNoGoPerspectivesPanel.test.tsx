/**
 * GoNoGoPerspectivesPanel had NO test file at all as of the panel's first
 * commit — the review that found this pointed at gateTypesPanel.test.tsx as
 * the shape to follow: a real AxiosError shape for the 409 case, so a
 * regression back to `result.error.message` (which drops
 * `response.data.detail`) would fail here rather than passing an entire
 * green suite.
 */
import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import GoNoGoPerspectivesPanel from '../GoNoGoPerspectivesPanel';
import goNoGoReducer from '../../../store/goNoGoSlice';
import { goNoGoService } from '../../../services/goNoGoService';
import type { GoNoGoPerspectiveRead } from '../../../types/goNoGo';

vi.mock('../../../services/goNoGoService', () => ({
  goNoGoService: {
    list: vi.fn(),
    record: vi.fn(),
    closeCondition: vi.fn(),
    listPerspectives: vi.fn(),
    createPerspective: vi.fn(),
    updatePerspective: vi.fn(),
  },
}));

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — only the first few columns' cells mount. This
// unvirtualized stand-in renders every column's cell for every row via the
// column's own `renderCell`, the same workaround gateTypesPanel.test.tsx and
// environmentTiersPanel.test.tsx use.
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

const PERSPECTIVES: GoNoGoPerspectiveRead[] = [
  {
    id: 1,
    tenant_id: 1,
    name: 'Quality',
    description: 'Test results and defect posture.',
    sort_order: 10,
    is_active: true,
  },
  {
    id: 2,
    tenant_id: 1,
    name: 'Process',
    description: 'Change and approval process was followed.',
    sort_order: 20,
    is_active: true,
  },
  {
    id: 3,
    tenant_id: 1,
    name: 'Legacy Acceptance',
    description: 'Superseded — retained so past sign-offs still resolve.',
    sort_order: 90,
    is_active: false,
  },
];

function renderPanel(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      goNoGo: goNoGoReducer,
      // Minimal stand-in — the panel only reads state.auth.user, following
      // rollbackPolicyPanel.test.tsx's own approach.
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <GoNoGoPerspectivesPanel />
    </Provider>
  );
}

describe('GoNoGoPerspectivesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(goNoGoService.listPerspectives).mockResolvedValue(PERSPECTIVES);
  });

  it('renders every seeded perspective, including an inactive one', async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByText('Quality')).toBeInTheDocument());

    expect(screen.getByText('Process')).toBeInTheDocument();
    // An inactive perspective must still render — an Admin needs to SEE it
    // to reactivate it via the Active toggle; hiding it would remove the
    // only path back.
    expect(screen.getByText('Legacy Acceptance')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();
    expect(screen.getAllByText('Active')).toHaveLength(2);

    // listPerspectives is called with includeInactive=true so a retired
    // perspective is fetchable at all — see fetchPerspectives's default.
    expect(goNoGoService.listPerspectives).toHaveBeenCalledWith(true);
  });

  it('lets a non-Admin see the list but offers no write controls at all', async () => {
    renderPanel('Member');
    await waitFor(() => expect(screen.getByText('Quality')).toBeInTheDocument());

    // Reads are open to any tenant member — B3a's rule — so the list itself
    // must render in full for a non-admin, unlike the false analogy to
    // /tenant/users a B3a reviewer once caught.
    expect(screen.getByText('Process')).toBeInTheDocument();
    expect(screen.getByText('Legacy Acceptance')).toBeInTheDocument();

    expect(screen.getByText(/adding or changing one requires an admin/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new perspective/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
  });

  it('shows the server reason when a duplicate name is refused, not the HTTP status', async () => {
    // A duplicate-name 409 — the whole point Task 7's brief called out.
    // Mocking a plain Error here would pass while the panel actually shows
    // "Request failed with status code 409"; only a real AxiosError shape
    // (response.data.detail) exercises formatApiError's extraction.
    vi.mocked(goNoGoService.createPerspective).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'A perspective named Quality already exists' },
      },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText('Quality')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /new perspective/i }));
    const nameField = await screen.findByLabelText(/^name/i);
    await userEvent.type(nameField, 'Quality');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(screen.getByText('A perspective named Quality already exists')).toBeInTheDocument();
    });
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
