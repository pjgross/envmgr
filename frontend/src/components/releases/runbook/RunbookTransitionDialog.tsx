/** Skip and reopen need a reason (spec §4); any transition may record when it
 * actually happened (Ruling R8 — the spec's rule is not limited to `done`).
 * With no `choices`, this is a single-target confirm for `to`. With
 * `choices`, it is a "Move to" picker over those targets — used by the
 * table's "Record time" control, which no longer assumes `done` is the only
 * reachable transition worth timestamping. The server enforces both the
 * ordering invariant and the reason requirement; this dialog only asks.
 *
 * The `task` prop is a snapshot from when the dialog opened. The dialog reads
 * the task's LIVE row from the store instead, so after a refusal (which
 * re-reads the composite — see runbookSlice) the error stays visible while
 * the offered targets follow what the server now allows. With `choices`, the
 * picker lists the live row's allowed_transitions; without, a `to` that is no
 * longer allowed is announced and its submit disabled. */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField,
} from '@mui/material';
import type { AppDispatch, RootState } from '../../../store';
import { transitionTask } from '../../../store/runbookSlice';
import type { RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { NEEDS_REASON, STATUS_LABEL, actionLabel } from './labels';

interface Props { planId: number; task: RunbookTaskRead; to: TaskStatus; choices?: TaskStatus[]; onClose: () => void }

const firstNoReason = (list: TaskStatus[]) => list.find((c) => !NEEDS_REASON(c)) ?? list[0];

export default function RunbookTransitionDialog({ planId, task: snapshot, to, choices, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const liveRow = useSelector((s: RootState) => s.runbook?.byPlan[planId]?.tasks.find((t) => t.id === snapshot.id));
  const task = liveRow ?? snapshot;
  // With no live row in the store (the dialog rendered on its own), trust the
  // caller's targets; once the store holds the task, the store wins.
  const allowed = liveRow ? liveRow.allowed_transitions : (choices ?? [to]);
  const liveChoices = choices ? allowed : undefined;
  const [target, setTarget] = useState<TaskStatus>(to);
  const [reason, setReason] = useState('');
  const [at, setAt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // A refresh can take the chosen target away; move to one that is still offered.
  useEffect(() => {
    if (liveChoices && liveChoices.length > 0 && !liveChoices.includes(target)) {
      setTarget(firstNoReason(liveChoices));
      setReason('');
    }
  }, [liveChoices, target]);
  const available = allowed.includes(target);
  const needsReason = NEEDS_REASON(target);
  const verb = `${actionLabel(target, task.status)} task`;
  const submit = async () => {
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    const body = { to_status: target, reason: reason.trim() || null, at: at ? new Date(at).toISOString() : null };
    const result = await dispatch(transitionTask({ planId, taskId: task.id, body }));
    setSubmitting(false);
    if (transitionTask.rejected.match(result)) setError(result.payload ?? 'Failed to update task');
    else onClose();
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{verb}: {task.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          {!available && (
            <Alert severity="info">
              This task is now {STATUS_LABEL[task.status].toLowerCase()}
              {allowed.length === 0 ? ' and there is nothing you can do with it right now.' : ` — "${actionLabel(target, snapshot.status)}" is no longer available.`}
            </Alert>
          )}
          {liveChoices && liveChoices.length > 1 && (
            <TextField select label="Move to" value={liveChoices.includes(target) ? target : ''}
                       onChange={(e) => { setTarget(e.target.value as TaskStatus); setReason(''); }}>
              {liveChoices.map((c) => <MenuItem key={c} value={c}>{actionLabel(c, task.status)}</MenuItem>)}
            </TextField>
          )}
          {needsReason && (
            <TextField label="Reason" required multiline minRows={2} value={reason}
                       onChange={(e) => setReason(e.target.value)} />
          )}
          <TextField label="Actually happened at (optional)" type="datetime-local" value={at}
                     onChange={(e) => setAt(e.target.value)} InputLabelProps={{ shrink: true }}
                     helperText="Leave empty for now" />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={submitting || !available || (needsReason && !reason.trim())}>{verb}</Button>
      </DialogActions>
    </Dialog>
  );
}
