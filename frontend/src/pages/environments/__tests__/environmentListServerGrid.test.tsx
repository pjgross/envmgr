import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import whitelists from '../../../constants/sortWhitelists.json';
import EnvironmentList, { environmentColumns, buildCustomFieldColumns } from '../EnvironmentList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn().mockResolvedValue({
      rows: [
        {
          id: 1,
          name: 'prod-a',
          description: null,
          tier_id: 3,
          tier_name: 'Production',
          tier_color: '#c62828',
          owner_user_id: 7,
          owner_username: 'alice',
          expires_at: null,
          reserved_now: false,
          status: 'active',
          tenant_id: 1,
          custom_fields: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    }),
    deleteEnvironment: vi.fn().mockResolvedValue(undefined),
    updateEnvironment: vi.fn(),
    createEnvironment: vi.fn(),
  },
}));

// Also unmocked-network-free: EnvironmentList fetches custom field
// definitions on mount alongside the environment page itself.
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

// The tier picker (create/edit dialog + tier filter) reads every tier via
// useAllEnvironmentTiers — deliberately not a paged slice of the grid.
vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

// The owner picker calls GET /tenant/users/lite straight through `api`,
// matching GatesTable.tsx.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
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

import { environmentService } from '../../../services/environmentService';
import { environmentTierService } from '../../../services/environmentTierService';
import api from '../../../services/api';
import type { CustomFieldDefinition } from '../../../types/customField';

// Shared by the create/edit dialog tests below: one active tier and one
// active user, so the Tier/Owner <Select>s in the dialog have something to
// pick and `handleSave`'s tier/owner-required checks are never what blocks
// the save.
const PRODUCTION_TIER = {
  id: 3,
  tenant_id: 1,
  name: 'Production',
  description: null,
  category: null,
  color: '#c62828',
  display_order: 1,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function renderEnvironmentList(url = '/environments') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <EnvironmentList />
      </MemoryRouter>
    </Provider>
  );
}

const mockList = vi.mocked(environmentService.listEnvironments);

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
  await screen.findByText('prod-a');

  const deleteButtons = screen
    .getAllByRole('button', { hidden: true })
    .filter((b) => b.getAttribute('aria-label') === 'Delete');
  expect(deleteButtons.length).toBeGreaterThan(0);
  fireEvent.click(deleteButtons[0]);

  const dialog = await screen.findByRole('dialog');
  const confirmButton = within(dialog).getByRole('button', { name: 'Delete' });
  fireEvent.click(confirmButton);
}

