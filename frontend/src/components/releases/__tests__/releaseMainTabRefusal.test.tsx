/**
 * A refused close must reach the user as the SERVER'S reason, not Axios's
 * "Request failed with status code 422". A plain Error carrying the final
 * text would pass a naive test while the app shows the generic message, so
 * the rejection here is a real AxiosError shape.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import { AxiosError } from 'axios';
import { store } from '../../../store';
import { setCredentials } from '../../../store/authSlice';
import { fetchRelease } from '../../../store/releaseSlice';
import { releaseService } from '../../../services/releaseService';
import ReleaseMainTab from '../ReleaseMainTab';

vi.mock('../../../services/releaseService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/releaseService')>();
  return { ...actual, releaseService: { ...actual.releaseService, transition: vi.fn(), getLifecycle: vi.fn(), get: vi.fn() } };
});

const RELEASE_ID = 7;

const RELEASE = {
  id: RELEASE_ID,
  tenant_id: 1,
  name: 'R1',
  description: null,
  release_type: 'standard',
  release_kind: 'project' as const,
  owning_project_id: null,
  owning_project_name: null,
  parent_release_id: null,
  template_id: null,
  lifecycle_template_id: 1,
  status: 'live',
  target_date: null,
  actual_date: null,
  scope_deadline: null,
  custom_fields: null,
  raised_by: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  operations_group_id: null,
  operations_group_name: null,
  declared_stable_at: null,
  declared_stable_by_username: null,
  handover_confirmed_at: null,
  handover_confirmed_by_username: null,
};

const lifecycle = {
  id: 1, definition: {
    states: [
      { key: 'live', label: 'Live', is_initial: false, is_terminal: false },
      { key: 'completed', label: 'Completed', is_initial: false, is_terminal: true, is_closed: true, requires_pir_complete: true },
    ],
    transitions: [{ from_state: 'live', to_state: 'completed', label: 'Close', allowed_roles: ['Admin'] }],
    field_permissions: { live: { standard_fields: {}, custom_fields: {} }, completed: { standard_fields: {}, custom_fields: {} } },
  },
};

describe('ReleaseMainTab — a refused close shows the server reason', () => {
  beforeEach(() => {
    store.dispatch(
      setCredentials({
        user: {
          id: 1,
          username: 'admin',
          email: 'admin@test.com',
          role: 'Admin',
          tenant_id: 1,
          is_active: true,
          is_master_admin: false,
        } as never,
        token: 'test-token',
      }),
    );
    store.dispatch(fetchRelease.fulfilled(RELEASE as never, 'requestId', RELEASE_ID));

    vi.mocked(releaseService.getLifecycle).mockResolvedValue(lifecycle as never);
    const err = new AxiosError('Request failed with status code 422');
    (err as unknown as { response: unknown }).response = {
      status: 422, data: { detail: 'Cannot close this release: the post-implementation review is not complete.' },
    };
    vi.mocked(releaseService.transition).mockRejectedValue(err);
  });

  it('renders the 422 detail, not the Axios message', async () => {
    render(
      <Provider store={store}>
        <SnackbarProvider>
          <MemoryRouter><ReleaseMainTab releaseId={RELEASE_ID} /></MemoryRouter>
        </SnackbarProvider>
      </Provider>,
    );
    await userEvent.click(await screen.findByRole('button', { name: /close/i }));
    await userEvent.click(await screen.findByRole('button', { name: /confirm/i }));
    await waitFor(() =>
      expect(screen.getByText(/post-implementation review is not complete/i)).toBeInTheDocument());
    expect(screen.queryByText(/status code 422/)).not.toBeInTheDocument();
  });
});
