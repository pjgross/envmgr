import type { ReactNode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import EnvironmentList, { environmentColumns } from '../EnvironmentList';
import EnvironmentDetail from '../EnvironmentDetail';

// Three rows so all three branches of the Compliance cell are observable in
// one render: quarantined, in gap but still inside grace, and clean.
const { QUARANTINED, IN_GAP, CLEAN } = vi.hoisted(() => {
  const base = {
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
  return {
    QUARANTINED: {
      ...base,
      id: 1,
      name: 'Legacy Box',
      name_compliant: false,
      quarantined: true,
      compliance_gaps: ["The name does not match this tenant's naming convention"],
    },
    IN_GAP: {
      ...base,
      id: 2,
      name: 'new-box',
      name_compliant: false,
      quarantined: false,
      compliance_gaps: ['No owner is recorded'],
    },
    CLEAN: {
      ...base,
      // name_compliant null means "no pattern applies" — COMPLIANT, never
      // unknown and never failing. A cell that treated null as a failure would
      // flag the whole estate of a tenant with no policy.
      ...{ id: 3, name: 'payments-uat-01', name_compliant: null },
      quarantined: false,
      compliance_gaps: [],
    },
  };
});

const POLICY = {
  is_enabled: true,
  name_pattern: '[a-z]+-(dev|uat|prod)-\\d{2}',
  name_pattern_example: 'payments-uat-01',
  required_attributes: ['owner'],
  grace_days: 14,
  effective_from: '2026-08-09T00:00:00Z',
};

vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn(),
    getEnvironment: vi.fn(),
    createEnvironment: vi.fn(),
    updateEnvironment: vi.fn(),
    deleteEnvironment: vi.fn().mockResolvedValue(undefined),
    listSystemsInEnvironment: vi
      .fn()
      .mockResolvedValue({ systems: [], missing_systems: [] }),
  },
}));

