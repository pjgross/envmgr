// frontend/src/services/buildService.ts
import api from './api';
import type { Build, BuildFilters } from '../types/build';

function toParams(filters: BuildFilters | undefined): Record<string, string | number> {
  if (!filters) return {};
  const out: Record<string, string | number> = {};
  if (filters.subsystem_id !== undefined) out.subsystem_id = filters.subsystem_id;
  if (filters.release_id !== undefined) out.release_id = filters.release_id;
  if (filters.branch) out.branch = filters.branch;
  if (filters.date_from) out.date_from = filters.date_from;
  if (filters.date_to) out.date_to = filters.date_to;
  if (filters.limit !== undefined) out.limit = filters.limit;
  if (filters.offset !== undefined) out.offset = filters.offset;
  return out;
}

export const buildService = {
  list: (filters?: BuildFilters): Promise<Build[]> =>
    api.get<Build[]>('/builds', { params: toParams(filters) }).then((r) => r.data),
  get: (id: number): Promise<Build> =>
    api.get<Build>(`/builds/${id}`).then((r) => r.data),
};
