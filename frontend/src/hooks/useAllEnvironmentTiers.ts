import { environmentTierService } from '../services/environmentTierService';
import { useSharedList } from './useSharedList';
import type { EnvironmentTierResponse } from '../types/environmentTier';

// `GET /environment-tiers/` defaults to 500 server-side; asked for explicitly
// so the number a picker can see is visible at this call site.
const LIMIT = 500;

const load = () => environmentTierService.listTiers({ limit: LIMIT });

/**
 * Every tier, for a picker.
 *
 * NOT `state.environmentTier.tiers`: that is the admin panel's list, which may
 * not be loaded on an environment page at all. A picker reading a paged slice
 * silently offers a subset — the class of bug the pagination programme exists
 * to remove.
 */
export function useAllEnvironmentTiers(): {
  tiers: EnvironmentTierResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const { rows, loading, truncated } = useSharedList<EnvironmentTierResponse>(
    'environment-tiers',
    load
  );
  return { tiers: rows, loading, truncated };
}
