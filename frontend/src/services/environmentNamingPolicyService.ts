import api from './api';
import type {
  EnvironmentNamingPolicy,
  EnvironmentNamingPolicyPreview,
  EnvironmentNamingPolicyUpdate,
} from '../types/environment';

const BASE = '/tenant/environment-naming-policy';

export interface NamingPolicyPreviewRequest {
  name_pattern?: string | null;
  required_attributes?: string[];
}

export const environmentNamingPolicyService = {
  /** Readable by any tenant member — the reason an environment is flagged has to be legible to whoever must fix it. */
  get: (): Promise<EnvironmentNamingPolicy> => api.get(BASE).then((r) => r.data),

  /**
   * Takes the update shape, never the read shape: the endpoint forbids extra
   * keys, so sending `effective_from` back is a 422.
   */
  save: (data: EnvironmentNamingPolicyUpdate): Promise<EnvironmentNamingPolicy> =>
    api.put(BASE, data).then((r) => r.data),

  /**
   * A POST because it carries a body, not because it changes anything — the
   * endpoint writes nothing. The regex is evaluated on the server, by the one
   * evaluator in the system; nothing here compiles a `RegExp`.
   */
  preview: (data: NamingPolicyPreviewRequest): Promise<EnvironmentNamingPolicyPreview> =>
    api.post(`${BASE}/preview`, data).then((r) => r.data),
};
