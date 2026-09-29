/**
 * Release detail → Runbook (Phase 9 C5a). One plan per environment, selected
 * by `?plan=`. The tab renders the composite the server computed; until the
 * plan is complete it re-reads every 30 s (paused while the document is
 * hidden, and re-read at once when it becomes visible again), because several
 * teams tick tasks at once during a cutover — and a failed or not-yet-started
 * cutover's screen must keep updating too (Ruling R15).
 *
 * Nothing here fails silently: a list that will not load says so instead of
 * "Loading…" forever, a failed refresh says the page is showing an older
 * read, and "Updated HH:MM" is always beside the state chip.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import type { AppDispatch, RootState } from '../../../store';
import { fetchRunbook, fetchRunbooks, transitionTask } from '../../../store/runbookSlice';
import type { RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';
import RunbookTaskTable from './RunbookTaskTable';
import RunbookTimeline from './RunbookTimeline';
import RunbookPlanDialog from './RunbookPlanDialog';
import RunbookTaskDialog from './RunbookTaskDialog';
import RunbookTransitionDialog from './RunbookTransitionDialog';
import RunbookTaskHistoryDialog from './RunbookTaskHistoryDialog';
import { NEEDS_REASON, PATTERN_LABEL } from './labels';

const POLL_MS = 30_000;
const STATE_COLOR = { not_started: 'default', in_progress: 'info', complete: 'success', failed: 'error' } as const;
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export default function RunbookTab({ releaseId }: { releaseId: number }) {
  const dispatch = useDispatch<AppDispatch>();
  const [params, setParams] = useSearchParams();
  const user = useSelector((s: RootState) => s.auth.user);
  const plans = useSelector((s: RootState) => s.runbook.plansByRelease[releaseId]);
  const listError = useSelector((s: RootState) => s.runbook.listError[releaseId]);
  const canEdit = !!user && (user.is_master_admin || user.role === 'Admin' || user.role === 'Release Manager');
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'table' | 'timeline'>('table');
  const [planDialog, setPlanDialog] = useState<'create' | 'edit' | null>(null);
  const [taskDialog, setTaskDialog] = useState<RunbookTaskRead | 'new' | null>(null);
  const [pending, setPending] = useState<{ task: RunbookTaskRead; to: TaskStatus; choices?: TaskStatus[] } | null>(null);
  const [history, setHistory] = useState<RunbookTaskRead | null>(null);
  // Tasks with a transition in flight: their action buttons are disabled so a
  // second click cannot send a second request. The ref is the source of truth
  // for the guard (state updates are async); the state drives rendering.
  const busyRef = useRef<Set<number>>(new Set());
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const markBusy = (id: number, on: boolean) => {
    if (on) busyRef.current.add(id); else busyRef.current.delete(id);
    setBusy(new Set(busyRef.current));
  };

  const loadList = useCallback(() => { dispatch(fetchRunbooks(releaseId)); }, [dispatch, releaseId]);
  useEffect(() => { setError(null); loadList(); }, [loadList]);

  // Only a plan that belongs to THIS release may be selected — a stale ?plan=
  // from another release must never render (re-render, don't just mount).
  const planId = useMemo(() => {
    if (!plans?.length) return null;
    const wanted = Number(params.get('plan'));
    return plans.some((p) => p.id === wanted) ? wanted : plans[0].id;
  }, [plans, params]);
  const read = useSelector((s: RootState) => (planId ? s.runbook.byPlan[planId] : undefined));
  const current = read && read.plan.release_id === releaseId ? read : undefined;
  const refreshError = useSelector((s: RootState) => (planId ? s.runbook.refreshError[planId] : undefined));
  const loadedAt = useSelector((s: RootState) => (planId ? s.runbook.loadedAt[planId] : undefined));

  useEffect(() => { if (planId) dispatch(fetchRunbook(planId)); }, [dispatch, planId]);

  // Poll until the plan is COMPLETE — not only while in progress (Ruling R15):
  // a failed cutover is exactly when people are watching the screen.
  const live = !!current && current.plan.state !== 'complete';
  useEffect(() => {
    if (!live || !planId) return undefined;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') dispatch(fetchRunbook(planId));
    }, POLL_MS);
    const onVisible = () => { if (document.visibilityState === 'visible') dispatch(fetchRunbook(planId)); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [dispatch, live, planId]);

  const selectPlan = (id: number) => {
    const next = new URLSearchParams(params);
    next.set('plan', String(id));
    setParams(next, { replace: true });
  };

  const onAction = useCallback(async (task: RunbookTaskRead, to: TaskStatus) => {
    if (!planId || busyRef.current.has(task.id)) return;
    if (NEEDS_REASON(to)) { setPending({ task, to }); return; }   // skip and reopen ask why
    setError(null);
    markBusy(task.id, true);
    try {
      const result = await dispatch(transitionTask({ planId, taskId: task.id, body: { to_status: to } }));
      if (transitionTask.rejected.match(result)) setError(result.payload ?? 'Failed to update task');
    } finally {
      markBusy(task.id, false);
    }
  }, [dispatch, planId]);

  const listAlert = listError && (
    <Alert severity="error" action={<Button color="inherit" size="small" onClick={loadList}>Retry</Button>}>
      Could not load runbooks: {listError}
    </Alert>
  );
  if (plans === undefined) {
    return listAlert || <Typography color="text.secondary">Loading runbooks…</Typography>;
  }

  return (
    <Stack spacing={2}>
      {listAlert}
      {refreshError && planId && (current ? (
        <Alert severity="warning"
               action={<Button color="inherit" size="small" onClick={() => dispatch(fetchRunbook(planId))}>Retry</Button>}>
          Could not refresh this runbook — showing it as last loaded{loadedAt ? ` at ${clock(loadedAt)}` : ''}. {refreshError}
        </Alert>
      ) : (
        <Alert severity="error"
               action={<Button color="inherit" size="small" onClick={() => dispatch(fetchRunbook(planId))}>Retry</Button>}>
          Could not load this runbook: {refreshError}
        </Alert>
      ))}
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
        {plans.length > 0 && (
          <TextField select size="small" label="Environment" value={planId ?? ''} sx={{ minWidth: 220 }}
                     onChange={(e) => selectPlan(Number(e.target.value))}>
            {plans.map((p) => <MenuItem key={p.id} value={p.id}>{p.environment_name ?? 'Unknown environment'}</MenuItem>)}
          </TextField>
        )}
        {canEdit && <Button variant="outlined" onClick={() => setPlanDialog('create')}>New runbook</Button>}
      </Stack>

      {plans.length === 0 && (
        <Typography color="text.secondary">There is no runbook for this release yet.</Typography>
      )}

      {current && (
        <>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
              <Box>
                <Typography variant="h6">{current.plan.name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {current.plan.environment_name} · starts {formatBookingDateTime(current.plan.anchor_start_at)}
                  {current.plan.deploy_pattern && ` · ${PATTERN_LABEL[current.plan.deploy_pattern]}`}
                </Typography>
                {current.plan.notes && (
                  <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>{current.plan.notes}</Typography>
                )}
              </Box>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Chip label={current.plan.state.replace('_', ' ')} color={STATE_COLOR[current.plan.state]} />
                {loadedAt && (
                  <Typography variant="body2" color="text.secondary">Updated {clock(loadedAt)}</Typography>
                )}
                <Typography variant="body2">Planned end {formatBookingDateTime(current.planned_end)}</Typography>
                <Typography variant="body2">Forecast end {formatBookingDateTime(current.forecast_end)}</Typography>
                <Typography variant="body2" color={current.slip_minutes ? 'warning.main' : 'text.secondary'}>
                  {current.slip_minutes ? `${current.slip_minutes} min late` : 'On time'}
                </Typography>
                {canEdit && <Button size="small" onClick={() => setPlanDialog('edit')}>Edit runbook</Button>}
                {canEdit && <Button size="small" variant="contained" onClick={() => setTaskDialog('new')}>Add task</Button>}
              </Stack>
            </Stack>
          </Paper>
          <ToggleButtonGroup size="small" exclusive value={view} onChange={(_e, v) => v && setView(v)} aria-label="Runbook view">
            <ToggleButton value="table">Table</ToggleButton>
            <ToggleButton value="timeline">Timeline</ToggleButton>
          </ToggleButtonGroup>
          {view === 'table'
            ? <RunbookTaskTable read={current} canEdit={canEdit} onAction={onAction} busy={busy}
                                onRecordTime={(task) => setPending({
                                  task,
                                  // Default to a target that needs no reason; offer every allowed one.
                                  to: task.allowed_transitions.find((t) => !NEEDS_REASON(t)) ?? task.allowed_transitions[0],
                                  choices: task.allowed_transitions,
                                })}
                                onHistory={(t) => setHistory(t)}
                                onEdit={(t) => setTaskDialog(t)} />
            : <RunbookTimeline read={current} />}
        </>
      )}

      {planDialog && (
        <RunbookPlanDialog releaseId={releaseId} existing={planDialog === 'edit' ? current?.plan : undefined}
                           onClose={(createdId) => { setPlanDialog(null); if (createdId) selectPlan(createdId); }} />
      )}
      {taskDialog && current && (
        <RunbookTaskDialog read={current} task={taskDialog === 'new' ? undefined : taskDialog}
                           onClose={() => setTaskDialog(null)} />
      )}
      {pending && current && (
        <RunbookTransitionDialog planId={current.plan.id} task={pending.task} to={pending.to} choices={pending.choices}
                                 onClose={() => setPending(null)} />
      )}
      {history && <RunbookTaskHistoryDialog task={history} onClose={() => setHistory(null)} />}
    </Stack>
  );
}
