import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import DeploymentList, { deploymentColumns } from '../DeploymentList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/deploymentService', () => ({
  deploymentService: {
    list: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { deploymentService } from '../../../services/deploymentService';

function renderDeploymentList(url = '/deployments') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <DeploymentList />
      </MemoryRouter>
    </Provider>
  );
}

function dispatchedParams() {
  const calls = vi.mocked(deploymentService.list).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('DeploymentList server-side grid', () => {
  it('sends paging, sorting and both filter params to the server', async () => {
    // The whole point of the conversion: filtering happens in SQL, not in a
    // useMemo over whatever page happened to arrive.
    renderDeploymentList('/deployments?page=1&sort_by=deployer_name&sort_dir=asc&environment_search=prod');

    await waitFor(() => expect(dispatchedParams()).toMatchObject({
      limit: 25,
      offset: 25,
      sort_by: 'deployer_name',
      sort_dir: 'asc',
      environment_search: 'prod',
    }));
  });

  it('marks joined and derived columns unsortable', () => {
    // GET /deployments whitelists status, deployer_name and deployed_at only.
    // A sortable header on anything else is a 422 the moment a user clicks it.
    const byField = Object.fromEntries(deploymentColumns.map((c) => [c.field, c]));

    expect(byField.status.sortable).not.toBe(false);
    expect(byField.deployer_name.sortable).not.toBe(false);
    expect(byField.deployed_at.sortable).not.toBe(false);

    expect(byField.environment_name.sortable).toBe(false);
    expect(byField.build_sha_short.sortable).toBe(false);
    expect(byField.release_name.sortable).toBe(false);
    expect(byField.change_request_title.sortable).toBe(false);
  });
});
