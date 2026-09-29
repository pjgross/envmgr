import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import { AxiosError, AxiosHeaders } from 'axios';
import runbookReducer from '../../../../store/runbookSlice';
import { runbookService } from '../../../../services/runbookService';
import type { RunbookRead, RunbookTaskEventRead, RunbookTaskRead } from '../../../../types/runbook';
import RunbookTab from '../RunbookTab';

vi.mock('../../../../services/runbookService', () => ({
  runbookService: {
    listForRelease: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    createTask: vi.fn(), updateTask: vi.fn(), removeTask: vi.fn(), setPredecessors: vi.fn(),
    transition: vi.fn(), events: vi.fn(),
  },
}));

const task = (over: Partial<RunbookTaskRead>): RunbookTaskRead => ({
  id: 1, name: 'Deploy API', description: null, kind: 'deploy', team_group_id: 3, team_name: 'Payments',
  system_id: 4, system_name: 'Payments API', system_on_release: true, duration_minutes: 30,
  fixed_start_at: null, status: 'not_started', actual_started_at: null, actual_finished_at: null, sort_order: 0,
  predecessor_ids: [], planned_start: '2026-10-01T18:00:00Z', planned_finish: '2026-10-01T18:30:00Z',
  forecast_start: '2026-10-01T18:00:00Z', forecast_finish: '2026-10-01T18:30:00Z', late_start: false,
  overrunning: false, slipped_past_fixed_start: false, blocked: false, critical: true,
  allowed_transitions: ['in_progress', 'done'], ...over,
});

const read = (releaseId: number, planId: number, state: RunbookRead['plan']['state'], tasks: RunbookTaskRead[]): RunbookRead => ({
  plan: { id: planId, release_id: releaseId, environment_id: 2, environment_name: `env-${releaseId}`,
          name: `Cutover ${releaseId}`, anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: 'canary', notes: null, state },
  planned_end: '2026-10-01T18:45:00Z', forecast_end: '2026-10-01T19:05:00Z', slip_minutes: 20, tasks,
});

function setup(releaseId: number, r: RunbookRead, role = 'Developer') {
  vi.mocked(runbookService.listForRelease).mockImplementation(async (rid) =>
    rid === releaseId ? [r.plan] : []);
  vi.mocked(runbookService.get).mockResolvedValue(r);
  const store = configureStore({ reducer: {
    runbook: runbookReducer,
    auth: (s = { user: { id: 1, role, is_master_admin: false } }) => s,
  }});
  const ui = (rid: number) => (
    <Provider store={store}><MemoryRouter><RunbookTab releaseId={rid} /></MemoryRouter></Provider>
  );
  return { store, ...render(ui(releaseId)), ui };
}

const conflict = (detail: string) => new AxiosError('Request failed with status code 409',
  'ERR_BAD_REQUEST', undefined, undefined, { status: 409, statusText: 'Conflict', headers: {},
  config: { headers: new AxiosHeaders() }, data: { detail } });

const setVisibility = (v: 'visible' | 'hidden') =>
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => v });

