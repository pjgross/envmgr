/** Create a runbook (environment, name, anchor, pattern) or edit one. The
 * environment is fixed after create — PATCH has no environment field. */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField } from '@mui/material';
import type { AppDispatch } from '../../../store';
import { createRunbook, deleteRunbook, updateRunbook } from '../../../store/runbookSlice';
import type { DeployPattern, RunbookPlanRead } from '../../../types/runbook';
import { toDateTimeLocal } from '../../../utils/datetime';
import { useAllEnvironments } from '../../../hooks/useAllEnvironments';
import { PATTERN_LABEL } from './labels';

interface Props { releaseId: number; existing?: RunbookPlanRead; onClose: (createdPlanId?: number) => void }

export default function RunbookPlanDialog({ releaseId, existing, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  // The shared picker hook: coalesces in-flight requests, and reports a
  // truncated list rather than pretending it is complete.
  const { environments: envs, truncated } = useAllEnvironments();
  const [environmentId, setEnvironmentId] = useState<number | ''>(existing?.environment_id ?? '');
  const [name, setName] = useState(existing?.name ?? 'Production cutover');
  const [anchor, setAnchor] = useState(existing ? toDateTimeLocal(existing.anchor_start_at) : '');
  const [pattern, setPattern] = useState<DeployPattern | ''>(existing?.deploy_pattern ?? '');
  const [notes, setNotes] = useState(existing?.notes ?? '');
  const [error, setError] = useState<string | null>(null);

  const valid = name.trim() !== '' && anchor !== '' && (!!existing || environmentId !== '');
  const save = async () => {
    setError(null);
    const common = { name: name.trim(), anchor_start_at: new Date(anchor).toISOString(),
                     deploy_pattern: pattern || null, notes: notes.trim() || null };
    const result = existing
      ? await dispatch(updateRunbook({ planId: existing.id, body: common }))
      : await dispatch(createRunbook({ releaseId, body: { ...common, environment_id: environmentId as number } }));
    if (result.meta.requestStatus === 'rejected') { setError((result.payload as string) ?? 'Failed to save runbook'); return; }
    onClose(existing ? undefined : (result.payload as { plan: { id: number } }).plan.id);
  };
  const remove = async () => {
    if (!existing) return;
    const result = await dispatch(deleteRunbook({ releaseId, planId: existing.id }));
    if (deleteRunbook.rejected.match(result)) setError(result.payload ?? 'Failed to delete runbook');
    else onClose();
  };
  return (
    <Dialog open onClose={() => onClose()} fullWidth maxWidth="sm">
      <DialogTitle>{existing ? 'Edit runbook' : 'New runbook'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          {!existing && (
            <TextField select label="Environment" required value={environmentId}
                       onChange={(e) => setEnvironmentId(Number(e.target.value))}
                       helperText={truncated ? 'Not every environment is listed — the estate exceeds the picker limit' : undefined}>
              {envs.map((e) => <MenuItem key={e.id} value={e.id}>{e.name}</MenuItem>)}
            </TextField>
          )}
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Starts at" type="datetime-local" required value={anchor}
                     onChange={(e) => setAnchor(e.target.value)} InputLabelProps={{ shrink: true }}
                     helperText="Tasks with nothing before them and no fixed time start here" />
          <TextField select label="Deploy pattern" value={pattern} onChange={(e) => setPattern(e.target.value as DeployPattern | '')}>
            <MenuItem value="">Not set</MenuItem>
            {Object.entries(PATTERN_LABEL).map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
          </TextField>
          <TextField label="Notes" multiline minRows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        {existing && existing.state === 'not_started' && <Button color="error" onClick={remove}>Delete runbook</Button>}
        <Button onClick={() => onClose()}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!valid}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
