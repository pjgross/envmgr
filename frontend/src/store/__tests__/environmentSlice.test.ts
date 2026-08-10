import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import environmentReducer, {
  fetchEnvironment,
  createEnvironment,
  updateEnvironment,
} from '../environmentSlice';
import environmentRequestReducer, {
  updateEnvironmentHandover,
} from '../environmentRequestSlice';
import { environmentService } from '../../services/environmentService';
import { environmentRequestService } from '../../services/environmentRequestService';
import type { EnvironmentResponse } from '../../types/environment';

vi.mock('../../services/environmentService', () => ({
  environmentService: {
    getEnvironment: vi.fn(),
    createEnvironment: vi.fn(),
    updateEnvironment: vi.fn(),
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

  // Found by opening the page, not by any test: renaming an environment to
  // something the tenant's B2 naming pattern rejects returned a 422 whose
  // reason rendered as the literal string "[object Object]". Neither mutating
  // thunk used rejectWithValue, so `.unwrap()` threw RTK's plain serialized
  // object and both consumers' `err instanceof Error ? err.message : String(err)`
  // stringified it. Worse than the wrong-message form in CLAUDE.md: no message
  // at all.
  //
  // The rejection must be an AXIOS-SHAPED error. A plain Error carrying the
  // final text would pass while the app was broken — that is the whole trap
  // this pitfall records.
  describe('a refused save surfaces the server reason, not [object Object]', () => {
    const axios422 = () =>
      Object.assign(new Error('Request failed with status code 422'), {
        isAxiosError: true,
        response: {
          status: 422,
          data: {
            detail:
              "The name does not match this tenant's naming convention (for example: 'Mortgage_UAT')",
          },
        },
      });

    it('on update', async () => {
      vi.mocked(environmentService.updateEnvironment).mockRejectedValue(axios422());
      const store = makeStore();

      const result = await store.dispatch(
        updateEnvironment({ id: 5, data: { name: 'renamed badly' } })
      );

      expect(updateEnvironment.rejected.match(result)).toBe(true);
      // What EnvironmentDetail renders, via `.unwrap()` throwing this payload.
      expect(result.payload).toContain('naming convention');
      expect(String(result.payload)).not.toBe('[object Object]');
      expect(store.getState().environment.error).toContain('naming convention');
    });

    it('on create', async () => {
      vi.mocked(environmentService.createEnvironment).mockRejectedValue(axios422());
      const store = makeStore();

      const result = await store.dispatch(
        createEnvironment({
          name: 'nope',
          tier_id: 2,
          owner_user_id: 9,
          // Required on create — a null expiry is only legal on PATCH.
          expires_at: '2026-12-31T00:00:00Z',
        })
      );

      expect(createEnvironment.rejected.match(result)).toBe(true);
      expect(result.payload).toContain('naming convention');
      expect(String(result.payload)).not.toBe('[object Object]');
    });
  });
});
