import api from './api';
import type {
  SystemDependencyResponse,
  SystemDependencyCreate,
  ComponentDependencyResponse,
  ComponentDependencyCreate,
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

  listComponentDependencies: (subsystemId: number): Promise<ComponentDependencyResponse[]> =>
    api.get(`/subsystems/${subsystemId}/dependencies`).then((r) => r.data),

  createComponentDependency: (
    subsystemId: number,
    data: ComponentDependencyCreate
  ): Promise<ComponentDependencyResponse> =>
    api.post(`/subsystems/${subsystemId}/dependencies`, data).then((r) => r.data),

  deleteComponentDependency: (subsystemId: number, depId: number): Promise<void> =>
    api.delete(`/subsystems/${subsystemId}/dependencies/${depId}`).then((r) => r.data),

  verifyEnvironment: (envId: number): Promise<VerifyResponse> =>
    api.get(`/environments/${envId}/verify`).then((r) => r.data),
};
