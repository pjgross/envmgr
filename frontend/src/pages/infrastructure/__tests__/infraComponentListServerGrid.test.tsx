import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import InfrastructureComponentList, { infraComponentColumns } from '../InfrastructureComponentList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/infrastructureComponentService', () => ({
  infrastructureComponentService: {
    listComponents: vi.fn().mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'db-a',
          description: null,
          component_type: 'managed_database',
          provider: 'aws',
          region: 'eu-west-1',
          location: 'macmini.lan',
          source: 'manual',
          external_id: null,
          custom_fields: null,
          tags: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    }),
    deleteComponent: vi.fn().mockResolvedValue(undefined),
  },
}));

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — only the first few columns' *headers* mount, and none
// of their cells, which would hide this page's actions column (Edit/Delete)
// from the delete test below no matter where it sits in the column list.
// This unvirtualized stand-in renders every column's cell for every row
// using the column's own `renderCell`/`valueGetter`, exactly what a real
// DataGrid would eventually put in the DOM once scrolled into view, and also
// captures the exact props the page passed — used by the
// `disableColumnFilter` assertion below, which needs the raw prop rather
// than anything DOM-observable.
const { capturedGridProps } = vi.hoisted(() => ({
  capturedGridProps: { current: undefined as Record<string, unknown> | undefined },
}));

vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  return {
    ...actual,
    DataGrid: (props: Record<string, unknown>) => {
      capturedGridProps.current = props;
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

import { infrastructureComponentService } from '../../../services/infrastructureComponentService';

function renderList(url = '/infrastructure-components') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <InfrastructureComponentList />
      </MemoryRouter>
    </Provider>
  );
}

const mockList = vi.mocked(infrastructureComponentService.listComponents);

function lastListParams() {
  const calls = mockList.mock.calls;
  return calls[calls.length - 1]?.[0];
}

function gridProps() {
  return capturedGridProps.current as { disableColumnFilter?: boolean };
}

async function deleteFirstRow() {
  // The grid renders its rows asynchronously once the fetch resolves and the
  // store updates — the row (and its actions column) isn't in the DOM yet
  // right after the initial `mockList` call.
  await screen.findByText('db-a');

  const deleteButtons = screen
    .getAllByRole('button', { hidden: true })
    .filter((b) => b.getAttribute('aria-label') === 'Delete');
  expect(deleteButtons.length).toBeGreaterThan(0);
  fireEvent.click(deleteButtons[0]);

  const dialog = await screen.findByRole('dialog');
  const confirmButton = within(dialog).getByRole('button', { name: 'Delete' });
  fireEvent.click(confirmButton);
}

describe('InfrastructureComponentList server-side grid', () => {
  // Each `it` below mounts its own InfrastructureComponentList against the
  // same store singleton (see `renderList`), and `mockList`'s call count is
  // otherwise cumulative across the whole file. The delete test asserts an
  // exact call count, which only means anything against a clean mock.
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sends paging, sorting and both filters', async () => {
    renderList('/infrastructure-components?page=1&sort_by=provider&sort_dir=desc&search=db&component_type=host');
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'provider', sort_dir: 'desc', search: 'db', component_type: 'host',
    }));
  });

  it('keeps the literal search term "all"', async () => {
    // 'all' is the selects' no-selection sentinel; in a text box it is a real
    // search term. Dropping it returns unfiltered results while the box reads
    // "all". Only pages with a text filter can exercise this.
    renderList('/infrastructure-components?search=all');
    await waitFor(() => expect(lastListParams()).toMatchObject({ search: 'all' }));
  });

  it('marks location and actions unsortable', () => {
    // GET /infrastructure-components/ whitelists name, component_type,
    // provider, region, source. `location` is a real column that is NOT
    // whitelisted — a sortable header on it 422s on first click.
    const byField = Object.fromEntries(infraComponentColumns.map((c) => [c.field, c]));
    ['name', 'component_type', 'provider', 'region', 'source'].forEach((f) =>
      expect(byField[f].sortable).not.toBe(false)
    );
    expect(byField.location.sortable).toBe(false);
    expect(byField.actions.sortable).toBe(false);
  });

  it('disables the column filter, which would filter only the loaded page', async () => {
    renderList('/infrastructure-components');
    await waitFor(() => expect(lastListParams()).toBeDefined());
    expect(gridProps().disableColumnFilter).toBe(true);
  });

  it('refetches after a delete instead of splicing the page', async () => {
    renderList('/infrastructure-components');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    await deleteFirstRow();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });
});
