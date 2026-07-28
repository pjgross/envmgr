import api from './api';
import type { EnvironmentHealthOverviewRow, HealthSample } from '../types/environmentHealth';

export const environmentHealthService = {
  overview: () => api.get<EnvironmentHealthOverviewRow[]>('/environments/health').then((r) => r.data),
  history: (envId: number, limit = 50) =>
    api.get<HealthSample[]>(`/environments/${envId}/health/history`, { params: { limit } }).then((r) => r.data),
};
