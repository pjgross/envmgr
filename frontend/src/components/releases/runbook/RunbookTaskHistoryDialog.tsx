/**
 * A task's instructions and its append-only history (Ruling R16). Read-only
 * and open to every viewer: the history is the audit trail of who moved the
 * task when, and a back-dated move shows both when it happened (`at`) and
 * when it was recorded. Read fresh on every open, newest first as the server
 * orders it.
 */
import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, List, ListItem, ListItemText, Stack, Typography,
} from '@mui/material';
import type { AppDispatch } from '../../../store';
import { fetchTaskEvents } from '../../../store/runbookSlice';
import type { RunbookTaskEventRead, RunbookTaskRead } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';
import { STATUS_LABEL } from './labels';

interface Props { task: RunbookTaskRead; onClose: () => void }

export default function RunbookTaskHistoryDialog({ task, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const [events, setEvents] = useState<RunbookTaskEventRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    setError(null);
    dispatch(fetchTaskEvents(task.id)).then((result) => {
      if (cancelled) return;
      if (fetchTaskEvents.fulfilled.match(result)) setEvents(result.payload);
      else setError((result.payload as string | undefined) ?? 'Failed to load task history');
    });
    return () => { cancelled = true; };
  }, [dispatch, task.id]);

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>History: {task.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Stack spacing={0.5}>
            <Typography variant="subtitle2">Instructions</Typography>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}
                        color={task.description ? 'text.primary' : 'text.secondary'}>
              {task.description || 'No instructions recorded for this task.'}
            </Typography>
          </Stack>
          <Typography variant="subtitle2">Status changes (newest first)</Typography>
          {error && <Alert severity="error">{error}</Alert>}
          {!error && events === null && <Typography color="text.secondary">Loading history…</Typography>}
          {events && events.length === 0 && (
            <Typography color="text.secondary">No status changes recorded yet.</Typography>
          )}
          {events && events.length > 0 && (
            <List dense aria-label={`Status changes for ${task.name}`}>
              {events.map((e) => (
                <ListItem key={e.id} disableGutters divider alignItems="flex-start">
                  <ListItemText
                    primary={`${STATUS_LABEL[e.from_status]} → ${STATUS_LABEL[e.to_status]}`}
                    secondary={
                      <>
                        <span>
                          At {formatBookingDateTime(e.at)} · recorded {formatBookingDateTime(e.recorded_at)}
                          {' · by '}{e.by_username ?? 'an unknown user'}
                        </span>
                        {e.note && <><br /><span>Note: {e.note}</span></>}
                      </>
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
