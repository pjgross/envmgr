import api from './api';
import type { VersionResponse, VersionCreate, VersionUpdate, ImportResult } from '../types/version';

export const versionService = {
  listVersions: (envId: number, currentOnly?: boolean): Promise<VersionResponse[]> =>
    api
      .get(`/environments/${envId}/versions`, {
        params: currentOnly !== undefined ? { current_only: currentOnly } : {},
      })
      .then((r) => r.data),

  recordVersion: (envId: number, data: VersionCreate): Promise<VersionResponse> =>
    api.post(`/environments/${envId}/versions`, data).then((r) => r.data),

  updateVersion: (envId: number, versionId: number, data: VersionUpdate): Promise<VersionResponse> =>
    api.patch(`/environments/${envId}/versions/${versionId}`, data).then((r) => r.data),

  deleteVersion: (envId: number, versionId: number): Promise<void> =>
    api.delete(`/environments/${envId}/versions/${versionId}`).then((r) => r.data),

  importEnvironments: (file: File): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    return api
      .post('/import/environments', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data);
  },

  importSystems: (file: File): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    return api
      .post('/import/systems', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data);
  },
};
