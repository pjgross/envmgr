import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import { AxiosError } from 'axios';
import closeoutReducer from '../../../store/closeoutSlice';
import releaseReducer from '../../../store/releaseSlice';
import userGroupReducer from '../../../store/userGroupSlice';
import { closeoutService } from '../../../services/closeoutService';
import type { CloseoutRead } from '../../../types/closeout';
import CloseoutTab from '../CloseoutTab';

vi.mock('../../../services/closeoutService', () => ({
  closeoutService: { get: vi.fn(), declareStable: vi.fn(), withdrawStable: vi.fn(),
                     confirmHandover: vi.fn(), withdrawHandover: vi.fn() },
}));
vi.mock('../../../services/userGroupService', () => ({
  userGroupService: { listGroups: vi.fn().mockResolvedValue({ rows: [{ id: 3, name: 'Platform Ops' }], total: 1 }) },
}));
vi.mock('../../../services/releaseService', () => ({
  releaseService: { update: vi.fn().mockResolvedValue({}) },
}));

const base: CloseoutRead = {
  hypercare: { state: 'active', phase: { id: 1, name: 'Hyper-care', start_date: '2026-09-01T00:00:00Z', end_date: '2026-09-15T00:00:00Z' },
               declared_stable_at: null, declared_stable_by_username: null },
  handover: { operations_group_id: null, operations_group_name: null, confirmed_at: null, confirmed_by_username: null },
  pir: { exists: true, status: 'draft', completed_at: null },
  incidents: { window_start: '2026-09-01T00:00:00Z', window_end: '2026-09-10T00:00:00Z',
               by_severity: { P1: 1, P2: 0, P3: 2, P4: 0 }, total: 3,
               items: [{ id: 9, title: 'Checkout 500s', severity: 'P1', status: 'new', detected_at: '2026-09-03T00:00:00Z' }] },
  close_targets: [
    { state_key: 'completed', label: 'Completed', requires_pir_complete: true, requires_handover_confirmed: true,
      unmet: ['the post-implementation review is not complete', 'ops handover is not confirmed'], can_close: false },
    { state_key: 'backed_out', label: 'Backed Out', requires_pir_complete: false, requires_handover_confirmed: false, unmet: [], can_close: true },
  ],
};

function renderTab(role = 'Admin') {
  const store = configureStore({ reducer: {
    closeout: closeoutReducer, release: releaseReducer, userGroup: userGroupReducer,
    auth: (state = { user: { id: 1, role, is_master_admin: false } }) => state,
  }});
  return render(<Provider store={store}><MemoryRouter><CloseoutTab releaseId={7} /></MemoryRouter></Provider>);
}

describe('CloseoutTab', () => {
  beforeEach(() => { vi.mocked(closeoutService.get).mockResolvedValue(base); });

  it('renders the four cards and the requirement ticks and crosses', async () => {
    renderTab();
    expect(await screen.findByText(/active/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Checkout 500s' })).toHaveAttribute('href', '/incidents/9');
    const completed = screen.getByTestId('close-target-completed');
    expect(within(completed).getByText(/review is not complete/)).toBeInTheDocument();
    expect(within(completed).getByText(/handover is not confirmed/)).toBeInTheDocument();
    expect(within(completed).getAllByLabelText('Not met')).toHaveLength(2);
    const backedOut = screen.getByTestId('close-target-backed_out');
    expect(within(backedOut).getByText(/no requirements/i)).toBeInTheDocument();
  });

  it('declares stable with a note and re-reads', async () => {
    vi.mocked(closeoutService.declareStable).mockResolvedValue({} as never);
    vi.mocked(closeoutService.get)
      .mockResolvedValueOnce(base)
      .mockResolvedValueOnce({ ...base, hypercare: { ...base.hypercare, state: 'stable',
        declared_stable_at: '2026-09-10T09:00:00Z', declared_stable_by_username: 'testadmin' } });
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /declare stable/i }));
    await userEvent.type(screen.getByLabelText(/note/i), 'no P1 in 14 days');
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(closeoutService.declareStable).toHaveBeenCalledWith(7, 'no P1 in 14 days');
    expect(await screen.findByText(/declared stable by testadmin/i)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /withdraw/i })).toBeInTheDocument();
  });

  it('shows the server reason when a write is refused', async () => {
    const err = new AxiosError('Request failed with status code 409');
    (err as unknown as { response: unknown }).response = { status: 409, data: { detail: 'This release is already declared stable; withdraw the declaration first' } };
    vi.mocked(closeoutService.declareStable).mockRejectedValue(err);
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /declare stable/i }));
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    // The dialog is still open here (the write was refused, not confirmed),
    // and MUI marks everything outside it aria-hidden — so the reason must
    // be found INSIDE the open dialog, not merely somewhere in the document.
    expect(await within(screen.getByRole('dialog')).findByText(/already declared stable/)).toBeInTheDocument();
    expect(screen.queryByText(/status code 409/)).not.toBeInTheDocument();
  });

  it('disables Confirm handover until a group is set, and a Developer sees no write controls', async () => {
    const first = renderTab();
    const btn = await screen.findByRole('button', { name: /confirm handover/i });
    expect(btn).toBeDisabled();
    // Unmount the first render before mounting the second: RTL's afterEach
    // cleanup only fires BETWEEN tests, so two render() calls in one test
    // otherwise leave both trees in `document.body`, and the first (Admin)
    // render's own "Declare stable" button would falsely satisfy a query
    // meant to prove the SECOND (Developer) render has none.
    first.unmount();
    renderTab('Developer');
    await waitFor(() => expect(screen.getAllByText(/hyper-care/i).length).toBeGreaterThan(0));
    expect(screen.queryByRole('button', { name: /declare stable/i })).not.toBeInTheDocument();
  });

  it('hides the incidents card when there is no window, and explains an empty target list', async () => {
    vi.mocked(closeoutService.get).mockResolvedValue({ ...base,
      hypercare: { ...base.hypercare, state: 'none', phase: null }, close_targets: [] });
    renderTab();
    // The Chip's own label is also "No hyper-care phase" (STATE_LABEL.none),
    // so the bare phrase matches twice; assert the explanatory paragraph text,
    // which is unique.
    expect(await screen.findByText(/no hyper-care phase on this release/i)).toBeInTheDocument();
    expect(screen.queryByText(/incidents in the window/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no state flagged as closed/i)).toBeInTheDocument();
  });
});
