import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { AxiosError } from 'axios';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import GateTypesPanel from '../GateTypesPanel';
import gateTypeReducer from '../../../store/gateTypeSlice';
import { gateTypeService } from '../../../services/gateTypeService';

vi.mock('../../../services/gateTypeService', () => ({
  gateTypeService: {
    listGateTypes: vi.fn(),
    createGateType: vi.fn(),
    updateGateType: vi.fn(),
    deleteGateType: vi.fn(),
  },
}));

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — only the first few columns' cells mount, which would
// hide columns this test asserts on. This unvirtualized stand-in renders
// every column's cell for every row via the column's own `renderCell`,
// exactly what a real DataGrid would eventually put in the DOM once
// scrolled into view. Same workaround as environmentTiersPanel.test.tsx.
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
    reducer: { gateType: gateTypeReducer },
  });
  return render(
    <Provider store={store}>
      <GateTypesPanel />
    </Provider>
  );
}

const GATE_TYPES = [
  {
    id: 1,
    tenant_id: 1,
    name: 'Functional',
    description: null,
    category: 'functional',
    failure_behaviour: 'block' as const,
    expected_evidence: ['Test execution report', 'Defect summary'],
    requires_deployment_link: true,
    display_order: 10,
    is_active: true,
  },
  {
    id: 2,
    tenant_id: 1,
    name: 'Business',
    description: null,
    category: null,
    failure_behaviour: 'accept_with_exception' as const,
    expected_evidence: ['Business sign-off'],
    requires_deployment_link: false,
    display_order: 70,
    is_active: true,
  },
];

describe('GateTypesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(gateTypeService.listGateTypes).mockResolvedValue({
      rows: GATE_TYPES,
      total: 2,
    });
  });

  it('shows the server reason when a save is refused, not the HTTP status', async () => {
    // A duplicate-name 409. Mocking a plain Error here would pass while the
    // app shows "Request failed with status code 409" — mock the AxiosError
    // shape so response.data.detail exists to be read.
    const err = new AxiosError('Request failed with status code 409');
    (err as unknown as { response: unknown }).response = {
      status: 409,
      data: { detail: 'A gate type named Security already exists' },
    };
    vi.mocked(gateTypeService.createGateType).mockRejectedValue(err);

    renderPanel();
    await waitFor(() => expect(screen.getByText('Functional')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /new gate type/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), 'Security');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/request failed with status code/i)
    ).not.toBeInTheDocument();
  });

  it('renders the expected-evidence kinds as an editable list', async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText('Test execution report')).toBeInTheDocument();
    });

    await userEvent.click(screen.getAllByRole('button', { name: /^edit$/i })[0]);

    // Both evidence kinds for Functional render as removable chips in the
    // edit dialog, not just as a joined string in the grid cell.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Test execution report')).toBeInTheDocument();
    expect(within(dialog).getByText('Defect summary')).toBeInTheDocument();

    // Remove one via its chip delete affordance.
    const chip = within(dialog).getByText('Defect summary').closest('.MuiChip-root');
    expect(chip).not.toBeNull();
    const deleteIcon = chip!.querySelector('.MuiChip-deleteIcon');
    expect(deleteIcon).not.toBeNull();
    await userEvent.click(deleteIcon as Element);
    expect(within(dialog).queryByText('Defect summary')).not.toBeInTheDocument();

    // Add a new one via the text field + Add button.
    await userEvent.type(
      within(dialog).getByLabelText(/add expected evidence/i),
      'Rollback plan'
    );
    await userEvent.click(within(dialog).getByRole('button', { name: /^add$/i }));
    expect(within(dialog).getByText('Rollback plan')).toBeInTheDocument();
  });

  it('labels failure_behaviour so nothing claims a gate blocks anything, and says the verdict is advisory', async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByText('Functional')).toBeInTheDocument());

    // The grid cell for a 'block' gate type must not read plain "Blocks".
    expect(screen.getByText('Blocks (advisory)')).toBeInTheDocument();
    expect(screen.queryByText(/^Blocks$/)).not.toBeInTheDocument();

    await userEvent.click(screen.getAllByRole('button', { name: /^edit$/i })[0]);
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/no gate refuses a deployment or a release transition/i)
    ).toBeInTheDocument();
  });

  it('sends the edited fields, including a full evidence list, on save', async () => {
    vi.mocked(gateTypeService.updateGateType).mockResolvedValueOnce({
      ...GATE_TYPES[1],
      name: 'Business sign-off',
    });
    renderPanel();
    await waitFor(() => expect(screen.getByText('Business')).toBeInTheDocument());

    await userEvent.click(screen.getAllByRole('button', { name: /^edit$/i })[1]);
    const dialog = await screen.findByRole('dialog');
    const nameField = within(dialog).getByLabelText(/^name/i);
    await userEvent.clear(nameField);
    await userEvent.type(nameField, 'Business sign-off');
    await userEvent.click(within(dialog).getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(gateTypeService.updateGateType).toHaveBeenCalled());
    const [id, body] = vi.mocked(gateTypeService.updateGateType).mock.calls[0];
    expect(id).toBe(2);
    expect(body).toMatchObject({
      name: 'Business sign-off',
      failure_behaviour: 'accept_with_exception',
      expected_evidence: ['Business sign-off'],
      requires_deployment_link: false,
      is_active: true,
    });
  });

  it('surfaces the server reason when a delete is refused', async () => {
    vi.mocked(gateTypeService.deleteGateType).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This gate type is in use by one or more gates' },
      },
    });
    renderPanel();
    await waitFor(() => expect(screen.getByText('Functional')).toBeInTheDocument());

    await userEvent.click(screen.getAllByRole('button', { name: /^delete$/i })[0]);
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(
        screen.getByText('This gate type is in use by one or more gates')
      ).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
