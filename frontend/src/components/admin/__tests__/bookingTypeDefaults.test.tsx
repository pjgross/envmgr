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

// Same DataGrid stand-in as bookingTypesPanel.test.tsx — the real grid
// virtualizes by container width and jsdom reports zero, so no cell mounts.
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

describe('BookingTypesPanel — B4 defaults', () => {
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
        default_protection_level: 'soft',
        default_duration_minutes: null,
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any);
    vi.mocked(bookingLifecycleService.createBookingType).mockResolvedValue({
      id: 7,
      tenant_id: 1,
      name: 'Release cycle',
      lifecycle_template_id: 5,
      is_active: true,
      description: null,
      color: null,
      default_protection_level: 'hard',
      default_duration_minutes: 20160,
      created_at: '2026-08-11T00:00:00Z',
      updated_at: '2026-08-11T00:00:00Z',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
  });

  async function openCreateAndFillName(name: string) {
    renderPanel();
    await waitFor(() => expect(screen.getByText('Standard')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /new type/i }));
    const dialog = screen.getByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/^name/i), name);
    await userEvent.click(within(dialog).getByLabelText(/lifecycle template/i));
    await userEvent.click(await screen.findByRole('option', { name: 'Standard Flow' }));
    return dialog;
  }

  it('sends both defaults when a booking type is created', async () => {
    const dialog = await openCreateAndFillName('Release cycle');

    await userEvent.click(within(dialog).getByLabelText(/protection/i));
    await userEvent.click(await screen.findByRole('option', { name: /protected/i }));
    await userEvent.type(within(dialog).getByLabelText(/default duration/i), '20160');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));

    await waitFor(() =>
      expect(bookingLifecycleService.createBookingType).toHaveBeenCalledWith(
        expect.objectContaining({
          default_protection_level: 'hard',
          default_duration_minutes: 20160,
        })
      )
    );
  });

  it('sends null rather than 0 when the duration is left blank', async () => {
    // A blank TextField yields '', and Number('') is 0 — which the API 422s on
    // `gt=0`. The panel must map blank to null. Asserting `toBeNull()`
    // explicitly rather than `objectContaining({default_duration_minutes: null})`
    // alone would not distinguish 0 from null under a loose matcher, so read
    // the argument back and compare identity.
    const dialog = await openCreateAndFillName('No preset');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(bookingLifecycleService.createBookingType).toHaveBeenCalled());
    const payload = vi.mocked(bookingLifecycleService.createBookingType).mock.calls[0][0] as {
      default_duration_minutes: number | null;
      default_protection_level: string;
    };
    expect(payload.default_duration_minutes).toBeNull();
    // And the untouched protection control still sends the soft default rather
    // than undefined — an omitted key would let the server's own default apply
    // today and silently diverge if that default ever changed.
    expect(payload.default_protection_level).toBe('soft');
  });
});
