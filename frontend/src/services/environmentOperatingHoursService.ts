import api from './api';
import type {
  OperatingHoursConfig,
  OperatingHoursConfigInput,
  EnvironmentUtilization,
  UtilizationOverview,
  UtilizationParams,
} from '../types/environmentOperatingHours';

export const environmentOperatingHoursService = {
  getConfig: (envId: number) =>
    api.get<OperatingHoursConfig>(`/environments/${envId}/operating-hours`).then((r) => r.data),
  putConfig: (envId: number, cfg: OperatingHoursConfigInput) =>
    api.put<OperatingHoursConfig>(`/environments/${envId}/operating-hours`, cfg).then((r) => r.data),
  utilization: (envId: number, params: UtilizationParams) =>
    api.get<EnvironmentUtilization>(`/environments/${envId}/utilization`, { params }).then((r) => r.data),
  overview: (params: UtilizationParams) =>
    api.get<UtilizationOverview>('/metrics/environments/utilization', { params }).then((r) => r.data),
};
