import { configureStore } from '@reduxjs/toolkit';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentRequestForm from '../EnvironmentRequestForm';
import environmentRequestReducer from '../../../store/environmentRequestSlice';
import { environmentRequestService } from '../../../services/environmentRequestService';
import { environmentService } from '../../../services/environmentService';
import { environmentTierService } from '../../../services/environmentTierService';
import type { EnvironmentResponse } from '../../../types/environment';
import type { EnvironmentTierResponse } from '../../../types/environmentTier';

// No HTTP anywhere in this test — it's about the payload the form builds and
// how it reads a rejected create, not about what the server returns.
vi.mock('../../../services/environmentRequestService', () => ({
  environmentRequestService: {
    createRequest: vi.fn(),
  },
}));

// The environment/tier pickers read every row via useAllEnvironments /
// useAllEnvironmentTiers (never a paged slice — see those hooks' docstrings).
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn(),
  },
}));
vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn(),
  },
}));

const ENVIRONMENTS: EnvironmentResponse[] = [
  {
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
    operations_group_id: null,
    operations_group_name: null,
    access_url: null,
    connection_notes: null,
    support_contact: null,
    sla_notes: null,
    known_limitations: null,
    decommission_notes: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
];

const TIERS: EnvironmentTierResponse[] = [
  {
    id: 4,
    tenant_id: 1,
    name: 'Performance',
    description: null,
    category: 'performance',
    color: null,
    display_order: 40,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    idle_threshold_days: null,
  },
];

function renderForm() {
  const store = configureStore({
    reducer: { environmentRequest: environmentRequestReducer },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/environment-requests/new']}>
        <EnvironmentRequestForm />
      </MemoryRouter>
    </Provider>
  );
}

async function selectEnvironment(name: string) {
  await userEvent.click(screen.getByRole('combobox', { name: 'Environment' }));
  await userEvent.click(await screen.findByRole('option', { name }));
}

async function selectTier(name: string) {
  await userEvent.click(screen.getByRole('combobox', { name: 'Tier' }));
  await userEvent.click(await screen.findByRole('option', { name }));
}

describe('EnvironmentRequestForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({
      rows: ENVIRONMENTS,
      total: 1,
    });
    vi.mocked(environmentTierService.listTiers).mockResolvedValue({
      rows: TIERS,
      total: 1,
    });
  });

  // Finding 1a — a rejected create must surface the server's reason
  // (`result.payload`), not the generic axios status text
  // (`result.error.message`). Shaped like a real AxiosError: `.message` is
  // the generic HTTP-status text axios sets, and the actual backend
  // explanation lives only at `response.data.detail`. A plain `Error`
  // carrying the final text on `.message` can't catch a regression to
  // `result.error.message`, because that shape already has the right text in
  // the one place the buggy code reads. See CLAUDE.md's note on this exact
  // defect, shipped in four other panels.
  it('surfaces the server-named reason when create is rejected', async () => {
    vi.mocked(environmentRequestService.createRequest).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { detail: "A 'access' request requires: environment_id" },
      },
    });

    renderForm();

    await selectEnvironment('Mortgage SIT');
    await userEvent.type(screen.getByLabelText(/^Justification/), 'Need to verify a fix');
    await userEvent.click(screen.getByRole('button', { name: 'Submit request' }));

    expect(
      await screen.findByText("A 'access' request requires: environment_id")
    ).toBeInTheDocument();
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  // Finding 1b — the submit control is gated on different fields per mode,
  // mirroring the backend's own `_assert_mode_fields`. Asserted in both
  // directions (disabled while incomplete, enabled once satisfied) so the
  // test fails whether the gate is removed or inverted.
  it('gates access-mode submission on the environment being chosen', async () => {
    renderForm();

    await userEvent.type(screen.getByLabelText(/^Justification/), 'Need to verify a fix');
    expect(screen.getByRole('button', { name: 'Submit request' })).toBeDisabled();

    await selectEnvironment('Mortgage SIT');
    expect(screen.getByRole('button', { name: 'Submit request' })).toBeEnabled();
  });

  it('gates new-environment-mode submission on name, tier and expiry all being present', async () => {
    renderForm();

    await userEvent.click(screen.getByRole('button', { name: 'New environment' }));
    await userEvent.type(screen.getByLabelText(/^Justification/), 'Need a dedicated perf env');
    expect(screen.getByRole('button', { name: 'Submit request' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/^Proposed name/), 'Mortgage PERF');
    expect(screen.getByRole('button', { name: 'Submit request' })).toBeDisabled();

    await selectTier('Performance');
    expect(screen.getByRole('button', { name: 'Submit request' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^Expiry/), { target: { value: '2026-09-01' } });
    expect(screen.getByRole('button', { name: 'Submit request' })).toBeEnabled();
  });

  // Finding 1c — switching modes must not carry the other mode's fields into
  // the payload. The backend nulls the irrelevant mode's fields server-side,
  // but the client should not be sending them at all.
  it('does not carry new-environment fields into an access-mode payload after switching modes', async () => {
    vi.mocked(environmentRequestService.createRequest).mockResolvedValue({
      id: 1,
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
      operations_group_id: null,
      operations_group_name: null,
      created_environment_id: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    renderForm();

    // Fill in the new-environment fields first...
    await userEvent.click(screen.getByRole('button', { name: 'New environment' }));
    await userEvent.type(screen.getByLabelText(/^Justification/), 'Need to verify a fix');
    await userEvent.type(screen.getByLabelText(/^Proposed name/), 'Mortgage PERF');
    await selectTier('Performance');
    fireEvent.change(screen.getByLabelText(/^Expiry/), { target: { value: '2026-09-01' } });

    // ...then switch back to access mode and finish there instead.
    await userEvent.click(screen.getByRole('button', { name: 'Access' }));
    await selectEnvironment('Mortgage SIT');
    await userEvent.click(screen.getByRole('button', { name: 'Submit request' }));

    await waitFor(() => expect(environmentRequestService.createRequest).toHaveBeenCalled());
    const payload = vi.mocked(environmentRequestService.createRequest).mock.calls[0][0];
    expect(payload).not.toHaveProperty('proposed_name');
    expect(payload).not.toHaveProperty('tier_id');
    expect(payload).not.toHaveProperty('expires_at');
    expect(payload).toEqual({
      kind: 'access',
      justification: 'Need to verify a fix',
      environment_id: 5,
    });
  });
});
