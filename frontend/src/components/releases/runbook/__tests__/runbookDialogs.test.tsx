import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import runbookReducer from '../../../../store/runbookSlice';
import { runbookService } from '../../../../services/runbookService';
import type { RunbookRead, RunbookTaskRead } from '../../../../types/runbook';
import RunbookTaskDialog from '../RunbookTaskDialog';
import RunbookTransitionDialog from '../RunbookTransitionDialog';
import RunbookPlanDialog from '../RunbookPlanDialog';

vi.mock('../../../../services/runbookService', () => ({
  runbookService: { get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), createTask: vi.fn(),
                    updateTask: vi.fn(), setPredecessors: vi.fn(), removeTask: vi.fn(), transition: vi.fn() },
}));
vi.mock('../../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: () => ({ environments: [{ id: 2, name: 'prod' }], loading: false, truncated: false }),
}));
vi.mock('../../../../services/userGroupService', () => ({
  userGroupService: { listGroups: vi.fn().mockResolvedValue({ rows: [{ id: 3, name: 'Payments' }], total: 1 }) },
}));
vi.mock('../../../../services/releaseService', () => ({
  releaseService: { listSystems: vi.fn().mockResolvedValue([{ id: 1, system_id: 4, system_name: 'Payments API', role: 'changing' }]) },
}));

const t = (id: number, name: string, over: Partial<RunbookTaskRead> = {}): RunbookTaskRead => ({
  id, name, description: null, kind: 'task', team_group_id: null, team_name: null, system_id: null, system_name: null,
  system_on_release: true, duration_minutes: 30, fixed_start_at: null, status: 'not_started', actual_started_at: null,
  actual_finished_at: null, sort_order: 0, predecessor_ids: [], planned_start: '2026-10-01T18:00:00Z',
  planned_finish: '2026-10-01T18:30:00Z', forecast_start: '2026-10-01T18:00:00Z', forecast_finish: '2026-10-01T18:30:00Z',
  late_start: false, overrunning: false, slipped_past_fixed_start: false, blocked: false, critical: false,
  allowed_transitions: [], ...over,
});
const read: RunbookRead = {
  plan: { id: 5, release_id: 7, environment_id: 2, environment_name: 'prod', name: 'Cutover',
          anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: null, notes: null, state: 'not_started' },
  planned_end: '2026-10-01T19:00:00Z', forecast_end: '2026-10-01T19:00:00Z', slip_minutes: 0,
  tasks: [t(1, 'Deploy API'), t(2, 'Smoke test', { predecessor_ids: [1] })],
};
const wrap = (ui: React.ReactElement) => render(
  <Provider store={configureStore({ reducer: { runbook: runbookReducer } })}>{ui}</Provider>);

describe('RunbookTaskDialog', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(runbookService.get).mockResolvedValue(read); });

  it('does not offer the task itself as its own predecessor', async () => {
    wrap(<RunbookTaskDialog read={read} task={read.tasks[1]} onClose={() => {}} />);
    await userEvent.click(screen.getByLabelText('Runs after'));
    const list = await screen.findByRole('listbox');
    expect(within(list).getByText('Deploy API')).toBeInTheDocument();
    expect(within(list).queryByText('Smoke test')).not.toBeInTheDocument();
  });

  it('an edit sends only update-schema keys, and predecessors separately', async () => {
    vi.mocked(runbookService.updateTask).mockResolvedValue(read);
    vi.mocked(runbookService.setPredecessors).mockResolvedValue(read);
    const onClose = vi.fn();
    wrap(<RunbookTaskDialog read={read} task={read.tasks[1]} onClose={onClose} />);
    const dur = screen.getByLabelText('Duration (minutes)');
    await userEvent.clear(dur);
    await userEvent.type(dur, '45');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    const [taskId, body] = vi.mocked(runbookService.updateTask).mock.calls[0];
    expect(taskId).toBe(2);
    expect(Object.keys(body).sort()).toEqual(
      ['description', 'duration_minutes', 'fixed_start_at', 'kind', 'name', 'system_id', 'team_group_id'].sort());
    expect(body.duration_minutes).toBe(45);
    expect(runbookService.setPredecessors).not.toHaveBeenCalled();   // unchanged set is not re-sent
    expect(onClose).toHaveBeenCalled();
  });

  it('a create sends predecessor_ids in the create body', async () => {
    vi.mocked(runbookService.createTask).mockResolvedValue(t(3, 'Ramp 10%') as never);
    wrap(<RunbookTaskDialog read={read} onClose={() => {}} />);
    await userEvent.type(screen.getByLabelText('Name'), 'Ramp 10%');
    await userEvent.click(screen.getByLabelText('Runs after'));
    await userEvent.click(await screen.findByRole('option', { name: 'Smoke test' }));
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    const [, body] = vi.mocked(runbookService.createTask).mock.calls[0];
    expect(body.predecessor_ids).toEqual([2]);
  });
});

