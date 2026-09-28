/** Skip and reopen need a reason (spec §4); any transition may record when it
 * actually happened (Ruling R8 — the spec's rule is not limited to `done`).
 * With no `choices`, this is a single-target confirm for `to`. With
 * `choices`, it is a "Move to" picker over those targets — used by the
 * table's "Record time" control, which no longer assumes `done` is the only
 * reachable transition worth timestamping. The server enforces both the
 * ordering invariant and the reason requirement; this dialog only asks. */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField,
} from '@mui/material';
import type { AppDispatch } from '../../../store';
import { transitionTask } from '../../../store/runbookSlice';
import type { RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { NEEDS_REASON, actionLabel } from './labels';

interface Props { planId: number; task: RunbookTaskRead; to: TaskStatus; choices?: TaskStatus[]; onClose: () => void }

export default function RunbookTransitionDialog({ planId, task, to, choices, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const [target, setTarget] = useState<TaskStatus>(choices?.[0] ?? to);
  const [reason, setReason] = useState('');
  const [at, setAt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const needsReason = NEEDS_REASON(target);
  const verb = `${actionLabel(target, task.status)} task`;
  const submit = async () => {
    setError(null);
    const body = { to_status: target, reason: reason.trim() || null, at: at ? new Date(at).toISOString() : null };
    const result = await dispatch(transitionTask({ planId, taskId: task.id, body }));
    if (transitionTask.rejected.match(result)) setError(result.payload ?? 'Failed to update task');
    else onClose();
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{verb}: {task.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          {choices && choices.length > 1 && (
            <TextField select label="Move to" value={target}
                       onChange={(e) => { setTarget(e.target.value as TaskStatus); setReason(''); }}>
              {choices.map((c) => <MenuItem key={c} value={c}>{actionLabel(c, task.status)}</MenuItem>)}
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
        <Button variant="contained" onClick={submit} disabled={needsReason && !reason.trim()}>{verb}</Button>
      </DialogActions>
    </Dialog>
  );
}
