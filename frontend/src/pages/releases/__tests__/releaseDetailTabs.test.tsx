import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store } from '../../../store';
import ReleaseDetail from '../ReleaseDetail';

// The real singleton store (see environmentDetailComponentsDeepLink.test.tsx
// for the sibling precedent), not a hand-assembled reducer map: ReleaseDetail's
// default "Main" panel and the RAID panel each reach several slices deep
// (auth, customField, raid, tenantAdmin, …) via nested components, and a
// duplicated copy of store/index.ts's reducer object would silently drift
// from the real app shape the moment a slice is added there and not here.
// Only `releaseService.get` is mocked, so `fetchRelease` runs for real
// through the real reducer and produces `release.detail` the same way the
// app does. Every OTHER thunk these nested tabs dispatch on mount
// (fetchDependencyAlerts, fetchRaidItems, fetchUsers, …) is left real too —
// their services hit relative URLs with no server behind them in this test,
// which reject asynchronously and are absorbed by each thunk's own
// rejected-action handling, the same way ReadinessBanner's direct axios call
// degrades to "nothing to show" rather than throwing.
vi.mock('../../../services/releaseService', async () => {
  const actual = await vi.importActual<typeof import('../../../services/releaseService')>(
    '../../../services/releaseService',
  );
  return { ...actual, releaseService: { ...actual.releaseService, get: vi.fn() } };
});

import { releaseService } from '../../../services/releaseService';

const RELEASE = {
  id: 7,
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
  status: 'draft',
  target_date: null,
  actual_date: null,
  scope_deadline: null,
  custom_fields: null,
  raised_by: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

// Full URL, not just the rendered tab: a `useState` fallback would also leave
// the clicked tab `aria-selected`, since MUI's own state still updates — only
// the URL tells "the tab changed" apart from "the tab is also in the URL".
function Path() {
  const location = useLocation();
  return <div data-testid="path">{location.pathname + location.search}</div>;
}

const renderAt = (search: string) =>
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/releases/7${search}`]}>
        <Routes>
          <Route path="/releases/:id" element={<><ReleaseDetail /><Path /></>} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  );

describe('ReleaseDetail — the tab is in the URL', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(releaseService.get).mockResolvedValue(RELEASE);
  });

  it('opens the tab named by ?tab=', async () => {
    renderAt('?tab=rollback');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Rollback' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when no tab is named', async () => {
    renderAt('');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when ?tab= names a tab that no longer exists', async () => {
    renderAt('?tab=gone');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('puts the tab in the URL when one is clicked', async () => {
    renderAt('');
    await userEvent.click(await screen.findByRole('tab', { name: 'RAID' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'RAID' })).toHaveAttribute('aria-selected', 'true'),
    );
    expect(screen.getByTestId('path')).toHaveTextContent('/releases/7?tab=raid');
  });
});
