import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ComponentTypesPanel from '../ComponentTypesPanel';
import componentTypeReducer from '../../../store/componentTypeSlice';
import { componentTypeService } from '../../../services/componentTypeService';

vi.mock('../../../services/componentTypeService', () => ({
  componentTypeService: {
    listTypes: vi.fn(),
    createType: vi.fn(),
    updateType: vi.fn(),
    deleteType: vi.fn(),
  },
}));

// See environmentTiersPanel.test.tsx: the real DataGrid virtualizes columns by
// container width and jsdom reports zero width, so the actions column's Delete
// button never mounts. This stand-in renders every column's cell.
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
  const store = configureStore({ reducer: { componentType: componentTypeReducer } });
  return render(
    <Provider store={store}>
      <ComponentTypesPanel />
    </Provider>
  );
}

describe('ComponentTypesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(componentTypeService.listTypes).mockResolvedValue([
      {
        id: 1,
        tenant_id: 1,
        name: 'Postgres',
        category: 'database',
        description: null,
        field_definitions: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any);
  });

  it('shows the server’s reason when a delete is refused, not the HTTP status', async () => {
    // Shaped like a real AxiosError: `.message` is the generic HTTP-status text
    // axios sets, and the backend's explanation lives only at
    // `response.data.detail`. Redux Toolkit's default `miniSerializeError`
    // copies name/message/stack/code and drops `response` entirely, so
    // `result.error.message` can only ever be the generic string. A fixture
    // that rejected with a plain `Error` carrying the final text would pass
    // against the broken code.
    vi.mocked(componentTypeService.deleteType).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This component type is in use by one or more subsystems' },
      },
    });
    renderPanel();

    await waitFor(() => expect(screen.getByText('Postgres')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(
        screen.getByText('This component type is in use by one or more subsystems')
      ).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
