import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import * as projectServiceModule from '../../../services/projectService';
import EnvironmentProjectsPanel from '../EnvironmentProjectsPanel';
import projectReducer from '../../../store/projectSlice';

// No `renderWithStore` helper exists in this codebase (checked before writing
// this test) — inlined the same way frontend/src/pages/admin/__tests__/
// userGroups.test.tsx and projects.test.tsx do.
vi.mock('../../../services/projectService', () => ({
  projectService: {
    listAgreementsForEnvironment: vi.fn(),
  },
}));

const { projectService } = projectServiceModule as unknown as {
  projectService: { listAgreementsForEnvironment: ReturnType<typeof vi.fn> };
};

const agreement = {
  id: 1,
  tenant_id: 1,
  project_id: 7,
  project_name: 'Mortgage Replatform',
  environment_id: 3,
  environment_name: 'UAT-1',
  starts_at: null,
  ends_at: null,
  notes: null,
  created_at: '2026-08-06T00:00:00Z',
};

function renderPanel() {
  const store = configureStore({
    reducer: {
      project: projectReducer,
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/environments/3']}>
        <EnvironmentProjectsPanel environmentId={3} />
      </MemoryRouter>
    </Provider>
  );
}

describe('EnvironmentProjectsPanel', () => {
  it('names projects from the response, never from a fetched list', async () => {
    // The name arrives ON the row. Resolving project_id against a separately
    // fetched, capped projects collection is the `.find()` failure
    // docs/pagination.md documents: a miss renders '—' and loses information.
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [agreement],
      total: 1,
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText('Mortgage Replatform')).toBeInTheDocument()
    );
  });

  it('says an agreement is a record and not a rule', async () => {
    // A1 records agreements and enforces nothing — no booking is refused, no
    // warning is raised. Without this line the first person to see the panel
    // will assume the opposite. Asserted so a later tidy-up cannot drop it.
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [agreement],
      total: 1,
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/not enforced/i)).toBeInTheDocument()
    );
  });

  it('shows an empty state rather than a bare table head', async () => {
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [],
      total: 0,
    });
    renderPanel();
    await waitFor(() => expect(screen.getByText(/no projects/i)).toBeInTheDocument());
  });

  it('shows a failed load rather than looking like an empty environment', async () => {
    // This thunk sets state.error but NO loading flag, so there is no skeleton
    // to fall back to — without the error branch a failed fetch renders the
    // empty state, and the page reads "no projects use this environment" when
    // the truth is "we could not find out". A blank page from a skeleton keyed
    // on a flag only the list thunk set is how this went wrong last time.
    vi.mocked(projectService.listAgreementsForEnvironment).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'Could not load usage agreements' } },
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/could not load usage agreements/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/no projects/i)).not.toBeInTheDocument();
  });
});