describe('RunbookTab', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => { vi.useRealTimers(); setVisibility('visible'); });

  it('renders the header and one row per task with its flags as text', async () => {
    const smoke = task({ id: 2, name: 'Smoke test', kind: 'verification', predecessor_ids: [1], blocked: true,
                         allowed_transitions: [], critical: false, late_start: true });
    setup(7, read(7, 5, 'in_progress', [task({}), smoke]));
    expect(await screen.findByText('Cutover 7')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add task/i })).not.toBeInTheDocument();  // Developer
    expect(screen.getByText(/Canary/)).toBeInTheDocument();
    expect(screen.getByText(/20 min late/i)).toBeInTheDocument();
    const row = screen.getByText('Smoke test').closest('[role="row"]') as HTMLElement;
    expect(within(row).getByText('Deploy API')).toBeInTheDocument();       // predecessor by name
    expect(within(row).getByLabelText(/blocked by a failed task/i)).toBeInTheDocument();
    expect(within(row).getByLabelText(/late start/i)).toBeInTheDocument();
  });

  it('renders only the actions the server allows, and a start re-renders from the response', async () => {
    const r = read(7, 5, 'not_started', [task({})]);
    setup(7, r);
    await screen.findByText('Deploy API');
    expect(screen.getByRole('button', { name: 'Start Deploy API' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Skip Deploy API/ })).not.toBeInTheDocument();
    vi.mocked(runbookService.transition).mockResolvedValue(
      read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    await userEvent.click(screen.getByRole('button', { name: 'Start Deploy API' }));
    expect(runbookService.transition).toHaveBeenCalledWith(1, { to_status: 'in_progress' });
    expect(await screen.findByRole('button', { name: 'Complete Deploy API' })).toBeInTheDocument();
  });

  it('shows the server refusal text, not an HTTP status', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByText('Deploy API');
    vi.mocked(runbookService.transition).mockRejectedValue(new AxiosError('Request failed with status code 409',
      'ERR_BAD_REQUEST', undefined, undefined, { status: 409, statusText: 'Conflict', headers: {},
      config: { headers: new AxiosHeaders() }, data: { detail: "'Deploy API' cannot start until these are done or skipped: Backup (in_progress)" } }));
    await userEvent.click(screen.getByRole('button', { name: 'Start Deploy API' }));
    expect(await screen.findByText(/Backup \(in_progress\)/)).toBeInTheDocument();
    expect(screen.queryByText(/status code/)).not.toBeInTheDocument();
  });

  it.each(['not_started', 'failed'] as const)(
    'keeps re-reading every 30 seconds while the plan is %s (Ruling R15)', async (state) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      setup(7, read(7, 5, state, [task({})]));
      await screen.findByText('Deploy API');
      const before = vi.mocked(runbookService.get).mock.calls.length;
      await act(async () => { vi.advanceTimersByTime(30_000); });
      expect(vi.mocked(runbookService.get).mock.calls.length).toBe(before + 1);
    });

  it('re-reads every 30 seconds while in progress and not once complete', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setup(7, read(7, 5, 'in_progress', [task({ status: 'in_progress' })]));
    await screen.findByText('Deploy API');
    const before = vi.mocked(runbookService.get).mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(vi.mocked(runbookService.get).mock.calls.length).toBe(before + 1);
    vi.mocked(runbookService.get).mockResolvedValue(read(7, 5, 'complete', [task({ status: 'done', allowed_transitions: [] })]));
    await act(async () => { vi.advanceTimersByTime(30_000); });
    const settled = vi.mocked(runbookService.get).mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(90_000); });
    expect(vi.mocked(runbookService.get).mock.calls.length).toBe(settled);
  });

  it("does not show the previous release's runbook after re-rendering for another release", async () => {
    const { rerender, ui } = setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByText('Cutover 7');
    vi.mocked(runbookService.listForRelease).mockResolvedValue([]);
    rerender(ui(8));
    await waitFor(() => expect(screen.queryByText('Cutover 7')).not.toBeInTheDocument());
    expect(await screen.findByText(/no runbook for this release yet/i)).toBeInTheDocument();
  });

  it('offers structure controls to a release manager only', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]), 'Release Manager');
    expect(await screen.findByRole('button', { name: /add task/i })).toBeInTheDocument();
  });

  it('offers "Record time" for a task with an available transition, opening a choice of targets', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByText('Deploy API');
    await userEvent.click(screen.getByRole('button', { name: 'Record a time for Deploy API' }));
    // Two allowed_transitions ('in_progress', 'done') -> a "Move to" picker
    // offering both as targets, not a single-target confirm.
    await userEvent.click(await screen.findByLabelText('Move to'));
    expect(await screen.findByRole('option', { name: 'Start' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Mark done' })).toBeInTheDocument();
  });

  it('the Timeline toggle switches from the task table to the timeline view', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByText('Deploy API');
    await userEvent.click(screen.getByRole('button', { name: 'Timeline' }));
    expect(await screen.findByLabelText(/Deploy API: planned/)).toBeInTheDocument();
  });
});

