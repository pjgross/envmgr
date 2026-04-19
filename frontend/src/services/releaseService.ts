import api from './api';
import type {
  ReleaseResponse,
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
} from '../types/release';
import type { ReleaseEventResponse, ReleaseEventCreatePayload } from '../types/releaseEvent';
import type { ReleaseChangeResponse, ReleaseChangeCreatePayload, ReleaseChangeUpdatePayload } from '../types/releaseChange';
import type { BookingResponse } from '../types/booking';
import type { ChangeRequestResponse } from '../types/changeRequest';

export const releaseService = {
  // --- Release CRUD ---
  list: (filters: ReleaseListFilters = {}): Promise<ReleaseResponse[]> =>
    api.get('/releases', { params: filters }).then((r) => r.data),

  get: (id: number): Promise<ReleaseResponse> =>
    api.get(`/releases/${id}`).then((r) => r.data),

  create: (data: ReleaseCreatePayload): Promise<ReleaseResponse> =>
    api.post('/releases', data).then((r) => r.data),

  update: (id: number, data: ReleaseUpdatePayload): Promise<ReleaseResponse> =>
    api.patch(`/releases/${id}`, data).then((r) => r.data),

  remove: (id: number): Promise<void> =>
    api.delete(`/releases/${id}`).then(() => undefined),

  transition: (id: number, data: ReleaseTransitionPayload): Promise<ReleaseResponse> =>
    api.post(`/releases/${id}/transition`, data).then((r) => r.data),

  listHistory: (id: number): Promise<ReleaseStatusHistory[]> =>
    api.get(`/releases/${id}/history`).then((r) => r.data),

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

  updatePhase: (releaseId: number, phaseId: number, data: TestPhaseUpdatePayload): Promise<TestPhaseResponse> =>
    api.put(`/releases/${releaseId}/phases/${phaseId}`, data).then((r) => r.data),

  deletePhase: (releaseId: number, phaseId: number): Promise<void> =>
    api.delete(`/releases/${releaseId}/phases/${phaseId}`).then(() => undefined),

  // --- Gates ---
  listGates: (releaseId: number): Promise<ReleaseGateResponse[]> =>
    api.get(`/releases/${releaseId}/gates`).then((r) => r.data),

  createGate: (releaseId: number, data: ReleaseGateCreatePayload): Promise<ReleaseGateResponse> =>
    api.post(`/releases/${releaseId}/gates`, data).then((r) => r.data),

  updateGate: (releaseId: number, gateId: number, data: ReleaseGateUpdatePayload): Promise<ReleaseGateResponse> =>
    api.put(`/releases/${releaseId}/gates/${gateId}`, data).then((r) => r.data),

  passGate: (releaseId: number, gateId: number, data: ReleaseGateDecisionPayload = {}): Promise<ReleaseGateResponse> =>
    api.post(`/releases/${releaseId}/gates/${gateId}/pass`, data).then((r) => r.data),

  failGate: (releaseId: number, gateId: number, data: ReleaseGateDecisionPayload = {}): Promise<ReleaseGateResponse> =>
    api.post(`/releases/${releaseId}/gates/${gateId}/fail`, data).then((r) => r.data),

  overrideGate: (releaseId: number, gateId: number, data: ReleaseGateDecisionPayload = {}): Promise<ReleaseGateResponse> =>
    api.post(`/releases/${releaseId}/gates/${gateId}/override`, data).then((r) => r.data),

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

  // --- Bookings ---
  listBookings: (releaseId: number): Promise<BookingResponse[]> =>
    api.get(`/releases/${releaseId}/bookings`).then((r) => r.data),

  bookForPhase: (releaseId: number, data: ReleaseBookingCreatePayload): Promise<BookingResponse> =>
    api.post(`/releases/${releaseId}/bookings`, data).then((r) => r.data),

  // --- Linked Change Requests ---
  listLinkedChangeRequests: (releaseId: number): Promise<ChangeRequestResponse[]> =>
    api.get(`/releases/${releaseId}/change-requests`).then((r) => r.data),

  linkChangeRequest: (releaseId: number, crId: number): Promise<void> =>
    api.post(`/releases/${releaseId}/change-requests/${crId}/link`).then(() => undefined),

  unlinkChangeRequest: (releaseId: number, crId: number): Promise<void> =>
    api.delete(`/releases/${releaseId}/change-requests/${crId}/link`).then(() => undefined),
};
