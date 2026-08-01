import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import IncidentList, { incidentColumns } from '../IncidentList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/incidentService', () => ({
  incidentService: {
    list: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

// Also unmocked-network-free: IncidentList fetches lifecycle templates (for
// the status filter) and systems (for the system filter) on mount.
vi.mock('../../../services/bookingLifecycleService', () => ({
  bookingLifecycleService: {
    listTemplates: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { incidentService } from '../../../services/incidentService';

function renderIncidentList(url = '/incidents') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <IncidentList />
      </MemoryRouter>
    </Provider>
  );
}

function lastListParams() {
  const calls = vi.mocked(incidentService.list).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('IncidentList server-side grid', () => {
  it('sends paging, sorting and all three select filters', async () => {
    renderIncidentList('/incidents?page=1&sort_by=severity&sort_dir=asc&status=open&severity=P1&system_id=3');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'severity', sort_dir: 'asc',
      status: 'open', severity: 'P1', system_id: '3',
    }));
  });

  it('marks joined and computed columns unsortable', () => {
    // GET /incidents whitelists title, severity, status, detected_at,
    // resolved_at only.
    const byField = Object.fromEntries(incidentColumns.map((c) => [c.field, c]));

    ['title', 'severity', 'status', 'detected_at', 'resolved_at']
      .forEach((f) => expect(byField[f].sortable).not.toBe(false));
    ['system_name', 'environment_name', 'release_name', 'fix_release', 'pir_status']
      .forEach((f) => expect(byField[f].sortable).toBe(false));
  });
});
