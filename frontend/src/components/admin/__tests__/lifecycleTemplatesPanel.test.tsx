import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import LifecycleTemplatesPanel from '../LifecycleTemplatesPanel';
import bookingLifecycleReducer from '../../../store/bookingLifecycleSlice';
import customFieldReducer from '../../../store/customFieldSlice';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listTemplates: vi.fn(),
    listBookingTypes: vi.fn(),
    deleteTemplate: vi.fn(),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
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
  const store = configureStore({
    reducer: { bookingLifecycle: bookingLifecycleReducer, customField: customFieldReducer },
  });
  return render(
    <Provider store={store}>
      <LifecycleTemplatesPanel />
    </Provider>
  );
}

describe('LifecycleTemplatesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([]);
    vi.mocked(bookingLifecycleService.listTemplates).mockResolvedValue([
      {
        id: 3,
        tenant_id: 1,
        name: 'Standard Flow',
        entity_type: 'booking',
        description: null,
        is_default: false,
        applies_to_kind: null,
        definition: { states: [], transitions: [], field_permissions: {} },
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
    vi.mocked(bookingLifecycleService.deleteTemplate).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This template is in use by one or more booking types' },
      },
    });
    renderPanel();

    await waitFor(() => expect(screen.getByText('Standard Flow')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(
      // The confirm button inside the dialog, not the row button behind it.
      Array.from(dialog.querySelectorAll('button')).find((b) => b.textContent === 'Delete')!
    );

    await waitFor(() =>
      expect(
        screen.getByText('This template is in use by one or more booking types')
      ).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  // Neither of these two icon buttons is wrapped in a Tooltip at all — unlike
  // the grid-row Edit/Delete pairs elsewhere in this PR, there is no MUI
  // fallback name here. Before this PR neither button had an accessible name.
  it('names the state and transition remove buttons in the template editor for a screen reader', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('button', { name: /new template/i }));
    const dialog = await screen.findByRole('dialog');

    // Two states with real keys — Add Transition stays disabled below two.
    await userEvent.click(within(dialog).getByRole('button', { name: /add state/i }));
    await userEvent.click(within(dialog).getByRole('button', { name: /add state/i }));
    const keyFields = within(dialog).getAllByLabelText('Key');
    await userEvent.type(keyFields[0], 'draft');
    await userEvent.type(keyFields[1], 'done');

    expect(
      within(dialog).getAllByRole('button', { name: /^remove state$/i })
    ).toHaveLength(2);

    await userEvent.click(within(dialog).getByRole('button', { name: /add transition/i }));

    expect(
      within(dialog).getByRole('button', { name: /^remove transition$/i })
    ).toBeInTheDocument();
    // 15s, not the 5s default. This is the SLOWEST test in the frontend suite:
    // it types nine characters through `userEvent`, and each keystroke is a full
    // event sequence that re-renders the whole template-editor dialog. Measured
    // 910ms in isolation but 2019ms under the full suite's parallel load, and it
    // timed out at 5000ms on a GitHub-hosted runner (PR #20) — two cores against
    // this machine's many, so roughly 2.5x again on top of the 2019ms. Nothing
    // about the test is wrong; the default timeout simply has no headroom for
    // the slowest test in the suite on the slowest hardware that runs it.
    // Prefer this over swapping `userEvent.type` for `fireEvent.change`, which
    // would be faster but would stop exercising the real per-keystroke path.
  }, 15000);
});
