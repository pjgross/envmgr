/**
 * Phase 9 C4, task 9 — RehearsalsPanel.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import RehearsalsPanel from '../RehearsalsPanel';
import rollbackReducer from '../../../store/rollbackSlice';
import { rollbackService } from '../../../services/rollbackService';
import type { RehearsalResponse } from '../../../types/rollback';

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

function makeStore() {
  return configureStore({ reducer: { rollback: rollbackReducer } });
}

function renderPanel(systemId = 1) {
  return render(
    <Provider store={makeStore()}>
      <RehearsalsPanel systemId={systemId} />
    </Provider>
  );
}

const STALE_PASSED: RehearsalResponse = {
  id: 1,
  system_id: 1,
  rehearsed_at: '2026-01-01T00:00:00Z',
  rehearsed_by_user_id: 3,
  rehearsed_by_username: 'bob',
  outcome: 'passed',
  notes: null,
  state: 'stale',
};

const CURRENT_FAILED: RehearsalResponse = {
  id: 2,
  system_id: 1,
  rehearsed_at: '2026-08-15T00:00:00Z',
  rehearsed_by_user_id: 3,
  rehearsed_by_username: 'bob',
  outcome: 'failed',
  notes: null,
  state: 'current',
};

const CURRENT_PASSED: RehearsalResponse = {
  ...CURRENT_FAILED,
  id: 3,
  outcome: 'passed',
};

describe('RehearsalsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the history and marks the latest as current or stale', async () => {
    vi.mocked(rollbackService.listRehearsals).mockResolvedValue([STALE_PASSED]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getAllByText(/stale/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/bob/)).toBeInTheDocument();
    });
  });

  it('does not present a failed rehearsal as a pass', async () => {
    // The readiness verdict treats a failed rehearsal as "no successful
    // rehearsal", so the panel must not render the same honest-pass marker
    // it would for a current, passed one — even though this rehearsal's own
    // freshness state is 'current'.
    vi.mocked(rollbackService.listRehearsals).mockResolvedValue([CURRENT_FAILED]);

    renderPanel();

    await waitFor(() => expect(rollbackService.listRehearsals).toHaveBeenCalled());
    expect(screen.queryByTestId('rehearsal-current')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText(/failed/i).length).toBeGreaterThan(0));
    expect(screen.getByText(/not a pass/i)).toBeInTheDocument();
  });

  it('marks a current, passed rehearsal honestly', async () => {
    vi.mocked(rollbackService.listRehearsals).mockResolvedValue([CURRENT_PASSED]);

    renderPanel();

    expect(await screen.findByTestId('rehearsal-current')).toBeInTheDocument();
  });

  it('refetches when systemId changes, not just on mount', async () => {
    vi.mocked(rollbackService.listRehearsals).mockResolvedValue([]);
    const store = makeStore();
    const { rerender } = render(
      <Provider store={store}>
        <RehearsalsPanel systemId={1} />
      </Provider>
    );
    await waitFor(() => expect(rollbackService.listRehearsals).toHaveBeenCalledWith(1));

    rerender(
      <Provider store={store}>
        <RehearsalsPanel systemId={2} />
      </Provider>
    );
    await waitFor(() => expect(rollbackService.listRehearsals).toHaveBeenCalledWith(2));
    expect(rollbackService.listRehearsals).toHaveBeenCalledTimes(2);
  });
});
