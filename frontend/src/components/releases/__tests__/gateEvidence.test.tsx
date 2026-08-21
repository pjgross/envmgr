/**
 * Phase 9 C2, task 10b: gate evidence and waivers. Task 10 (first half —
 * gate typing on GatesTable, ReadinessBanner) is covered by
 * gateTypeAndReadiness.test.tsx and deliberately not repeated here.
 */
import { configureStore } from '@reduxjs/toolkit';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { AxiosError } from 'axios';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import GateEvidenceList from '../GateEvidenceList';
import AddEvidenceDialog from '../AddEvidenceDialog';
import WaiverDialog from '../WaiverDialog';
import releaseReducer from '../../../store/releaseSlice';
import { releaseService } from '../../../services/releaseService';
import { deploymentService } from '../../../services/deploymentService';
import type { GateEvidenceResponse } from '../../../types/gateEvidence';
import type { ReleaseGateResponse } from '../../../types/release';
import type { Deployment } from '../../../types/deployment';

const snackbarSuccess = vi.fn();
const snackbarError = vi.fn();

vi.mock('../../../hooks/useSnackbar', () => ({
  useSnackbar: () => ({
    success: snackbarSuccess,
    error: snackbarError,
    info: vi.fn(),
    warning: vi.fn(),
    show: vi.fn(),
  }),
}));

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    listGateEvidence: vi.fn(),
    addGateEvidence: vi.fn(),
    deleteGateEvidence: vi.fn(),
    overrideGate: vi.fn(),
  },
}));

vi.mock('../../../services/deploymentService', () => ({
  deploymentService: { list: vi.fn() },
}));

function makeStore() {
  return configureStore({ reducer: { release: releaseReducer } });
}

const EVIDENCE_NON_STALE: GateEvidenceResponse = {
  id: 1,
  gate_id: 10,
  kind: 'Test execution report',
  label: 'Regression run #48',
  url: 'https://ci.example.test/runs/48',
  notes: null,
  deployment_id: null,
  added_by: 5,
  created_at: '2026-08-10T00:00:00Z',
  is_stale: false,
};

const EVIDENCE_STALE: GateEvidenceResponse = {
  ...EVIDENCE_NON_STALE,
  id: 2,
  label: 'Regression run #40 (older)',
  is_stale: true,
};

const GATE_PENDING: ReleaseGateResponse = {
  id: 10,
  tenant_id: 1,
  release_id: 1,
  due_date: '2026-09-01T00:00:00Z',
  name: 'Security Gate',
  status: 'pending',
  decided_by: null,
  decided_at: null,
  decision_notes: null,
  gate_type_id: null,
  test_phase_id: null,
  criteria: [],
  overdue_criterion_count: 0,
  waiver: null,
};

// Overridden, but predates C2's waiver tracking — no GateWaiver row, so
// `waiver` stays null even though status is 'overridden'. Exercises the
// dishonest-fallback path WaiverDialog keeps for exactly this case.
const GATE_OVERRIDDEN: ReleaseGateResponse = {
  ...GATE_PENDING,
  status: 'overridden',
  decided_by: 7,
  decided_at: '2026-08-01T00:00:00Z',
  decision_notes: 'Known issue, ticket ENV-123 tracks the fix.',
};

const LIVE_WAIVER = {
  id: 1,
  reason: 'Accepted risk pending fix',
  approved_by_user_id: 7,
  approved_by_username: 'alice',
  expires_at: '2026-12-31T00:00:00Z',
  remediation: 'Fix tracked in ENV-124',
  created_at: '2026-08-01T00:00:00Z',
  state: 'live' as const,
};

const GATE_OVERRIDDEN_WITH_LIVE_WAIVER: ReleaseGateResponse = {
  ...GATE_OVERRIDDEN,
  waiver: LIVE_WAIVER,
};

const GATE_OVERRIDDEN_WITH_EXPIRED_WAIVER: ReleaseGateResponse = {
  ...GATE_OVERRIDDEN,
  waiver: { ...LIVE_WAIVER, id: 2, expires_at: '2026-01-01T00:00:00Z', state: 'expired' as const },
};

