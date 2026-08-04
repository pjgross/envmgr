import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UserGroupDetail from '../UserGroupDetail';
import userGroupReducer from '../../../store/userGroupSlice';
import { userGroupService } from '../../../services/userGroupService';
import type { UserGroupMemberResponse, UserGroupResponse } from '../../../types/userGroup';

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    getGroup: vi.fn(),
    listMembers: vi.fn(),
    addMember: vi.fn(),
    removeMember: vi.fn(),
  },
}));

// UserGroupDetail hits `/tenant/users/lite` directly through the shared axios
// instance rather than a service object — see the comment in the component.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn() },
}));

import api from '../../../services/api';

const mockedApiGet = vi.mocked(api.get);

function makeGroup(overrides: Partial<UserGroupResponse> = {}): UserGroupResponse {
  return {
    id: 1,
    tenant_id: 1,
    name: 'Platform Ops',
    description: 'Runs the SIT estate',
    member_count: 1,
    environment_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeMember(overrides: Partial<UserGroupMemberResponse> = {}): UserGroupMemberResponse {
  return {
    id: 1,
    user_id: 10,
    username: 'alice',
    group_id: 1,
    created_at: '2026-01-02T00:00:00Z',
    ...overrides,
  };
}

function renderPage(role: 'Admin' | 'Member' = 'Admin') {
  const store = configureStore({
    reducer: {
      userGroup: userGroupReducer,
      auth: (state = { user: { role, is_master_admin: false } }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/tenant/groups/1']}>
        <Routes>
          <Route path="/tenant/groups/:id" element={<UserGroupDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

describe('UserGroupDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(userGroupService.getGroup).mockResolvedValue(makeGroup());
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [makeMember()],
      total: 1,
    });
    mockedApiGet.mockResolvedValue({ data: [{ id: 20, username: 'bob' }] });
  });

  it('renders member usernames that came with the API rows', async () => {
    renderPage('Admin');
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
  });

  it('shows the group name from a fetch, not the (unpopulated) groups list', async () => {
    // Finding 3: a deep link never populates the paginated `groups` slice,
    // so the detail page must fetch its own group rather than reading
    // `groups.find(...)`.
    renderPage('Admin');
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    expect(screen.getByText('Runs the SIT estate')).toBeInTheDocument();
  });

  it('surfaces the server reason when adding a member is refused', async () => {
    // AxiosError SHAPE: generic text on `.message`, the real reason only at
    // response.data.detail. A plain Error carrying the final text would pass
    // against the `result.error.message` defect this repo has shipped
    // three times already.
    vi.mocked(userGroupService.addMember).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'bob is already a member of this group.' },
      },
    });
    renderPage('Admin');

    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText(/add member/i));
    await userEvent.click(await screen.findByRole('option', { name: 'bob' }));
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(screen.getByText('bob is already a member of this group.')).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('leaves the page usable with an empty picker when /tenant/users/lite fails', async () => {
    mockedApiGet.mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'boom' } },
    });
    renderPage('Admin');

    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    // The picker renders with no crash; there is simply nothing to pick.
    await userEvent.click(screen.getByLabelText(/add member/i));
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });

  it('shows the member list but not the write controls for a non-admin', async () => {
    renderPage('Member');
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    expect(screen.queryByLabelText(/add member/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
  });

  it('shows the write controls for an admin', async () => {
    renderPage('Admin');
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    expect(screen.getByLabelText(/add member/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
  });
});
