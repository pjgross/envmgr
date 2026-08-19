/**
 * `DecommissionPanel` — the surface that drives B5's whole workflow: banner,
 * controls, and the attestation checklist, together.
 *
 * Adaptations from the task-12 brief's illustrative test code, made because
 * this file is written against the REAL wire contract (backend feature-
 * complete as of Task 9), not the brief's shorthand:
 *
 *  - `RemainingBookingSummary` has no `purpose` field (only
 *    id/start_date/end_date/status — deliberately thin, see
 *    types/decommission.ts). The "B5 acts only where it says" fixture below
 *    uses the real shape and asserts on status + date range instead.
 *  - There is no GET for previously-signed attestations. `attestations` is
 *    an OPTIONAL extra this panel accepts on top of `Decommission` — see
 *    `DecommissionWithChecklist` in the component file.
 *  - Team membership is resolved by an async `userGroupService.listMembers`
 *    call (mirroring `HandoverSection`), so any assertion gated on
 *    `teamMember` uses `findByRole`/`waitFor` rather than a bare `getByRole`
 *    immediately after render.
 *  - `Cancel decommission` opens a small reason dialog (`CancelRequest.reason`
 *    is required server-side, min_length=1) rather than firing on one click —
 *    the error-surfacing test opens it, types a reason, and confirms.
 *
 * Mocking strategy: `services/api` is mocked directly (not
 * `decommissionService`), so the REAL thunks in `decommissionSlice` and the
 * REAL `decommissionService` run — this is what makes the AxiosError-shape
 * test honest: it proves `result.payload` (not `result.error.message`)
 * reaches the screen through the whole real chain, the same pattern
 * `ContentionVerdict.test.tsx` uses. `userGroupService` is mocked separately,
 * matching `handoverSection.test.tsx`.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { AxiosError } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: { listMembers: vi.fn() },
}));

import api from '../../../services/api';
import { userGroupService } from '../../../services/userGroupService';
import decommissionReducer from '../../../store/decommissionSlice';
import DecommissionPanel from '../DecommissionPanel';
import type { DecommissionWithChecklist, DecommissionPanelEnvironment, DecommissionPanelUser } from '../DecommissionPanel';
import type { Attestation, DecommissionStep } from '../../../types/decommission';

let nextAttestationId = 1000;
/** A minimal, valid `Attestation` (the real wire shape — `id`,
 * `decommission_id`, numeric `signed_by`, `notes` included even though this
 * panel's own display type, `SignedStepView`, drops all four). */
function makeAttestation(overrides: Partial<Attestation> & { step_key: string }): Attestation {
  return {
    id: nextAttestationId++,
    decommission_id: 7, // matches WARNED.id below
    signed_by: 999,
    notes: null,
    signed_at: '2026-08-19T10:00:00Z',
    reference: null,
    signed_by_username: null,
    ...overrides,
  };
}

const ownedEnv: DecommissionPanelEnvironment = {
  id: 1,
  name: 'Mortgage UAT',
  owner_user_id: 10,
  operations_group_id: 7,
};

const owner: DecommissionPanelUser = {
  id: 10,
  username: 'owner.olivia',
  role: 'Developer',
  is_master_admin: false,
};

const bystander: DecommissionPanelUser = {
  id: 11,
  username: 'bystander.bob',
  role: 'Developer',
  is_master_admin: false,
};

const teamMember: DecommissionPanelUser = {
  id: 12,
  username: 'ops.carl',
  role: 'Developer',
  is_master_admin: false,
};

const WARNED: DecommissionWithChecklist = {
  id: 7,
  environment_id: 1,
  reason: 'Project closed',
  warned_at: '2026-08-18T09:00:00Z',
  scheduled_teardown_at: '2026-08-23T09:00:00Z',
  initiated_by: 3,
  extension_requested_at: null,
  extension_reason: null,
  extension_until: null,
  extension_decided_at: null,
  extension_granted: null,
  torn_down_at: null,
  cancelled_at: null,
  cancel_reason: null,
  state: 'warned',
  initiated_by_username: 'ops.alice',
  attestations: [],
};

const STEPS: DecommissionStep[] = [
  {
    id: 1,
    key: 'final_backup',
    label: 'Final backup taken',
    description: null,
    display_order: 1,
    is_required: true,
    is_active: true,
  },
  {
    id: 2,
    key: 'teardown',
    label: 'Infrastructure torn down',
    description: null,
    display_order: 2,
    is_required: true,
    is_active: true,
  },
];

function makeStore() {
  return configureStore({ reducer: { decommission: decommissionReducer } });
}

