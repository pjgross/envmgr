import api from './api';
import type {
  SystemDependencyResponse,
  SystemDependencyCreate,
  ComponentDependencyResponse,
  ComponentDependencyCreate,
  ComponentEndpointCreate,
  ComponentEndpointUpdate,
  VerifyResponse,
} from '../types/dependency';

export const dependencyService = {
  listSystemDependencies: (systemId: number): Promise<SystemDependencyResponse[]> =>
    api.get(`/systems/${systemId}/dependencies`).then((r) => r.data),

  createSystemDependency: (
    systemId: number,
    data: SystemDependencyCreate
  ): Promise<SystemDependencyResponse> =>
    api.post(`/systems/${systemId}/dependencies`, data).then((r) => r.data),

  deleteSystemDependency: (systemId: number, depId: number): Promise<void> =>
    api.delete(`/systems/${systemId}/dependencies/${depId}`).then((r) => r.data),

  updateSystemDependency: (
    systemId: number,
    depId: number,
    data: Partial<SystemDependencyCreate>
  ): Promise<SystemDependencyResponse> =>
    api.patch<SystemDependencyResponse>(`/systems/${systemId}/dependencies/${depId}`, data).then((r) => r.data),

  listComponentDependencies: (subsystemId: number): Promise<ComponentDependencyResponse[]> =>
    api.get(`/subsystems/${subsystemId}/dependencies`).then((r) => r.data),

  createComponentDependency: (
    subsystemId: number,
    data: ComponentDependencyCreate
  ): Promise<ComponentDependencyResponse> =>
    api.post(`/subsystems/${subsystemId}/dependencies`, data).then((r) => r.data),

  deleteComponentDependency: (subsystemId: number, depId: number): Promise<void> =>
    api.delete(`/subsystems/${subsystemId}/dependencies/${depId}`).then((r) => r.data),

  updateComponentDependency: (
    subsystemId: number,
    depId: number,
    data: Partial<ComponentDependencyCreate>
  ): Promise<ComponentDependencyResponse> =>
    api.patch<ComponentDependencyResponse>(`/subsystems/${subsystemId}/dependencies/${depId}`, data).then((r) => r.data),

  createComponentEndpoint: (
    subsystemId: number,
    depId: number,
    data: ComponentEndpointCreate
  ): Promise<ComponentDependencyResponse> =>
    api.post(`/subsystems/${subsystemId}/dependencies/${depId}/endpoints`, data).then((r) => r.data),

  updateComponentEndpoint: (
    subsystemId: number,
    depId: number,
    endpointId: number,
    data: ComponentEndpointUpdate
  ): Promise<ComponentDependencyResponse> =>
    api.patch(`/subsystems/${subsystemId}/dependencies/${depId}/endpoints/${endpointId}`, data).then((r) => r.data),

  deleteComponentEndpoint: (
    subsystemId: number,
    depId: number,
    endpointId: number
  ): Promise<ComponentDependencyResponse> =>
    api.delete(`/subsystems/${subsystemId}/dependencies/${depId}/endpoints/${endpointId}`).then((r) => r.data),

  verifyEnvironment: (envId: number): Promise<VerifyResponse> =>
    api.get(`/environments/${envId}/verify`).then((r) => r.data),
};
