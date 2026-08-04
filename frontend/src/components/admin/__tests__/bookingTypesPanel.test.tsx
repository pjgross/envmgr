import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import BookingTypesPanel from '../BookingTypesPanel';
import bookingLifecycleReducer from '../../../store/bookingLifecycleSlice';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listTemplates: vi.fn(),
    listBookingTypes: vi.fn(),
    createBookingType: vi.fn(),
    updateBookingType: vi.fn(),
    deleteBookingType: vi.fn(),
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
  const store = configureStore({ reducer: { bookingLifecycle: bookingLifecycleReducer } });
  return render(
    <Provider store={store}>
      <BookingTypesPanel />
    </Provider>
  );
}

describe('BookingTypesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bookingLifecycleService.listTemplates).mockResolvedValue([
      { id: 5, tenant_id: 1, name: 'Standard Flow', entity_type: 'booking', definition: {} },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any);
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([
      {
        id: 1,
        tenant_id: 1,
        name: 'Standard',
        lifecycle_template_id: 5,
        is_active: true,
        description: null,
        color: null,
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
    vi.mocked(bookingLifecycleService.deleteBookingType).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This booking type is in use by one or more bookings' },
      },
    });
    renderPanel();

    await waitFor(() => expect(screen.getByText('Standard')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(
        screen.getByText('This booking type is in use by one or more bookings')
      ).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('shows the server’s reason when a create is refused', async () => {
    // The create path reads the rejection separately from the delete path, so
    // fixing one does not fix the other.
    vi.mocked(bookingLifecycleService.createBookingType).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'A booking type with that name already exists' },
      },
    });
    renderPanel();

    await waitFor(() => expect(screen.getByText('Standard')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /new type/i }));
    const dialog = screen.getByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/^name/i), 'Standard');
    await userEvent.click(within(dialog).getByLabelText(/lifecycle template/i));
    await userEvent.click(await screen.findByRole('option', { name: 'Standard Flow' }));
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));

    await waitFor(() =>
      expect(
        screen.getByText('A booking type with that name already exists')
      ).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
