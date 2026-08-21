/**
 * Phase 9 C4, Finding 8 — RollbackPolicyPanel had NO test file at all: the
 * only UI coverage of the policy that turns a warning into a blocker was a
 * check that the button which OPENS the admin page exists. This is the
 * committed version.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import RollbackPolicyPanel from '../RollbackPolicyPanel';
import rollbackReducer from '../../../store/rollbackSlice';
import { rollbackService } from '../../../services/rollbackService';
import type { RollbackPolicy } from '../../../types/rollback';

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

const POLICY: RollbackPolicy = {
  require_rollback_plan: false,
  require_current_rehearsal: false,
  rehearsal_validity_days: 90,
};

function renderPanel(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      rollback: rollbackReducer,
      // Minimal stand-in — the panel only reads state.auth.user, following
      // EnvironmentLifecyclePanel.test.tsx's own approach.
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <RollbackPolicyPanel />
    </Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(rollbackService.getPolicy).mockResolvedValue(POLICY);
  vi.mocked(rollbackService.updatePolicy).mockResolvedValue({
    ...POLICY,
    require_rollback_plan: true,
  });
});

describe('RollbackPolicyPanel', () => {
  it('loads the policy in force', async () => {
    renderPanel();
    await waitFor(() => expect(rollbackService.getPolicy).toHaveBeenCalled());
    expect(await screen.findByDisplayValue('90')).toBeInTheDocument();
    expect(screen.getByLabelText('Require a rollback plan')).not.toBeChecked();
    expect(screen.getByLabelText('Require a current rehearsal')).not.toBeChecked();
  });

  it('saves exactly the three fields the backend accepts, reflecting the toggled value', async () => {
    renderPanel();
    await screen.findByDisplayValue('90');

    await userEvent.click(screen.getByLabelText('Require a rollback plan'));
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(rollbackService.updatePolicy).toHaveBeenCalledWith({
        require_rollback_plan: true,
        require_current_rehearsal: false,
        rehearsal_validity_days: 90,
      })
    );
    expect(await screen.findByText(/policy saved/i)).toBeInTheDocument();
  });

  it('lets a non-admin view but not change the policy', async () => {
    renderPanel('Member');
    await screen.findByDisplayValue('90');

    expect(screen.getByText(/changing it requires an admin/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Require a rollback plan')).toBeDisabled();
    expect(screen.getByLabelText('Require a current rehearsal')).toBeDisabled();
    // No Save button offered at all for a non-writer — matches
    // EnvironmentNamingPolicyPanel/EnvironmentLifecyclePanel's own
    // show-don't-hide convention for a non-admin.
    expect(screen.queryByRole('button', { name: /^save$/i })).not.toBeInTheDocument();
  });

  it('shows the server reason when a save is refused, not the generic Axios message', async () => {
    // RTK's default serializer drops response.data.detail — mock a real
    // AxiosError shape so this would fail if the panel ever read
    // result.error.message instead of formatApiError's text.
    const axiosError = Object.assign(new Error('Request failed with status code 403'), {
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Only an Admin may change this policy.' } },
    });
    vi.mocked(rollbackService.updatePolicy).mockRejectedValue(axiosError);

    renderPanel();
    await screen.findByDisplayValue('90');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByText(/only an admin may change this policy/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/status code 403/i)).not.toBeInTheDocument();
  });

  it('says the policy is advisory and blocks nothing on its own — the copy must not lie', async () => {
    renderPanel();
    await screen.findByDisplayValue('90');
    expect(
      screen.getByText(/nothing here is enforced by this product/i)
    ).toBeInTheDocument();
  });
});