describe('GateEvidenceList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(deploymentService.list).mockResolvedValue({ rows: [], total: 0 });
  });

  it('marks stale evidence with a superseded chip, and leaves non-stale evidence unmarked', async () => {
    render(
      <Provider store={makeStore()}>
        <GateEvidenceList releaseId={1} evidence={[EVIDENCE_NON_STALE, EVIDENCE_STALE]} onDelete={vi.fn()} />
      </Provider>
    );

    expect(await screen.findByText('Regression run #48')).toBeInTheDocument();
    expect(screen.getByText('Regression run #40 (older)')).toBeInTheDocument();
    expect(screen.getByText(/superseded/i)).toBeInTheDocument();

    // Only the stale row is marked — not both.
    const rows = screen.getAllByText(/regression run/i);
    expect(rows).toHaveLength(2);
  });

  it('renders "No evidence attached" for an empty list rather than an empty region', () => {
    render(
      <Provider store={makeStore()}>
        <GateEvidenceList releaseId={1} evidence={[]} onDelete={vi.fn()} />
      </Provider>
    );
    expect(screen.getByText(/no evidence attached/i)).toBeInTheDocument();
  });
});

describe('AddEvidenceDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(deploymentService.list).mockResolvedValue({ rows: [], total: 0 });
  });

  function renderDialog(props?: Partial<{ expectedEvidence: string[]; requiresDeploymentLink: boolean }>) {
    const store = makeStore();
    render(
      <Provider store={store}>
        <AddEvidenceDialog
          open
          onClose={vi.fn()}
          releaseId={1}
          gateId={10}
          expectedEvidence={props?.expectedEvidence ?? ['Test execution report', 'Security scan']}
          requiresDeploymentLink={props?.requiresDeploymentLink ?? false}
        />
      </Provider>
    );
    return store;
  }

  it("offers the gate type's expected kinds but still accepts an unlisted one", async () => {
    vi.mocked(releaseService.addGateEvidence).mockResolvedValue({
      ...EVIDENCE_NON_STALE,
      id: 99,
      kind: 'Something bespoke',
      label: 'Ad hoc note',
    });

    renderDialog();

    const kindField = screen.getByRole('combobox', { name: /kind/i });
    await userEvent.click(kindField);
    expect(await screen.findByText('Test execution report')).toBeInTheDocument();
    expect(screen.getByText('Security scan')).toBeInTheDocument();

    // Free-solo: type something that is NOT one of the offered kinds.
    await userEvent.type(kindField, 'Something bespoke');
    await userEvent.type(screen.getByLabelText(/^label/i), 'Ad hoc note');
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(releaseService.addGateEvidence).toHaveBeenCalledWith(
        10,
        expect.objectContaining({ kind: 'Something bespoke', label: 'Ad hoc note' })
      )
    );
  });

  it('does not refuse evidence with no deployment — hint shows, submit stays enabled', async () => {
    vi.mocked(releaseService.addGateEvidence).mockResolvedValue({
      ...EVIDENCE_NON_STALE,
      id: 100,
    });

    renderDialog({ requiresDeploymentLink: true });

    await userEvent.type(screen.getByLabelText(/^label/i), 'Ops runbook');
    await userEvent.type(screen.getByRole('combobox', { name: /kind/i }), 'Runbook');

    // The hint is present...
    expect(screen.getByText(/expects evidence to link a deployment/i)).toBeInTheDocument();
    // ...but it is a hint, not a validation error: submit stays enabled and works.
    const addButton = screen.getByRole('button', { name: /^add$/i });
    expect(addButton).toBeEnabled();

    await userEvent.click(addButton);

    await waitFor(() =>
      expect(releaseService.addGateEvidence).toHaveBeenCalledWith(
        10,
        expect.objectContaining({ deployment_id: undefined })
      )
    );
  });

  it('offers deployments through the picker and includes the chosen one in the payload', async () => {
    const deployment: Deployment = {
      id: 55,
      tenant_id: 1,
      build_id: 200,
      build_sha_short: 'a1b2c3d',
      environment_id: 3,
      environment_name: 'UAT',
      release_id: 1,
      release_name: 'Release 1',
      change_request_id: 1,
      change_request_title: null,
      event_id: 'evt-1',
      deployer_name: null,
      deployed_at: '2026-08-14T09:00:00Z',
      completed_at: null,
      status: 'success',
      custom_fields: {},
      created_at: '2026-08-14T09:00:00Z',
      updated_at: '2026-08-14T09:00:00Z',
    };
    vi.mocked(deploymentService.list).mockResolvedValue({ rows: [deployment], total: 1 });
    vi.mocked(releaseService.addGateEvidence).mockResolvedValue({ ...EVIDENCE_NON_STALE, id: 101 });

    renderDialog();

    await userEvent.type(screen.getByLabelText(/^label/i), 'Verified against UAT');
    await userEvent.type(screen.getByRole('combobox', { name: /kind/i }), 'Manual verification');

    await userEvent.click(screen.getByRole('combobox', { name: /deployment/i }));
    const option = await screen.findByText(/UAT/);
    await userEvent.click(option);

    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(releaseService.addGateEvidence).toHaveBeenCalledWith(
        10,
        expect.objectContaining({ deployment_id: 55 })
      )
    );
  });

  it("surfaces the server's reason when the save is refused", async () => {
    const err = new AxiosError('Request failed with status code 422');
    (err as unknown as { response: unknown }).response = {
      status: 422,
      data: { detail: 'label: field required' },
    };
    vi.mocked(releaseService.addGateEvidence).mockRejectedValue(err);

    renderDialog();

    await userEvent.type(screen.getByLabelText(/^label/i), 'Whatever');
    await userEvent.type(screen.getByLabelText(/kind/i), 'Test execution report');
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() => expect(snackbarError).toHaveBeenCalledWith('label: field required'));
    expect(snackbarError).not.toHaveBeenCalledWith(
      expect.stringMatching(/request failed with status code/i)
    );
  });
});

