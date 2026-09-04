import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store } from '../../../store';
import ReleaseDetail from '../ReleaseDetail';

// Same technique as releaseDetailTabs.test.tsx (the sibling for the
// `project`-kind branch): the real singleton store, only `releaseService.get`
// mocked. `release_kind: 'enterprise'` takes ReleaseDetail's OTHER branch —
// the one the whole-branch review found had been given none of the page
// shell, then (in a later re-review) found had a Delete button that opened
// no dialog because `{confirmDialog}` was never mounted in that branch. No
// prior test rendered ReleaseDetail with an enterprise release at all, which
// is exactly why that regression went unnoticed through a fix wave and a
// review — this file exists to close that gap.
vi.mock('../../../services/releaseService', async () => {
  const actual = await vi.importActual<typeof import('../../../services/releaseService')>(
    '../../../services/releaseService',
  );
  return { ...actual, releaseService: { ...actual.releaseService, get: vi.fn() } };
});

import { releaseService } from '../../../services/releaseService';

const ENTERPRISE_RELEASE = {
  id: 9,
  tenant_id: 1,
  name: 'Enterprise Release 1',
  description: null,
  release_type: 'standard',
  release_kind: 'enterprise' as const,
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

const renderAt = (search = '') =>
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/releases/9${search}`]}>
        <Routes>
          <Route path="/releases/:id" element={<ReleaseDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  );

describe('ReleaseDetail — enterprise release branch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(releaseService.get).mockResolvedValue(ENTERPRISE_RELEASE);
  });

  it('renders exactly one h1 carrying the release name', async () => {
    renderAt();
    const headings = await screen.findAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent('Enterprise Release 1');
  });

  it('renders the back link to /releases', async () => {
    renderAt();
    expect(await screen.findByRole('link', { name: 'Back to Releases' })).toHaveAttribute(
      'href',
      '/releases',
    );
  });

  it('clicking Delete opens the confirmation dialog', async () => {
    renderAt();
    await userEvent.click(await screen.findByTitle('Delete release'));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Delete release');
    expect(dialog).toHaveTextContent('Delete release "Enterprise Release 1"? This cannot be undone.');
  });
});
