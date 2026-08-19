import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentLifecyclePanel from '../EnvironmentLifecyclePanel';
import EnvironmentTiersPanel from '../EnvironmentTiersPanel';
import environmentLifecyclePolicyReducer from '../../../store/environmentLifecyclePolicySlice';
import decommissionReducer from '../../../store/decommissionSlice';
import environmentTierReducer from '../../../store/environmentTierSlice';
import { environmentLifecyclePolicyService } from '../../../services/environmentLifecyclePolicyService';
import { decommissionService } from '../../../services/decommissionService';
import { environmentTierService } from '../../../services/environmentTierService';

vi.mock('../../../services/environmentLifecyclePolicyService', () => ({
  environmentLifecyclePolicyService: {
    get: vi.fn(),
    save: vi.fn(),
  },
}));

vi.mock('../../../services/decommissionService', () => ({
  decommissionService: {
    getForEnvironment: vi.fn(),
    initiate: vi.fn(),
    requestExtension: vi.fn(),
    decideExtension: vi.fn(),
    signAttestation: vi.fn(),
    tearDown: vi.fn(),
    cancel: vi.fn(),
    listSteps: vi.fn(),
    createStep: vi.fn(),
    updateStep: vi.fn(),
    deleteStep: vi.fn(),
    listWorklist: vi.fn(),
  },
}));

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
  },
}));

// The real DataGrid virtualizes columns by container width, and jsdom always
// reports zero width — an unvirtualized stand-in, same as
// environmentTiersPanel.test.tsx / userGroups.test.tsx, so every column's
// renderCell actually mounts.
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

const POLICY = {
  idle_detection_enabled: true,
  idle_threshold_days: 30,
  decommission_notice_days: 5,
};

const STEP = {
  id: 1,
  key: 'final_backup',
  label: 'Final backup taken',
  description: 'A snapshot or export exists outside the environment itself.',
  display_order: 10,
  is_required: true,
  is_active: true,
};

function renderPanel(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      environmentLifecyclePolicy: environmentLifecyclePolicyReducer,
      decommission: decommissionReducer,
      // Minimal stand-in — the panel only reads `state.auth.user`, the same
      // approach UserGroups.tsx's own test takes.
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <EnvironmentLifecyclePanel />
    </Provider>
  );
}

function renderTiersPanel() {
  const store = configureStore({
    reducer: { environmentTier: environmentTierReducer },
  });
  return render(
    <Provider store={store}>
      <EnvironmentTiersPanel />
    </Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(environmentLifecyclePolicyService.get).mockResolvedValue(POLICY);
  vi.mocked(environmentLifecyclePolicyService.save).mockResolvedValue(POLICY);
  vi.mocked(decommissionService.listSteps).mockResolvedValue([STEP]);
});

