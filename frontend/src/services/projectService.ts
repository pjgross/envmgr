import api from './api';
import type {
  ProjectCreate,
  ProjectResponse,
  ProjectUpdate,
  UsageAgreementCreate,
  UsageAgreementResponse,
} from '../types/project';
import type { Paged } from '../types/pagination';

export const projectService = {
  listProjects: (params?: {
    search?: string;
    is_active?: boolean;
    limit?: number;
    offset?: number;
    sort_by?: 'name' | 'code' | 'created_at';
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<ProjectResponse>> =>
    api.get<ProjectResponse[]>('/projects', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  getProject: (id: number): Promise<ProjectResponse> =>
    api.get(`/projects/${id}`).then((r) => r.data),

  createProject: (data: ProjectCreate): Promise<ProjectResponse> =>
    api.post('/projects', data).then((r) => r.data),

  updateProject: (id: number, data: ProjectUpdate): Promise<ProjectResponse> =>
    api.patch(`/projects/${id}`, data).then((r) => r.data),

  deleteProject: (id: number): Promise<void> =>
    api.delete(`/projects/${id}`).then((r) => r.data),

  listAgreementsForProject: (
    projectId: number,
    params?: { limit?: number; offset?: number }
  ): Promise<Paged<UsageAgreementResponse>> =>
    api
      .get<UsageAgreementResponse[]>(`/projects/${projectId}/usage-agreements`, { params })
      .then((r) => ({
        rows: r.data,
        total: Number(r.headers['x-total-count'] ?? r.data.length),
      })),

  listAgreementsForEnvironment: (
    environmentId: number,
    params?: { limit?: number; offset?: number }
  ): Promise<Paged<UsageAgreementResponse>> =>
    api
      .get<UsageAgreementResponse[]>(`/environments/${environmentId}/usage-agreements`, {
        params,
      })
      .then((r) => ({
        rows: r.data,
        total: Number(r.headers['x-total-count'] ?? r.data.length),
      })),

  createAgreement: (
    projectId: number,
    data: UsageAgreementCreate
  ): Promise<UsageAgreementResponse> =>
    api.post(`/projects/${projectId}/usage-agreements`, data).then((r) => r.data),

  deleteAgreement: (projectId: number, agreementId: number): Promise<void> =>
    api.delete(`/projects/${projectId}/usage-agreements/${agreementId}`).then((r) => r.data),
};