vi.mock('../../../services/environmentNamingPolicyService', () => ({
  environmentNamingPolicyService: {
    get: vi.fn(),
    save: vi.fn(),
    preview: vi.fn(),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: { listDefinitions: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn().mockResolvedValue({
      rows: [
        {
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
        },
      ],
      total: 1,
    }),
  },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: { listSystems: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

// The panels EnvironmentDetail mounts unconditionally below Handover. Left
// unmocked each renders its own error Alert in jsdom, which would collide with
// this file's alert assertions.
vi.mock('../../../services/projectService', () => ({
  projectService: {
    listAgreementsForEnvironment: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroupsForEnvironment: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

// The owner picker calls GET /tenant/users/lite straight through `api`.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [{ id: 7, username: 'alice' }] }) },
}));

// The real DataGrid virtualizes columns by container width and jsdom reports
// zero width, so only the first few columns' cells mount — which would hide the
// Compliance cell no matter where it sits. Same stand-in as
// environmentListServerGrid.test.tsx.
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
import { environmentNamingPolicyService } from '../../../services/environmentNamingPolicyService';

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

function renderDetail(envId: number) {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/environments/${envId}`]}>
        <Routes>
          <Route path="/environments/:id" element={<EnvironmentDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ rows: [QUARANTINED, IN_GAP, CLEAN], total: 3 });
  vi.mocked(environmentNamingPolicyService.get).mockResolvedValue(POLICY);
  vi.mocked(environmentService.getEnvironment).mockResolvedValue(QUARANTINED);
});

describe('B2 advises; it never blocks', () => {
  it('leaves every action on a quarantined row exactly as it is on a clean one', async () => {
    // The fixture is deliberately one where a block COULD be observed: the row
    // is quarantined AND the page renders its actions. A3's reviewer gated a
    // control on a gap and watched 50 tests pass because the fixture could not
    // have shown the control either way.
    renderList();
    await screen.findByText('Legacy Box');

    const quarantinedActions = within(screen.getByTestId('cell-1-actions'));
    const cleanActions = within(screen.getByTestId('cell-3-actions'));
    for (const label of ['Edit', 'Delete']) {
      const onQuarantined = quarantinedActions.getByRole('button', { name: label });
      expect(onQuarantined).toBeEnabled();
      expect(cleanActions.getByRole('button', { name: label })).toBeEnabled();
    }

    expect(screen.queryByText(/cannot be booked/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/blocked/i)).not.toBeInTheDocument();
  });

  it('says on the detail page that a quarantined environment is still usable', async () => {
    renderDetail(1);
    // The name appears in both the breadcrumb and the heading.
    await screen.findAllByText(/Legacy Box/);
    const banner = await screen.findByTestId('compliance-banner');
    expect(banner).toHaveTextContent(/Quarantined by the naming/i);
    expect(banner).toHaveTextContent(/still be booked/i);
    // The gap itself, verbatim from the server — the browser does not word it.
    expect(banner).toHaveTextContent(/does not match/i);
  });

  it('does not call an environment still inside its grace period quarantined', async () => {
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(IN_GAP);
    renderDetail(2);
    await screen.findAllByText(/new-box/);

    const banner = await screen.findByTestId('compliance-banner');
    expect(banner).toHaveTextContent(/does not meet the naming/i);
    expect(banner).toHaveTextContent(/Nothing is restricted/i);
    // It may say it *will* be quarantined if the grace period elapses; it must
    // not say it already is.
    expect(banner).not.toHaveTextContent(/Quarantined by the naming/i);
  });

  it('renders no banner at all for an environment with no gaps', async () => {
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(CLEAN);
    renderDetail(3);
    await screen.findAllByText(/payments-uat-01/);
    expect(screen.queryByTestId('compliance-banner')).not.toBeInTheDocument();
  });
});

describe('the Compliance column', () => {
  it('labels a quarantined row, a row still in grace, and a clean row differently', async () => {
    renderList();
    await screen.findByText('Legacy Box');

    expect(within(screen.getByTestId('cell-1-compliance')).getByText('Quarantined')).toBeInTheDocument();
    expect(within(screen.getByTestId('cell-2-compliance')).getByText('Policy gap')).toBeInTheDocument();
    // name_compliant null + no gaps: no policy applies, so nothing is claimed.
    expect(screen.getByTestId('cell-3-compliance')).toHaveTextContent('—');
  });

  it('is unsortable — no single column backs it', () => {
    // It is computed from name_compliant + created_at + the policy, so a
    // sortable header would send a sort_by that `sorting()` answers with a 422.
    const col = environmentColumns.find((c) => c.field === 'compliance');
    expect(col?.sortable).toBe(false);
  });
});

describe('the compliance filters', () => {
  it('sends compliance_gap and quarantined from the URL', async () => {
    // A key missing from useServerGrid's filterKeys is written to the URL by
    // setFilter but never read back into `filters`, so it never reaches the
    // request — the URL reads ?quarantined=true beside an unfiltered grid.
    renderList('/environments?compliance_gap=true&quarantined=true');
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ compliance_gap: 'true', quarantined: 'true' })
    );
  });

  it("returns to an OMITTED key, never 'all', when a chip is switched off", async () => {
    // buildParams' own no-selection sentinel is 'all', so a vocabulary
    // containing it builds byte-identical params for two different states and
    // the grid never refetches. An empty ?compliance_gap= is a 422 server-side.
    renderList();
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    // The filter chip, by role: only a clickable Chip is a button, so this
    // cannot accidentally match the same label rendered in a grid cell.
    const chip = screen.getByRole('button', { name: 'Policy gap' });
    await userEvent.click(chip);
    await waitFor(() => expect(lastListParams()).toMatchObject({ compliance_gap: 'true' }));

    await userEvent.click(chip);
    await waitFor(() => expect(lastListParams()).not.toHaveProperty('compliance_gap'));
    expect(Object.values(lastListParams() ?? {})).not.toContain('all');
  });

  it('filters on quarantined independently of the policy-gap chip', async () => {
    renderList();
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('button', { name: 'Quarantined' }));
    await waitFor(() => expect(lastListParams()).toMatchObject({ quarantined: 'true' }));
    expect(lastListParams()).not.toHaveProperty('compliance_gap');
  });
});

describe('the naming pattern on the forms', () => {
  it('shows the tenant pattern and its example under the name field', async () => {
    // The example is what the 422 will quote, so the form has to teach the same
    // name the server would accept.
    renderList();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    await userEvent.click(screen.getByRole('button', { name: /new environment/i }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/payments-uat-01/)).toBeInTheDocument();
  });

  it('says nothing about a pattern when the tenant has no policy', async () => {
    // An empty helper text is worse than none: it implies a rule exists.
    vi.mocked(environmentNamingPolicyService.get).mockResolvedValue({
      ...POLICY,
      is_enabled: false,
      name_pattern: null,
      name_pattern_example: null,
    });
    renderList();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    await userEvent.click(screen.getByRole('button', { name: /new environment/i }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByText(/must match/i)).not.toBeInTheDocument();
  });
});
