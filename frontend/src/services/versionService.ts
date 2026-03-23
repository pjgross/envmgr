import api from './api';
import type { VersionResponse, VersionCreate, ImportResult } from '../types/version';

export const versionService = {
  listVersions: (envId: number, currentOnly?: boolean): Promise<VersionResponse[]> =>
    api
      .get(`/environments/${envId}/versions`, {
        params: currentOnly !== undefined ? { current_only: currentOnly } : {},
      })
      .then((r) => r.data),

  recordVersion: (envId: number, data: VersionCreate): Promise<VersionResponse> =>
    api.post(`/environments/${envId}/versions`, data).then((r) => r.data),

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