describe('RunbookTab — final-review fixes', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => { vi.useRealTimers(); setVisibility('visible'); });

  it('a refused transition re-reads the composite, so the row stops offering the stale action (UI-1)', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByRole('button', { name: 'Start Deploy API' });
    const before = vi.mocked(runbookService.get).mock.calls.length;
    // Somebody else started it: the server refuses, and the re-read says so.
    vi.mocked(runbookService.get).mockResolvedValue(
      read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    vi.mocked(runbookService.transition).mockRejectedValue(conflict("'Deploy API' is in_progress and cannot move to in_progress"));
    await userEvent.click(screen.getByRole('button', { name: 'Start Deploy API' }));
    expect(await screen.findByText(/is in_progress and cannot move/)).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(runbookService.get).mock.calls.length).toBe(before + 1));
    expect(vi.mocked(runbookService.get).mock.lastCall).toEqual([5]);
    expect(await screen.findByRole('button', { name: 'Complete Deploy API' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start Deploy API' })).not.toBeInTheDocument();
  });

  it('after a refusal in the Record time dialog, the error stays and the targets follow the refreshed row (UI-1)', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    await userEvent.click(await screen.findByRole('button', { name: 'Record a time for Deploy API' }));
    vi.mocked(runbookService.get).mockResolvedValue(
      read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    vi.mocked(runbookService.transition).mockRejectedValue(conflict('Somebody else moved it'));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Start task' }));
    expect(await within(dialog).findByText('Somebody else moved it')).toBeInTheDocument();
    // The picker now offers what the server allows for an in-progress task.
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Complete task' })).toBeInTheDocument());
    await userEvent.click(within(dialog).getByLabelText('Move to'));
    expect(await screen.findByRole('option', { name: 'Fail' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Start' })).not.toBeInTheDocument();
    expect(within(dialog).getByText('Somebody else moved it')).toBeInTheDocument();
  });

  it('a list that will not load says so instead of "Loading runbooks…" forever (R2)', async () => {
    vi.mocked(runbookService.listForRelease).mockRejectedValue(conflict('database unavailable'));
    const store = configureStore({ reducer: {
      runbook: runbookReducer, auth: (s = { user: { id: 1, role: 'Developer', is_master_admin: false } }) => s,
    }});
    render(<Provider store={store}><MemoryRouter><RunbookTab releaseId={7} /></MemoryRouter></Provider>);
    expect(await screen.findByText(/Could not load runbooks: database unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/Loading runbooks/)).not.toBeInTheDocument();
    vi.mocked(runbookService.listForRelease).mockResolvedValue([]);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(/no runbook for this release yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/Could not load runbooks/)).not.toBeInTheDocument();
  });

  it('a failed refresh says the page is showing an older read; "Updated HH:MM" is always shown (R2)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setup(7, read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    await screen.findByText('Deploy API');
    expect(screen.getByText(/^Updated \d{1,2}:\d{2}/)).toBeInTheDocument();
    expect(screen.queryByText(/Could not refresh/)).not.toBeInTheDocument();
    vi.mocked(runbookService.get).mockRejectedValue(conflict('gateway timeout'));
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(await screen.findByText(/Could not refresh this runbook — showing it as last loaded at .*gateway timeout/))
      .toBeInTheDocument();
    expect(screen.getByText('Deploy API')).toBeInTheDocument();          // the last good read stays
    expect(screen.queryByText(/Could not load runbooks/)).not.toBeInTheDocument();
  });

  it('re-reads at once when the page becomes visible again, without waiting for the timer (UI-3)', async () => {
    setup(7, read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    await screen.findByText('Deploy API');
    await waitFor(() => expect(runbookService.get).toHaveBeenCalled());
    const before = vi.mocked(runbookService.get).mock.calls.length;
    setVisibility('hidden');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(vi.mocked(runbookService.get).mock.calls.length).toBe(before);
    setVisibility('visible');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(vi.mocked(runbookService.get).mock.calls.length).toBe(before + 1);
  });

  it('shows "Record time" only when a transition that needs no reason exists (UI-4)', async () => {
    setup(7, read(7, 5, 'not_started', [
      task({ id: 1, name: 'Only skippable', allowed_transitions: ['skipped'] }),
      task({ id: 2, name: 'Failed one', status: 'failed', allowed_transitions: ['skipped', 'in_progress'] }),  // reason target first on purpose
    ]), 'Release Manager');
    await screen.findByText('Only skippable');
    expect(screen.getByRole('button', { name: 'Skip Only skippable' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record a time for Only skippable' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Record a time for Failed one' }));
    const dialog = await screen.findByRole('dialog');
    // Defaults to the no-reason target, but still offers every allowed one.
    expect(within(dialog).getByRole('button', { name: 'Retry task' })).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/^Reason/)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByLabelText('Move to'));
    expect(await screen.findByRole('option', { name: 'Skip' })).toBeInTheDocument();
  });

  it('disables a row\'s actions while its transition is in flight, so a second click sends nothing (M3)', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    const start = await screen.findByRole('button', { name: 'Start Deploy API' });
    let resolve: (r: RunbookRead) => void = () => {};
    vi.mocked(runbookService.transition).mockReturnValue(new Promise<RunbookRead>((r) => { resolve = r; }));
    await userEvent.click(start);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start Deploy API' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Record a time for Deploy API' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Start Deploy API' }), { pointerEventsCheck: 0 });
    expect(runbookService.transition).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolve(read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    });
    expect(await screen.findByRole('button', { name: 'Complete Deploy API' })).toBeEnabled();
  });

  it('History shows the task instructions and its events, newest first, to any viewer; plan notes show in the header (R3)', async () => {
    const r = read(7, 5, 'in_progress', [task({ status: 'done', allowed_transitions: [],
      description: 'Run deploy.sh with --canary' })]);
    r.plan.notes = 'Bridge call: 0800 000 000';
    setup(7, r);                                             // a Developer, not a manager
    expect(await screen.findByText('Bridge call: 0800 000 000')).toBeInTheDocument();
    const events: RunbookTaskEventRead[] = [
      { id: 12, from_status: 'in_progress', to_status: 'done', at: '2026-10-01T18:40:00Z',
        recorded_at: '2026-10-01T18:55:00Z', by_username: 'dba1', note: null },
      { id: 11, from_status: 'not_started', to_status: 'in_progress', at: '2026-10-01T18:05:00Z',
        recorded_at: '2026-10-01T18:05:00Z', by_username: null, note: 'late start, waiting on DNS' },
    ];
    vi.mocked(runbookService.events).mockResolvedValue(events);
    await userEvent.click(screen.getByRole('button', { name: 'History for Deploy API' }));
    const dialog = await screen.findByRole('dialog');
    expect(runbookService.events).toHaveBeenCalledWith(1);
    expect(within(dialog).getByText('Run deploy.sh with --canary')).toBeInTheDocument();
    const items = await within(dialog).findAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('In progress → Done');
    expect(items[0]).toHaveTextContent('by dba1');
    expect(items[1]).toHaveTextContent('Not started → In progress');
    expect(items[1]).toHaveTextContent('Note: late start, waiting on DNS');
    expect(items[1]).toHaveTextContent('by an unknown user');
  });
});
