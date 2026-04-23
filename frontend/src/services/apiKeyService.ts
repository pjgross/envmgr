// frontend/src/services/apiKeyService.ts
import api from './api';
import type { ApiKey, ApiKeyCreatePayload, ApiKeyCreated } from '../types/apiKey';

export const apiKeyService = {
  list: (): Promise<ApiKey[]> =>
    api.get<ApiKey[]>('/api-keys').then((r) => r.data),
  create: (data: ApiKeyCreatePayload): Promise<ApiKeyCreated> =>
    api.post<ApiKeyCreated>('/api-keys', data).then((r) => r.data),
  revoke: (id: number): Promise<void> =>
    api.delete(`/api-keys/${id}`).then(() => undefined),
};
