import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
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

const TIERS = [
  {
    id: 1,
    tenant_id: 1,
    name: 'Dev',
    description: null,
    category: 'dev',
    color: '#90A4AE',
    display_order: 10,
    is_active: true,
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  },
  {
    id: 2,
    tenant_id: 1,
    name: 'Production',
    description: null,
    category: 'production',
    color: '#EF5350',
    display_order: 70,
    is_active: false,
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

    await waitFor(() => expect(screen.getByText('Dev')).toBeInTheDocument());
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();
  });

  it('surfaces the in-use conflict when a delete is refused', async () => {
    vi.mocked(environmentTierService.deleteTier).mockRejectedValue(
      new Error('This tier is in use by one or more environments')
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Dev')).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: /delete/i })[0]);
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/in use by one or more environments/i)
      ).toBeInTheDocument()
    );
  });
});
