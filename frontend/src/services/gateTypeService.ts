import api from './api';
import type { GateTypeResponse, GateTypeCreate, GateTypeUpdate } from '../types/gateType';
import type { Paged } from '../types/pagination';

// No trailing slash: the router registers list at "" under the
// /api/v1/gate-types prefix (app/main.py), unlike /environment-tiers/.
export const gateTypeService = {
  listGateTypes: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    include_inactive?: boolean;
  }): Promise<Paged<GateTypeResponse>> =>
    api.get<GateTypeResponse[]>('/gate-types', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  createGateType: (data: GateTypeCreate): Promise<GateTypeResponse> =>
    api.post('/gate-types', data).then((r) => r.data),

  updateGateType: (id: number, data: GateTypeUpdate): Promise<GateTypeResponse> =>
    api.put(`/gate-types/${id}`, data).then((r) => r.data),

  deleteGateType: (id: number): Promise<void> =>
    api.delete(`/gate-types/${id}`).then((r) => r.data),
};
