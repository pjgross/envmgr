import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import ChangeRequestList, { changeRequestColumns } from '../ChangeRequestList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/changeRequestService', () => ({
  changeRequestService: {
    list: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

// Also unmocked-network-free: ChangeRequestList fetches environments and
// infrastructure components on mount to populate the filter dropdowns.
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    listEnvironments: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/infrastructureComponentService', () => ({
  infrastructureComponentService: {
    listComponents: vi.fn().mockResolvedValue([]),
  },
}));

import { changeRequestService } from '../../../services/changeRequestService';

function renderChangeRequestList(url = '/change-requests') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <ChangeRequestList />
      </MemoryRouter>
    </Provider>
  );
}

function lastListParams() {
  const calls = vi.mocked(changeRequestService.list).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('ChangeRequestList server-side grid', () => {
  it('sends paging, sorting and the collection filters as scalars', async () => {
    renderChangeRequestList('/change-requests?page=1&sort_by=title&sort_dir=asc&environment_id=4');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'title', sort_dir: 'asc', environment_id: '4',
    }));
  });

  it('marks id and computed columns unsortable', () => {
    // GET /change-requests whitelists title, change_type, status and
    // scheduled_start only. `id` is in no endpoint's whitelist.
    const byField = Object.fromEntries(changeRequestColumns.map((c) => [c.field, c]));

    ['title', 'change_type', 'status', 'scheduled_start']
      .forEach((f) => expect(byField[f].sortable).not.toBe(false));
    ['id', 'environments', 'hosts', 'has_outage']
      .forEach((f) => expect(byField[f].sortable).toBe(false));
  });
});
