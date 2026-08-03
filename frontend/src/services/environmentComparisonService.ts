import api from './api';
import type { EnvironmentComparison } from '../types/environmentComparison';

export const environmentComparisonService = {
  /**
   * The response is symmetric — there is no `reference` parameter. Nominating
   * a reference environment is presentation, applied in the page.
   */
  compare: (left: number, right: number): Promise<EnvironmentComparison> =>
    api.get('/environments/compare', { params: { left, right } }).then((r) => r.data),
};
