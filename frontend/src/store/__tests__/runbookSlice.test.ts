import { describe, it, expect, vi, beforeEach } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { AxiosError, AxiosHeaders } from 'axios';
import runbookReducer, { fetchRunbook, transitionTask, createTask } from '../runbookSlice';
import { runbookService } from '../../services/runbookService';
import type { PlanState, RunbookRead } from '../../types/runbook';

vi.mock('../../services/runbookService', () => ({
  runbookService: {
    listForRelease: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    createTask: vi.fn(), updateTask: vi.fn(), removeTask: vi.fn(), setPredecessors: vi.fn(),
    transition: vi.fn(), events: vi.fn(),
  },
}));

const composite = (state: PlanState): RunbookRead => ({
  plan: { id: 5, release_id: 7, environment_id: 2, environment_name: 'prod', name: 'Cutover',
          anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: null, notes: null, state },
  planned_end: '2026-10-01T19:00:00Z', forecast_end: '2026-10-01T19:00:00Z', slip_minutes: 0, tasks: [],
});

function conflict(detail: string) {
  return new AxiosError('Request failed with status code 409', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 409, statusText: 'Conflict', headers: {}, config: { headers: new AxiosHeaders() }, data: { detail },
  });
}

const makeStore = () => configureStore({ reducer: { runbook: runbookReducer } });

describe('runbookSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores a fetched composite by plan id', async () => {
    vi.mocked(runbookService.get).mockResolvedValue(composite('not_started'));
    const store = makeStore();
    await store.dispatch(fetchRunbook(5));
    expect(store.getState().runbook.byPlan[5].plan.state).toBe('not_started');
  });

  it('a transition stores the composite the server returns', async () => {
    vi.mocked(runbookService.transition).mockResolvedValue(composite('in_progress'));
    const store = makeStore();
    await store.dispatch(transitionTask({ planId: 5, taskId: 9, body: { to_status: 'in_progress' } }));
    expect(store.getState().runbook.byPlan[5].plan.state).toBe('in_progress');
  });

  it('a refused transition rejects with the server detail, not the HTTP status', async () => {
    vi.mocked(runbookService.transition).mockRejectedValue(conflict("'Smoke' cannot start until these are done or skipped: Deploy API (not_started)"));
    const store = makeStore();
    const result = await store.dispatch(transitionTask({ planId: 5, taskId: 9, body: { to_status: 'in_progress' } }));
    expect(result.payload).toContain('Deploy API (not_started)');
    expect(result.payload).not.toContain('status code');
  });

  it('creating a task re-reads the composite', async () => {
    vi.mocked(runbookService.createTask).mockResolvedValue({ id: 11 } as never);
    vi.mocked(runbookService.get).mockResolvedValue(composite('not_started'));
    const store = makeStore();
    await store.dispatch(createTask({ planId: 5, body: { name: 'T', duration_minutes: 5 } }));
    expect(runbookService.get).toHaveBeenCalledWith(5);
    expect(store.getState().runbook.byPlan[5]).toBeDefined();
  });
});
