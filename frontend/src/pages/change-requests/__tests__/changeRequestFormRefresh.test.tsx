import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import ChangeRequestForm from '../ChangeRequestForm';
import type { EnvironmentResponse } from '../../../types/environment';
import type { BookingLifecycleTemplate } from '../../../types/bookingLifecycle';
import type { ChangeRequestResponse } from '../../../types/changeRequest';

// No HTTP anywhere in this test — it's about which callback fires after a
// successful create and whether the slice itself mutates `list`, not about
// what the server returns.
vi.mock('../../../services/changeRequestService', () => ({
  changeRequestService: {
    create: vi.fn(),
  },
}));
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn(),
  },
}));
vi.mock('../../../services/infrastructureComponentService', () => ({
  infrastructureComponentService: {
    listComponents: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listTemplates: vi.fn(),
  },
}));
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

import { changeRequestService } from '../../../services/changeRequestService';
import { environmentService } from '../../../services/environmentService';
import { bookingLifecycleService } from '../../../services/bookingLifecycleService';

const ENV: EnvironmentResponse = {
  id: 1,
  name: 'Env A',
  description: null,
  environment_type: 'test',
  status: 'active',
  tenant_id: 1,
  custom_fields: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const LIFECYCLE_TEMPLATE: BookingLifecycleTemplate = {
  id: 7,
  tenant_id: 1,
  entity_type: 'change_request',
  name: 'Standard Change',
  description: null,
  is_default: true,
  definition: { states: [], transitions: [], field_permissions: {} },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const CREATE_RESPONSE: ChangeRequestResponse = {
  id: 99,
  tenant_id: 1,
  title: 'Test CR',
  description: null,
  change_type: 'configuration',
  status: 'draft',
  lifecycle_id: 7,
  subsystem_id: null,
  environment_ids: [1],
  host_ids: [],
  environments: [{ id: 1, name: 'Env A' }],
  hosts: [],
  derived_environment_ids: [],
  derived_environments: [],
  release_id: null,
  has_outage: false,
  outage_start: null,
  outage_end: null,
  scheduled_start: '2026-08-10T09:00:00Z',
  scheduled_end: '2026-08-11T09:00:00Z',
  custom_fields: null,
  raised_by: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

async function fillAndSubmit() {
  const user = userEvent.setup();

  await user.click(screen.getByLabelText('Environments'));
  await user.click(await screen.findByText('Env A'));

  fireEventChange(screen.getByLabelText(/Title/), 'Test CR');
  await screen.findByText('Standard Change (default)');
  fireEventChange(screen.getByLabelText(/Scheduled Start/), '2026-08-10T09:00');
  fireEventChange(screen.getByLabelText(/Scheduled End/), '2026-08-11T09:00');

  await user.click(screen.getByRole('button', { name: 'Create Change Request' }));
}

// react-hook-form's registered inputs need a native change event, not
// userEvent.type, to fire reliably for datetime-local/text fields here.
function fireEventChange(el: HTMLElement, value: string) {
  const input = el as HTMLInputElement;
  input.focus();
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!.call(
    input,
    value
  );
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('ChangeRequestForm create-success refresh', () => {
  beforeEach(() => {
    vi.mocked(changeRequestService.create).mockReset().mockResolvedValue(CREATE_RESPONSE);
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({ rows: [ENV], total: 1 });
    vi.mocked(bookingLifecycleService.listTemplates).mockResolvedValue([LIFECYCLE_TEMPLATE]);
  });

  it(
    'calls onCreated instead of relying on the slice to splice the new row into ' +
      "changeRequest.list — the slice no longer touches it on create",
    async () => {
      // Nothing seeded `changeRequest.list` here, and nothing in this test
      // renders ChangeRequestList — so any change to its length below can only
      // come from the removed createChangeRequest.fulfilled unshift.
      expect(store.getState().changeRequest.list).toHaveLength(0);

      const dispatchSpy = vi.spyOn(store, 'dispatch');
      const onCreated = vi.fn();
      const onClose = vi.fn();

      render(
        <Provider store={store}>
          <MemoryRouter>
            <ChangeRequestForm open onClose={onClose} onCreated={onCreated} />
          </MemoryRouter>
        </Provider>
      );

      await fillAndSubmit();

      await vi.waitFor(() => expect(changeRequestService.create).toHaveBeenCalledTimes(1));
      await vi.waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));

      // Regression guard 1: createChangeRequest.fulfilled previously did
      // state.list.unshift(action.payload) — that would corrupt a
      // server-paged window regardless of the mounted page's filter, sort or
      // page, and never adjusted `total` either. The slice must leave `list`
      // alone; only ChangeRequestList's own grid.refetch() (wired through
      // onCreated) may change it.
      expect(store.getState().changeRequest.list).toHaveLength(0);

      // Regression guard 2: the form itself must not dispatch a bare,
      // unparameterised fetchChangeRequests() — that would silently
      // overwrite ChangeRequestList's current page/sort/filter view with the
      // endpoint's unfiltered page-1 default. The parent owns the refresh.
      const dispatchedBareListFetch = dispatchSpy.mock.calls.some(([action]) => {
        return (
          typeof action === 'object' &&
          action !== null &&
          'type' in action &&
          String((action as { type: unknown }).type).startsWith('changeRequest/list')
        );
      });
      expect(dispatchedBareListFetch).toBe(false);

      dispatchSpy.mockRestore();
    }
  );
});
