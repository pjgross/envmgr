import api from './api';
import type {
  EnvironmentSubSystemHostsResponse,
  HostAttachment,
  InfrastructureComponentCreate,
  InfrastructureComponentResponse,
  InfrastructureComponentSource,
  InfrastructureComponentType,
  InfrastructureComponentUpdate,
} from '../types/infrastructureComponent';

export const infrastructureComponentService = {
  listComponents: (params?: {
    component_type?: InfrastructureComponentType;
    provider?: string;
    region?: string;
    source?: InfrastructureComponentSource;
    search?: string;
  }): Promise<InfrastructureComponentResponse[]> =>
    api.get('/infrastructure-components/', { params }).then((r) => r.data),

  getComponent: (id: number): Promise<InfrastructureComponentResponse> =>
    api.get(`/infrastructure-components/${id}`).then((r) => r.data),

  createComponent: (
    data: InfrastructureComponentCreate
  ): Promise<InfrastructureComponentResponse> =>
    api.post('/infrastructure-components/', data).then((r) => r.data),

  updateComponent: (
    id: number,
    data: InfrastructureComponentUpdate
  ): Promise<InfrastructureComponentResponse> =>
    api.patch(`/infrastructure-components/${id}`, data).then((r) => r.data),

  deleteComponent: (id: number): Promise<void> =>
    api.delete(`/infrastructure-components/${id}`).then((r) => r.data),

  listEnvSubsystemHosts: (
    envId: number,
    subsystemId: number
  ): Promise<EnvironmentSubSystemHostsResponse> =>
    api
      .get(`/environments/${envId}/subsystems/${subsystemId}/hosts`)
      .then((r) => r.data),

  setEnvSubsystemHosts: (
    envId: number,
    subsystemId: number,
    attachments: HostAttachment[]
  ): Promise<EnvironmentSubSystemHostsResponse> =>
    api
      .put(`/environments/${envId}/subsystems/${subsystemId}/hosts`, attachments)
      .then((r) => r.data),
};
