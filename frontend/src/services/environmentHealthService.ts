import api from './api';
import type { Paged } from '../types/pagination';
import type { EnvironmentHealthOverviewRow, HealthSample } from '../types/environmentHealth';

export const environmentHealthService = {
  /**
   * Both calls return the server's unwindowed total alongside the rows. Each
   * endpoint is capped — the overview at the shared 500, history at its own 50
   * — and a caller that drops the total cannot tell a complete answer from a
   * truncated one.
   */
  overview: (params: { limit?: number; offset?: number } = {}): Promise<Paged<EnvironmentHealthOverviewRow>> =>
    api.get('/environments/health', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  history: (envId: number, limit = 50): Promise<Paged<HealthSample>> =>
    api.get(`/environments/${envId}/health/history`, { params: { limit } }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
};
