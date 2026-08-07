import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import MoveScopeItemDialog from '../MoveScopeItemDialog';
import type { ReleaseListItemResponse } from '../../../types/release';

const snackbarError = vi.fn();
const snackbarSuccess = vi.fn();

vi.mock('../../../hooks/useSnackbar', () => ({
  useSnackbar: () => ({
    success: snackbarSuccess,
    error: snackbarError,
    info: vi.fn(),
    warning: vi.fn(),
    show: vi.fn(),
  }),
}));

vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    list: vi.fn(),
  },
}));

import { releaseService } from '../../../services/releaseService';

function makeRelease(id: number): ReleaseListItemResponse {
  return {
    id,
    tenant_id: 1,
    name: `Release ${id}`,
    description: null,
    release_type: 'project',
    release_kind: 'project',
    owning_project_id: null,
    owning_project_name: null,
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
    phase_count: 0,
    scope_count: 0,
    blocker_count: 0,
    overdue_criterion_count: 0,
    scope_additions_count: 0,
    scope_removals_count: 0,
    scope_change_count: 0,
    scope_creep_count: 0,
    window_status: 'open',
    days_to_cutoff: null,
    systems: [],
  };
}

function renderDialog() {
  return render(
    <Provider store={store}>
      <MoveScopeItemDialog
        open
        onClose={() => {}}
        changeId={1}
        currentReleaseId={null}
      />
    </Provider>
  );
}

describe('MoveScopeItemDialog', () => {
  beforeEach(() => {
    vi.mocked(releaseService.list).mockReset();
    snackbarError.mockReset();
    snackbarSuccess.mockReset();
  });

  // GAP 2: the dialog fetches its own release list on open rather than
  // reading `state.release.list` (the Releases tab's filtered/sorted
  // server-side page). Assert both halves: the direct fetch happens with
  // the documented `limit: 200`, and no `fetchReleases` thunk (which would
  // read/write the shared slice) is ever dispatched.
  it('fetches its own release list with limit 200 and never dispatches fetchReleases', async () => {
    vi.mocked(releaseService.list).mockResolvedValue({
      rows: [makeRelease(1)],
      total: 1,
    });
    const dispatchSpy = vi.spyOn(store, 'dispatch');

    renderDialog();

    await waitFor(() =>
      expect(releaseService.list).toHaveBeenCalledWith({ limit: 200 })
    );
    expect(releaseService.list).toHaveBeenCalledTimes(1);

    const dispatchedFetchReleases = dispatchSpy.mock.calls.some(([action]) => {
      return (
        typeof action === 'object' &&
        action !== null &&
        'type' in action &&
        String((action as { type: unknown }).type).startsWith('release/list')
      );
    });
    expect(dispatchedFetchReleases).toBe(false);

    dispatchSpy.mockRestore();
  });

  // GAP 3 (part 1): a failed fetch used to leave `.catch(() => setReleases([]))`
  // — an empty dropdown with no explanation. It should surface the failure
  // the same way `handleSave` already does, through `snackbar.error`.
  it('surfaces a fetch failure through snackbar.error instead of silently emptying the dropdown', async () => {
    vi.mocked(releaseService.list).mockRejectedValue(new Error('network down'));

    renderDialog();

    await waitFor(() => expect(snackbarError).toHaveBeenCalledWith('network down'));
  });

  // GAP 3 (part 2): 200 is the backend's max page size, so a tenant with
  // more than 200 releases gets a silently truncated dropdown unless the
  // dialog uses the service's `total` to say so.
  it('shows helper text when the release total exceeds the 200-row fetch', async () => {
    const rows = Array.from({ length: 200 }, (_, i) => makeRelease(i + 1));
    vi.mocked(releaseService.list).mockResolvedValue({ rows, total: 250 });

    renderDialog();

    await waitFor(() =>
      expect(
        screen.getByText('Only the first 200 of 250 releases are shown.')
      ).toBeInTheDocument()
    );
  });

  it('shows no truncation helper text when every release fits in the fetch', async () => {
    vi.mocked(releaseService.list).mockResolvedValue({
      rows: [makeRelease(1), makeRelease(2)],
      total: 2,
    });

    renderDialog();

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    expect(screen.queryByText(/Only the first/)).not.toBeInTheDocument();
  });
});
