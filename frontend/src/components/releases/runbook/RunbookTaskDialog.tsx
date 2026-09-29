/**
 * Add or edit a task (Admin/RM). The PATCH sends only RunbookTaskUpdate keys —
 * never the read model (the schema is extra="forbid"; echoing a read row is a
 * 422 on every save). Predecessors travel separately, and only when changed.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField,
} from '@mui/material';
import type { AppDispatch } from '../../../store';
import { createTask, deleteTask, setPredecessors, updateTask } from '../../../store/runbookSlice';
import { userGroupService } from '../../../services/userGroupService';
import { releaseService } from '../../../services/releaseService';
import type { RunbookRead, RunbookTaskRead, TaskKind } from '../../../types/runbook';
import { toDateTimeLocal } from '../../../utils/datetime';
import { KIND_LABEL } from './labels';

interface Props { read: RunbookRead; task?: RunbookTaskRead; onClose: () => void }
type Option = { id: number; name: string };
const TEAM_LIMIT = 500;

const sameSet = (a: number[], b: number[]) => a.length === b.length && [...a].sort().join() === [...b].sort().join();

export default function RunbookTaskDialog({ read, task, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const planId = read.plan.id;
  const [name, setName] = useState(task?.name ?? '');
  const [description, setDescription] = useState(task?.description ?? '');
  const [kind, setKind] = useState<TaskKind>(task?.kind ?? 'task');
  const [duration, setDuration] = useState(String(task?.duration_minutes ?? 30));
  const [teamId, setTeamId] = useState<number | ''>(task?.team_group_id ?? '');
  const [systemId, setSystemId] = useState<number | ''>(task?.system_id ?? '');
  const [fixedStart, setFixedStart] = useState(task?.fixed_start_at ? toDateTimeLocal(task.fixed_start_at) : '');
  const [preds, setPreds] = useState<number[]>(task?.predecessor_ids ?? []);
  const [teams, setTeams] = useState<Option[]>([]);
  // 'loading' | loaded with the server's total | 'failed' — the Team picker says which.
  const [teamsTotal, setTeamsTotal] = useState<number | 'loading' | 'failed'>('loading');
  const [systems, setSystems] = useState<Option[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    userGroupService.listGroups({ limit: TEAM_LIMIT })
      .then((r) => { setTeams(r.rows.map((g) => ({ id: g.id, name: g.name }))); setTeamsTotal(r.total); })
      .catch(() => setTeamsTotal('failed'));
    releaseService.listSystems(read.plan.release_id).then((rows) =>
      setSystems(rows.map((s) => ({ id: s.system_id, name: s.system_name ?? '—' }))));
  }, [read.plan.release_id]);

  // A task whose system left the release still shows it (spec §3), so keep it selectable.
  const systemOptions = useMemo(() => {
    if (task?.system_id && !systems.some((s) => s.id === task.system_id)) {
      return [...systems, { id: task.system_id, name: `${task.system_name ?? '—'} (no longer on this release)` }];
    }
    return systems;
  }, [systems, task]);
  // Likewise a task whose team was archived: listGroups omits it, but the task
  // still names it, so it stays selectable (and saving the form keeps it).
  // Called "archived" only when the list is complete — otherwise it may just
  // sit past the page the picker could load.
  const teamsTruncated = typeof teamsTotal === 'number' && teamsTotal > teams.length;
  const teamOptions = useMemo(() => {
    if (task?.team_group_id && !teams.some((g) => g.id === task.team_group_id)) {
      const suffix = typeof teamsTotal === 'number' && !teamsTruncated ? ' (archived)' : '';
      return [...teams, { id: task.team_group_id, name: `${task.team_name ?? '—'}${suffix}` }];
    }
    return teams;
  }, [teams, teamsTotal, teamsTruncated, task]);
  const teamHelper = teamsTotal === 'failed'
    ? 'Could not load teams — only the current assignment can be kept.'
    : teamsTruncated ? `Showing the first ${teams.length} of ${teamsTotal} teams.` : undefined;
  const predecessorOptions = read.tasks.filter((candidate) => candidate.id !== task?.id);
  const minutes = Number(duration);
  const valid = name.trim() !== '' && Number.isInteger(minutes) && minutes >= 0;

  const save = async () => {
    setError(null);
    const fields = {
      name: name.trim(), description: description.trim() || null, kind, duration_minutes: minutes,
      team_group_id: teamId === '' ? null : teamId, system_id: systemId === '' ? null : systemId,
      fixed_start_at: fixedStart ? new Date(fixedStart).toISOString() : null,
    };
    const result = task
      ? await dispatch(updateTask({ planId, taskId: task.id, body: fields }))
      : await dispatch(createTask({ planId, body: { ...fields, predecessor_ids: preds } }));
    if (result.meta.requestStatus === 'rejected') { setError((result.payload as string) ?? 'Failed to save task'); return; }
    if (task && !sameSet(preds, task.predecessor_ids)) {
      const p = await dispatch(setPredecessors({ planId, taskId: task.id, ids: preds }));
      if (setPredecessors.rejected.match(p)) { setError(p.payload ?? 'Failed to update dependencies'); return; }
    }
    onClose();
  };

  const remove = async () => {
    if (!task) return;
    const result = await dispatch(deleteTask({ planId, taskId: task.id }));
    if (deleteTask.rejected.match(result)) setError(result.payload ?? 'Failed to delete task');
    else onClose();
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{task ? `Edit ${task.name}` : 'Add task'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Description" multiline minRows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          <TextField select label="Kind" value={kind} onChange={(e) => setKind(e.target.value as TaskKind)}
                     SelectProps={{ inputProps: { 'aria-label': 'Kind' } }}>
            {Object.entries(KIND_LABEL).map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
          </TextField>
          <TextField label="Duration (minutes)" type="number" inputProps={{ min: 0 }} value={duration}
                     onChange={(e) => setDuration(e.target.value)} />
          <TextField select label="Team" value={teamId} onChange={(e) => setTeamId(e.target.value === '' ? '' : Number(e.target.value))}
                     SelectProps={{ inputProps: { 'aria-label': 'Team' } }}
                     helperText={teamHelper} FormHelperTextProps={{ sx: teamsTotal === 'failed' ? { color: 'error.main' } : undefined }}>
            <MenuItem value="">No team (Admin / Release Manager only)</MenuItem>
            {teamOptions.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
          </TextField>
          <TextField select label="System" value={systemId} onChange={(e) => setSystemId(e.target.value === '' ? '' : Number(e.target.value))}
                     SelectProps={{ inputProps: { 'aria-label': 'System' } }}>
            <MenuItem value="">None</MenuItem>
            {systemOptions.map((s) => <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>)}
          </TextField>
          <TextField label="Start no earlier than (optional)" type="datetime-local" value={fixedStart}
                     onChange={(e) => setFixedStart(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField select label="Runs after" value={preds} SelectProps={{ multiple: true, inputProps: { 'aria-label': 'Runs after' } }}
                     onChange={(e) => setPreds(typeof e.target.value === 'string' ? [] : (e.target.value as unknown as number[]))}
                     helperText="This task cannot start until all of these are done or skipped">
            {predecessorOptions.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        {task && task.status === 'not_started' && <Button color="error" onClick={remove}>Delete</Button>}
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!valid}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
