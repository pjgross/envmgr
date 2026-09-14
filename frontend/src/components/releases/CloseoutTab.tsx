/**
 * CloseoutTab — Phase 9 C6. Four cards in lifecycle order: hyper-care,
 * incidents in the window, ops handover, closing.
 *
 * THE SERVER DECIDES; THIS TAB REPORTS. `close_targets` is computed by the
 * same function that raises the transition's 422, so a tick here and a
 * refusal on the Main tab cannot disagree. Nothing here touches
 * TransitionControls — see ReadinessBanner's header for the standing rule.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, InputLabel, Link, List, ListItem, ListItemText, MenuItem, Paper,
  Select, Stack, TextField, Tooltip, Typography,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import type { AppDispatch, RootState } from '../../store';
import { fetchCloseout, declareStable, withdrawStable, confirmHandover, withdrawHandover } from '../../store/closeoutSlice';
import { updateRelease } from '../../store/releaseSlice';
import { fetchUserGroups } from '../../store/userGroupSlice';
import { entityTabPath } from '../../pages/admin/entityConfigTabs';
import type { HypercareState } from '../../types/closeout';

interface Props { releaseId: number }

const STATE_LABEL: Record<HypercareState, string> = {
  none: 'No hyper-care phase', planned: 'Planned', active: 'Active', overdue: 'Overdue', stable: 'Stable',
};
const STATE_COLOR: Record<HypercareState, 'default' | 'info' | 'success' | 'warning'> = {
  none: 'default', planned: 'info', active: 'info', overdue: 'warning', stable: 'success',
};

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—');
const fmtDateTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—');

type Pending = 'declare' | 'withdraw-stable' | 'confirm' | 'withdraw-handover' | null;

export default function CloseoutTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const user = useSelector((s: RootState) => s.auth.user);
  const data = useSelector((s: RootState) => s.closeout.byRelease[releaseId]);
  const loadError = useSelector((s: RootState) => s.closeout.error);
  const groups = useSelector((s: RootState) => s.userGroup.groups);
  const canWrite = user?.role === 'Admin' || user?.role === 'Release Manager' || user?.is_master_admin === true;

  const [pending, setPending] = useState<Pending>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    dispatch(fetchCloseout(releaseId));
    dispatch(fetchUserGroups({}));
  }, [dispatch, releaseId]);

  // Clears any stale reason from a previous refusal before a new dialog
  // opens, so re-opening the dialog for a different action never shows a
  // leftover message from the one before it.
  const openDialog = (p: Pending) => {
    setError(null);
    setPending(p);
  };

  const run = async () => {
    if (!pending) return;
    setSubmitting(true);
    setError(null);
    const thunk = { declare: declareStable, 'withdraw-stable': withdrawStable,
                    confirm: confirmHandover, 'withdraw-handover': withdrawHandover }[pending];
    const result = await dispatch(thunk({ releaseId, note: note.trim() || undefined }));
    setSubmitting(false);
    if (thunk.rejected.match(result)) {
      setError(result.payload ?? 'Request failed');
      return;
    }
    setPending(null);
    setNote('');
  };

  const setGroup = async (value: number | '') => {
    setError(null);
    const result = await dispatch(updateRelease({ id: releaseId, data: { operations_group_id: value === '' ? null : value } }));
    if (updateRelease.rejected.match(result)) {
      setError(result.payload ?? 'Failed to set the operations group');
      return;
    }
    dispatch(fetchCloseout(releaseId));
  };

  if (loadError && !data) return <Alert severity="error">{loadError}</Alert>;
  if (!data) return <Typography variant="body2">Loading…</Typography>;

  const { hypercare, handover, pir, incidents, close_targets } = data;
  const groupValue: number | '' = handover.operations_group_id ?? '';
  const groupIsArchived = groupValue !== '' && !groups.some((g) => g.id === groupValue);

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>Hyper-care</Typography>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
          <Chip label={STATE_LABEL[hypercare.state]} color={STATE_COLOR[hypercare.state]} size="small" />
          {hypercare.phase && (
            <Typography variant="body2">{hypercare.phase.name}: {fmt(hypercare.phase.start_date)} – {fmt(hypercare.phase.end_date)}</Typography>
          )}
        </Stack>
        {!hypercare.phase && hypercare.state !== 'stable' && (
          <Typography variant="body2" color="text.secondary">
            No hyper-care phase on this release. Add one, with kind Hyper-care, under Gates &amp; Test Phases.
          </Typography>
        )}
        {hypercare.declared_stable_at ? (
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2">Declared stable by {hypercare.declared_stable_by_username ?? 'unknown'} on {fmtDateTime(hypercare.declared_stable_at)}</Typography>
            {canWrite && <Button size="small" onClick={() => openDialog('withdraw-stable')}>Withdraw</Button>}
          </Stack>
        ) : (
          canWrite && <Button variant="contained" size="small" onClick={() => openDialog('declare')}>Declare stable</Button>
        )}
      </Paper>

      {hypercare.state !== 'none' && hypercare.state !== 'planned' && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>Incidents in the window</Typography>
          <Typography variant="caption" color="text.secondary">
            {fmt(incidents.window_start)} – {fmt(incidents.window_end)} · caused by this release
          </Typography>
          <Stack direction="row" spacing={1} sx={{ my: 1 }}>
            {Object.entries(incidents.by_severity).map(([sev, n]) => (
              <Chip key={sev} label={`${sev}: ${n}`} size="small" color={n > 0 && (sev === 'P1' || sev === 'P2') ? 'error' : 'default'} />
            ))}
          </Stack>
          {incidents.total === 0 ? (
            <Typography variant="body2" color="text.secondary">No incidents in the window.</Typography>
          ) : (
            <List dense>
              {incidents.items.map((i) => (
                <ListItem key={i.id} disableGutters>
                  <ListItemText
                    primary={<Link component={RouterLink} to={`/incidents/${i.id}`}>{i.title}</Link>}
                    secondary={`${i.severity} · ${i.status} · ${fmtDateTime(i.detected_at)}`}
                  />
                </ListItem>
              ))}
              {incidents.total > incidents.items.length && (
                <Typography variant="caption">Showing {incidents.items.length} of {incidents.total}.</Typography>
              )}
            </List>
          )}
        </Paper>
      )}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>Ops handover</Typography>
        <FormControl size="small" sx={{ minWidth: 260, mb: 1 }} disabled={!canWrite}>
          <InputLabel id="closeout-ops-group-label">Operations group</InputLabel>
          <Select labelId="closeout-ops-group-label" label="Operations group" value={groupValue}
                  onChange={(e) => setGroup(e.target.value as number | '')}>
            <MenuItem value="">No group</MenuItem>
            {groupIsArchived && (
              <MenuItem value={groupValue}>{handover.operations_group_name ?? 'Archived group'} (deleted)</MenuItem>
            )}
            {groups.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
          </Select>
        </FormControl>
        {handover.confirmed_at ? (
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2">Handover confirmed by {handover.confirmed_by_username ?? 'unknown'} on {fmtDateTime(handover.confirmed_at)}</Typography>
            {canWrite && <Button size="small" onClick={() => openDialog('withdraw-handover')}>Withdraw</Button>}
          </Stack>
        ) : (
          canWrite && (
            <Tooltip title={handover.operations_group_id ? '' : 'Set the operations group first'}>
              <span>
                <Button variant="contained" size="small" disabled={!handover.operations_group_id}
                        onClick={() => openDialog('confirm')}>Confirm handover</Button>
              </span>
            </Tooltip>
          )
        )}
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>Closing</Typography>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Post-implementation review: {pir.exists ? pir.status : 'none'}
        </Typography>
        {close_targets.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            This release's lifecycle has no state flagged as closed.
            {user?.role === 'Admin' && <> Flag one in the <Link component={RouterLink} to={entityTabPath('releases', 'lifecycle')}>lifecycle editor</Link>.</>}
          </Typography>
        ) : (
          close_targets.map((t) => {
            const pirReason = t.unmet.find((r) => r.includes('post-implementation'));
            const handoverReason = t.unmet.find((r) => r.includes('handover'));
            return (
              <Box key={t.state_key} data-testid={`close-target-${t.state_key}`} sx={{ mb: 1 }}>
                <Typography variant="subtitle2">{t.label}</Typography>
                {!t.requires_pir_complete && !t.requires_handover_confirmed ? (
                  <Typography variant="body2" color="text.secondary">No requirements.</Typography>
                ) : (
                  <Stack spacing={0.5}>
                    {t.requires_pir_complete && (
                      <Requirement met={!pirReason} label="Post-implementation review complete" reason={pirReason} />
                    )}
                    {t.requires_handover_confirmed && (
                      <Requirement met={!handoverReason} label="Ops handover confirmed" reason={handoverReason} />
                    )}
                  </Stack>
                )}
              </Box>
            );
          })
        )}
      </Paper>

      <Dialog open={pending !== null} onClose={() => !submitting && setPending(null)} fullWidth maxWidth="sm">
        <DialogTitle>
          {{ declare: 'Declare stable', 'withdraw-stable': 'Withdraw stability declaration',
             confirm: 'Confirm ops handover', 'withdraw-handover': 'Withdraw handover confirmation' }[pending ?? 'declare']}
        </DialogTitle>
        <DialogContent>
          {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
          <TextField label="Note (optional)" fullWidth multiline rows={3} value={note}
                     onChange={(e) => setNote(e.target.value)} sx={{ mt: 1 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPending(null)} disabled={submitting}>Cancel</Button>
          <Button variant="contained" onClick={run} disabled={submitting}>Confirm</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function Requirement({ met, label, reason }: { met: boolean; label: string; reason?: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      {met ? <CheckCircleIcon color="success" fontSize="small" aria-label="Met" />
           : <CancelIcon color="error" fontSize="small" aria-label="Not met" />}
      <Typography variant="body2">{label}{!met && reason ? ` — ${reason}` : ''}</Typography>
    </Stack>
  );
}