function renderPanel(props: {
  decommission: DecommissionWithChecklist | null;
  steps: DecommissionStep[];
  env?: DecommissionPanelEnvironment;
  currentUser?: DecommissionPanelUser | null;
}) {
  const store = makeStore();
  return {
    store,
    ...render(
      <Provider store={store}>
        <DecommissionPanel
          decommission={props.decommission}
          steps={props.steps}
          env={props.env ?? ownedEnv}
          currentUser={props.currentUser}
        />
      </Provider>
    ),
  };
}

describe('DecommissionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: nobody is a member of anything, unless a test says otherwise —
    // a network hiccup (or an unmocked call) must never widen who can act.
    vi.mocked(userGroupService.listMembers).mockResolvedValue({ rows: [], total: 0 });
  });

  it('shows the teardown date and the state chip', async () => {
    renderPanel({ decommission: WARNED, steps: STEPS });

    expect(screen.getByText(/23 Aug 2026/)).toBeInTheDocument();
    expect(screen.getByText(/warned/i)).toBeInTheDocument();
  });

  it('shows who initiated the decommission — B5 fix wave: the panel could never show this, because the read never resolved it', async () => {
    renderPanel({ decommission: WARNED, steps: STEPS });

    expect(screen.getByText(/initiated by ops\.alice/i)).toBeInTheDocument();
  });

  it('renders nothing for the initiator when the field is absent, rather than crashing', async () => {
    renderPanel({
      decommission: { ...WARNED, initiated_by_username: null },
      steps: STEPS,
    });

    expect(screen.queryByText(/initiated by/i)).not.toBeInTheDocument();
  });

  it('offers the extension control to the owner and not to a bystander', async () => {
    const { rerender, store } = renderPanel({
      decommission: WARNED,
      steps: STEPS,
      currentUser: owner,
    });
    expect(screen.getByRole('button', { name: /request extension/i })).toBeInTheDocument();

    rerender(
      <Provider store={store}>
        <DecommissionPanel
          decommission={WARNED}
          steps={STEPS}
          env={ownedEnv}
          currentUser={bystander}
        />
      </Provider>
    );
    expect(screen.queryByRole('button', { name: /request extension/i })).not.toBeInTheDocument();
  });

  it('lists every required step with its signer once signed', async () => {
    const signed: DecommissionWithChecklist = {
      ...WARNED,
      attestations: [
        makeAttestation({
          step_key: 'final_backup',
          signed_by_username: 'ops.bob',
          signed_at: '2026-08-19T10:00:00Z',
          reference: 'SNAP-42',
        }),
      ],
    };

    renderPanel({ decommission: signed, steps: STEPS });

    expect(screen.getByText('Final backup taken')).toBeInTheDocument();
    expect(screen.getByText(/ops\.bob/)).toBeInTheDocument();
    expect(screen.getByText(/SNAP-42/)).toBeInTheDocument();
    expect(screen.getByText('Infrastructure torn down')).toBeInTheDocument();
  });

  it('renders a previously-signed step as signed on the FIRST render, with no signing action taken', async () => {
    // FINDING 2 from the task-12 review: `GET /environments/{id}/decommission`
    // now carries real attestations (a LEFT JOIN in
    // `list_attestations`, never a per-worklist-row query). Nothing here
    // dispatches signAttestation — this proves the checklist seeds itself
    // from the wire response alone, so a reload cannot make an
    // already-signed step look unsigned (the 409-with-no-explanation this
    // finding described).
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [
        {
          id: 1,
          user_id: teamMember.id,
          username: teamMember.username,
          group_id: 7,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
    const signed: DecommissionWithChecklist = {
      ...WARNED,
      attestations: [
        makeAttestation({
          step_key: 'final_backup',
          signed_by_username: 'ops.bob',
          signed_at: '2026-08-19T10:00:00Z',
          reference: 'SNAP-42',
        }),
      ],
    };

    renderPanel({ decommission: signed, steps: STEPS, currentUser: teamMember });

    expect(await screen.findByText(/signed by ops\.bob/i)).toBeInTheDocument();
    // No re-sign affordance for a step that already has a signature.
    expect(screen.queryAllByRole('button', { name: /^sign$/i })).toHaveLength(1); // only "teardown"'s
    expect(api.post).not.toHaveBeenCalled();
  });

  it('disables Tear down until every required step is signed, and says why', async () => {
    // A control that is merely disabled teaches nothing. The reason renders
    // beside it — the same call the 422 makes by naming the missing steps
    // (by KEY, deliberately, so this text cannot collide with a step's own
    // label elsewhere on the page).
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [{ id: 1, user_id: teamMember.id, username: teamMember.username, group_id: 7, created_at: '2026-01-01T00:00:00Z' }],
      total: 1,
    });

    renderPanel({ decommission: WARNED, steps: STEPS, currentUser: teamMember });

    const tearDownButton = await screen.findByRole('button', { name: /tear down/i });
    await waitFor(() => expect(tearDownButton).toBeDisabled());
    expect(screen.getByText(/final backup taken/i)).toBeInTheDocument();
    expect(screen.getByText(/sign .* before tearing down/i)).toBeInTheDocument();
  });

  it('enables Tear down once the last required step is signed', async () => {
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [{ id: 1, user_id: teamMember.id, username: teamMember.username, group_id: 7, created_at: '2026-01-01T00:00:00Z' }],
      total: 1,
    });
    const allSigned: DecommissionWithChecklist = {
      ...WARNED,
      attestations: STEPS.map((s) =>
        makeAttestation({
          step_key: s.key,
          signed_by_username: 'ops.bob',
          signed_at: '2026-08-19T10:00:00Z',
          reference: 'x',
        })
      ),
    };

    renderPanel({ decommission: allSigned, steps: STEPS, currentUser: teamMember });

    const tearDownButton = await screen.findByRole('button', { name: /tear down/i });
    await waitFor(() => expect(tearDownButton).toBeEnabled());
  });

  it('re-renders when the decommission changes without unmounting', async () => {
    // A frontend test that only ever MOUNTS cannot see state that outlives an
    // unmount, nor a stale effect. Rerender with new props, do not remount.
    const { rerender, store } = renderPanel({ decommission: WARNED, steps: STEPS });
    expect(screen.getByText(/23 Aug 2026/)).toBeInTheDocument();

    const moved: DecommissionWithChecklist = {
      ...WARNED,
      scheduled_teardown_at: '2026-09-30T09:00:00Z',
    };
    rerender(
      <Provider store={store}>
        <DecommissionPanel decommission={moved} steps={STEPS} env={ownedEnv} />
      </Provider>
    );

    expect(screen.getByText(/30 Sep 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/23 Aug 2026/)).not.toBeInTheDocument();
  });

  it('surfaces the server error text when cancelling is refused', async () => {
    // Mock the AxiosError SHAPE. A test rejecting with a plain Error carrying
    // the final text passes while the app shows "Request failed with status
    // code 422" — RTK's miniSerializeError drops response.data.detail.
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [{ id: 1, user_id: teamMember.id, username: teamMember.username, group_id: 7, created_at: '2026-01-01T00:00:00Z' }],
      total: 1,
    });
    const err = new AxiosError('Request failed with status code 422');
    err.response = {
      data: { detail: 'Sign these first: final_backup, teardown' },
      status: 422,
      statusText: '',
      headers: {},
      config: {} as never,
    };
    vi.mocked(api.post).mockRejectedValueOnce(err);

    renderPanel({ decommission: WARNED, steps: STEPS, currentUser: teamMember });

    const cancelTrigger = await screen.findByRole('button', { name: /cancel decommission/i });
    await userEvent.click(cancelTrigger);
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/reason/i), 'Changed our minds');
    await userEvent.click(within(dialog).getByRole('button', { name: /confirm cancellation/i }));

    await waitFor(() => {
      expect(screen.getByText(/Sign these first: final_backup, teardown/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});

describe('starting a decommission', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(userGroupService.listMembers).mockResolvedValue({ rows: [], total: 0 });
  });

  // FINDING 1 from the task-12 review: `initiateDecommission` existed in the
  // slice and nothing called it — the primary journey (starting a
  // decommission at all) was unreachable from the product, B3b's mistake
  // repeated. `decommission` is now `| null`; the panel offers its own
  // "Start decommission" entry point, gated the same way every other run
  // action is (`assert_may_run` — team or admin).

  it('offers Start decommission when there is none, and initiating renders the panel in the warned state', async () => {
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [
        {
          id: 1,
          user_id: teamMember.id,
          username: teamMember.username,
          group_id: 7,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
    const created: DecommissionWithChecklist = {
      ...WARNED,
      id: 99,
      reason: 'Freeing capacity',
      attestations: [],
    };
    vi.mocked(api.post).mockResolvedValueOnce({
      data: created,
      status: 201,
      statusText: '',
      headers: {},
      config: {} as never,
    });

    renderPanel({ decommission: null, steps: STEPS, currentUser: teamMember });

    const startButton = await screen.findByRole('button', { name: /start decommission/i });
    await userEvent.click(startButton);
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/reason/i), 'Freeing capacity');
    await userEvent.click(
      within(dialog).getByRole('button', { name: /confirm start/i })
    );

    await waitFor(() => {
      expect(screen.getByText(/warned/i)).toBeInTheDocument();
    });
    // The entry point is gone once a live decommission exists — a second
    // POST would 409.
    expect(screen.queryByRole('button', { name: /start decommission/i })).not.toBeInTheDocument();
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe('/environments/1/decommission');
  });

  it('does not offer Start decommission while a live one already exists', async () => {
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [
        {
          id: 1,
          user_id: teamMember.id,
          username: teamMember.username,
          group_id: 7,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });

    renderPanel({ decommission: WARNED, steps: STEPS, currentUser: teamMember });

    // Give the (irrelevant here) membership fetch a chance to resolve before
    // asserting a negative.
    await waitFor(() => expect(userGroupService.listMembers).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /start decommission/i })).not.toBeInTheDocument();
  });

  it('does not offer Start decommission to a bystander', async () => {
    renderPanel({ decommission: null, steps: STEPS, currentUser: bystander });

    await waitFor(() => expect(userGroupService.listMembers).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /start decommission/i })).not.toBeInTheDocument();
  });

  it('surfaces the server error text when starting is refused', async () => {
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [
        {
          id: 1,
          user_id: teamMember.id,
          username: teamMember.username,
          group_id: 7,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
    const err = new AxiosError('Request failed with status code 422');
    err.response = {
      data: {
        detail:
          "scheduled_teardown_at cannot be earlier than the tenant's 5-day notice period",
      },
      status: 422,
      statusText: '',
      headers: {},
      config: {} as never,
    };
    vi.mocked(api.post).mockRejectedValueOnce(err);

    renderPanel({ decommission: null, steps: STEPS, currentUser: teamMember });

    const startButton = await screen.findByRole('button', { name: /start decommission/i });
    await userEvent.click(startButton);
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/reason/i), 'Too soon');
    await userEvent.click(
      within(dialog).getByRole('button', { name: /confirm start/i })
    );

    await waitFor(() => {
      expect(
        screen.getByText(/cannot be earlier than the tenant's 5-day notice period/)
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});

describe('B5 acts only where it says', () => {
  it('renders the remaining bookings and offers no control that changes one', async () => {
    // RemainingBookingSummary carries no `purpose` field (deliberately thin —
    // id/start_date/end_date/status only). Assert on the real shape.
    const withBookings: DecommissionWithChecklist = {
      ...WARNED,
      remaining_bookings: [
        { id: 11, start_date: '2026-09-05T09:00:00Z', end_date: '2026-09-10T17:00:00Z', status: 'approved' },
      ],
    };

    renderPanel({ decommission: withBookings, steps: STEPS, currentUser: teamMember });

    expect(screen.getByText(/approved booking/i)).toBeInTheDocument();
    expect(screen.getByText(/10 Sep 2026/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /cancel booking/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /move booking/i })).not.toBeInTheDocument();
  });

  // Task 15's own addition. `RemainingBookingSummary` is a disclosure, never
  // an editable view — extending the block above (not duplicating it) with
  // the remaining two mutation shapes named in the task-15 brief
  // ("no cancel-booking, no move-booking, no shorten") and a case with
  // MULTIPLE remaining bookings of DIFFERENT statuses, so a control keyed
  // off a single booking's row could not hide behind an empty list.
  it('offers no shorten control either, and none appears for any remaining booking, admin or team', async () => {
    const withBookings: DecommissionWithChecklist = {
      ...WARNED,
      remaining_bookings: [
        { id: 11, start_date: '2026-09-05T09:00:00Z', end_date: '2026-09-10T17:00:00Z', status: 'approved' },
        { id: 12, start_date: '2026-09-12T09:00:00Z', end_date: '2026-09-14T17:00:00Z', status: 'draft' },
      ],
    };
    const admin: DecommissionPanelUser = {
      id: 99,
      username: 'admin.amy',
      role: 'Admin',
      is_master_admin: false,
    };

    renderPanel({ decommission: withBookings, steps: STEPS, currentUser: admin });

    expect(screen.getByText(/approved booking/i)).toBeInTheDocument();
    expect(screen.getByText(/draft booking/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /shorten/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /cancel booking/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /move booking/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reschedule/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /edit booking/i })).not.toBeInTheDocument();
    // The remaining-bookings list itself renders no interactive element at
    // all — every button on the page belongs to the decommission workflow
    // (checklist / extension / tear down / cancel decommission), never to
    // one of the booking rows just asserted above.
    const bookingsHeading = screen.getByText(/bookings not touched by teardown/i);
    const bookingsSection = bookingsHeading.parentElement as HTMLElement;
    expect(within(bookingsSection).queryAllByRole('button')).toHaveLength(0);
  });
});
