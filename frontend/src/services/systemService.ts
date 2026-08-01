import api from './api';
import type {
  SystemResponse,
  SubSystemResponse,
  SystemCreate,
  SystemUpdate,
  SubSystemCreate,
  SubSystemUpdate,
} from '../types/system';

export const systemService = {
  // `limit` is optional and unused by any caller yet except `useAllSystems`
  // (SystemCatalog itself is not converted to server-side paging until Task 3
  // of the C3 rollout, which is also when this gains `offset`/`search`/sort
  // params and a `Paged<SystemResponse>` return). Widened now, rather than
  // left bare, so a picker asking for "every system" states the number it
  // asked for instead of silently trusting the backend's default.
  listSystems: (params?: { limit?: number }): Promise<SystemResponse[]> =>
    api.get('/systems/', { params }).then((r) => r.data),

  getSystem: (id: number): Promise<SystemResponse> => api.get(`/systems/${id}`).then((r) => r.data),

  createSystem: (data: SystemCreate): Promise<SystemResponse> =>
    api.post('/systems/', data).then((r) => r.data),

  updateSystem: (id: number, data: SystemUpdate): Promise<SystemResponse> =>
    api.patch(`/systems/${id}`, data).then((r) => r.data),

  deleteSystem: (id: number): Promise<void> => api.delete(`/systems/${id}`).then((r) => r.data),

  listSubSystems: (systemId: number): Promise<SubSystemResponse[]> =>
    api.get(`/systems/${systemId}/subsystems`).then((r) => r.data),

  getSubSystem: (systemId: number, subId: number): Promise<SubSystemResponse> =>
    api.get(`/systems/${systemId}/subsystems/${subId}`).then((r) => r.data),

  createSubSystem: (systemId: number, data: SubSystemCreate): Promise<SubSystemResponse> =>
    api.post(`/systems/${systemId}/subsystems`, data).then((r) => r.data),

  updateSubSystem: (
    systemId: number,
    subId: number,
    data: SubSystemUpdate
  ): Promise<SubSystemResponse> =>
    api.patch(`/systems/${systemId}/subsystems/${subId}`, data).then((r) => r.data),

  deleteSubSystem: (systemId: number, subId: number): Promise<void> =>
    api.delete(`/systems/${systemId}/subsystems/${subId}`).then((r) => r.data),
};