describe('WaiverDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderDialog(gate: ReleaseGateResponse | null = GATE_PENDING) {
    const store = makeStore();
    render(
      <Provider store={store}>
        <WaiverDialog
          open
          onClose={vi.fn()}
          releaseId={1}
          gate={gate}
          users={[{ id: 7, username: 'alice' }]}
        />
      </Provider>
    );
    return store;
  }

  it('submits reason, approver and remediation, and an empty expiry means permanent', async () => {
    vi.mocked(releaseService.overrideGate).mockResolvedValue({ ...GATE_PENDING, status: 'overridden' });

    renderDialog();

    await userEvent.type(screen.getByLabelText(/reason/i), 'Accepted risk pending fix');
    await userEvent.type(screen.getByLabelText(/remediation/i), 'Fix in ENV-124');
    // Expiry deliberately left blank.

    await userEvent.click(screen.getByRole('button', { name: /waive gate/i }));

    await waitFor(() =>
      expect(releaseService.overrideGate).toHaveBeenCalledWith(
        1,
        10,
        expect.objectContaining({
          notes: 'Accepted risk pending fix',
          remediation: 'Fix in ENV-124',
          expires_at: null,
        })
      )
    );
    // "No expiry (permanent)" is the honest label for an empty expiry —
    // never "today", which formatExpiry reserves for an expiry landing now.
    expect(screen.getByText(/no expiry \(permanent\)/i)).toBeInTheDocument();
  });

  it('sends the picked approver and a concrete expiry date', async () => {
    vi.mocked(releaseService.overrideGate).mockResolvedValue({ ...GATE_PENDING, status: 'overridden' });

    renderDialog();

    await userEvent.type(screen.getByLabelText(/reason/i), 'Temporary waiver');
    await userEvent.click(screen.getByLabelText(/approver/i));
    await userEvent.click(await screen.findByText('alice'));

    const expiryInput = screen.getByLabelText(/expiry/i);
    fireEvent.change(expiryInput, { target: { value: '2026-12-31' } });

    await userEvent.click(screen.getByRole('button', { name: /waive gate/i }));

    await waitFor(() =>
      expect(releaseService.overrideGate).toHaveBeenCalledWith(
        1,
        10,
        expect.objectContaining({
          notes: 'Temporary waiver',
          approved_by_user_id: 7,
          expires_at: '2026-12-31T00:00:00Z',
        })
      )
    );
  });

  it("surfaces the server's reason when the override is refused", async () => {
    const err = new AxiosError('Request failed with status code 422');
    (err as unknown as { response: unknown }).response = {
      status: 422,
      data: { detail: 'notes are required when overriding a gate' },
    };
    vi.mocked(releaseService.overrideGate).mockRejectedValue(err);

    renderDialog();

    await userEvent.type(screen.getByLabelText(/reason/i), 'x');
    await userEvent.click(screen.getByRole('button', { name: /waive gate/i }));

    await waitFor(() =>
      expect(snackbarError).toHaveBeenCalledWith('notes are required when overriding a gate')
    );
  });

  it('prefills the reason from an already-overridden gate, and re-initialises on re-render for a different gate', async () => {
    // Re-render, don't just mount: this must react to the GATE PROP
    // changing on an already-mounted dialog, not just to first mount.
    const store = makeStore();
    const { rerender } = render(
      <Provider store={store}>
        <WaiverDialog open onClose={vi.fn()} releaseId={1} gate={GATE_OVERRIDDEN} users={[]} />
      </Provider>
    );

    expect(await screen.findByDisplayValue(/known issue, ticket env-123/i)).toBeInTheDocument();
    expect(screen.getByText(/currently overridden/i)).toBeInTheDocument();

    const otherOverridden: ReleaseGateResponse = {
      ...GATE_OVERRIDDEN,
      id: 20,
      name: 'Business Sign-off',
      decision_notes: 'Different reason entirely.',
    };
    rerender(
      <Provider store={store}>
        <WaiverDialog open onClose={vi.fn()} releaseId={1} gate={otherOverridden} users={[]} />
      </Provider>
    );

    expect(await screen.findByDisplayValue(/different reason entirely/i)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/known issue, ticket env-123/i)).not.toBeInTheDocument();
  });

  it('renders the REAL waiver — approver, expiry and remediation — when the gate carries one (task 10c)', () => {
    renderDialog(GATE_OVERRIDDEN_WITH_LIVE_WAIVER);

    // Approver: the server-resolved username, not a guess from the local
    // `users` list (passed here as [] to prove it isn't needed).
    expect(screen.getByText(/approved by alice/i)).toBeInTheDocument();
    expect(screen.getByText(/accepted risk pending fix/i)).toBeInTheDocument();
    // Remediation has no home anywhere else in the UI before this task.
    expect(screen.getByText(/fix tracked in env-124/i)).toBeInTheDocument();
    // Expiry, via the shared WaiverChip.
    expect(screen.getByText(/expires/i)).toBeInTheDocument();
    // The dishonest fallback panel must not also render.
    expect(screen.queryByText(/no waiver record/i)).not.toBeInTheDocument();
  });

  it('renders the dishonest-fallback panel only when the gate has no waiver record', () => {
    renderDialog(GATE_OVERRIDDEN);

    expect(screen.getByText(/currently overridden — no waiver record/i)).toBeInTheDocument();
    expect(screen.getByText(/predates waiver tracking/i)).toBeInTheDocument();
  });

  it('an expired waiver is visibly distinct from a live one', () => {
    renderDialog(GATE_OVERRIDDEN_WITH_LIVE_WAIVER);
    expect(screen.getByText(/currently overridden/i)).toBeInTheDocument();
    expect(screen.queryByText(/waiver expired/i)).not.toBeInTheDocument();
    // The live chip must not read as expired.
    expect(screen.getByText(/^expires /i)).toBeInTheDocument();
    cleanup();

    renderDialog(GATE_OVERRIDDEN_WITH_EXPIRED_WAIVER);
    // Distinct heading AND a distinct chip label — not just a colour swap
    // nothing in the DOM text would let a test (or an assistive tech user)
    // tell apart.
    expect(screen.getByText(/waiver expired — unmet again/i)).toBeInTheDocument();
    expect(screen.getByText(/^expired /i)).toBeInTheDocument();
    expect(screen.queryByText(/^currently overridden$/i)).not.toBeInTheDocument();
  });
});
