import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ReleaseForm from '../ReleaseForm';
import releaseReducer from '../../../store/releaseSlice';
import bookingLifecycleReducer from '../../../store/bookingLifecycleSlice';
import customFieldReducer from '../../../store/customFieldSlice';
import projectReducer from '../../../store/projectSlice';
import type { ReleaseResponse } from '../../../types/release';
import type { BookingLifecycleTemplate } from '../../../types/bookingLifecycle';

// No HTTP — these tests are about the Owning project picker's wiring
// (fetching only active projects, sending owning_project_id, and the
// archived-project resubmit hazard from the Task 4 review), not about what
// the server actually returns for anything else.
vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    create: vi.fn(),
    update: vi.fn(),
    get: vi.fn(),
  },
}));

vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listTemplates: vi.fn().mockResolvedValue([]),
    listBookingTypes: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn(),
  },
}));

import { releaseService } from '../../../services/releaseService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';
import { projectService } from '../../../services/projectService';

const PROJECT = {
  id: 3,
  tenant_id: 1,
  name: 'Mortgage',
  code: 'MTG',
  description: null,
  team_group_id: null,
  team_group_name: null,
  environment_count: 0,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const TEMPLATE: BookingLifecycleTemplate = {
  id: 1,
  tenant_id: 1,
  entity_type: 'release',
  name: 'Standard',
  description: null,
  is_default: true,
  applies_to_kind: null,
  definition: {
    states: [{ key: 'draft', label: 'Draft', is_initial: true, is_terminal: false }],
    transitions: [],
    field_permissions: {
      draft: {
        standard_fields: {
          name: { editable_by: ['*'] },
        },
      },
    },
  },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

// Already assigned to a project that has since been archived — reproduces
// the Task 4 review hazard: ReleaseForm sends a fixed-whitelist payload on
// every save regardless of what changed, so this field is always resent.
const RELEASE: ReleaseResponse = {
  id: 10,
  tenant_id: 1,
  name: 'Release with archived project',
  description: null,
  release_type: 'Standard',
  release_kind: 'project',
  owning_project_id: 9,
  owning_project_name: 'Wound Down',
  parent_release_id: null,
  template_id: null,
  lifecycle_template_id: 1,
  status: 'draft',
  target_date: null,
  actual_date: null,
  scope_deadline: null,
  custom_fields: null,
  raised_by: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function makeStore() {
  return configureStore({
    reducer: {
      release: releaseReducer,
      bookingLifecycle: bookingLifecycleReducer,
      customField: customFieldReducer,
      project: projectReducer,
      // Minimal stand-in — the form only reads state.auth.user.
      auth: (state = { user: { id: 1, role: 'Release Manager', is_master_admin: false } }) =>
        state,
    },
  });
}

function renderForm(release?: ReleaseResponse) {
  const store = makeStore();
  const onClose = vi.fn();
  render(
    <Provider store={store}>
      <MemoryRouter>
        <ReleaseForm open onClose={onClose} release={release} />
      </MemoryRouter>
    </Provider>
  );
  return { onClose };
}

describe('ReleaseForm owning-project picker', () => {
  beforeEach(() => {
    vi.mocked(projectService.listProjects).mockReset().mockResolvedValue({
      rows: [PROJECT],
      total: 1,
    });
    vi.mocked(bookingLifecycleService.listTemplates).mockReset().mockResolvedValue([TEMPLATE]);
    vi.mocked(releaseService.create).mockReset();
    vi.mocked(releaseService.update).mockReset();
    vi.mocked(releaseService.get).mockReset().mockResolvedValue(RELEASE);
  });

  it('fetches only active projects for the picker', async () => {
    renderForm();
    await waitFor(() =>
      expect(projectService.listProjects).toHaveBeenCalledWith(
        expect.objectContaining({ is_active: true })
      )
    );
  });

  it('sends owning_project_id when a project is chosen on create, away from the Kind toggle', async () => {
    vi.mocked(releaseService.create).mockResolvedValue({ ...RELEASE, id: 99, owning_project_id: 3 });
    const user = userEvent.setup();
    renderForm();

    await user.type(await screen.findByLabelText('name'), 'New Release');

    await user.click(screen.getByRole('combobox', { name: 'Owning project' }));
    await user.click(await screen.findByRole('option', { name: 'Mortgage' }));

    await user.click(screen.getByRole('button', { name: /create release/i }));

    await waitFor(() => expect(releaseService.create).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(releaseService.create).mock.calls[0][0];
    expect(payload.owning_project_id).toBe(PROJECT.id);
    // Distinct from the Kind toggle (release_kind='project' means "not
    // enterprise") — picking a project must never change it.
    expect(payload.release_kind).toBe('project');
  });

  it('omits no owning project as null, and never confuses it with release_kind', async () => {
    vi.mocked(releaseService.create).mockResolvedValue({ ...RELEASE, id: 100 });
    const user = userEvent.setup();
    renderForm();

    await user.type(await screen.findByLabelText('name'), 'No Project Release');
    await user.click(screen.getByRole('button', { name: /create release/i }));

    await waitFor(() => expect(releaseService.create).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(releaseService.create).mock.calls[0][0];
    expect(payload.owning_project_id).toBeNull();
  });

  // The Task 4 review's hazard: ReleaseForm resubmits a fixed-shape payload
  // on every save. The backend carve-out tolerates resubmitting the row's
  // own already-archived project id — confirmed here, not assumed.
  it('still saves when the release\'s own project has since been archived (Task 4 carve-out)', async () => {
    // The archived project (id 9) is no longer in the active list.
    vi.mocked(projectService.listProjects).mockResolvedValue({ rows: [], total: 0 });
    vi.mocked(releaseService.update).mockResolvedValue({ ...RELEASE });

    const { onClose } = renderForm(RELEASE);

    // The archived project still renders by name — a blank/invalid select
    // would mean the value was lost, not merely unavailable to re-pick.
    expect(await screen.findByText(/wound down/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(releaseService.update).toHaveBeenCalledWith(
        RELEASE.id,
        expect.objectContaining({ owning_project_id: 9 })
      )
    );
    // No exception escaped handleSubmit's try block — the archived id round
    // tripped successfully rather than being rejected by the backend.
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
