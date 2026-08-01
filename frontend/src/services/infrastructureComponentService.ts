import api from './api';
import type {
  EnvironmentSubSystemHostsResponse,
  HostAttachment,
  HostImpactResponse,
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
    limit?: number;
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

  hostImpact: (hostIds: number[]): Promise<HostImpactResponse> => {
    if (hostIds.length === 0) {
      return Promise.resolve({ host_ids: [], environments: [] });
    }
    // Axios serialises array params as `host_ids=1&host_ids=2` with repeat serialiser
    return api
      .get('/infrastructure-components/impact', {
        params: { host_ids: hostIds },
        paramsSerializer: { indexes: null },
      })
      .then((r) => r.data);
  },
};
