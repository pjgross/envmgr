import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import environmentReducer, { fetchEnvironment } from '../environmentSlice';
import environmentRequestReducer, {
  updateEnvironmentHandover,
} from '../environmentRequestSlice';
import { environmentService } from '../../services/environmentService';
import { environmentRequestService } from '../../services/environmentRequestService';
import type { EnvironmentResponse } from '../../types/environment';

vi.mock('../../services/environmentService', () => ({
  environmentService: {
    getEnvironment: vi.fn(),
  },
}));

vi.mock('../../services/environmentRequestService', () => ({
  environmentRequestService: {
    updateHandover: vi.fn(),
  },
}));

const ENVIRONMENT: EnvironmentResponse = {
  id: 5,
  name: 'Mortgage SIT',
  description: null,
  tier_id: 2,
  tier_name: 'SIT',
  tier_color: null,
  owner_user_id: 9,
  owner_username: 'owner',
  expires_at: null,
  reserved_now: false,
  status: 'active',
  tenant_id: 1,
  custom_fields: null,
  operations_group_id: 7,
  operations_group_name: 'Platform Ops',
  access_url: null,
  connection_notes: null,
  support_contact: null,
  sla_notes: null,
  known_limitations: null,
  decommission_notes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function makeStore() {
  return configureStore({
    reducer: { environment: environmentReducer, environmentRequest: environmentRequestReducer },
  });
}

describe('environmentSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  // Minor fix: updateEnvironmentHandover (dispatched by HandoverSection) had
  // no reducer case in environmentSlice at all, so EnvironmentDetail's
  // `currentEnvironment` stayed stale after a handover save until the page
  // was fully re-navigated to.
  it('refreshes currentEnvironment after a handover save', async () => {
    vi.mocked(environmentService.getEnvironment).mockResolvedValue(ENVIRONMENT);
    vi.mocked(environmentRequestService.updateHandover).mockResolvedValue({
      ...ENVIRONMENT,
      connection_notes: 'VPN then RDP to the app server',
    });

    const store = makeStore();
    await store.dispatch(fetchEnvironment(5));
    expect(store.getState().environment.currentEnvironment?.connection_notes).toBeNull();

    await store.dispatch(
      updateEnvironmentHandover({
        environmentId: 5,
        data: { connection_notes: 'VPN then RDP to the app server' },
      })
    );

    expect(store.getState().environment.currentEnvironment?.connection_notes).toBe(
      'VPN then RDP to the app server'
    );
  });
});
