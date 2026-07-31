import api from './api';
import type { Paged } from '../types/pagination';
import type {
  ReleaseResponse,
  ReleaseListItemResponse,
  ReleaseStatusHistory,
  ReleaseCreatePayload,
  ReleaseUpdatePayload,
  ReleaseTransitionPayload,
  ReleaseListFilters,
  TestPhaseResponse,
  TestPhaseCreatePayload,
  TestPhaseUpdatePayload,
  ReleaseGateResponse,
  ReleaseGateCreatePayload,
  ReleaseGateUpdatePayload,
  ReleaseGateDecisionPayload,
  ReleaseSystemResponse,
  ReleaseSystemCreatePayload,
  ReleaseDependencyResponse,
  ReleaseDependencyCreatePayload,
  ReleaseDependencyAlert,
  ReleaseCalendarEntry,
  ReleaseTimelineEntry,
  ReleaseBookingCreatePayload,
  ReleaseEnvironmentCoverageResponse,
  ReleaseBulkBookingPayload,
  BulkBookResultResponse,
  ScopeChurnAnalyticsResponse,
} from '../types/release';
import type {
  GateCriterion,
  GateCriterionWithGate,
  GateCriterionCreatePayload,
  GateCriterionUpdatePayload,
} from '../types/gateCriterion';
import type { ReleaseEventResponse, ReleaseEventCreatePayload } from '../types/releaseEvent';
import type {
  ReleaseChangeResponse,
  ReleaseChangeCreatePayload,
  ReleaseChangeUpdatePayload,
  ReleaseChangeMovePayload,
  ReleaseChangeReleaseHistoryResponse,
  ReleaseChangeStatusHistoryResponse,
  ScopeImportResult,
} from '../types/releaseChange';
import type { BookingResponse } from '../types/booking';
import type { ChangeRequestResponse } from '../types/changeRequest';

