// frontend/src/services/buildService.ts
import api from './api';
import type { Paged } from '../types/pagination';
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
  if (filters.sort_by) out.sort_by = filters.sort_by;
  if (filters.sort_dir) out.sort_dir = filters.sort_dir;
  if (filters.subsystem_search) out.subsystem_search = filters.subsystem_search;
  return out;
}

export const buildService = {
  list: (filters?: BuildFilters): Promise<Paged<Build>> =>
    api.get<Build[]>('/builds', { params: toParams(filters) }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
  get: (id: number): Promise<Build> =>
    api.get<Build>(`/builds/${id}`).then((r) => r.data),
};
