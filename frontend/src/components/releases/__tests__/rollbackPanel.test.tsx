/**
 * Phase 9 C4, task 9 — RollbackPanel and RollbackPlanDialog.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
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
import type { ReleaseReadinessResponse } from '../../../types/gateReadiness';

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
    getReadiness: vi.fn(),
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

// A component the panel does NOT render a row for (role 'regression'), but
// whose plan IS present in the plans list — the shape Finding 5 says no
// fixture in the old suite ever exercised. Used to prove the rollup renders
// the BACKEND's answer rather than one derived from `visiblePlans`.
const PLAN_REPORTING: RollbackPlanResponse = {
  id: 102,
  release_id: 1,
  system_id: 12,
  system_name: 'Reporting',
  steps: 'N/A — not a changing component.',
  reversibility: 'irreversible',
  estimated_minutes: null,
  notes: null,
  agreed_by_user_id: null,
  agreed_by_username: null,
  agreed_at: null,
};

function readinessFixture(
  overrides: Partial<ReleaseReadinessResponse> = {}
): ReleaseReadinessResponse {
  return {
    ok: true,
    release_id: 1,
    checked_at: '2026-08-21T00:00:00Z',
    blockers: [],
    warnings: [],
    reversibility: null,
    ...overrides,
  };
}

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
    vi.mocked(releaseService.getReadiness).mockResolvedValue(readinessFixture());
  });

  it('shows the release rollup and names the irreversible component', async () => {
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_PAYMENTS]);
    vi.mocked(releaseService.getReadiness).mockResolvedValue(
      readinessFixture({ reversibility: 'irreversible' })
    );

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

  it('surfaces the server reason when agreeing to a plan is refused (Finding 4)', async () => {
    // Before the fix, agreeRollbackPlan had NO .rejected reducer and
    // handleAgree never inspected the dispatch result — a refused agreement
    // produced nothing: no alert, no state change, the Agree button just
    // stayed there. A plain rejected Error would pass a naive assertion
    // here; use a real AxiosError shape so the test would fail if the code
    // ever read `result.error.message` (the generic "Request failed with
    // status code 409") instead of `formatApiError`'s server-supplied text.
    const err = new AxiosError('Request failed with status code 409');
    (err as unknown as { response: unknown }).response = {
      status: 409,
      data: { detail: 'This plan was deleted in another tab.' },
    };
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_PAYMENTS]);
    vi.mocked(rollbackService.agreePlan).mockRejectedValue(err);

    renderPanel();

    const agreeButton = await screen.findByRole('button', { name: /^agree$/i });
    await userEvent.click(agreeButton);

    await waitFor(() =>
      expect(screen.getByText(/this plan was deleted in another tab/i)).toBeInTheDocument()
    );
    // The generic Axios message must never be what the user sees.
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
    // And the Agree button is still there — nothing pretended the agreement
    // succeeded.
    expect(screen.getByRole('button', { name: /^agree$/i })).toBeInTheDocument();
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

  // ── Finding 5 — discriminating tests for the rollup, post F1/F2 fix ──────
  // Three mutations (drop the role filter, hardcode the rollup, hardcode the
  // row chip) all survived the old 6-test suite. The old rollup was computed
  // client-side from `visiblePlans`, so no fixture could tell "reads the
  // backend's field" apart from "recomputes the same thing" — they always
  // agreed. These tests deliberately make the backend's `reversibility` and
  // what the VISIBLE rows would imply DISAGREE, so only "renders
  // readiness.reversibility, unmodified" can pass all three.

  it('renders the rollup from readiness.reversibility, not a value derived from the visible rows', async () => {
    // Every VISIBLE row is 'reversible' (Notifications). If the rollup were
    // still computed client-side from the rows on screen, it would read
    // "Reversible" or "No rollback plans yet" — never "Irreversible". A
    // fixture on a regression-role component (PLAN_REPORTING, never
    // rendered as a row) supplies the disagreement: only the backend knows
    // about it, the same shape an orphaned plan (Findings 1+2) takes.
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_NOTIFICATIONS, PLAN_REPORTING]);
    vi.mocked(releaseService.getReadiness).mockResolvedValue(
      readinessFixture({ reversibility: 'irreversible' })
    );

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText(/Rollback readiness: Irreversible/i)).toBeInTheDocument();
    });
    // The Reporting row must still not render at all (role 'regression').
    expect(screen.queryByText('Reporting')).not.toBeInTheDocument();
  });

  it('does NOT render a rollup when readiness has none, even though a visible plan is irreversible', async () => {
    // The reverse disagreement: a visible, irreversible plan is on screen,
    // but the backend reports no rollup (e.g. the readiness fetch is still
    // resolving to null, or genuinely has none to report). A client-side
    // fallback that derived from `visiblePlans` would show "Irreversible"
    // here; the fix must show the neutral "No rollback plans yet" chip
    // instead, because that value never came from the server.
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_PAYMENTS]);
    vi.mocked(releaseService.getReadiness).mockResolvedValue(readinessFixture());

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText('No rollback plans yet')).toBeInTheDocument();
    });
    // Payments' OWN row chip is unaffected — it still names its own plan's
    // reversibility (see the per-row test below); only the release-level
    // rollup chip is null here.
    expect(screen.queryByText(/Rollback readiness:/i)).not.toBeInTheDocument();
  });

  it('the per-row reversibility chip reflects each plan\'s own value, independent of the rollup', async () => {
    // The rollup (from readiness) and the two rows' own values are all
    // DIFFERENT here — 'lossy' overall, 'irreversible' for Payments,
    // 'reversible' for Notifications. A hardcoded row chip ("Reversible" for
    // every row, the mutation the old suite missed) fails this immediately,
    // and so would a row chip that read the rollup instead of its own plan.
    vi.mocked(rollbackService.listPlans).mockResolvedValue([PLAN_PAYMENTS, PLAN_NOTIFICATIONS]);
    vi.mocked(releaseService.getReadiness).mockResolvedValue(
      readinessFixture({ reversibility: 'lossy' })
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText('Payments')).toBeInTheDocument());

    const paymentsRow = screen.getByText('Payments').closest('tr');
    const notificationsRow = screen.getByText('Notifications').closest('tr');
    expect(paymentsRow).not.toBeNull();
    expect(notificationsRow).not.toBeNull();
    expect(within(paymentsRow as HTMLElement).getByText('Irreversible')).toBeInTheDocument();
    expect(within(notificationsRow as HTMLElement).getByText('Reversible')).toBeInTheDocument();
    // And the release-level rollup names the THIRD, different value.
    expect(screen.getByText(/Rollback readiness: Lossy/i)).toBeInTheDocument();
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
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('leaves the record-rollback action enabled when plans are missing', async () => {
    // The UI half of the backend guard (test_c4_records_never_refuses.py).
    // Assert the control is THERE and ENABLED on a fixture where a row would
    // otherwise render with no plan at all — a fixture that renders no
    // control cannot detect gating.
    vi.mocked(releaseService.listSystems).mockResolvedValue(SYSTEMS);
    vi.mocked(rollbackService.listPlans).mockResolvedValue([]);
    vi.mocked(rollbackService.listAuthorisations).mockResolvedValue([]);
    vi.mocked(releaseService.getReadiness).mockResolvedValue(readinessFixture());

    renderPanel();

    expect(await screen.findByRole('button', { name: /record a rollback/i })).toBeEnabled();
  });
});
