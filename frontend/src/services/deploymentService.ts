// frontend/src/services/deploymentService.ts
import api from './api';
import type { Paged } from '../types/pagination';
import type {
  Deployment,
  DeploymentFilters,
  DeploymentLinkChangeRequest,
} from '../types/deployment';

function toParams(filters: DeploymentFilters | undefined): Record<string, string | number> {
  if (!filters) return {};
  const out: Record<string, string | number> = {};
  if (filters.environment_id !== undefined) out.environment_id = filters.environment_id;
  if (filters.release_id !== undefined) out.release_id = filters.release_id;
  if (filters.build_id !== undefined) out.build_id = filters.build_id;
  if (filters.status) out.status = filters.status;
  if (filters.date_from) out.date_from = filters.date_from;
  if (filters.date_to) out.date_to = filters.date_to;
  if (filters.limit !== undefined) out.limit = filters.limit;
  if (filters.offset !== undefined) out.offset = filters.offset;
  if (filters.sort_by) out.sort_by = filters.sort_by;
  if (filters.sort_dir) out.sort_dir = filters.sort_dir;
  if (filters.environment_search) out.environment_search = filters.environment_search;
  if (filters.release_search) out.release_search = filters.release_search;
  return out;
}

export const deploymentService = {
  list: (filters?: DeploymentFilters): Promise<Paged<Deployment>> =>
    api.get<Deployment[]>('/deployments', { params: toParams(filters) }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
  get: (id: number): Promise<Deployment> =>
    api.get<Deployment>(`/deployments/${id}`).then((r) => r.data),
  linkChange: (id: number, data: DeploymentLinkChangeRequest): Promise<Deployment> =>
    api.post<Deployment>(`/deployments/${id}/link-change`, data).then((r) => r.data),
  forEnvironment: (envId: number): Promise<Deployment[]> =>
    api.get<Deployment[]>(`/environments/${envId}/deployments`).then((r) => r.data),
};