export const releaseService = {
  // --- Release CRUD ---
  list: (params: ReleaseListFilters = {}): Promise<Paged<ReleaseListItemResponse>> =>
    api.get('/releases', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  get: (id: number): Promise<ReleaseResponse> =>
    api.get(`/releases/${id}`).then((r) => r.data),

  create: (data: ReleaseCreatePayload): Promise<ReleaseResponse> =>
    api.post('/releases', data).then((r) => r.data),

  update: (id: number, data: ReleaseUpdatePayload): Promise<ReleaseResponse> =>
    api.put(`/releases/${id}`, data).then((r) => r.data),

  remove: (id: number): Promise<void> =>
    api.delete(`/releases/${id}`).then(() => undefined),

  transition: (id: number, data: ReleaseTransitionPayload): Promise<ReleaseResponse> =>
    api.post(`/releases/${id}/transition`, data).then((r) => r.data),

  listHistory: (id: number): Promise<ReleaseStatusHistory[]> =>
    api.get(`/releases/${id}/history`).then((r) => r.data),

  getLifecycle: (id: number): Promise<import('../types/bookingLifecycle').BookingLifecycleTemplate> =>
    api.get(`/releases/${id}/lifecycle`).then((r) => r.data),

  // --- Calendar / Timeline ---
  listCalendar: (from: string, to: string): Promise<ReleaseCalendarEntry[]> =>
    api.get('/releases/calendar', { params: { from, to } }).then((r) => r.data),

  listTimeline: (filters: ReleaseListFilters = {}): Promise<ReleaseTimelineEntry[]> =>
    api.get('/releases/timeline', { params: filters }).then((r) => r.data),

  // --- Test Phases ---
  listPhases: (releaseId: number): Promise<TestPhaseResponse[]> =>
    api.get(`/releases/${releaseId}/phases`).then((r) => r.data),

  createPhase: (releaseId: number, data: TestPhaseCreatePayload): Promise<TestPhaseResponse> =>
    api.post(`/releases/${releaseId}/phases`, data).then((r) => r.data),

  updatePhase: (_releaseId: number, phaseId: number, data: TestPhaseUpdatePayload): Promise<TestPhaseResponse> =>
    api.put(`/phases/${phaseId}`, data).then((r) => r.data),

  deletePhase: (_releaseId: number, phaseId: number): Promise<void> =>
    api.delete(`/phases/${phaseId}`).then(() => undefined),

  // --- Gates ---
  listGates: (releaseId: number): Promise<ReleaseGateResponse[]> =>
    api.get(`/releases/${releaseId}/gates`).then((r) => r.data),

  createGate: (releaseId: number, data: ReleaseGateCreatePayload): Promise<ReleaseGateResponse> =>
    api.post(`/releases/${releaseId}/gates`, data).then((r) => r.data),

  updateGate: (_releaseId: number, gateId: number, data: ReleaseGateUpdatePayload): Promise<ReleaseGateResponse> =>
    api.put(`/gates/${gateId}`, data).then((r) => r.data),

  deleteGate: (_releaseId: number, gateId: number): Promise<void> =>
    api.delete(`/gates/${gateId}`).then(() => undefined),

  passGate: (_releaseId: number, gateId: number, data: ReleaseGateDecisionPayload = {}): Promise<ReleaseGateResponse> =>
    api.post(`/gates/${gateId}/pass`, data).then((r) => r.data),

  failGate: (_releaseId: number, gateId: number, data: ReleaseGateDecisionPayload = {}): Promise<ReleaseGateResponse> =>
    api.post(`/gates/${gateId}/fail`, data).then((r) => r.data),

  overrideGate: (_releaseId: number, gateId: number, data: ReleaseGateDecisionPayload = {}): Promise<ReleaseGateResponse> =>
    api.post(`/gates/${gateId}/override`, data).then((r) => r.data),

  // --- Systems ---
  listSystems: (releaseId: number): Promise<ReleaseSystemResponse[]> =>
    api.get(`/releases/${releaseId}/systems`).then((r) => r.data),

  addSystem: (releaseId: number, data: ReleaseSystemCreatePayload): Promise<ReleaseSystemResponse> =>
    api.post(`/releases/${releaseId}/systems`, data).then((r) => r.data),

  removeSystem: (releaseSystemId: number): Promise<void> =>
    api.delete(`/release-systems/${releaseSystemId}`).then(() => undefined),

  // --- Dependencies ---
  listDependencies: (releaseId: number): Promise<ReleaseDependencyResponse[]> =>
    api.get(`/releases/${releaseId}/dependencies`).then((r) => r.data),

  addDependency: (releaseId: number, data: ReleaseDependencyCreatePayload): Promise<ReleaseDependencyResponse> =>
    api.post(`/releases/${releaseId}/dependencies`, data).then((r) => r.data),

  removeDependency: (releaseDependencyId: number): Promise<void> =>
    api.delete(`/release-dependencies/${releaseDependencyId}`).then(() => undefined),

  listDependencyAlerts: (releaseId: number): Promise<ReleaseDependencyAlert[]> =>
    api.get(`/releases/${releaseId}/dependency-alerts`).then((r) => r.data),

  acknowledgeAlert: (releaseId: number, dependencyId: number): Promise<void> =>
    api.post(`/releases/${releaseId}/dependency-alerts/${dependencyId}/acknowledge`).then(() => undefined),

  // --- Events ---
  listEvents: (releaseId: number): Promise<ReleaseEventResponse[]> =>
    api.get(`/releases/${releaseId}/events`).then((r) => r.data),

  createEvent: (releaseId: number, data: ReleaseEventCreatePayload): Promise<ReleaseEventResponse> =>
    api.post(`/releases/${releaseId}/events`, data).then((r) => r.data),

  // --- Changes (scope items) ---
  listChanges: (releaseId: number): Promise<ReleaseChangeResponse[]> =>
    api.get(`/releases/${releaseId}/changes`).then((r) => r.data),

  createChange: (releaseId: number, data: ReleaseChangeCreatePayload): Promise<ReleaseChangeResponse> =>
    api.post(`/releases/${releaseId}/changes`, data).then((r) => r.data),

  updateChange: (changeId: number, data: ReleaseChangeUpdatePayload): Promise<ReleaseChangeResponse> =>
    api.put(`/release-changes/${changeId}`, data).then((r) => r.data),

  deleteChange: (changeId: number): Promise<void> =>
    api.delete(`/release-changes/${changeId}`).then(() => undefined),

  moveReleaseChange: (changeId: number, payload: ReleaseChangeMovePayload): Promise<ReleaseChangeResponse> =>
    api.post(`/release-changes/${changeId}/move`, payload).then((r) => r.data),

  listBacklogChanges: (): Promise<ReleaseChangeResponse[]> =>
    api.get('/release-changes?backlog=true').then((r) => r.data),

  fetchReleaseChangeReleaseHistory: (changeId: number): Promise<ReleaseChangeReleaseHistoryResponse[]> =>
    api.get(`/release-changes/${changeId}/release-history`).then((r) => r.data),

  fetchReleaseChangeStatusHistory: (changeId: number): Promise<ReleaseChangeStatusHistoryResponse[]> =>
    api.get(`/release-changes/${changeId}/status-history`).then((r) => r.data),

  // --- Scope spreadsheet import ---
  importScope: (releaseId: number, file: File): Promise<ScopeImportResult> => {
    const formData = new FormData();
    formData.append('file', file);
    return api
      .post(`/releases/${releaseId}/scope/import`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data);
  },

  downloadScopeImportTemplate: async (): Promise<void> => {
    const response = await api.get('/releases/scope/import-template', {
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', 'scope-import-template.xlsx');
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  },

  // --- Bookings ---
  listBookings: (releaseId: number): Promise<BookingResponse[]> =>
    api.get(`/releases/${releaseId}/bookings`).then((r) => r.data),

  getEnvironmentCoverage: (releaseId: number): Promise<ReleaseEnvironmentCoverageResponse> =>
    api.get(`/releases/${releaseId}/environment-coverage`).then((r) => r.data),

  getScopeChurnAnalytics: (
    params: { date_from?: string; date_to?: string } = {}
  ): Promise<ScopeChurnAnalyticsResponse> =>
    api.get('/releases/scope-churn-analytics', { params }).then((r) => r.data),

  bookForPhase: (releaseId: number, data: ReleaseBookingCreatePayload): Promise<BookingResponse> =>
    api.post(`/releases/${releaseId}/bookings`, data).then((r) => r.data),

  bulkBookEnvironments: (releaseId: number, payload: ReleaseBulkBookingPayload): Promise<BulkBookResultResponse> =>
    api.post(`/releases/${releaseId}/bookings/bulk`, payload).then((r) => r.data),

  // --- Linked Change Requests ---
  listLinkedChangeRequests: (releaseId: number): Promise<ChangeRequestResponse[]> =>
    api.get(`/releases/${releaseId}/change-requests`).then((r) => r.data),

  linkChangeRequest: (releaseId: number, crId: number): Promise<void> =>
    api.post(`/releases/${releaseId}/change-requests/${crId}/link`).then(() => undefined),

  unlinkChangeRequest: (releaseId: number, crId: number): Promise<void> =>
    api.delete(`/releases/${releaseId}/change-requests/${crId}/link`).then(() => undefined),

  // --- Gate Criteria ---
  listCriteria: (releaseId: number, gateId: number): Promise<GateCriterion[]> =>
    api.get(`/releases/${releaseId}/gates/${gateId}/criteria`).then((r) => r.data),

  createCriterion: (releaseId: number, gateId: number, payload: GateCriterionCreatePayload): Promise<GateCriterion> =>
    api.post(`/releases/${releaseId}/gates/${gateId}/criteria`, payload).then((r) => r.data),

  updateCriterion: (criterionId: number, payload: GateCriterionUpdatePayload): Promise<GateCriterion> =>
    api.put(`/gate-criteria/${criterionId}`, payload).then((r) => r.data),

  completeCriterion: (criterionId: number): Promise<GateCriterion> =>
    api.post(`/gate-criteria/${criterionId}/complete`).then((r) => r.data),

  reopenCriterion: (criterionId: number): Promise<GateCriterion> =>
    api.post(`/gate-criteria/${criterionId}/reopen`).then((r) => r.data),

  deleteCriterion: (criterionId: number): Promise<void> =>
    api.delete(`/gate-criteria/${criterionId}`).then(() => undefined),

  listReleaseOverdueCriteria: (releaseId: number): Promise<GateCriterionWithGate[]> =>
    api.get(`/releases/${releaseId}/overdue-criteria`).then((r) => r.data),
};
