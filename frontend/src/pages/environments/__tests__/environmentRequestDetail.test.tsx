import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentRequestDetail from '../EnvironmentRequestDetail';
import environmentRequestReducer from '../../../store/environmentRequestSlice';
import userGroupReducer from '../../../store/userGroupSlice';
import { environmentRequestService } from '../../../services/environmentRequestService';
import { userGroupService } from '../../../services/userGroupService';
import type { EnvironmentRequestResponse, WelcomePack } from '../../../types/environmentRequest';
import type { UserGroupResponse } from '../../../types/userGroup';

// No HTTP anywhere in this test — the service layer is mocked, and the page
// is exercised through the store the same way environmentRequestForm.test.tsx
// exercises the form.
vi.mock('../../../services/environmentRequestService', () => ({
  environmentRequestService: {
    getRequest: vi.fn(),
    allowedTransitions: vi.fn(),
    transition: vi.fn(),
    updateRequest: vi.fn(),
    getWelcomePack: vi.fn(),
  },
}));

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn(),
  },
}));

const BASE_REQUEST: EnvironmentRequestResponse = {
  id: 7,
  tenant_id: 1,
  kind: 'access',
  status: 'submitted',
  lifecycle_id: 1,
  requested_by: 2,
  requester_username: 'alice',
  justification: 'Need to verify a fix',
  needed_by: null,
  environment_id: 5,
  environment_name: 'Mortgage SIT',
  proposed_name: null,
  tier_id: null,
  tier_name: null,
  expires_at: null,
  operations_group_id: 7,
  operations_group_name: 'Platform Ops',
  created_environment_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const APPROVE_ONLY = [
  { from_state: 'submitted', to_state: 'approved', label: 'Approve', allowed_roles: [] },
];

function renderDetail(
  overrides: Partial<EnvironmentRequestResponse> = {},
  user: { id: number; role: string; is_master_admin: boolean } = {
    id: 1,
    role: 'Admin',
    is_master_admin: false,
  }
) {
  vi.mocked(environmentRequestService.getRequest).mockResolvedValue({
    ...BASE_REQUEST,
    ...overrides,
  });
  const store = configureStore({
    reducer: {
      environmentRequest: environmentRequestReducer,
      userGroup: userGroupReducer,
      // A stub reducer, not the real authSlice — this page only ever reads
      // state.auth.user, and the real slice's shape is bigger than any test
      // here needs. Same pattern as userGroupDetail.test.tsx.
      auth: (state = { user }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/environment-requests/${BASE_REQUEST.id}`]}>
        <Routes>
          <Route path="/environment-requests/:id" element={<EnvironmentRequestDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

function makeWelcomePack(overrides: Partial<WelcomePack> = {}): WelcomePack {
  return {
    environment: {
      id: 9,
      name: 'Mortgage PERF',
      tier: 'Performance',
      status: 'inactive',
      owner: 'alice',
      expires_at: null,
    },
    access: {
      access_url: 'Not provided',
      connection_notes: 'Not provided',
      support_contact: 'Not provided',
    },
    support: {
      sla_notes: 'Not provided',
      operations_group: 'Platform Ops',
      operations_group_members: ['alice', 'bob'],
    },
    caveats: { known_limitations: 'Not provided' },
    offboarding: { decommission_notes: 'Not provided' },
    context: { requested_by: 'alice', justification: 'Need to verify a fix', kind: 'access' },
    ...overrides,
  };
}

describe('EnvironmentRequestDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentRequestService.allowedTransitions).mockResolvedValue(APPROVE_ONLY);
  });

  // The backend's /allowed-transitions already applies both the role check
  // and the group-membership check — the page must render exactly what it
  // returns, not compute its own list (which would drift from the rule) and
  // not render every transition disabled (which tells the user nothing about
  // why a button doesn't work).
  it('renders only the transitions this actor may actually make', async () => {
    vi.mocked(environmentRequestService.allowedTransitions).mockResolvedValue([
      { from_state: 'submitted', to_state: 'approved', label: 'Approve', allowed_roles: [] },
    ]);
    renderDetail();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    );
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
  });

  // AxiosError SHAPE: generic text on `.message`, the real reason only at
  // response.data.detail. Reading `result.error.message` here would show the
  // user "Request failed with status code 403" instead of who is allowed to
  // act — this is the exact defect CLAUDE.md records as shipped four times
  // already in other panels.
  it('surfaces the server reason when a transition is refused', async () => {
    vi.mocked(environmentRequestService.transition).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 403',
      response: {
        status: 403,
        data: { detail: 'Only the operating team ... can action this request' },
      },
    });
    renderDetail();
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(screen.getByText(/Only the operating team/)).toBeInTheDocument());
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('shows the welcome pack only once the request is fulfilled', async () => {
    renderDetail({ status: 'submitted' });
    await waitFor(() => expect(environmentRequestService.getRequest).toHaveBeenCalled());
    expect(screen.queryByText('Welcome Pack')).not.toBeInTheDocument();
    expect(environmentRequestService.getWelcomePack).not.toHaveBeenCalled();
  });

  it('renders the welcome pack once the request is fulfilled', async () => {
    vi.mocked(environmentRequestService.getWelcomePack).mockResolvedValue(makeWelcomePack());
    renderDetail({ status: 'fulfilled' });

    const heading = await screen.findByText('Welcome Pack');
    // I3: scoped to the pack's OWN container. BASE_REQUEST also has
    // operations_group_name 'Platform Ops', rendered bare by the request
    // card above this Paper — `screen.getByText('Platform Ops')` (the old
    // assertion) matched THAT node, not the pack's "Operating team: Platform
    // Ops" line, and so didn't discriminate a mutation that deleted the
    // pack's own operating-team/member rendering.
    const pack = within(heading.closest('.MuiPaper-root') as HTMLElement);
    expect(pack.getByText('Operating team: Platform Ops')).toBeInTheDocument();
    expect(pack.getByText('alice')).toBeInTheDocument();
    expect(pack.getByText('bob')).toBeInTheDocument();
    // The backend substitutes "Not provided" for every empty free-text
    // field — asserting it survived to the DOM guards against a falsy check
    // that hides the section instead of showing the fallback text. See
    // welcomePack.test.tsx for the dedicated, discriminating coverage of
    // this and the rest of the pack's body.
    expect(pack.getAllByText('Not provided').length).toBeGreaterThan(0);
  });

  // I1: fetchEnvironmentRequest.pending now sets `loading` and clears
  // `error`; before this fix `loading` was set ONLY by the list thunk, so a
  // direct navigation left it false, the skeleton was dead code, and
  // `if (!current) return null` rendered a permanently blank page — even
  // though `fetchEnvironmentRequest.rejected` was already setting `error`,
  // the page never read it.
  it('shows the server reason and a retry action when the request fails to load, and recovers on retry', async () => {
    vi.mocked(environmentRequestService.getRequest).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Request not found' } },
    });
    const store = configureStore({
      reducer: {
        environmentRequest: environmentRequestReducer,
        userGroup: userGroupReducer,
        auth: (state = { user: { id: 1, role: 'Admin', is_master_admin: false } }) => state,
      },
    });
    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={[`/environment-requests/${BASE_REQUEST.id}`]}>
          <Routes>
            <Route path="/environment-requests/:id" element={<EnvironmentRequestDetail />} />
          </Routes>
        </MemoryRouter>
      </Provider>
    );

    expect(await screen.findByText('Request not found')).toBeInTheDocument();

    vi.mocked(environmentRequestService.getRequest).mockResolvedValue(BASE_REQUEST);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    // The page title AND the "Environment" field body both read "Mortgage
    // SIT" — the heading role picks out the title unambiguously.
    expect(await screen.findByRole('heading', { name: 'Mortgage SIT' })).toBeInTheDocument();
    expect(screen.queryByText('Request not found')).not.toBeInTheDocument();
  });

  // I2: opening request 8 must not render request 7's data — wrong name,
  // wrong status, and (worse) request 7's allowed-transition GATING — while
  // request 8's own fetch is still in flight.
  it('does not render the previous request while a new one is loading', async () => {
    let resolveGetRequest!: (value: EnvironmentRequestResponse) => void;
    vi.mocked(environmentRequestService.getRequest).mockImplementation(
      () => new Promise((resolve) => { resolveGetRequest = resolve; })
    );
    const store = configureStore({
      reducer: {
        environmentRequest: environmentRequestReducer,
        userGroup: userGroupReducer,
        auth: (state = { user: { id: 1, role: 'Admin', is_master_admin: false } }) => state,
      },
      preloadedState: {
        environmentRequest: {
          requests: [],
          total: 0,
          current: { ...BASE_REQUEST, id: 7, environment_name: 'Old Request Env' },
          allowedTransitions: APPROVE_ONLY,
          welcomePack: null,
          welcomePackLoading: false,
          welcomePackError: null,
          loading: false,
          error: null,
        },
      },
    });

    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/environment-requests/8']}>
          <Routes>
            <Route path="/environment-requests/:id" element={<EnvironmentRequestDetail />} />
          </Routes>
        </MemoryRouter>
      </Provider>
    );

    expect(screen.queryByText('Old Request Env')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();

    resolveGetRequest({ ...BASE_REQUEST, id: 8, environment_name: 'New Request Env' });
    // Same heading-role reasoning as the retry test above — the title and
    // the "Environment" field body render the same string.
    expect(await screen.findByRole('heading', { name: 'New Request Env' })).toBeInTheDocument();
  });

  // I4: the two re-dispatches after a successful transition had no
  // dedicated coverage — deleting them left the suite green, so the button
  // set would silently go stale after every approve/reject/etc.
  it('re-fetches the request and its allowed transitions after a successful transition', async () => {
    vi.mocked(environmentRequestService.transition).mockResolvedValue({
      ...BASE_REQUEST,
      status: 'approved',
    });
    renderDetail();

    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(environmentRequestService.getRequest).toHaveBeenCalledTimes(2));
    expect(environmentRequestService.allowedTransitions).toHaveBeenCalledTimes(2);
  });

  // I5: no existing test ever rendered this page as a non-Admin at all —
  // removing `isAdmin &&` from the picker's gate left the suite green.
  it('does not show the operations-group picker to a non-admin', async () => {
    renderDetail(
      {
        kind: 'new_environment',
        status: 'submitted',
        environment_id: null,
        environment_name: null,
        proposed_name: 'Mortgage PERF',
        tier_id: 4,
        tier_name: 'Performance',
        expires_at: '2027-01-01T00:00:00Z',
        operations_group_id: null,
        operations_group_name: null,
      },
      { id: 2, role: 'Test Manager', is_master_admin: false }
    );

    await waitFor(() => expect(environmentRequestService.getRequest).toHaveBeenCalled());
    expect(screen.queryByRole('combobox', { name: 'Operations Group' })).not.toBeInTheDocument();
    expect(userGroupService.listGroups).not.toHaveBeenCalled();
  });

  // C1 fix pass: a new-environment request cannot be fulfilled without an
  // operations_group_id (fulfilment 409s otherwise). update_request accepts
  // a group-only PATCH while status is 'draft', 'submitted' OR 'approved'
  // now (see environment_request_service.py's carve-out) — the picker gates
  // on all three, not draft alone, so an admin can still fix a request that
  // reached 'approved' with no team ever assigned (C1's actual failure
  // mode — the seeded template gives 'approved' exactly one outgoing edge).
  it('lets an admin assign the operations group on a draft new-environment request', async () => {
    const groups: UserGroupResponse[] = [
      {
        id: 3,
        tenant_id: 1,
        name: 'Platform Ops',
        description: null,
        member_count: 2,
        environment_count: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ];
    vi.mocked(userGroupService.listGroups).mockResolvedValue({ rows: groups, total: 1 });
    vi.mocked(environmentRequestService.updateRequest).mockResolvedValue({
      ...BASE_REQUEST,
      kind: 'new_environment',
      status: 'draft',
      environment_id: null,
      environment_name: null,
      proposed_name: 'Mortgage PERF',
      tier_id: 4,
      tier_name: 'Performance',
      expires_at: '2027-01-01T00:00:00Z',
      operations_group_id: 3,
      operations_group_name: 'Platform Ops',
    });

    renderDetail({
      kind: 'new_environment',
      status: 'draft',
      environment_id: null,
      environment_name: null,
      proposed_name: 'Mortgage PERF',
      tier_id: 4,
      tier_name: 'Performance',
      expires_at: '2027-01-01T00:00:00Z',
      operations_group_id: null,
      operations_group_name: null,
    });

    await userEvent.click(await screen.findByRole('combobox', { name: 'Operations Group' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Platform Ops' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(environmentRequestService.updateRequest).toHaveBeenCalledWith(7, {
        operations_group_id: 3,
      })
    );
  });

  // C1's actual point of no return, before the fix: 'approved' has exactly
  // one outgoing edge (approved -> fulfilled), fulfilment 409s forever on a
  // null group, and the request is never terminal. This is the frontend
  // half of the recovery path the backend test suite proves end-to-end.
  it('lets an admin assign the operations group on an approved new-environment request', async () => {
    const groups: UserGroupResponse[] = [
      {
        id: 3,
        tenant_id: 1,
        name: 'Platform Ops',
        description: null,
        member_count: 2,
        environment_count: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ];
    vi.mocked(userGroupService.listGroups).mockResolvedValue({ rows: groups, total: 1 });
    vi.mocked(environmentRequestService.updateRequest).mockResolvedValue({
      ...BASE_REQUEST,
      kind: 'new_environment',
      status: 'approved',
      environment_id: null,
      environment_name: null,
      proposed_name: 'Mortgage PERF',
      tier_id: 4,
      tier_name: 'Performance',
      expires_at: '2027-01-01T00:00:00Z',
      operations_group_id: 3,
      operations_group_name: 'Platform Ops',
    });

    renderDetail({
      kind: 'new_environment',
      status: 'approved',
      environment_id: null,
      environment_name: null,
      proposed_name: 'Mortgage PERF',
      tier_id: 4,
      tier_name: 'Performance',
      expires_at: '2027-01-01T00:00:00Z',
      operations_group_id: null,
      operations_group_name: null,
    });

    await userEvent.click(await screen.findByRole('combobox', { name: 'Operations Group' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Platform Ops' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(environmentRequestService.updateRequest).toHaveBeenCalledWith(7, {
        operations_group_id: 3,
      })
    );
  });

  // Mirrors the operations-group picker's error path: it also reads
  // `result.payload`, and this is the second rejected-thunk read on the page.
  it('surfaces the server reason when setting the operations group is refused', async () => {
    vi.mocked(userGroupService.listGroups).mockResolvedValue({
      rows: [
        {
          id: 3,
          tenant_id: 1,
          name: 'Platform Ops',
          description: null,
          member_count: 2,
          environment_count: 1,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
    vi.mocked(environmentRequestService.updateRequest).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'User group not found' } },
    });

    renderDetail({
      kind: 'new_environment',
      status: 'draft',
      environment_id: null,
      environment_name: null,
      proposed_name: 'Mortgage PERF',
      tier_id: 4,
      tier_name: 'Performance',
      expires_at: '2027-01-01T00:00:00Z',
      operations_group_id: null,
      operations_group_name: null,
    });

    await userEvent.click(await screen.findByRole('combobox', { name: 'Operations Group' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Platform Ops' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByText('User group not found')).toBeInTheDocument());
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
