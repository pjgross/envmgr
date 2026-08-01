import api from './api';
import type {
  EnvironmentResponse,
  EnvironmentSystemResponse,
  EnvironmentSystemsResponse,
  EnvironmentSubsystemResponse,
  EnvironmentSubsystemUpdate,
  EnvironmentCreate,
  EnvironmentUpdate,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
  EnvironmentTopologyData,
} from '../types/environment';

export const environmentService = {
  listEnvironments: (params?: {
    status?: string;
    environment_type?: string;
    // Task 3 (pagination C3) widens this with offset/sort_by/sort_dir when
    // the service starts returning Paged<EnvironmentResponse>; `limit` is
    // added now so a picker can request an explicit window instead of
    // relying on the endpoint's implicit default.
    limit?: number;
  }): Promise<EnvironmentResponse[]> => api.get('/environments/', { params }).then((r) => r.data),

  getEnvironment: (id: number): Promise<EnvironmentResponse> =>
    api.get(`/environments/${id}`).then((r) => r.data),

  createEnvironment: (data: EnvironmentCreate): Promise<EnvironmentResponse> =>
    api.post('/environments/', data).then((r) => r.data),

  updateEnvironment: (id: number, data: EnvironmentUpdate): Promise<EnvironmentResponse> =>
    api.patch(`/environments/${id}`, data).then((r) => r.data),

  deleteEnvironment: (id: number): Promise<void> =>
    api.delete(`/environments/${id}`).then((r) => r.data),

  listSystemsInEnvironment: (envId: number): Promise<EnvironmentSystemsResponse> =>
    api.get(`/environments/${envId}/systems`).then((r) => r.data),

  addSystemToEnvironment: (
    envId: number,
    data: EnvironmentSystemCreate
  ): Promise<EnvironmentSystemResponse> =>
    api.post(`/environments/${envId}/systems`, data).then((r) => r.data),

  updateSystemInEnvironment: (
    envId: number,
    systemId: number,
    data: EnvironmentSystemUpdate
  ): Promise<EnvironmentSystemResponse> =>
    api.patch(`/environments/${envId}/systems/${systemId}`, data).then((r) => r.data),

  removeSystemFromEnvironment: (envId: number, systemId: number): Promise<void> =>
    api.delete(`/environments/${envId}/systems/${systemId}`).then((r) => r.data),

  listEnvironmentSubsystems: (envId: number): Promise<EnvironmentSubsystemResponse[]> =>
    api.get(`/environments/${envId}/subsystems`).then((r) => r.data),

  updateEnvironmentSubsystem: (
    envId: number,
    subsystemId: number,
    data: EnvironmentSubsystemUpdate
  ): Promise<EnvironmentSubsystemResponse> =>
    api.patch(`/environments/${envId}/subsystems/${subsystemId}`, data).then((r) => r.data),

  getEnvironmentTopology: (envId: number): Promise<EnvironmentTopologyData> =>
    api.get(`/environments/${envId}/topology`).then((r) => r.data),
};
