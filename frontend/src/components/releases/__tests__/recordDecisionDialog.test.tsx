/**
 * RecordDecisionDialog — Phase 9 C3, Task 9.
 *
 * C3 RECORDS A DECISION A HUMAN TOOK; IT REFUSES NOTHING beyond input
 * validation. These tests pin: the live readiness verdict (including the
 * rollback-rehearsal answer read from the SAME verdict, not a re-asked
 * field) is shown before it is frozen server-side; one sign-off row per
 * ACTIVE perspective, fetched — never hardcoded; a tenant with no active
 * perspectives gets an empty state pointing at admin rather than a
 * silently unsigned form; the payload carries no snapshot fields; and a
 * rejected save surfaces the server's `detail` — mocked as a real
 * `AxiosError` shape, since a plain `Error` carrying the final text would
 * pass this test while RTK's default serializer drops `detail` in the app.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import RecordDecisionDialog from '../RecordDecisionDialog';
import goNoGoReducer from '../../../store/goNoGoSlice';
import { goNoGoService } from '../../../services/goNoGoService';
import { releaseService } from '../../../services/releaseService';
import api from '../../../services/api';
import type { GoNoGoDecisionRead, GoNoGoPerspectiveRead } from '../../../types/goNoGo';
import type { ReleaseReadinessResponse } from '../../../types/gateReadiness';

vi.mock('../../../services/goNoGoService', () => ({
  goNoGoService: {
    list: vi.fn(),
    record: vi.fn(),
    closeCondition: vi.fn(),
    listPerspectives: vi.fn(),
  },
}));

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    getReadiness: vi.fn(),
  },
}));

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn() },
}));

const USERS = [
  { id: 1, username: 'alice' },
  { id: 2, username: 'bob' },
];

const PERSPECTIVES: GoNoGoPerspectiveRead[] = [
  { id: 10, tenant_id: 1, name: 'Quality', description: null, sort_order: 0, is_active: true },
  {
    id: 11,
    tenant_id: 1,
    name: 'Operations',
    description: null,
    sort_order: 1,
    is_active: true,
  },
  {
    id: 12,
    tenant_id: 1,
    name: 'Retired perspective',
    description: null,
    sort_order: 2,
    is_active: false,
  },
];

// The backend computes `ok` purely from `len(blockers) == 0`
// (release_readiness_service.py) — it says nothing about warnings. Both C4
// policy flags default off, so a release with a missing rehearsal
// ordinarily emits exactly this shape: ok=True, no blockers, one WARNING.
// `ok: false` here would be a state the real backend can never produce.
const READINESS_WITH_MISSING_REHEARSAL: ReleaseReadinessResponse = {
  ok: true,
  release_id: 1,
  checked_at: '2026-09-05T00:00:00Z',
  blockers: [],
  warnings: [
    {
      type: 'rehearsal_missing',
      ref_kind: 'system',
      ref_id: 5,
      gate_name: null,
      gate_type: null,
      detail: 'Payments has no rollback rehearsal on record.',
    },
  ],
  reversibility: 'lossy',
};

const DECISION_RESPONSE: GoNoGoDecisionRead = {
  id: 100,
  tenant_id: 1,
  release_id: 1,
  outcome: 'go',
  rationale: 'All checks passed.',
  decided_at: '2026-09-05T09:00:00Z',
  chaired_by_user_id: 1,
  chaired_by_username: 'alice',
  attendees: [1],
  attendee_usernames: ['alice'],
  snapshot_ok: true,
  snapshot_blockers: [],
  snapshot_warnings: [],
  snapshot_reversibility: null,
  snapshot_rehearsal_state: null,
  signoffs: [],
  conditions: [],
  unmet_condition_count: 0,
};

function makeStore() {
  return configureStore({ reducer: { goNoGo: goNoGoReducer } });
}

function renderDialog(onClose = vi.fn(), onRecorded = vi.fn()) {
  const utils = render(
    <Provider store={makeStore()}>
      <RecordDecisionDialog releaseId={1} open onClose={onClose} onRecorded={onRecorded} />
    </Provider>
  );
  return { ...utils, onClose, onRecorded };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(goNoGoService.listPerspectives).mockResolvedValue(PERSPECTIVES);
  vi.mocked(goNoGoService.record).mockResolvedValue(DECISION_RESPONSE);
  vi.mocked(releaseService.getReadiness).mockResolvedValue(READINESS_WITH_MISSING_REHEARSAL);
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/tenant/users/lite') {
      return Promise.resolve({ data: USERS, headers: { 'x-total-count': String(USERS.length) } });
    }
    return Promise.resolve({ data: [], headers: {} });
  });
});

describe('RecordDecisionDialog', () => {
  it('shows the live readiness verdict, including the rollback-rehearsal answer from that same verdict', async () => {
    renderDialog();

    await waitFor(() => expect(releaseService.getReadiness).toHaveBeenCalledWith(1));
    expect(
      await screen.findByText(/0 blocker\(s\), 1 warning\(s\) in the current verdict/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no rollback rehearsal has been recorded/i)
    ).toBeInTheDocument();

    // `ok: true` here (matching what the backend actually emits with both
    // C4 policy flags off) must never be read as "nothing to see" — the
    // banner must not claim a clean verdict while the very next line says
    // the rehearsal is missing. Gating on `readiness.ok` alone reproduces
    // exactly this self-contradiction.
    expect(
      screen.queryByText(/no blockers or warnings in the current verdict/i)
    ).not.toBeInTheDocument();
  });

  it('answers the rehearsal question positively when the verdict has no rehearsal finding', async () => {
    vi.mocked(releaseService.getReadiness).mockResolvedValue({
      ok: true,
      release_id: 1,
      checked_at: '2026-09-05T00:00:00Z',
      blockers: [],
      warnings: [],
      reversibility: null,
    });

    renderDialog();

    expect(
      await screen.findByText(/current rollback rehearsal is on record/i)
    ).toBeInTheDocument();
  });

  it('renders one sign-off row per ACTIVE perspective, fetched — never a hardcoded three', async () => {
    renderDialog();

    await waitFor(() => expect(goNoGoService.listPerspectives).toHaveBeenCalled());
    expect(await screen.findByText('Quality')).toBeInTheDocument();
    expect(screen.getByText('Operations')).toBeInTheDocument();
    // Inactive perspective must never render a sign-off row.
    expect(screen.queryByText('Retired perspective')).not.toBeInTheDocument();
  });

  it('shows an empty state pointing at admin when no active perspectives exist, not a silently unsigned form', async () => {
    vi.mocked(goNoGoService.listPerspectives).mockResolvedValue([
      { ...PERSPECTIVES[0], is_active: false },
    ]);

    renderDialog();

    await waitFor(() => expect(goNoGoService.listPerspectives).toHaveBeenCalled());
    expect(
      await screen.findByText(/no active go\/no-go perspectives are configured/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/admin/i)).toBeInTheDocument();
    // No perspective table renders at all in this state.
    expect(screen.queryByText('Quality')).not.toBeInTheDocument();
  });

  it('does not disable Record when there are zero active perspectives — C3 does not police the completeness of its own record', async () => {
    vi.mocked(goNoGoService.listPerspectives).mockResolvedValue([
      { ...PERSPECTIVES[0], is_active: false },
    ]);

    renderDialog();
    await screen.findByText(/no active go\/no-go perspectives are configured/i);

    // `canSave` never references perspectives or signoffs by design — a
    // meeting where nobody signed is still a real decision worth recording.
    await userEvent.type(screen.getByLabelText(/rationale/i), 'No sign-offs configured yet');

    expect(screen.getByRole('button', { name: /^record go$/i })).toBeEnabled();
  });

  it('sends outcome, rationale, decided_at, attendees, signoffs and conditions — and no snapshot fields', async () => {
    const { onRecorded, onClose } = renderDialog();

    await screen.findByText('Quality');

    await userEvent.type(screen.getByLabelText(/rationale/i), 'Everything looks good');

    // Attendees.
    const attendeesInput = screen.getByLabelText(/^attendees$/i);
    await userEvent.click(attendeesInput);
    await userEvent.click(await screen.findByRole('option', { name: 'alice' }));
    await userEvent.keyboard('{Escape}');

    // Sign off Quality with bob, dissenting no_go with a note.
    const qualityRow = screen.getByText('Quality').closest('tr') as HTMLElement;
    const signoffInput = within(qualityRow).getByLabelText(/sign-off — quality/i);
    await userEvent.click(signoffInput);
    await userEvent.click(await screen.findByRole('option', { name: 'bob' }));
    await userEvent.keyboard('{Escape}');

    // Add a condition.
    await userEvent.click(screen.getByRole('button', { name: /add condition/i }));
    await userEvent.type(screen.getByLabelText(/^text$/i), 'Confirm backups');

    await userEvent.click(screen.getByRole('button', { name: /^record go$/i }));

    await waitFor(() => expect(goNoGoService.record).toHaveBeenCalled());
    const [releaseId, body] = vi.mocked(goNoGoService.record).mock.calls[0];
    expect(releaseId).toBe(1);

    expect(body.outcome).toBe('go');
    expect(body.rationale).toBe('Everything looks good');
    expect(typeof body.decided_at).toBe('string');
    expect(body.attendees).toEqual([1]);
    expect(body.signoffs).toEqual([
      { perspective_id: 10, user_id: 2, verdict: 'go', dissent_note: null },
    ]);
    expect(body.conditions).toEqual([
      { text: 'Confirm backups', owner_user_id: null, due_date: null },
    ]);

    // No snapshot_* field of any kind may be present on the payload — the
    // server captures the snapshot itself.
    expect(Object.keys(body).some((k) => k.startsWith('snapshot'))).toBe(false);

    await waitFor(() => expect(onRecorded).toHaveBeenCalled());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    // 20s, not the 5s default. This test timed out on CI (PR #22) despite
    // passing locally: 1031ms in isolation, 2451ms under parallel load on a
    // 279s CI suite (12× wall-clock slowdown vs 23s local). The test drives the
    // entire form through `userEvent` — rationale, attendees, sign-offs, and
    // conditions — and each keystroke re-renders the dialog. Nothing about the
    // test is wrong; the CI runner provides no headroom for the suite's slowest
    // test. Prefer this over swapping `userEvent.type` for `fireEvent.change`,
    // which would be faster but would stop exercising the real per-keystroke path.
  }, 20000);

  it("shows the server's detail on a rejected save, not the generic Axios message (real AxiosError shape)", async () => {
    const axiosError = Object.assign(new Error('Request failed with status code 422'), {
      isAxiosError: true,
      response: { status: 422, data: { detail: 'rationale is required' } },
    });
    vi.mocked(goNoGoService.record).mockRejectedValue(axiosError);

    renderDialog();
    await screen.findByText('Quality');

    await userEvent.type(screen.getByLabelText(/rationale/i), 'anything');
    await userEvent.click(screen.getByRole('button', { name: /^record go$/i }));

    await waitFor(() =>
      expect(screen.getByText(/rationale is required/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/status code 422/i)).not.toBeInTheDocument();
  });

  it('initialises "Decided at" to local time via toDateTimeLocal, not a UTC slice', async () => {
    renderDialog();
    const field = screen.getByLabelText(/decided at/i) as HTMLInputElement;
    await waitFor(() => expect(field.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/));
  });
});
