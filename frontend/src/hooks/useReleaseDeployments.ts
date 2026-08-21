import { deploymentService } from '../services/deploymentService';
import { useSharedList } from './useSharedList';
import type { Deployment } from '../types/deployment';

// A release's own deployments are bounded by the release's own structure
// (builds × environments), not a growth-bearing list — 500 is generous
// headroom, matching the shared-picker convention elsewhere (useAllSystems
// etc.), not a truncation risk in practice.
const LIMIT = 500;

/**
 * Deployments for one release, for `AddEvidenceDialog`'s "which deployment
 * does this evidence vouch for" picker.
 *
 * Keyed per release (unlike `useAllSystems`'s fixed key) so `useSharedList`
 * coalesces two consumers on the SAME release without confusing two
 * different releases' deployments — e.g. `GateEvidenceList` (resolving a
 * deployment_id it already has) and `AddEvidenceDialog` (offering the
 * picker) mounted together for the same gate share one request.
 */
export function useReleaseDeployments(releaseId: number): {
  deployments: Deployment[];
  loading: boolean;
  truncated: boolean;
} {
  const key = `release-deployments:${releaseId}`;
  // Deliberately defined inline, capturing releaseId — safe because `key`
  // changes exactly when releaseId does, so useSharedList's effect (keyed
  // on `key` alone) re-fires at the right time regardless of `load` being a
  // fresh closure each render. See useSharedList's own JSDoc: it is the
  // FIXED key that other callers rely on, not a ban on closing over a prop.
  const load = () => deploymentService.list({ release_id: releaseId, limit: LIMIT });
  const { rows, loading, truncated } = useSharedList<Deployment>(key, load);
  return { deployments: rows, loading, truncated };
}
