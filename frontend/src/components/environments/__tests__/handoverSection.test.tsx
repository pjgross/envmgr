import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import HandoverSection from '../HandoverSection';
import environmentRequestReducer from '../../../store/environmentRequestSlice';
import { environmentRequestService } from '../../../services/environmentRequestService';
import { userGroupService } from '../../../services/userGroupService';
import type { EnvironmentResponse } from '../../../types/environment';
import type { UserGroupMemberResponse } from '../../../types/userGroup';

// This section writes through updateEnvironmentHandover, which calls
// environmentRequestService.updateHandover — see environmentRequestSlice.ts.
vi.mock('../../../services/environmentRequestService', () => ({
  environmentRequestService: {
    updateHandover: vi.fn(),
  },
}));

// Group membership is not on the frontend's user object (see task-11 brief) —
// the section fetches it itself via userGroupService.listMembers.
vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    listMembers: vi.fn(),
  },
}));

const ENVIRONMENT: EnvironmentResponse = {
  id: 5,
  name: 'Mortgage SIT',
  description: null,
  tier_id: 2,
  tier_name: 'SIT',
  tier_color: null,
  owner_user_id: 9,
  owner_username: 'owner',
  expires_at: null,
  reserved_now: false,
  idle: false,
  decommission_state: null,
  status: 'active',
  tenant_id: 1,
  custom_fields: null,
  operations_group_id: 7,
  operations_group_name: 'Platform Ops',
  access_url: null,
  connection_notes: null,
  support_contact: null,
  sla_notes: null,
  known_limitations: null,
  decommission_notes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function makeMember(overrides: Partial<UserGroupMemberResponse> = {}): UserGroupMemberResponse {
  return {
    id: 1,
    user_id: 42,
    username: 'alice',
    group_id: 7,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderSection(
  user: { id: number; role: string; is_master_admin: boolean } | null,
  environment: EnvironmentResponse = ENVIRONMENT
) {
  const store = configureStore({
    reducer: {
      environmentRequest: environmentRequestReducer,
      auth: (state = { user }) => state,
    },
  });
  return render(
    <Provider store={store}>
      <HandoverSection environment={environment} />
    </Provider>
  );
}

describe('HandoverSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('is editable for a member of the operating team who is not an admin', async () => {
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [makeMember({ user_id: 42 })],
      total: 1,
    });
    renderSection({ id: 42, role: 'Viewer', is_master_admin: false });

    expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it('is read-only for someone outside the team', async () => {
    vi.mocked(userGroupService.listMembers).mockResolvedValue({
      rows: [makeMember({ user_id: 99 })],
      total: 1,
    });
    renderSection({ id: 42, role: 'Viewer', is_master_admin: false });

    await waitFor(() => expect(userGroupService.listMembers).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });

  // If the membership fetch fails, the gate must fall back to Admin-only,
  // never to editable — a network error must never widen who can write
  // handover content.
  it('falls back to read-only, not editable, when the membership fetch fails', async () => {
    vi.mocked(userGroupService.listMembers).mockRejectedValue(new Error('network error'));
    renderSection({ id: 42, role: 'Viewer', is_master_admin: false });

    await waitFor(() => expect(userGroupService.listMembers).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });

  // The endpoint rejects anything else with a 422; the UI must not send
  // tier_id or owner_user_id even accidentally. An Admin needs no group
  // membership, so this exercises the edit path without depending on the
  // listMembers mock.
  it('sends only handover keys', async () => {
    vi.mocked(environmentRequestService.updateHandover).mockResolvedValue({
      ...ENVIRONMENT,
      connection_notes: 'VPN then RDP to the app server',
    });
    renderSection({ id: 1, role: 'Admin', is_master_admin: false });

    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    await userEvent.type(
      screen.getByLabelText('How to connect'),
      'VPN then RDP to the app server'
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(environmentRequestService.updateHandover).toHaveBeenCalled());
    const [envId, payload] = vi.mocked(environmentRequestService.updateHandover).mock.calls[0];
    expect(envId).toBe(5);
    expect(Object.keys(payload).sort()).toEqual(
      [
        'access_url',
        'connection_notes',
        'decommission_notes',
        'known_limitations',
        'sla_notes',
        'support_contact',
      ].sort()
    );
  });

  // AxiosError SHAPE, same as every other rejected-thunk test in this repo:
  // generic text on `.message`, the real reason only at response.data.detail.
  it('surfaces the server reason when saving the handover is refused', async () => {
    vi.mocked(environmentRequestService.updateHandover).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: { status: 422, data: { detail: 'access_url: value is not a valid URL' } },
    });
    renderSection({ id: 1, role: 'Admin', is_master_admin: false });

    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(screen.getByText('access_url: value is not a valid URL')).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