describe('EnvironmentLifecyclePanel', () => {
  it('loads the policy in force', async () => {
    renderPanel();
    expect(await screen.findByDisplayValue('30')).toBeInTheDocument();
    expect(screen.getByDisplayValue('5')).toBeInTheDocument();
    const toggle = screen.getByRole('checkbox', { name: /idle detection enabled/i });
    expect(toggle).toBeChecked();
  });

  it('a tenant with no saved policy reads the unsaved defaults, not an error', async () => {
    // get_policy answers an UNSAVED default instance (disabled, 30/5) rather
    // than 404ing — a caller that treated this as an error state would show
    // a broken page for the ordinary "never configured" tenant.
    vi.mocked(environmentLifecyclePolicyService.get).mockResolvedValue({
      idle_detection_enabled: false,
      idle_threshold_days: 30,
      decommission_notice_days: 5,
    });
    renderPanel();
    expect(await screen.findByDisplayValue('30')).toBeInTheDocument();
    expect(screen.queryByText(/fail|error/i)).not.toBeInTheDocument();
  });

  it('PUTs the update model and never the read model', async () => {
    // The schema declares extra="forbid" and — unlike the naming policy —
    // this read model has no id/timestamps to begin with, so the two models
    // happen to share one key set today. Pin it explicitly anyway: a field
    // added to either side later must not silently leak into the other.
    renderPanel();
    await screen.findByDisplayValue('30');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(environmentLifecyclePolicyService.save).toHaveBeenCalled());
    const body = vi.mocked(environmentLifecyclePolicyService.save).mock.calls[0][0];
    expect(Object.keys(body).sort()).toEqual([
      'decommission_notice_days',
      'idle_detection_enabled',
      'idle_threshold_days',
    ]);
  });

  it('shows a non-admin the settings read-only rather than hiding them', async () => {
    // Reads are open to any tenant member (get_current_user); only writes
    // are Admin (require_tenant_admin()). B3a's UserGroups UI was over-gated
    // on exactly the false analogy with /tenant/users — which really is
    // admin-gated throughout — and it took a review to catch. The fields
    // must still be VISIBLE and populated for a non-admin, just disabled.
    renderPanel('Member');
    await screen.findByDisplayValue('30');
    expect(screen.getByDisplayValue('30')).toBeInTheDocument();
    expect(screen.getByDisplayValue('5')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /idle detection enabled/i })).toBeChecked();

    expect(screen.queryByRole('button', { name: /^save$/i })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /idle detection enabled/i })).toBeDisabled();
    expect(screen.getByDisplayValue('30')).toBeDisabled();
  });

  it('shows the write controls for an admin', async () => {
    renderPanel('Admin');
    await screen.findByDisplayValue('30');
    expect(screen.getByRole('button', { name: /^save$/i })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /idle detection enabled/i })).not.toBeDisabled();
  });

  it('says what enabling idle detection will do, since it defaults to off', async () => {
    // Same shape as B2's `?governance_gap=true` matching every existing
    // environment on first deploy — flipping this switch is estate-wide and
    // immediate, not something that only affects bookings made from now on.
    renderPanel();
    await screen.findByDisplayValue('30');
    expect(screen.getByText(/immediately flags every environment/i)).toBeInTheDocument();
  });

  it('shows the server error text, not an HTTP status, on a refused save', async () => {
    const axiosError = Object.assign(new Error('Request failed with status code 422'), {
      isAxiosError: true,
      response: {
        status: 422,
        data: { detail: 'idle_threshold_days must be between 1 and 3650' },
      },
    });
    vi.mocked(environmentLifecyclePolicyService.save).mockRejectedValue(axiosError);

    renderPanel();
    await screen.findByDisplayValue('30');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByText(/must be between 1 and 3650/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/status code 422/i)).not.toBeInTheDocument();
  });

  it('lists the decommission checklist steps and lets an admin retire one without alarming data-loss language', async () => {
    vi.mocked(decommissionService.deleteStep).mockResolvedValue(undefined);
    renderPanel();
    await screen.findByDisplayValue('30');
    expect(await screen.findByText('Final backup taken')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));
    // Deleting is a soft delete that is never refused (see
    // decommissionService.deleteStep's comment) and existing attestations
    // keep step_key as a plain string — so the confirmation must not claim
    // data is lost or that the delete could be blocked.
    expect(screen.queryByText(/cannot be undone/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/will be lost/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^retire$/i }));

    await waitFor(() => expect(decommissionService.deleteStep).toHaveBeenCalledWith(1));
  });

  it('hides the step write controls for a non-admin', async () => {
    renderPanel('Member');
    await screen.findByDisplayValue('30');
    await screen.findByText('Final backup taken');
    expect(screen.queryByRole('button', { name: /new step/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it('sends the full DecommissionStepWrite shape on create, not a partial patch', async () => {
    vi.mocked(decommissionService.createStep).mockResolvedValue({
      ...STEP,
      id: 2,
      key: 'dns_removed',
      label: 'DNS entries removed',
    });
    renderPanel();
    await screen.findByDisplayValue('30');
    await userEvent.click(screen.getByRole('button', { name: /new step/i }));

    await userEvent.type(screen.getByLabelText(/^key/i), 'dns_removed');
    await userEvent.type(screen.getByLabelText(/^label/i), 'DNS entries removed');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(decommissionService.createStep).toHaveBeenCalled());
    const body = vi.mocked(decommissionService.createStep).mock.calls[0][0];
    expect(body).toMatchObject({
      key: 'dns_removed',
      label: 'DNS entries removed',
      is_required: true,
      is_active: true,
    });
  });

  // Task 14, rule 3: NULL means "use the tenant default" — a legitimate
  // state, not a missing value. This exercises EnvironmentTiersPanel (the
  // "tier editor" the brief names as a file to modify) rather than
  // EnvironmentLifecyclePanel, but the dispatch's own test command for this
  // task names only this file, so it lives here alongside the other two
  // discrimination proofs. See environmentTiersPanel.test.tsx for the fuller
  // set of tier-override tests (blank-on-null, populated-when-set, explicit
  // null on clear, typed value on create).
  it('leaves the tier threshold blank rather than showing the tenant default', async () => {
    vi.mocked(environmentTierService.listTiers).mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'Dev',
          description: null,
          category: 'dev',
          color: '#90A4AE',
          display_order: 10,
          is_active: true,
          created_at: '2026-08-16T00:00:00Z',
          updated_at: '2026-08-16T00:00:00Z',
          // No per-tier override on record — must render blank, never
          // pre-filled with the tenant's idle_threshold_days (30 above).
          idle_threshold_days: null,
        },
      ],
      total: 1,
    });
    renderTiersPanel();
    await waitFor(() => expect(screen.getByText('Dev')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    const field = await screen.findByLabelText(/idle threshold override/i);
    expect(field).toHaveValue(null);
    expect(field).not.toHaveValue(30);
  });
});