describe('EnvironmentList server-side grid', () => {
  // Each `it` below mounts its own EnvironmentList against the same store
  // singleton (see `renderEnvironmentList`), and `mockList`'s call count is
  // otherwise cumulative across the whole file. The delete test asserts an
  // exact call count, which only means anything against a clean mock.
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sends paging, sorting and the search filter', async () => {
    renderEnvironmentList('/environments?page=1&sort_by=status&sort_dir=desc&search=prod');
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'status', sort_dir: 'desc', search: 'prod',
    }));
  });

  it('keeps the literal search term "all"', async () => {
    // `all` is the selects' no-selection sentinel. On a text box it is a real
    // search term, and dropping it returns unfiltered results while the box
    // still reads "all". This is the first page since PR A with a text filter.
    renderEnvironmentList('/environments?search=all');
    await waitFor(() => expect(lastListParams()).toMatchObject({ search: 'all' }));
  });

  it('sends the tier and governance-gap filters', async () => {
    // Both are new filterKeys. A key missing from filterKeys is written to the
    // URL by setFilter but never read back into `filters`, so it never reaches
    // the request — the URL reads `?tier_id=3` beside an unfiltered grid.
    renderEnvironmentList('/environments?tier_id=3&governance_gap=true');
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ tier_id: '3', governance_gap: 'true' })
    );
  });

  it('refetches when the governance-gap chip is toggled on', async () => {
    // The trap this guards: a filter whose "off" value collides with
    // buildParams' own no-selection sentinel builds byte-identical params in
    // both states, so the fetch effect (keyed on the resolved params) never
    // re-runs and the grid silently keeps the old rows. Off is '', which
    // buildParams drops; on is 'true', which it keeps.
    renderEnvironmentList('/environments');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(lastListParams()).not.toHaveProperty('governance_gap');

    fireEvent.click(screen.getByText('Missing owner'));

    await waitFor(() => expect(lastListParams()).toMatchObject({ governance_gap: 'true' }));
  });

  it('marks actions and custom-field columns unsortable', () => {
    const byField = Object.fromEntries(environmentColumns.map((c) => [c.field, c]));
    ['name', 'tier', 'status', 'owner', 'expires_at', 'created_at'].forEach((f) =>
      expect(byField[f].sortable).not.toBe(false)
    );
    expect(byField.actions.sortable).toBe(false);
  });

  it('leaves reserved_now unsortable — it is not in the backend whitelist', () => {
    // The backend computes it from live bookings, so `sorting()` answers a
    // sort_by=reserved_now with a 422. A sortable header would look clickable
    // and fail on click.
    const col = environmentColumns.find((c) => c.field === 'reserved_now');
    expect(col?.sortable).toBe(false);
  });

  it('offers exactly the columns the backend will sort by', () => {
    // Guards the other direction from the two assertions above: a column
    // added here but absent from the whitelist earns a 422 on click, and one
    // named differently from its whitelist entry (e.g. `tier_name` for
    // `tier`) sends a sort_by the server rejects. Custom-field and `actions`
    // columns are excluded above by being `sortable: false`.
    const sortableFields = environmentColumns
      .filter((c) => c.sortable !== false)
      .map((c) => c.field);
    expect(new Set(sortableFields)).toEqual(new Set(whitelists.environments.sortable));
  });

  it('disables the column filter, which would filter only the loaded page', async () => {
    renderEnvironmentList('/environments');
    await waitFor(() => expect(lastListParams()).toBeDefined());
    expect(gridProps().disableColumnFilter).toBe(true);
  });

  it('refetches after a delete instead of splicing the page', async () => {
    // Editing a 25-row window is structurally wrong: it ignores the active
    // filter/sort/page and never adjusts `total`.
    renderEnvironmentList('/environments');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    await deleteFirstRow();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('marks per-tenant custom-field columns unsortable, since none is in the backend whitelist', () => {
    // Unlike environmentColumns above, these columns are built at render
    // time from the tenant's custom field definitions, so the static
    // column-list test above can't see them. @mui/x-data-grid virtualizes
    // columns by container width, and jsdom reports zero layout width, so a
    // real render only ever puts the first few static columns in the DOM —
    // there is no way to scroll a custom-field column into view to inspect
    // its header. `buildCustomFieldColumns` is exported from EnvironmentList
    // for exactly this reason: assert on the GridColDef it produces
    // directly, the same way the static columns are asserted on above.
    const def: CustomFieldDefinition = {
      id: 1,
      tenant_id: 1,
      entity_type: 'environment',
      entity_subtype: null,
      field_key: 'region',
      label: 'Region',
      field_type: 'text',
      required: false,
      display_order: 1,
      options: null,
      lifecycle_states: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };

    const [column] = buildCustomFieldColumns([def]);

    expect(column.field).toBe('region');
    expect(column.sortable).toBe(false);
  });

  // These two carry the whole "a null expiry means no expiry planned"
  // decision: EnvironmentList gates the expiry-required validation on
  // `!editTarget` (so Edit tolerates a blank expiry while Create still
  // demands one), and the update payload always sends an explicit
  // `expires_at: null` rather than omitting the key, because the backend
  // keys on `model_fields_set` and an omitted key means "leave alone".
  // Neither behaviour has any other test guarding it — both would survive
  // deletion with a fully green suite.
  it('lets Edit save a blank expiry, sending explicit null rather than leaving it alone', async () => {
    vi.mocked(environmentTierService.listTiers).mockResolvedValueOnce({
      rows: [PRODUCTION_TIER],
      total: 1,
    });
    vi.mocked(api.get).mockResolvedValueOnce({ data: [{ id: 7, username: 'alice' }] });
    const updateMock = vi.mocked(environmentService.updateEnvironment).mockResolvedValueOnce({
      id: 1,
      name: 'prod-a',
      description: null,
      tier_id: 3,
      tier_name: 'Production',
      tier_color: '#c62828',
      owner_user_id: 7,
      owner_username: 'alice',
      expires_at: null,
      reserved_now: false,
      status: 'active',
      tenant_id: 1,
      custom_fields: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    renderEnvironmentList('/environments');
    // The prod-a fixture (see the environmentService mock above) already has
    // expires_at: null — exactly the row this decision is about.
    await screen.findByText('prod-a');

    const editButtons = screen
      .getAllByRole('button', { hidden: true })
      .filter((b) => b.getAttribute('aria-label') === 'Edit');
    expect(editButtons.length).toBeGreaterThan(0);
    fireEvent.click(editButtons[0]);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Expires')).toHaveValue('');

    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    // Synchronous: handleSave's validation runs in the click handler itself,
    // before the dialog has any chance to close on a successful dispatch.
    expect(within(dialog).queryByText(/expiry date is required/i)).not.toBeInTheDocument();

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(1, expect.objectContaining({ expires_at: null }))
    );
  });

  it('still requires an expiry on Create, even though Edit tolerates a blank one', async () => {
    vi.mocked(environmentTierService.listTiers).mockResolvedValueOnce({
      rows: [PRODUCTION_TIER],
      total: 1,
    });
    vi.mocked(api.get).mockResolvedValueOnce({ data: [{ id: 7, username: 'alice' }] });
    const createMock = vi.mocked(environmentService.createEnvironment);

    renderEnvironmentList('/environments');
    await screen.findByText('prod-a');

    fireEvent.click(screen.getByRole('button', { name: /new environment/i }));

    const dialog = await screen.findByRole('dialog');
    // Not an exact 'Name' match: the field is `required`, so MUI appends a
    // visually-hidden asterisk to the label's accessible name ("Name *").
    await userEvent.type(within(dialog).getByLabelText(/^Name/), 'staging-b');

    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Tier' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Production' }));

    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Owner' }));
    await userEvent.click(await screen.findByRole('option', { name: 'alice' }));

    // Expiry deliberately left blank.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }));

    expect(await within(dialog).findByText(/expiry date is required/i)).toBeInTheDocument();
    expect(createMock).not.toHaveBeenCalled();
  });
});