describe('RunbookTransitionDialog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('skip requires a reason before it can be submitted', async () => {
    vi.mocked(runbookService.transition).mockResolvedValue(read);
    wrap(<RunbookTransitionDialog planId={5} task={read.tasks[0]} to="skipped" onClose={() => {}} />);
    const submit = screen.getByRole('button', { name: 'Skip task' });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Reason'), 'not needed in EU');
    await userEvent.click(submit);
    expect(runbookService.transition).toHaveBeenCalledWith(1, { to_status: 'skipped', reason: 'not needed in EU', at: null });
  });

  it('with choices, lets the user pick the target and only requires a reason for one that needs it', async () => {
    vi.mocked(runbookService.transition).mockResolvedValue(read);
    wrap(<RunbookTransitionDialog planId={5} task={read.tasks[0]} to="in_progress"
                                  choices={['in_progress', 'done']} onClose={() => {}} />);
    // Defaults to the first choice, which needs no reason.
    expect(screen.queryByLabelText('Reason')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start task' })).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('Move to'));
    await userEvent.click(await screen.findByRole('option', { name: 'Mark done' }));
    const submit = screen.getByRole('button', { name: 'Mark done task' });
    const at = screen.getByLabelText(/Actually happened at/);
    fireEvent.change(at, { target: { value: '2026-10-01T18:00' } });
    await userEvent.click(submit);
    const [, body] = vi.mocked(runbookService.transition).mock.calls[0];
    expect(body).toEqual({ to_status: 'done', reason: null, at: new Date('2026-10-01T18:00').toISOString() });
  });

  it('with choices, shows the Reason field once a reason-needing target is chosen', async () => {
    wrap(<RunbookTransitionDialog planId={5} task={read.tasks[0]} to="in_progress"
                                  choices={['in_progress', 'skipped']} onClose={() => {}} />);
    await userEvent.click(screen.getByLabelText('Move to'));
    await userEvent.click(await screen.findByRole('option', { name: 'Skip' }));
    expect(screen.getByLabelText('Reason')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip task' })).toBeDisabled();
  });
});

describe('RunbookPlanDialog', () => {
  it('creates a runbook for the chosen environment and returns its id', async () => {
    vi.mocked(runbookService.create).mockResolvedValue(read);
    const onClose = vi.fn();
    wrap(<RunbookPlanDialog releaseId={7} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText(/Environment/));
    await userEvent.click(await screen.findByRole('option', { name: 'prod' }));
    fireEvent.change(screen.getByLabelText(/Starts at/), { target: { value: '2026-10-01T18:00' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    const [releaseId, body] = vi.mocked(runbookService.create).mock.calls[0];
    expect(releaseId).toBe(7);
    expect(body.environment_id).toBe(2);
    expect(onClose).toHaveBeenCalledWith(5);
  });
});
