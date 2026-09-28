import api from './api';
import type {
  RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead, RunbookTaskCreate,
  RunbookTaskEventRead, RunbookTaskRead, RunbookTaskUpdate, TransitionRequest,
} from '../types/runbook';

export const runbookService = {
  listForRelease: (releaseId: number): Promise<RunbookPlanRead[]> =>
    api.get(`/releases/${releaseId}/runbooks`, { params: { limit: 100 } }).then((r) => r.data),
  get: (planId: number): Promise<RunbookRead> => api.get(`/runbooks/${planId}`).then((r) => r.data),
  create: (releaseId: number, body: RunbookPlanCreate): Promise<RunbookRead> =>
    api.post(`/releases/${releaseId}/runbooks`, body).then((r) => r.data),
  update: (planId: number, body: RunbookPlanUpdate): Promise<RunbookRead> =>
    api.patch(`/runbooks/${planId}`, body).then((r) => r.data),
  remove: (planId: number): Promise<void> => api.delete(`/runbooks/${planId}`).then(() => undefined),
  createTask: (planId: number, body: RunbookTaskCreate): Promise<RunbookTaskRead> =>
    api.post(`/runbooks/${planId}/tasks`, body).then((r) => r.data),
  updateTask: (taskId: number, body: RunbookTaskUpdate): Promise<RunbookRead> =>
    api.patch(`/runbook-tasks/${taskId}`, body).then((r) => r.data),
  removeTask: (taskId: number): Promise<void> => api.delete(`/runbook-tasks/${taskId}`).then(() => undefined),
  setPredecessors: (taskId: number, ids: number[]): Promise<RunbookRead> =>
    api.put(`/runbook-tasks/${taskId}/predecessors`, { predecessor_ids: ids }).then((r) => r.data),
  transition: (taskId: number, body: TransitionRequest): Promise<RunbookRead> =>
    api.post(`/runbook-tasks/${taskId}/transition`, body).then((r) => r.data),
  events: (taskId: number): Promise<RunbookTaskEventRead[]> =>
    api.get(`/runbook-tasks/${taskId}/events`, { params: { limit: 100 } }).then((r) => r.data),
};
