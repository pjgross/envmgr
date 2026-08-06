import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import EnvironmentDetail from '../EnvironmentDetail';

// Regression coverage for the bug this task fixes: EnvironmentDetail carried
// its own copy of the environment form that Task 9 could only compile
// against (see the removed TODO(task-10)) — it PATCHed without
// `owner_user_id`, so saving a legacy unowned environment 422'd, and it had
// no expiry field at all. `expires_at: null` means "no expiry planned", a
// legitimate state — the form must never demand one.

const { UNOWNED_ENV, OWNED_ENV } = vi.hoisted(() => ({
  UNOWNED_ENV: {
    id: 1,
    name: 'legacy-env',
    description: null,
    tier_id: 3,
    tier_name: 'Production',
    tier_color: '#c62828',
    owner_user_id: null,
    owner_username: null,
    expires_at: null,
    reserved_now: false,
    status: 'active' as const,
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
  OWNED_ENV: {
    id: 2,
    name: 'owned-env',
    description: null,
    tier_id: 3,
    tier_name: 'Production',
    tier_color: '#c62828',
    owner_user_id: 7,
    owner_username: 'alice',
    expires_at: null,
    reserved_now: false,
    status: 'active' as const,
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
}));

// No HTTP — these tests are about the payload EnvironmentDetail builds and
// sends, not about what the server returns.
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    getEnvironment: vi.fn(),
    updateEnvironment: vi.fn(),
    listSystemsInEnvironment: vi.fn().mockResolvedValue({ systems: [], missing_systems: [] }),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

// The tier picker reads every tier via useAllEnvironmentTiers — deliberately
// not a paged slice.
vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn().mockResolvedValue({
      rows: [
        {
          id: 3,
          tenant_id: 1,
          name: 'Production',
          description: null,
          category: null,
          color: '#c62828',
          display_order: 1,
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    }),
  },
}));

// The owner picker calls GET /tenant/users/lite straight through `api`,
// matching GatesTable.tsx and EnvironmentList's own form.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [{ id: 7, username: 'alice' }] }) },
}));

import { environmentService } from '../../../services/environmentService';

function renderDetail(envId: number) {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/environments/${envId}`]}>
        <Routes>
          <Route path="/environments/:id" element={<EnvironmentDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

// The Tier/Owner <Select>s pair an `<InputLabel id>` with the Select's own
// `labelId`, unlike SystemDetail's dialogs — so, unlike that page's tests,
// `getByRole('combobox', { name })` finds them directly.

describe('EnvironmentDetail governance form', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentService.listSystemsInEnvironment).mockResolvedValue({
      systems: [],
      missing_systems: [],
    });
  });

  it('saves with no expiry set — a null expires_at must not be blocked by validation', async () => {
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(OWNED_ENV);
    vi.mocked(environmentService.updateEnvironment).mockResolvedValue(OWNED_ENV);

    renderDetail(2);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'owned-env' })).toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

    // The Expires field is blank (no expiry planned) and is left untouched.
    expect(screen.getByLabelText('Expires')).toHaveValue('');

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(environmentService.updateEnvironment).toHaveBeenCalled());

    // Explicit null, not omitted: EnvironmentUpdate.expires_at keys on
    // model_fields_set, so only an explicit null clears a stored expiry —
    // an omitted key would leave whatever was already stored untouched.
    expect(environmentService.updateEnvironment).toHaveBeenCalledWith(
      2,
      expect.objectContaining({ expires_at: null })
    );

    // No validation error blocked the save.
    expect(screen.queryByText(/expiry date is required/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // editMode exits on a successful save — the Edit button reappears.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    );
  });

  it('sends owner_user_id once an owner is chosen for a legacy unowned environment', async () => {
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(UNOWNED_ENV);
    vi.mocked(environmentService.updateEnvironment).mockResolvedValue({
      ...UNOWNED_ENV,
      owner_user_id: 7,
      owner_username: 'alice',
    });

    renderDetail(1);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'legacy-env' })).toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

    // No owner is selected yet — Save must refuse rather than PATCH without
    // owner_user_id (the exact bug this task fixes).
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText(/named owner is required/i)).toBeInTheDocument();
    expect(environmentService.updateEnvironment).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('combobox', { name: 'Owner' }));
    await userEvent.click(await screen.findByRole('option', { name: 'alice' }));

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(environmentService.updateEnvironment).toHaveBeenCalled());
    expect(environmentService.updateEnvironment).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ owner_user_id: 7, tier_id: 3, expires_at: null })
    );
  });

  it('keeps a deactivated owner selectable in edit mode, symmetric with EnvironmentList', async () => {
    // GET /tenant/users/lite (mocked above to [{id: 7, username: 'alice'}])
    // omits deactivated users, but the backend's owner validation does not
    // check is_active — an environment can legitimately hold a deactivated
    // owner. Before this fix EnvironmentList's own picker handled this (an
    // "(inactive)" option), but EnvironmentDetail had no equivalent, so
    // editing the *same* environment from the detail page rendered a blank
    // required Owner Select plus a MUI out-of-range warning.
    const DEACTIVATED_OWNER_ENV = {
      ...OWNED_ENV,
      id: 3,
      name: 'deactivated-owner-env',
      owner_user_id: 42,
      owner_username: 'retired-bob',
    };
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(DEACTIVATED_OWNER_ENV);
    vi.mocked(environmentService.updateEnvironment).mockResolvedValue(DEACTIVATED_OWNER_ENV);

    renderDetail(3);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'deactivated-owner-env' })).toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

    const ownerSelect = screen.getByRole('combobox', { name: 'Owner' });
    expect(ownerSelect).toHaveTextContent('retired-bob');
    expect(ownerSelect).toHaveTextContent(/inactive/i);

    // Save must not be blocked by the "owner required" check — the id is
    // already present in form state, just not in the fetched user list.
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.queryByText(/named owner is required/i)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(environmentService.updateEnvironment).toHaveBeenCalledWith(
        3,
        expect.objectContaining({ owner_user_id: 42 })
      )
    );
  });
});
