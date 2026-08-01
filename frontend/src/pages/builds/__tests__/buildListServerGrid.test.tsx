import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BuildList, { buildColumns } from '../BuildList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/buildService', () => ({
  buildService: {
    list: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { buildService } from '../../../services/buildService';

function renderBuildList(url = '/builds') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <BuildList />
      </MemoryRouter>
    </Provider>
  );
}

function dispatchedParams() {
  const calls = vi.mocked(buildService.list).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('BuildList server-side grid', () => {
  it('sends paging, sorting and the subsystem search to the server', async () => {
    renderBuildList('/builds?page=2&sort_by=git_branch&sort_dir=asc&subsystem_search=auth');

    await waitFor(() => expect(dispatchedParams()).toMatchObject({
      limit: 25,
      offset: 50,
      sort_by: 'git_branch',
      sort_dir: 'asc',
      subsystem_search: 'auth',
    }));
  });

  it('marks joined, derived and computed columns unsortable', () => {
    // GET /builds whitelists git_branch, build_number and commit_timestamp only.
    const byField = Object.fromEntries(buildColumns.map((c) => [c.field, c]));

    expect(byField.git_branch.sortable).not.toBe(false);
    expect(byField.build_number.sortable).not.toBe(false);
    expect(byField.commit_timestamp.sortable).not.toBe(false);

    expect(byField.subsystem_name.sortable).toBe(false);
    expect(byField.git_sha_short.sortable).toBe(false);
    expect(byField.release_name.sortable).toBe(false);
    expect(byField.latest_step.sortable).toBe(false);
  });

  it('explains why the computed column cannot be sorted', () => {
    // latest_step is derived in the browser from pipeline_steps. A header that
    // simply stops working reads as a bug; this one says why.
    const latestStep = buildColumns.find((c) => c.field === 'latest_step');
    expect(latestStep?.renderHeader).toBeDefined();
  });
});
