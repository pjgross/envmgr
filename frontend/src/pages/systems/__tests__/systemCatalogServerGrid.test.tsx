import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import SystemCatalog, { systemColumns, buildCustomFieldColumns } from '../SystemCatalog';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn().mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'payments',
          description: null,
          github_repository_url: null,
          custom_fields: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    }),
    deleteSystem: vi.fn().mockResolvedValue(undefined),
  },
}));

// Also unmocked-network-free: SystemCatalog fetches custom field definitions
// on mount alongside the system list itself.
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
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

import { systemService } from '../../../services/systemService';
import type { CustomFieldDefinition } from '../../../types/customField';

function renderCatalog(url = '/systems') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <SystemCatalog />
      </MemoryRouter>
    </Provider>
  );
}

const mockList = vi.mocked(systemService.listSystems);

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
  await screen.findByText('payments');

  const deleteButtons = screen
    .getAllByRole('button', { hidden: true })
    .filter((b) => b.getAttribute('aria-label') === 'Delete');
  expect(deleteButtons.length).toBeGreaterThan(0);
  fireEvent.click(deleteButtons[0]);

  const dialog = await screen.findByRole('dialog');
  const confirmButton = within(dialog).getByRole('button', { name: 'Delete' });
  fireEvent.click(confirmButton);
}

describe('SystemCatalog server-side grid', () => {
  // Each `it` below mounts its own SystemCatalog against the same store
  // singleton (see `renderCatalog`), and `mockList`'s call count is otherwise
  // cumulative across the whole file. The delete test asserts an exact call
  // count, which only means anything against a clean mock.
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sends paging, sorting and the search filter', async () => {
    renderCatalog('/systems?page=1&sort_by=name&sort_dir=desc&search=payments');
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'name', sort_dir: 'desc', search: 'payments',
    }));
  });

  it('keeps the literal search term "all"', async () => {
    // 'all' is the selects' no-selection sentinel; in a text box it is a real
    // search term. Dropping it returns unfiltered results while the box reads
    // "all".
    renderCatalog('/systems?search=all');
    await waitFor(() => expect(lastListParams()).toMatchObject({ search: 'all' }));
  });

  it('leaves only name sortable', () => {
    // GET /systems/ whitelists `name` ALONE. description and
    // github_repository_url are ordinary data columns that nonetheless 422
    // if marked sortable — the same shape as `location` on the hosts page.
    const byField = Object.fromEntries(systemColumns.map((c) => [c.field, c]));
    expect(byField.name.sortable).not.toBe(false);
    ['description', 'github_repository_url', 'actions'].forEach((f) =>
      expect(byField[f].sortable).toBe(false));
  });

  it('disables the column filter, which would filter only the loaded page', () => {
    renderCatalog('/systems');
    expect(gridProps().disableColumnFilter).toBe(true);
  });

  it('refetches after a delete instead of splicing the page', async () => {
    renderCatalog('/systems');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    await deleteFirstRow();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('marks per-tenant custom-field columns unsortable, since none is in the backend whitelist', () => {
    // Unlike systemColumns above, these columns are built at render time from
    // the tenant's custom field definitions, so the static column-list test
    // above can't see them. @mui/x-data-grid virtualizes columns by
    // container width, and jsdom reports zero layout width, so a real render
    // only ever puts the first few static columns in the DOM — there is no
    // way to scroll a custom-field column into view to inspect its header.
    // `buildCustomFieldColumns` is exported from SystemCatalog for exactly
    // this reason: assert on the GridColDef it produces directly, the same
    // way the static columns are asserted on above.
    const def: CustomFieldDefinition = {
      id: 1,
      tenant_id: 1,
      entity_type: 'system',
      entity_subtype: null,
      field_key: 'criticality',
      label: 'Criticality',
      field_type: 'text',
      required: false,
      display_order: 1,
      options: null,
      lifecycle_states: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };

    const [column] = buildCustomFieldColumns([def]);

    expect(column.field).toBe('criticality');
    expect(column.sortable).toBe(false);
  });
});
