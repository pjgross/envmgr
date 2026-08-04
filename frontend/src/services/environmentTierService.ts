import api from './api';
import type {
  EnvironmentTierResponse,
  EnvironmentTierCreate,
  EnvironmentTierUpdate,
} from '../types/environmentTier';
import type { Paged } from '../types/pagination';

export const environmentTierService = {
  listTiers: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<EnvironmentTierResponse>> =>
    api.get<EnvironmentTierResponse[]>('/environment-tiers/', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  createTier: (data: EnvironmentTierCreate): Promise<EnvironmentTierResponse> =>
    api.post('/environment-tiers/', data).then((r) => r.data),

  updateTier: (
    id: number,
    data: EnvironmentTierUpdate
  ): Promise<EnvironmentTierResponse> =>
    api.patch(`/environment-tiers/${id}`, data).then((r) => r.data),

  deleteTier: (id: number): Promise<void> =>
    api.delete(`/environment-tiers/${id}`).then((r) => r.data),
};
