/**
 * Phase 9 C4, task 9 — RollbackPanel and RollbackPlanDialog.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { AxiosError } from 'axios';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import RollbackPanel from '../RollbackPanel';
import RollbackPlanDialog from '../RollbackPlanDialog';
import rollbackReducer from '../../../store/rollbackSlice';
import { rollbackService } from '../../../services/rollbackService';
import { releaseService } from '../../../services/releaseService';
import type { RollbackPlanResponse } from '../../../types/rollback';
import type { ReleaseSystemResponse } from '../../../types/release';

vi.mock('../../../services/rollbackService', () => ({
  rollbackService: {
    listPlans: vi.fn(),
    upsertPlan: vi.fn(),
    agreePlan: vi.fn(),
    deletePlan: vi.fn(),
    listAuthorisations: vi.fn(),
    recordAuthorisation: vi.fn(),
    listRehearsals: vi.fn(),
    recordRehearsal: vi.fn(),
    getPolicy: vi.fn(),
    updatePolicy: vi.fn(),
  },
}));

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    listSystems: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { rollback: rollbackReducer } });
}

const SYSTEMS: ReleaseSystemResponse[] = [
  {
    id: 1,
    tenant_id: 1,
    release_id: 1,
    system_id: 10,
    system_name: 'Payments',
    role: 'changing',
    deployment_date: null,
  },
  {
    id: 2,
    tenant_id: 1,
    release_id: 1,
    system_id: 11,
    system_name: 'Notifications',
    role: 'changing',
    deployment_date: null,
  },
  {
    id: 3,
    tenant_id: 1,
    release_id: 1,
    system_id: 12,
    system_name: 'Reporting',
    role: 'regression',
    deployment_date: null,
  },
];

const PLAN_PAYMENTS: RollbackPlanResponse = {
  id: 100,
  release_id: 1,
  system_id: 10,
  system_name: 'Payments',
  steps: 'Restore the payments DB from the last snapshot.',
  reversibility: 'irreversible',
  estimated_minutes: 45,
  notes: null,
  agreed_by_user_id: null,
  agreed_by_username: null,
  agreed_at: null,
};

const PLAN_NOTIFICATIONS: RollbackPlanResponse = {
  id: 101,
  release_id: 1,
  system_id: 11,
  system_name: 'Notifications',
  steps: 'Redeploy the previous image.',
  reversibility: 'reversible',
  estimated_minutes: 10,
  notes: null,
  agreed_by_user_id: 5,
  agreed_by_username: 'alice',
  agreed_at: '2026-08-20T00:00:00Z',
};

function renderPanel(releaseId = 1) {
  return render(
    <Provider store={makeStore()}>
      <RollbackPanel releaseId={releaseId} />
    </Provider>
  );
}

describe('RollbackPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(releaseService.listSystems).mockResolvedValue(SYSTEMS);
    vi.mocked(rollbackService.listAuthorisations).mockResolvedValue([]);
  });

  it('shows the release rollup and names the irreversible component', async () => {
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_PAYMENTS]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getAllByText(/irreversible/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/Payments/)).toBeInTheDocument();
    });
  });

  it('distinguishes a written plan from an agreed one', async () => {
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_PAYMENTS, PLAN_NOTIFICATIONS]);

    renderPanel();

    await waitFor(() => {
      // Payments has a written but unagreed plan — an Agree action, enabled.
      expect(screen.getByRole('button', { name: /agree/i })).toBeEnabled();
      // Notifications has an agreed plan — named, not offered an Agree button.
      expect(screen.getByText(/agreed by alice/i)).toBeInTheDocument();
    });
  });

  it('only shows a row for changing/config_only components, not a regression one', async () => {
    vi.mocked(rollbackService.listPlans).mockResolvedValue([]);

    renderPanel();

    await waitFor(() => expect(releaseService.listSystems).toHaveBeenCalled());
    expect(screen.getByText('Payments')).toBeInTheDocument();
    expect(screen.getByText('Notifications')).toBeInTheDocument();
    expect(screen.queryByText('Reporting')).not.toBeInTheDocument();
  });

  it('refetches plans and authorisations when releaseId changes, not just on mount', async () => {
    vi.mocked(rollbackService.listPlans).mockResolvedValue([]);
    const store = makeStore();
    const { rerender } = render(
      <Provider store={store}>
        <RollbackPanel releaseId={1} />
      </Provider>
    );
    await waitFor(() => expect(rollbackService.listPlans).toHaveBeenCalledWith(1));

    rerender(
      <Provider store={store}>
        <RollbackPanel releaseId={2} />
      </Provider>
    );
    await waitFor(() => expect(rollbackService.listPlans).toHaveBeenCalledWith(2));
    expect(rollbackService.listPlans).toHaveBeenCalledTimes(2);
  });
});

describe('RollbackPlanDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the server reason when a save is refused', async () => {
    const err = new AxiosError('Request failed with status code 404');
    (err as unknown as { response: unknown }).response = {
      status: 404,
      data: { detail: 'System not found' },
    };
    vi.mocked(rollbackService.upsertPlan).mockRejectedValue(err);

    render(
      <Provider store={makeStore()}>
        <RollbackPlanDialog releaseId={1} systemId={10} systemName="Payments" open onClose={vi.fn()} />
      </Provider>
    );

    await userEvent.type(screen.getByLabelText(/steps/i), 'Restore from backup');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/System not found/)).toBeInTheDocument());
    // The generic Axios message must never be what the user sees.
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});

describe('C4 records; it never refuses', () => {
  it('leaves the record-rollback action enabled when plans are missing', async () => {
    // The UI half of the backend guard (test_c4_records_never_refuses.py).
    // Assert the control is THERE and ENABLED on a fixture where a row would
    // otherwise render with no plan at all — a fixture that renders no
    // control cannot detect gating.
    vi.mocked(releaseService.listSystems).mockResolvedValue(SYSTEMS);
    vi.mocked(rollbackService.listPlans).mockResolvedValue([]);
    vi.mocked(rollbackService.listAuthorisations).mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByRole('button', { name: /record a rollback/i })).toBeEnabled();
  });
});
