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
import type { DecommissionStep } from '../../../types/decommission';

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
  decommission: DecommissionWithChecklist;
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
        {
          step_key: 'final_backup',
          signed_by_username: 'ops.bob',
          signed_at: '2026-08-19T10:00:00Z',
          reference: 'SNAP-42',
        },
      ],
    };

    renderPanel({ decommission: signed, steps: STEPS });

    expect(screen.getByText('Final backup taken')).toBeInTheDocument();
    expect(screen.getByText(/ops\.bob/)).toBeInTheDocument();
    expect(screen.getByText(/SNAP-42/)).toBeInTheDocument();
    expect(screen.getByText('Infrastructure torn down')).toBeInTheDocument();
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
      attestations: STEPS.map((s) => ({
        step_key: s.key,
        signed_by_username: 'ops.bob',
        signed_at: '2026-08-19T10:00:00Z',
        reference: 'x',
      })),
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
});
