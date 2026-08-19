import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import whitelists from '../../../constants/sortWhitelists.json';
import EnvironmentList, {
  environmentColumns,
  buildCustomFieldColumns,
  loadColumnModel,
} from '../EnvironmentList';

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
          operations_group_id: null,
          operations_group_name: null,
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

// B2's naming policy, read for the name field's helper text in the create/edit
// dialog. Mocked at the service rather than left to the `api` mock above: it
// goes through the same module, so an unmocked policy fetch races the owner
// picker for `api.get`'s mockResolvedValueOnce and whichever lands first wins —
// which is exactly how it failed, in one of the four tests that use it.
vi.mock('../../../services/environmentNamingPolicyService', () => ({
  environmentNamingPolicyService: {
    get: vi.fn().mockResolvedValue({
      is_enabled: false,
      name_pattern: null,
      name_pattern_example: null,
      required_attributes: [],
      grace_days: 14,
      effective_from: '2026-08-09T00:00:00Z',
    }),
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

import { environmentService } from '../../../services/environmentService';
import { environmentTierService } from '../../../services/environmentTierService';
import { customFieldService } from '../../../services/customFieldService';
import api from '../../../services/api';
import type { CustomFieldDefinition } from '../../../types/customField';
import type { GridColDef } from '@mui/x-data-grid';

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

  it('sends the owner and expiring-within-days filters', async () => {
    // Both are new filterKeys added to close the gap between the spec (which
    // said the list would gain owner and governance-gap filters, plus an
    // expiry window) and what had shipped (tier and governance-gap only —
    // `expiring_within_days` existed on the backend with no UI consumer at
    // all).
    renderEnvironmentList('/environments?owner_user_id=7&expiring_within_days=30');
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ owner_user_id: '7', expiring_within_days: '30' })
    );
  });

  it('sends the operations_group_id filter', async () => {
    // Every other filter added to this page has a round-trip test that it
    // survives the URL via useServerGrid's filterKeys; operations_group_id
    // didn't. A key missing from filterKeys is written to the URL by
    // setFilter but never read back into `filters`, same trap as the
    // tier/governance-gap test above.
    renderEnvironmentList('/environments?operations_group_id=4');
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ operations_group_id: '4' })
    );
  });

  it('does not send owner_user_id or expiring_within_days when neither filter is set', async () => {
    // The discriminating half for the previous test: proves these two keys
    // are genuinely optional filters reflecting the Select's own state,
    // rather than always being sent (which would silently over-filter every
    // request). The row-level discriminating half — a differently-owned or
    // non-expiring-soon row that must NOT appear — is covered on the
    // backend by test_filtering_by_owner and
    // test_expiring_within_days_excludes_a_null_expiry
    // (test_environment_governance_filters.py); this mocked-service test
    // can only assert what params the page builds, not what rows a real
    // server would return for them.
    renderEnvironmentList('/environments');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(lastListParams()).not.toHaveProperty('owner_user_id');
    expect(lastListParams()).not.toHaveProperty('expiring_within_days');
  });

  it('keeps a retired tier selectable in the filter when it is the current filter value', async () => {
    // The tier *filter* used to list active tiers only, so an environment on
    // a retired tier stayed visible in the grid but could never be filtered
    // for — a `?tier_id=` deep link onto a retired tier rendered a blank
    // Select over an already-filtered grid. Same shape as the create/edit
    // form's existing fix (`t.is_active || t.id === form.tier_id`), applied
    // to the filter.
    vi.mocked(environmentTierService.listTiers).mockResolvedValueOnce({
      rows: [
        {
          id: 5,
          tenant_id: 1,
          name: 'Retired',
          description: null,
          category: null,
          color: null,
          display_order: 2,
          is_active: false,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });

    renderEnvironmentList('/environments?tier_id=5');
    await waitFor(() => expect(lastListParams()).toMatchObject({ tier_id: '5' }));

    const tierSelect = screen.getByRole('combobox', { name: 'Tier' });
    expect(tierSelect).toHaveTextContent('Retired');
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

    fireEvent.click(screen.getByText('Governance gap'));

    await waitFor(() => expect(lastListParams()).toMatchObject({ governance_gap: 'true' }));
  });

  it('renders the operations group name that came with the row', async () => {
    // The name travels with the row. Resolving it against the groups
    // collection would render '—' on a miss, which is information lost.
    vi.mocked(environmentService.listEnvironments).mockResolvedValueOnce({
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
          idle: false,
          decommission_state: null,
          status: 'active',
          tenant_id: 1,
          custom_fields: null,
          operations_group_id: 4,
          operations_group_name: 'SRE',
          access_url: null,
          connection_notes: null,
          support_contact: null,
          sla_notes: null,
          known_limitations: null,
          decommission_notes: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });

    renderEnvironmentList('/environments');
    await waitFor(() => {
      const columns = (capturedGridProps.current?.columns ?? []) as GridColDef[];
      expect(columns.some((c) => c.field === 'operations_group_name')).toBe(true);
    });
    const byField = Object.fromEntries(
      (capturedGridProps.current?.columns as GridColDef[]).map((c) => [c.field, c])
    );
    // Not in the backend whitelist — it is a joined column, not an
    // Environment column, so a sortable header would 422 on click.
    expect(byField.operations_group_name.sortable).toBe(false);

    // The row's own operations_group_name, not a lookup against the groups
    // collection (which is empty in this test) — a resolve-by-id bug would
    // render '—' here instead.
    await screen.findByText('SRE');
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

    // Namespaced (`cf_${field_key}`), not the raw key — see the collision
    // tests below for why. `headerName` is untouched, since that's what the
    // user actually sees.
    expect(column.field).toBe('cf_region');
    expect(column.headerName).toBe('Region');
    expect(column.sortable).toBe(false);
  });

  it('never generates a custom-field column whose field collides with a static one', () => {
    // The bug this branch shipped: the demo tenant has a custom field
    // definition keyed 'owner' — evidently how people recorded an owner
    // before this page had a real Owner column — and this branch added a
    // static column also named 'owner'. Two GridColDefs with the same
    // `field` make MUI treat them as one column internally: duplicate
    // headers, and a visibility toggle on one silently hides the other.
    // `tier`, `expires_at` and `reserved_now` are this branch's other new
    // static fields — any of them is one tenant custom-field rename away
    // from the same collision.
    const staticFields = new Set(environmentColumns.map((c) => c.field));
    expect(staticFields).toEqual(
      new Set([
        'name',
        'tier',
        'owner',
        'expires_at',
        'reserved_now',
        // B5's Idle and Decommission columns. Neither can collide with a
        // tenant custom field the way `owner` did: buildCustomFieldColumns
        // namespaces every custom column `cf_<key>` — see the collision
        // tests in environmentIdleColumn.test.tsx for a `field_key: 'idle'`
        // custom field specifically.
        'idle',
        'decommission_state',
        // B2's Compliance column. Named `compliance`, not after a field a
        // tenant might key a custom field on — and namespacing makes a
        // collision impossible either way.
        'compliance',
        'status',
        'operations_group_name',
        'created_at',
        'actions',
      ])
    );

    const defs: CustomFieldDefinition[] = ['owner', 'tier', 'expires_at', 'reserved_now', 'region'].map(
      (key, i) => ({
        id: i + 1,
        tenant_id: 1,
        entity_type: 'environment',
        entity_subtype: null,
        field_key: key,
        label: key,
        field_type: 'text',
        required: false,
        display_order: i,
        options: null,
        lifecycle_states: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      })
    );

    const customCols = buildCustomFieldColumns(defs);
    expect(customCols).toHaveLength(defs.length);
    customCols.forEach((col) => expect(staticFields.has(col.field)).toBe(false));
    // And they don't collide with each other either.
    expect(new Set(customCols.map((c) => c.field)).size).toBe(customCols.length);
  });

  it('renders the static Owner column and a colliding custom Owner field as two distinct columns', async () => {
    // Reproduces the exact demo-tenant fixture: a custom field keyed
    // 'owner'. Before the fix both grid entries shared `field: 'owner'`;
    // now the custom one is `cf_owner`. Assert on the columns actually
    // handed to DataGrid (capturedGridProps), not rendered DOM header text —
    // the un-virtualized stand-in above renders body cells only, no header
    // row, and even a real DataGrid wouldn't disambiguate two columns that
    // share one `field` since MUI keys its column lookup by `field`.
    vi.mocked(customFieldService.listDefinitions).mockResolvedValueOnce([
      {
        id: 99,
        tenant_id: 1,
        entity_type: 'environment',
        entity_subtype: null,
        field_key: 'owner',
        label: 'Owner',
        field_type: 'text',
        required: false,
        display_order: 1,
        options: null,
        lifecycle_states: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]);

    renderEnvironmentList('/environments');
    await screen.findByText('prod-a');
    await waitFor(() => {
      const columns = (capturedGridProps.current?.columns ?? []) as GridColDef[];
      expect(columns.some((c) => c.field === 'cf_owner')).toBe(true);
    });

    const columns = capturedGridProps.current?.columns as GridColDef[];
    const ownerHeaders = columns.filter((c) => c.headerName === 'Owner');
    // Two sources, two columns, two distinct field ids — not collapsed into
    // one and not duplicated under the same id.
    expect(ownerHeaders).toHaveLength(2);
    expect(new Set(ownerHeaders.map((c) => c.field))).toEqual(new Set(['owner', 'cf_owner']));
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
      idle: false,
      decommission_state: null,
      status: 'active',
      tenant_id: 1,
      custom_fields: null,
      operations_group_id: null,
      operations_group_name: null,
      access_url: null,
      connection_notes: null,
      support_contact: null,
      sla_notes: null,
      known_limitations: null,
      decommission_notes: null,
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

  // Same decision, same shape, as the expires_at pair above:
  // operations_group_id must always be sent explicitly on update — including
  // explicit null — because EnvironmentUpdate also keys on
  // model_fields_set, and an omitted key means "leave alone". Neither
  // behaviour has any other test guarding it.
  it('lets Edit save with no operations group, sending explicit null rather than leaving it alone', async () => {
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
      idle: false,
      decommission_state: null,
      status: 'active',
      tenant_id: 1,
      custom_fields: null,
      operations_group_id: null,
      operations_group_name: null,
      access_url: null,
      connection_notes: null,
      support_contact: null,
      sla_notes: null,
      known_limitations: null,
      decommission_notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    renderEnvironmentList('/environments');
    // The prod-a fixture (see the environmentService mock above) already has
    // operations_group_id: null — exactly the row this decision is about.
    await screen.findByText('prod-a');

    const editButtons = screen
      .getAllByRole('button', { hidden: true })
      .filter((b) => b.getAttribute('aria-label') === 'Edit');
    expect(editButtons.length).toBeGreaterThan(0);
    fireEvent.click(editButtons[0]);

    const dialog = await screen.findByRole('dialog');
    // No group selected — form.operations_group_id starts '' for this row.
    await within(dialog).findByRole('combobox', { name: 'Operations Group' });

    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ operations_group_id: null })
      )
    );
  });

  it('keeps a soft-deleted operations group selectable in the edit dialog', async () => {
    // Same shape as the retired-tier (filter) and deactivated-owner (form)
    // cases above: an environment can carry a group id that GET
    // /tenant/groups no longer lists because the group was soft-deleted.
    // Without the keep-selectable branch, MUI renders the Select blank with
    // an out-of-range warning while form state still holds the id.
    vi.mocked(environmentTierService.listTiers).mockResolvedValueOnce({
      rows: [PRODUCTION_TIER],
      total: 1,
    });
    vi.mocked(api.get).mockResolvedValueOnce({ data: [{ id: 7, username: 'alice' }] });
    vi.mocked(environmentService.listEnvironments).mockResolvedValueOnce({
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
          idle: false,
          decommission_state: null,
          status: 'active',
          tenant_id: 1,
          custom_fields: null,
          operations_group_id: 4,
          operations_group_name: 'SRE',
          access_url: null,
          connection_notes: null,
          support_contact: null,
          sla_notes: null,
          known_limitations: null,
          decommission_notes: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });

    renderEnvironmentList('/environments');
    await screen.findByText('prod-a');

    const editButtons = screen
      .getAllByRole('button', { hidden: true })
      .filter((b) => b.getAttribute('aria-label') === 'Edit');
    fireEvent.click(editButtons[0]);

    const dialog = await screen.findByRole('dialog');
    const groupSelect = within(dialog).getByRole('combobox', { name: 'Operations Group' });
    expect(groupSelect).toHaveTextContent('SRE');
    expect(groupSelect).toHaveTextContent(/deleted/i);
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

  describe('loadColumnModel', () => {
    afterEach(() => {
      localStorage.removeItem('environments-list-columns-777');
    });

    it('discards a persisted entry for a column id that no longer exists', () => {
      // Simulates exactly what shipped: MUI auto-persisted {"owner": false}
      // while the static and custom-field 'owner' columns collided. A
      // *different* stale key (one that, unlike 'owner', doesn't happen to
      // be reused by a real column) demonstrates the general mechanism —
      // the 'owner' case itself is inherently unrecoverable this way, since
      // that exact key legitimately names today's static column too; see
      // the comment on loadColumnModel and this suite's commit message.
      localStorage.setItem(
        'environments-list-columns-777',
        JSON.stringify({ retired_field: false, status: false })
      );

      const model = loadColumnModel(777, ['name', 'tier', 'owner', 'status']);

      expect(model).toEqual({ status: false });
    });

    it('always keeps a cf_-prefixed entry, even for a custom field not in the known list yet', () => {
      // Custom-field definitions load asynchronously (fetchDefinitions), so
      // on the very first render `knownStaticFields` only reflects the
      // static columns. A namespaced entry must survive that window rather
      // than being wrongly treated as stale and dropped before the
      // tenant's definitions have even arrived.
      localStorage.setItem(
        'environments-list-columns-777',
        JSON.stringify({ cf_region: false })
      );

      const model = loadColumnModel(777, ['name', 'tier', 'owner', 'status']);

      expect(model).toEqual({ cf_region: false });
    });

    it('defaults knownStaticFields to the real static column list, not a hardcoded one', () => {
      // No second argument — exercises the default parameter, which reads
      // `environmentColumns` directly rather than a copy-pasted list that
      // could drift from it.
      localStorage.setItem(
        'environments-list-columns-777',
        JSON.stringify({ owner: false, made_up_field: true })
      );

      const model = loadColumnModel(777);

      expect(model).toEqual({ owner: false });
    });
  });
});
