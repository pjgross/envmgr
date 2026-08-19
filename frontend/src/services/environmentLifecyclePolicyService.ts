import api from './api';
import type {
  EnvironmentLifecyclePolicy,
  EnvironmentLifecyclePolicyUpdate,
} from '../types/decommission';

const BASE = '/tenant/environment-lifecycle-policy';

export const environmentLifecyclePolicyService = {
  /**
   * Readable by any tenant member (`get_current_user`, not
   * `require_tenant_admin`) — same split as the naming policy: the settings
   * that decide whether an environment reads as idle have to be legible to
   * whoever owns it, not just to Admins.
   */
  get: (): Promise<EnvironmentLifecyclePolicy> => api.get(BASE).then((r) => r.data),

  /**
   * Takes the UPDATE shape, never the read shape. `EnvironmentLifecyclePolicyUpdate`
   * declares `extra="forbid"` — a caller that spreads the read model back
   * (or adds a stray key) gets a 422 on every save.
   */
  save: (data: EnvironmentLifecyclePolicyUpdate): Promise<EnvironmentLifecyclePolicy> =>
    api.put(BASE, data).then((r) => r.data),
};
