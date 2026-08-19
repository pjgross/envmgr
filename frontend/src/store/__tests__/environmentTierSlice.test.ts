import { describe, expect, it } from 'vitest';
import reducer, { updateEnvironmentTier } from '../environmentTierSlice';
import type { EnvironmentTierResponse } from '../../types/environmentTier';

const tier = (
  id: number,
  display_order: number,
  overrides: Partial<EnvironmentTierResponse> = {}
): EnvironmentTierResponse => ({
  id,
  tenant_id: 1,
  name: `Tier ${id}`,
  description: null,
  category: null,
  color: null,
  display_order,
  is_active: true,
  created_at: '2026-08-04T00:00:00Z',
  updated_at: '2026-08-04T00:00:00Z',
  idle_threshold_days: null,
  ...overrides,
});

describe('environmentTierSlice', () => {
  it('re-sorts state.tiers by display_order after an update moves a tier', () => {
    // Dev(1)=10, SIT(2)=20, UAT(3)=30 — an edit that moves UAT to the front
    // (display_order 5) must be reflected in list order immediately, the
    // same as a create does, not just after the next full fetch.
    const initialState = {
      tiers: [tier(1, 10, { name: 'Dev' }), tier(2, 20, { name: 'SIT' }), tier(3, 30, { name: 'UAT' })],
      total: 3,
      loading: false,
      error: null,
    };

    const updated = tier(3, 5, { name: 'UAT' });
    const state = reducer(initialState, {
      type: updateEnvironmentTier.fulfilled.type,
      payload: updated,
    });

    expect(state.tiers.map((t) => t.id)).toEqual([3, 1, 2]);
  });
});
