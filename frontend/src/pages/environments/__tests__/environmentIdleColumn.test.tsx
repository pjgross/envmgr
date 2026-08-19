import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import EnvironmentList, { environmentColumns, buildCustomFieldColumns } from '../EnvironmentList';
import type { CustomFieldDefinition } from '../../../types/customField';

// Task 11 (B5): the Idle chip and the Decommission-state chip on the
// environment list, plus the ?idle= filter. Backend (Tasks 1-9) and the
// frontend types/service/slice (Task 10) already carry `idle: boolean` and
// `decommission_state: DecommissionState | null` on every row — see
// EnvironmentResponse in types/environment.ts.
//
// Mocking pattern (services + an un-virtualized DataGrid stand-in) matches
// environmentListServerGrid.test.tsx and environmentCompliance.test.tsx: the
// real DataGrid virtualizes columns by container width, jsdom always reports
// zero width, and only the first few columns' cells would ever mount — which
// would hide these two new columns no matter where they sit in the list.

const BASE_ENV = {
  description: null,
  tier_id: 3,
  tier_name: 'Production',
  tier_color: '#c62828',
  owner_user_id: 7,
  owner_username: 'alice',
  expires_at: null,
  reserved_now: false,
  status: 'active' as const,
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
};

const IDLE_ROW = { ...BASE_ENV, id: 1, name: 'Ghost UAT', idle: true, decommission_state: null };
const BUSY_ROW = { ...BASE_ENV, id: 2, name: 'Busy SIT', idle: false, decommission_state: null };
const DYING_ROW = {
  ...BASE_ENV,
  id: 3,
  name: 'Old Perf',
  idle: true,
  decommission_state: 'warned' as const,
};

vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
    getEnvironment: vi.fn(),
    createEnvironment: vi.fn(),
    updateEnvironment: vi.fn(),
    deleteEnvironment: vi.fn().mockResolvedValue(undefined),
  },
}));

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

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: { listDefinitions: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

// The owner picker calls GET /tenant/users/lite straight through `api`.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}));

// Un-virtualized DataGrid stand-in — see the header comment above.
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
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        valueGetter?: (params: any) => unknown;
      }>;
      return (
        <table>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)} data-testid={`row-${row.id}`}>
                {columns.map((col) => (
                  <td key={col.field} data-testid={`cell-${row.id}-${col.field}`}>
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

const mockList = vi.mocked(environmentService.listEnvironments);

function lastListParams() {
  const calls = mockList.mock.calls;
  return calls[calls.length - 1]?.[0];
}

function renderList(url = '/environments') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <EnvironmentList />
      </MemoryRouter>
    </Provider>
  );
}

const CUSTOM_FIELD_TEMPLATE: CustomFieldDefinition = {
  id: 1,
  tenant_id: 1,
  entity_type: 'environment',
  entity_subtype: null,
  field_key: 'idle',
  label: 'Idle?',
  field_type: 'text',
  required: false,
  display_order: 1,
  options: null,
  lifecycle_states: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ rows: [], total: 0 });
});

describe('EnvironmentList — B5 idle and decommission columns', () => {
  it('renders the Idle chip only for idle rows', async () => {
    mockList.mockResolvedValue({ rows: [IDLE_ROW, BUSY_ROW], total: 2 });
    renderList();

    await screen.findByText('Ghost UAT');
    expect(screen.getAllByTestId('idle-chip')).toHaveLength(1);
    // The busy row's cell renders the same dash reserved_now uses for
    // "false", not a second (empty) chip.
    expect(screen.getByTestId('cell-2-idle')).toHaveTextContent('—');
  });

  it('renders the decommission state as a chip', async () => {
    mockList.mockResolvedValue({ rows: [DYING_ROW], total: 1 });
    renderList();

    await screen.findByText('Old Perf');
    const chip = screen.getByTestId('decommission-chip');
    expect(chip).toHaveTextContent(/warned/i);
  });

  it('renders nothing at all for a row with no decommission — never an empty chip', async () => {
    mockList.mockResolvedValue({ rows: [BUSY_ROW], total: 1 });
    renderList();

    await screen.findByText('Busy SIT');
    expect(screen.queryByTestId('decommission-chip')).not.toBeInTheDocument();
    // Not even a dash: null decommission_state is the common case, not an
    // edge case worth a placeholder.
    expect(screen.getByTestId('cell-2-decommission_state')).toHaveTextContent('');
  });

  it('sends ?idle=true when the filter is set to Idle only', async () => {
    renderList();
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('combobox', { name: 'Idle' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Idle only' }));

    await waitFor(() => expect(lastListParams()).toMatchObject({ idle: 'true' }));
  });

  it('omits the idle key entirely when the filter is Any', async () => {
    // NEVER `all` — buildParams' own no-selection sentinel. A vocabulary
    // containing it would build byte-identical params for two different
    // states, and the grid would never refetch — this has now bitten A3, A4,
    // B2 and B4 in turn.
    renderList();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole('combobox', { name: 'Idle' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Idle only' }));
    await waitFor(() => expect(lastListParams()).toMatchObject({ idle: 'true' }));

    await userEvent.click(screen.getByRole('combobox', { name: 'Idle' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Any' }));

    await waitFor(() => expect(lastListParams()).not.toHaveProperty('idle'));
    expect(Object.values(lastListParams() ?? {})).not.toContain('all');
  });

  it('does not offer Idle or Decommission as sortable columns', () => {
    // Both are computed server-side — idle a correlated EXISTS,
    // decommission_state a correlated scalar subquery — and neither is in
    // ENVIRONMENT_SORTS. A bare ?sort_by=idle would 500 (it isn't even in
    // the sorting() whitelist, so in practice it 422s before that — but
    // sortable: false is what stops the header looking clickable at all).
    const byField = Object.fromEntries(environmentColumns.map((c) => [c.field, c]));
    expect(byField.idle.sortable).toBe(false);
    expect(byField.decommission_state.sortable).toBe(false);
  });

  it('has no custom-field column whose field collides with a static one', () => {
    // A tenant custom field keyed `idle` would otherwise share a grid-column
    // id with the new static `idle` column, and MUI's spurious visibility
    // change gets PERSISTED by saveColumnModel — silently hiding the real
    // column, unrepairable for anyone whose stored model already shares the
    // key. No fixture defines a colliding custom field, so only this
    // structural assertion can catch it.
    const staticFields = new Set(environmentColumns.map((c) => c.field));
    const [customCol] = buildCustomFieldColumns([CUSTOM_FIELD_TEMPLATE]);

    expect(customCol.field).toBe('cf_idle');
    expect(staticFields.has(customCol.field)).toBe(false);
  });

  it('reads a custom field by its RAW key, not the namespaced column id', () => {
    // The namespace is a grid-column id only. A valueGetter that looked up
    // `cf_idle` would render a correctly-named, permanently-empty column.
    const [customCol] = buildCustomFieldColumns([CUSTOM_FIELD_TEMPLATE]);

    expect(
      customCol.valueGetter!({ row: { custom_fields: { idle: 'yes' } } } as never)
    ).toBe('yes');
  });
});
