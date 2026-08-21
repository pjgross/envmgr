/**
 * Phase 9 C4, Finding 8 — RecordRollbackDialog had NO test file at all: the
 * only UI coverage of the audit-record writer was a check that the button
 * which OPENS it exists. This is the committed version.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import RecordRollbackDialog from '../RecordRollbackDialog';
import rollbackReducer from '../../../store/rollbackSlice';
import { rollbackService } from '../../../services/rollbackService';
import type { RollbackAuthorisationResponse } from '../../../types/rollback';

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

const SYSTEMS = [
  { id: 10, name: 'Payments' },
  { id: 11, name: 'Notifications' },
];

const AUTH_RESPONSE: RollbackAuthorisationResponse = {
  id: 500,
  release_id: 1,
  decided_by_user_id: 2,
  decided_by_username: 'admin',
  decided_at: '2026-08-21T02:14:00Z',
  trigger: 'error rate',
  rationale: 'reverting to the previous build',
  system_ids: [10],
  system_names: ['Payments'],
};

function makeStore() {
  return configureStore({ reducer: { rollback: rollbackReducer } });
}

function renderDialog(onClose = vi.fn()) {
  const utils = render(
    <Provider store={makeStore()}>
      <RecordRollbackDialog releaseId={1} open onClose={onClose} systems={SYSTEMS} />
    </Provider>
  );
  return { ...utils, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(rollbackService.recordAuthorisation).mockResolvedValue(AUTH_RESPONSE);
});

describe('RecordRollbackDialog', () => {
  it('says it records and never refuses — C4\'s central promise, stated in the dialog', () => {
    renderDialog();
    expect(
      screen.getByText(/it never checks whether a plan exists or was agreed/i)
    ).toBeInTheDocument();
  });

  it('disables Record until trigger, rationale and at least one system are filled', async () => {
    renderDialog();
    const recordButton = screen.getByRole('button', { name: /^record$/i });
    expect(recordButton).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/trigger/i), 'Checkout error rate spike');
    expect(recordButton).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/rationale/i), 'Reverting while we investigate');
    expect(recordButton).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/affected systems/i));
    await userEvent.click(await screen.findByRole('option', { name: 'Payments' }));
    // Close the listbox so the Record button is reachable.
    await userEvent.keyboard('{Escape}');

    expect(recordButton).toBeEnabled();
  });

  it('records with the selected systems and closes on success', async () => {
    const { onClose } = renderDialog();

    await userEvent.type(screen.getByLabelText(/trigger/i), 'error rate');
    await userEvent.type(screen.getByLabelText(/rationale/i), 'reverting');
    await userEvent.click(screen.getByLabelText(/affected systems/i));
    await userEvent.click(await screen.findByRole('option', { name: 'Payments' }));
    await userEvent.keyboard('{Escape}');

    await userEvent.click(screen.getByRole('button', { name: /^record$/i }));

    await waitFor(() => expect(rollbackService.recordAuthorisation).toHaveBeenCalled());
    const [releaseId, body] = vi.mocked(rollbackService.recordAuthorisation).mock.calls[0];
    expect(releaseId).toBe(1);
    expect(body.trigger).toBe('error rate');
    expect(body.rationale).toBe('reverting');
    expect(body.system_ids).toEqual([10]);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('shows the server reason when the record is refused, not the generic Axios message', async () => {
    const axiosError = Object.assign(new Error('Request failed with status code 422'), {
      isAxiosError: true,
      response: { status: 422, data: { detail: 'decided_at cannot be in the future' } },
    });
    vi.mocked(rollbackService.recordAuthorisation).mockRejectedValue(axiosError);

    renderDialog();
    await userEvent.type(screen.getByLabelText(/trigger/i), 'error rate');
    await userEvent.type(screen.getByLabelText(/rationale/i), 'reverting');
    await userEvent.click(screen.getByLabelText(/affected systems/i));
    await userEvent.click(await screen.findByRole('option', { name: 'Payments' }));
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: /^record$/i }));

    await waitFor(() =>
      expect(screen.getByText(/decided_at cannot be in the future/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/status code 422/i)).not.toBeInTheDocument();
  });

  it('resets the form fields each time the dialog is reopened', async () => {
    const { rerender, onClose } = renderDialog();
    await userEvent.type(screen.getByLabelText(/trigger/i), 'stale draft text');

    rerender(
      <Provider store={makeStore()}>
        <RecordRollbackDialog releaseId={1} open={false} onClose={onClose} systems={SYSTEMS} />
      </Provider>
    );
    rerender(
      <Provider store={makeStore()}>
        <RecordRollbackDialog releaseId={1} open onClose={onClose} systems={SYSTEMS} />
      </Provider>
    );

    expect(screen.getByLabelText(/trigger/i)).toHaveValue('');
  });
});
