import api from './api';
import type {
  EnvironmentResponse,
  EnvironmentSystemResponse,
  EnvironmentCreate,
  EnvironmentUpdate,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
} from '../types/environment';

export const environmentService = {
  listEnvironments: (params?: { status?: string; environment_type?: string }): Promise<EnvironmentResponse[]> =>
    api.get('/environments/', { params }).then((r) => r.data),

  getEnvironment: (id: number): Promise<EnvironmentResponse> =>
    api.get(`/environments/${id}`).then((r) => r.data),

  createEnvironment: (data: EnvironmentCreate): Promise<EnvironmentResponse> =>
    api.post('/environments/', data).then((r) => r.data),

  updateEnvironment: (id: number, data: EnvironmentUpdate): Promise<EnvironmentResponse> =>
    api.patch(`/environments/${id}`, data).then((r) => r.data),

  deleteEnvironment: (id: number): Promise<void> =>
    api.delete(`/environments/${id}`).then((r) => r.data),

  listSystemsInEnvironment: (envId: number): Promise<EnvironmentSystemResponse[]> =>
    api.get(`/environments/${envId}/systems`).then((r) => r.data),

  addSystemToEnvironment: (envId: number, data: EnvironmentSystemCreate): Promise<EnvironmentSystemResponse> =>
    api.post(`/environments/${envId}/systems`, data).then((r) => r.data),

  updateSystemInEnvironment: (
    envId: number,
    systemId: number,
    data: EnvironmentSystemUpdate
  ): Promise<EnvironmentSystemResponse> =>
    api.patch(`/environments/${envId}/systems/${systemId}`, data).then((r) => r.data),

  removeSystemFromEnvironment: (envId: number, systemId: number): Promise<void> =>
    api.delete(`/environments/${envId}/systems/${systemId}`).then((r) => r.data),
};
