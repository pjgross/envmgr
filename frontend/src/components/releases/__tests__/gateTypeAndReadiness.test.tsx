/**
 * Phase 9 C2, task 10 (first half): gate typing on the release page, and the
 * readiness banner. Evidence/waiver UI is task 10b and is deliberately not
 * covered here.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { useSelector } from 'react-redux';
import { AxiosError } from 'axios';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import GatesTable from '../GatesTable';
import ReadinessBanner from '../ReadinessBanner';
import TransitionControls from '../../lifecycle/TransitionControls';
import releaseReducer from '../../../store/releaseSlice';
import gateTypeReducer from '../../../store/gateTypeSlice';
import { releaseService } from '../../../services/releaseService';
import { gateTypeService } from '../../../services/gateTypeService';
import type { ReleaseGateResponse } from '../../../types/release';
import type { GateTypeResponse } from '../../../types/gateType';
import type { ReleaseReadinessResponse } from '../../../types/gateReadiness';

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

// GatesTable reads GET /tenant/users/lite straight through `api` for the
// criterion-assignee select — irrelevant to these tests but must not hit
// a real network call.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}));

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    listGates: vi.fn(),
    createGate: vi.fn(),
    updateGate: vi.fn(),
    deleteGate: vi.fn(),
    passGate: vi.fn(),
    failGate: vi.fn(),
    overrideGate: vi.fn(),
    createCriterion: vi.fn(),
    updateCriterion: vi.fn(),
    completeCriterion: vi.fn(),
    reopenCriterion: vi.fn(),
    deleteCriterion: vi.fn(),
    getReadiness: vi.fn(),
  },
}));

vi.mock('../../../services/gateTypeService', () => ({
  gateTypeService: {
    listGateTypes: vi.fn(),
    createGateType: vi.fn(),
    updateGateType: vi.fn(),
    deleteGateType: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({
    reducer: { release: releaseReducer, gateType: gateTypeReducer },
  });
}

// Mirrors how ReleasePlanTab wires GatesTable to the store: `gates` is read
// from Redux and handed down as a prop, so a fulfilled updateGate dispatch
// actually re-renders GatesTable with the new value — not just mounts once.
function GatesTableHarness({ releaseId }: { releaseId: number }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const gates = useSelector((s: any) => s.release.gates as ReleaseGateResponse[]);
  return <GatesTable releaseId={releaseId} gates={gates} onRefresh={() => {}} />;
}

const GATE: ReleaseGateResponse = {
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

const GATE_TYPES: GateTypeResponse[] = [
  {
    id: 1,
    tenant_id: 1,
    name: 'Functional',
    description: null,
    category: 'functional',
    failure_behaviour: 'warn',
    expected_evidence: [],
    requires_deployment_link: false,
    display_order: 10,
    is_active: true,
  },
  {
    id: 2,
    tenant_id: 1,
    name: 'Security',
    description: null,
    category: 'security',
    failure_behaviour: 'block',
    expected_evidence: [],
    requires_deployment_link: false,
    display_order: 20,
    is_active: true,
  },
];

function renderGatesTable(gate: ReleaseGateResponse = GATE) {
  const store = makeStore();
  store.dispatch({ type: 'release/listGates/fulfilled', payload: [gate] });
  render(
    <Provider store={store}>
      <GatesTableHarness releaseId={1} />
    </Provider>
  );
  return store;
}

describe('GatesTable — gate typing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(gateTypeService.listGateTypes).mockResolvedValue({
      rows: GATE_TYPES,
      total: 2,
    });
  });

  it("sets a gate's type: calls update with the right payload and shows the new type", async () => {
    vi.mocked(releaseService.updateGate).mockResolvedValue({
      ...GATE,
      gate_type_id: 2,
    });

    renderGatesTable();

    const combobox = await screen.findByRole('combobox', { name: /type for gate security gate/i });
    expect(combobox).toHaveTextContent('Untyped');

    await userEvent.click(combobox);
    await userEvent.click(await screen.findByRole('option', { name: 'Security' }));

    await waitFor(() =>
      expect(releaseService.updateGate).toHaveBeenCalledWith(1, 10, { gate_type_id: 2 })
    );

    // Re-render, don't just mount: the combobox must reflect the fulfilled
    // update coming back through the store, not just the click that fired it.
    await waitFor(() => expect(combobox).toHaveTextContent('Security'));
  });

  it("surfaces the server's reason when a type change is refused", async () => {
    const err = new AxiosError('Request failed with status code 422');
    (err as unknown as { response: unknown }).response = {
      status: 422,
      data: { detail: 'gate_type_id: no such gate type in this tenant' },
    };
    vi.mocked(releaseService.updateGate).mockRejectedValue(err);

    renderGatesTable();

    const combobox = await screen.findByRole('combobox', { name: /type for gate security gate/i });
    await userEvent.click(combobox);
    await userEvent.click(await screen.findByRole('option', { name: 'Functional' }));

    await waitFor(() =>
      expect(snackbarError).toHaveBeenCalledWith('gate_type_id: no such gate type in this tenant')
    );
    // The generic Axios message must never be what the user sees.
    expect(snackbarError).not.toHaveBeenCalledWith(
      expect.stringMatching(/request failed with status code/i)
    );
  });

  it('keeps the type control (and the Decide control) enabled on a gate whose type would block the verdict', async () => {
    // A gate typed 'block' still gets no special treatment from GatesTable —
    // there is nothing here that could disable on the strength of it, and
    // this pins that down rather than assuming it from the diff.
    vi.mocked(releaseService.updateGate).mockResolvedValue({ ...GATE, gate_type_id: 2 });
    renderGatesTable({ ...GATE, gate_type_id: 2 }); // pre-typed as 'Security' (failure_behaviour: block)

    const combobox = await screen.findByRole('combobox', { name: /type for gate security gate/i });
    expect(combobox).toBeEnabled();
    expect(screen.getByRole('button', { name: /decide/i })).toBeEnabled();
  });
});

// Task 10c — the waiver record is readable, not just written. WaiverDialog's
// own rendering of approver/expiry/remediation is covered in
// gateEvidence.test.tsx; this covers the GatesTable ROW: the status chip
// must read as visibly distinct for an expired waiver (requirement: an
// expired waiver must never look like a live one, since the readiness
// verdict treats it as a blocker again), and the expand panel's Waiver
// section must render for an overridden gate.
describe('GatesTable — waiver rendering (task 10c)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(gateTypeService.listGateTypes).mockResolvedValue({ rows: GATE_TYPES, total: 2 });
  });

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

  it('shows a plain "overridden" chip for a live waiver', async () => {
    renderGatesTable({ ...GATE, status: 'overridden', waiver: LIVE_WAIVER });

    expect(await screen.findByText('overridden')).toBeInTheDocument();
    expect(screen.queryByText(/overridden \(expired\)/i)).not.toBeInTheDocument();
  });

  it('shows a distinct "overridden (expired)" chip for an expired waiver', async () => {
    renderGatesTable({
      ...GATE,
      status: 'overridden',
      waiver: { ...LIVE_WAIVER, id: 2, expires_at: '2026-01-01T00:00:00Z', state: 'expired' as const },
    });

    expect(await screen.findByText(/overridden \(expired\)/i)).toBeInTheDocument();
    expect(screen.queryByText('overridden')).not.toBeInTheDocument();
  });

  it('renders approver, expiry and remediation in the expand panel', async () => {
    renderGatesTable({ ...GATE, status: 'overridden', waiver: LIVE_WAIVER });

    await userEvent.click(screen.getByRole('button', { name: /expand gate security gate/i }));

    expect(await screen.findByText(/approved by alice/i)).toBeInTheDocument();
    expect(screen.getByText(/fix tracked in env-124/i)).toBeInTheDocument();
    expect(screen.getByText(/expires/i)).toBeInTheDocument();
  });

  it('the expand panel says so honestly when an overridden gate has no waiver record', async () => {
    renderGatesTable({ ...GATE, status: 'overridden', waiver: null });

    await userEvent.click(screen.getByRole('button', { name: /expand gate security gate/i }));

    expect(await screen.findByText(/no waiver record/i)).toBeInTheDocument();
  });
});

describe('ReadinessBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const READINESS: ReleaseReadinessResponse = {
    ok: false,
    release_id: 1,
    checked_at: '2026-08-20T00:00:00Z',
    blockers: [
      {
        type: 'gate_failed',
        ref_kind: 'gate',
        ref_id: 10,
        gate_name: 'Security Gate',
        gate_type: 'Security',
        detail: 'The gate was failed.',
      },
    ],
    warnings: [
      {
        type: 'evidence_missing',
        ref_kind: 'gate',
        ref_id: 11,
        gate_name: 'Functional Gate',
        gate_type: 'Functional',
        detail: 'Expected but not supplied: Test execution report',
      },
    ],
  };

  it('renders blockers and warnings, each naming its gate, with advisory framing asserted', async () => {
    vi.mocked(releaseService.getReadiness).mockResolvedValue(READINESS);

    render(<ReadinessBanner releaseId={1} />);

    expect(await screen.findByText(/security gate/i)).toBeInTheDocument();
    expect(screen.getByText(/the gate was failed/i)).toBeInTheDocument();
    expect(screen.getByText(/functional gate/i)).toBeInTheDocument();
    expect(screen.getByText(/expected but not supplied/i)).toBeInTheDocument();

    // Advisory framing: says plainly that it advises...
    expect(screen.getByText(/advisory only/i)).toBeInTheDocument();
    // ...and never claims the release itself is blocked/stopped.
    expect(screen.queryByText(/this release is blocked/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/release cannot/i)).not.toBeInTheDocument();
  });

  it('renders nothing when the release has no blockers or warnings', async () => {
    vi.mocked(releaseService.getReadiness).mockResolvedValue({
      ok: true,
      release_id: 1,
      checked_at: '2026-08-20T00:00:00Z',
      blockers: [],
      warnings: [],
    });

    const { container } = render(<ReadinessBanner releaseId={1} />);
    await waitFor(() => expect(releaseService.getReadiness).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('refetches when releaseId changes, not just on mount', async () => {
    vi.mocked(releaseService.getReadiness).mockImplementation((id: number) =>
      Promise.resolve({ ...READINESS, release_id: id })
    );

    const { rerender } = render(<ReadinessBanner releaseId={1} />);
    await waitFor(() => expect(releaseService.getReadiness).toHaveBeenCalledWith(1));

    rerender(<ReadinessBanner releaseId={2} />);
    await waitFor(() => expect(releaseService.getReadiness).toHaveBeenCalledWith(2));
    expect(releaseService.getReadiness).toHaveBeenCalledTimes(2);
  });
});

describe('C2 advises; it never blocks', () => {
  it('renders a release with readiness blockers still showing enabled transition controls', async () => {
    // The UI half of the backend guard (test_c2_advises_never_blocks.py). A
    // prior reviewer on this branch gated a control on an absence and 50
    // page tests stayed green because the fixture supplied no allowed
    // transitions — so this fixture supplies a REAL one, so the assertion
    // is capable of failing if something wires readiness into the gate.
    vi.mocked(releaseService.getReadiness).mockResolvedValue({
      ok: false,
      release_id: 1,
      checked_at: '2026-08-20T00:00:00Z',
      blockers: [
        {
          type: 'gate_pending',
          ref_kind: 'gate',
          ref_id: 10,
          gate_name: 'Security Gate',
          gate_type: 'Security',
          detail: 'The gate has not been decided.',
        },
      ],
      warnings: [],
    });

    const lifecycleDefinition = {
      states: [
        { key: 'draft', label: 'Draft' },
        { key: 'submitted', label: 'Submitted' },
      ],
      transitions: [
        {
          from_state: 'draft',
          to_state: 'submitted',
          label: 'Submit',
          allowed_roles: ['Release Manager'],
        },
      ],
    };

    render(
      <>
        <ReadinessBanner releaseId={1} />
        <TransitionControls
          currentState="draft"
          userRole="Release Manager"
          lifecycleDefinition={lifecycleDefinition}
          recordValues={{}}
          onTransition={vi.fn()}
        />
      </>
    );

    // The banner is showing a blocker...
    expect(await screen.findByText(/security gate/i)).toBeInTheDocument();
    // ...and the transition button is unaffected by it.
    expect(screen.getByRole('button', { name: /submit/i })).toBeEnabled();
  });
});
