import api from './api';
import type {
  RaidItemResponse,
  RaidItemCreatePayload,
  RaidItemUpdatePayload,
  RaidListFilters,
  RaidLinksResponse,
  RaidSummaryResponse,
  RaidRollupResponse,
  RaidItemType,
  RaidRelation,
  RaidConfig,
  RaidConfigUpdatePayload,
} from '../types/raid';

export const raidService = {
  // --- Items ---
  list: (releaseId: number, filters: RaidListFilters = {}): Promise<RaidItemResponse[]> =>
    api.get(`/releases/${releaseId}/raid`, { params: filters }).then((r) => r.data),

  get: (releaseId: number, itemId: number): Promise<RaidItemResponse> =>
    api.get(`/releases/${releaseId}/raid/${itemId}`).then((r) => r.data),

  create: (releaseId: number, data: RaidItemCreatePayload): Promise<RaidItemResponse> =>
    api.post(`/releases/${releaseId}/raid`, data).then((r) => r.data),

  update: (releaseId: number, itemId: number, data: RaidItemUpdatePayload): Promise<RaidItemResponse> =>
    api.patch(`/releases/${releaseId}/raid/${itemId}`, data).then((r) => r.data),

  remove: (releaseId: number, itemId: number): Promise<void> =>
    api.delete(`/releases/${releaseId}/raid/${itemId}`).then(() => undefined),

  promote: (releaseId: number, itemId: number, targetType: RaidItemType): Promise<RaidItemResponse> =>
    api
      .post(`/releases/${releaseId}/raid/${itemId}/promote`, { target_type: targetType })
      .then((r) => r.data),

  // --- Links (scope + relations) ---
  getLinks: (releaseId: number, itemId: number): Promise<RaidLinksResponse> =>
    api.get(`/releases/${releaseId}/raid/${itemId}/links`).then((r) => r.data),

  addScopeLink: (releaseId: number, itemId: number, releaseChangeId: number): Promise<RaidLinksResponse> =>
    api
      .post(`/releases/${releaseId}/raid/${itemId}/scope-links`, { release_change_id: releaseChangeId })
      .then((r) => r.data),

  removeScopeLink: (releaseId: number, itemId: number, releaseChangeId: number): Promise<void> =>
    api
      .delete(`/releases/${releaseId}/raid/${itemId}/scope-links/${releaseChangeId}`)
      .then(() => undefined),

  addRelation: (
    releaseId: number,
    itemId: number,
    toItemId: number,
    relation: RaidRelation,
  ): Promise<RaidLinksResponse> =>
    api
      .post(`/releases/${releaseId}/raid/${itemId}/relations`, { to_item_id: toItemId, relation })
      .then((r) => r.data),

  removeRelation: (
    releaseId: number,
    itemId: number,
    toItemId: number,
    relation: RaidRelation,
  ): Promise<void> =>
    api
      .delete(`/releases/${releaseId}/raid/${itemId}/relations`, {
        params: { to_item_id: toItemId, relation },
      })
      .then(() => undefined),

  // --- Summary / rollup ---
  summary: (releaseId: number): Promise<RaidSummaryResponse> =>
    api.get(`/releases/${releaseId}/raid/summary`).then((r) => r.data),

  rollup: (enterpriseId: number): Promise<RaidRollupResponse> =>
    api.get(`/releases/${enterpriseId}/rollup/raid`).then((r) => r.data),

  // --- Tenant config ---
  getConfig: (): Promise<RaidConfig> =>
    api.get('/tenant/raid-config').then((r) => r.data),

  updateConfig: (data: RaidConfigUpdatePayload): Promise<RaidConfig> =>
    api.put('/tenant/raid-config', data).then((r) => r.data),
};
