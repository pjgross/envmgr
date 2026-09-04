import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import EnvironmentDetail from '../EnvironmentDetail';

// Regression coverage for the bug the coordinator's fix-request caught:
// EnvironmentDetail used to lazy-load `envSubsystems` only from the Tabs
// `onChange` click handler. That was sound before this task's URL-tab
// conversion — clicking was the only way to reach the Components tab — but
// once `?tab=components` became a legitimate entry point (a deep link, a
// bookmark, or a plain reload while on that tab), landing there directly
// rendered the Components grid with nothing loaded and no click to save it.
// A test that only ever clicks the tab (as EnvironmentDetailGovernanceForm's
// suite does for Overview) cannot see this — it must render straight at the
// URL and never dispatch a click.

const ENV = {
  id: 5,
  name: 'components-deep-link-env',
  description: null,
  tier_id: 3,
  tier_name: 'Production',
  tier_color: '#c62828',
  owner_user_id: 7,
  owner_username: 'alice',
  expires_at: null,
  reserved_now: false,
  idle: false,
  decommission_state: null,
  status: 'active' as const,
  tenant_id: 1,
  custom_fields: null,
  operations_group_id: null,
  operations_group_name: null,
  access_url: null,
  connection_notes: null,
  support_contact: null,
  sla_notes: null,
  known_limitations: null,
  decommission_notes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

// No HTTP — this is about whether the fetch fires for the right tab, not
// about what the server returns. Same mock surface as
// EnvironmentDetailGovernanceForm.test.tsx, the sibling that already
// exercises this page against the real singleton `store`.
vi.mock('../../../services/environmentService', () => ({
  environmentService: {
    getEnvironment: vi.fn(),
    listSystemsInEnvironment: vi.fn().mockResolvedValue({ systems: [], missing_systems: [] }),
    listEnvironmentSubsystems: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: { listDefinitions: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: { listSystems: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: { listTiers: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}));

vi.mock('../../../services/projectService', () => ({
  projectService: { listAgreementsForEnvironment: vi.fn().mockResolvedValue({ rows: [], total: 0 }) },
}));

vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    listGroupsForEnvironment: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
  },
}));

import { environmentService } from '../../../services/environmentService';

function renderAt(search: string) {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/environments/5${search}`]}>
        <Routes>
          <Route path="/environments/:id" element={<EnvironmentDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

describe('EnvironmentDetail — Components tab deep link loads subsystems', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(ENV);
    vi.mocked(environmentService.listSystemsInEnvironment).mockResolvedValue({
      systems: [],
      missing_systems: [],
    });
    vi.mocked(environmentService.listEnvironmentSubsystems).mockResolvedValue([]);
  });

  it('loads subsystems on landing directly at ?tab=components — no click involved', async () => {
    renderAt('?tab=components');

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Components' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );

    await waitFor(() =>
      expect(environmentService.listEnvironmentSubsystems).toHaveBeenCalledWith(5),
    );
  });

  it('does not load subsystems when the deep link names a different tab', async () => {
    renderAt('?tab=overview');

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );

    expect(environmentService.listEnvironmentSubsystems).not.toHaveBeenCalled();
  });

  it('loads subsystems exactly once when the tab is reached by a click, not twice', async () => {
    // Guards against a regression the other shape of this fix could
    // introduce: keying the load on `tab` in a `useEffect` must replace the
    // click-bound dispatch, not sit alongside it — one still-live call site
    // firing on click plus the tab-keyed effect firing on the resulting
    // state change would double the request every time a user clicks in
    // (rather than deep-links in).
    renderAt('');

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );
    expect(environmentService.listEnvironmentSubsystems).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('tab', { name: 'Components' }));

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Components' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );
    await waitFor(() =>
      expect(environmentService.listEnvironmentSubsystems).toHaveBeenCalledTimes(1),
    );
  });
});
