import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentTiersPanel from '../EnvironmentTiersPanel';
import environmentTierReducer from '../../../store/environmentTierSlice';
import { environmentTierService } from '../../../services/environmentTierService';

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
  },
}));

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — only the first few columns' cells mount, which would
// hide the Status and actions columns this test asserts on (see the same
// workaround in environmentListServerGrid.test.tsx). This unvirtualized
// stand-in renders every column's cell for every row via the column's own
// `renderCell`, exactly what a real DataGrid would eventually put in the DOM
// once scrolled into view.
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

function renderPanel() {
  const store = configureStore({
    reducer: { environmentTier: environmentTierReducer },
  });
  return render(
    <Provider store={store}>
      <EnvironmentTiersPanel />
    </Provider>
  );
}

// The panel trusts the order the service returns (the real endpoint sorts by
// display_order server-side; the panel does not re-sort on fetch), so the
// array literal order here IS what should land in the DOM. To prove the DOM
// order tracks display_order and not some other field the fixture would
// otherwise coincidentally agree with, id and name ordering are made to
// *disagree* with display_order: Production has the higher id and comes
// alphabetically after Dev, yet its lower display_order (10 vs 70) puts it
// first. A test that only checked presence — or one where display_order,
// id and alphabetical order all happened to coincide — would not catch
// rows being reversed or display_order being ignored.
const TIERS = [
  {
    id: 99,
    tenant_id: 1,
    name: 'Production',
    description: null,
    category: 'production',
    color: '#EF5350',
    display_order: 10,
    is_active: false,
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  },
  {
    id: 1,
    tenant_id: 1,
    name: 'Dev',
    description: null,
    category: 'dev',
    color: '#90A4AE',
    display_order: 70,
    is_active: true,
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  },
];

describe('EnvironmentTiersPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentTierService.listTiers).mockResolvedValue({
      rows: TIERS,
      total: 2,
    });
  });

  it('lists tiers in progression order with their active state', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getByText('Production')).toBeInTheDocument());
    expect(screen.getByText('Dev')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();

    // Production (display_order 10) must render before Dev (display_order
    // 70) even though Dev has the lower id and comes first alphabetically —
    // this only holds if display_order, not some other field, drives order.
    const rows = screen.getAllByRole('row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Production')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Dev')).toBeInTheDocument();
  });

  it('surfaces the in-use conflict when a delete is refused', async () => {
    // Shaped like a real AxiosError: `.message` is the generic HTTP-status
    // text axios sets, and the actual backend explanation lives only at
    // `response.data.detail`. A plain `Error` carrying the final text on
    // `.message` (the old fixture here) can't catch a regression to
    // `result.error.message`, because that shape already has the right text
    // in the one place the buggy code reads.
    vi.mocked(environmentTierService.deleteTier).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This tier is in use by one or more environments' },
      },
    });
    renderPanel();

    await waitFor(() => expect(screen.getByText('Dev')).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: /delete/i })[0]);
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(
        screen.getByText('This tier is in use by one or more environments')
      ).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
