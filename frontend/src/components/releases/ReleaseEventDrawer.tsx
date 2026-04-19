/**
 * ReleaseEventDrawer — right-hand drawer showing release events and allowing
 * users to post new events.
 * Reads GET /releases/:id/events and posts POST /releases/:id/events.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  TextField,
  Toolbar,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseEvents, createReleaseEvent } from '../../store/releaseSlice';
import { fetchReleaseEventTypes } from '../../store/releaseEventTypeSlice';
import { useSnackbar } from '../../hooks/useSnackbar';

interface Props {
  open: boolean;
  releaseId: number;
  onClose: () => void;
}

const DRAWER_WIDTH = 400;

export default function ReleaseEventDrawer({ open, releaseId, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { events, loading } = useSelector((state: RootState) => state.release);
  const eventTypes = useSelector((state: RootState) => state.releaseEventType.list);

  const [showForm, setShowForm] = useState(false);
  const [eventTypeId, setEventTypeId] = useState<number | ''>('');
  const [description, setDescription] = useState('');
  const [occurredAt, setOccurredAt] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      dispatch(fetchReleaseEvents(releaseId));
      dispatch(fetchReleaseEventTypes());
    }
  }, [open, releaseId, dispatch]);

  const handleSubmit = async () => {
    if (!eventTypeId || !description.trim()) return;
    setSubmitting(true);
    try {
      await dispatch(
        createReleaseEvent({
          releaseId,
          data: {
            event_type_id: eventTypeId as number,
            description: description.trim(),
            occurred_at: occurredAt || null,
          },
        })
      ).unwrap();
      snackbar.success('Event recorded');
      setDescription('');
      setOccurredAt('');
      setEventTypeId('');
      setShowForm(false);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to record event');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}
    >
      <Toolbar />
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Event Log
          </Typography>
          <IconButton
            size="small"
            onClick={() => setShowForm((v) => !v)}
            title="Log new event"
          >
            <AddIcon />
          </IconButton>
          <IconButton onClick={onClose} size="small" sx={{ ml: 0.5 }}>
            <CloseIcon />
          </IconButton>
        </Box>
        <Divider sx={{ mb: 2 }} />

        {/* New event form */}
        {showForm && (
          <Box
            sx={{
              mb: 2,
              p: 2,
              border: 1,
              borderColor: 'divider',
              borderRadius: 1,
              display: 'flex',
              flexDirection: 'column',
              gap: 1.5,
            }}
          >
            <Typography variant="subtitle2">Log New Event</Typography>
            <TextField
              select
              label="Event Type"
              size="small"
              fullWidth
              value={eventTypeId}
              onChange={(e) => setEventTypeId(e.target.value === '' ? '' : Number(e.target.value))}
            >
              {eventTypes.map((t) => (
                <MenuItem key={t.id} value={t.id}>
                  {t.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Description"
              size="small"
              fullWidth
              multiline
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <TextField
              label="Occurred At (optional)"
              type="datetime-local"
              size="small"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={occurredAt}
              onChange={(e) => setOccurredAt(e.target.value)}
            />
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Button size="small" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
              <Button
                size="small"
                variant="contained"
                onClick={handleSubmit}
                disabled={submitting || !eventTypeId || !description.trim()}
              >
                {submitting ? 'Saving…' : 'Save'}
              </Button>
            </Box>
          </Box>
        )}

        {/* Event list */}
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : events.length === 0 ? (
          <Typography color="text.secondary" variant="body2">
            No events recorded yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {events.map((ev) => {
              const typeName =
                eventTypes.find((t) => t.id === ev.event_type_id)?.name ?? `Type ${ev.event_type_id}`;
              return (
                <ListItem key={ev.id} disableGutters alignItems="flex-start" sx={{ py: 0.5 }}>
                  <ListItemText
                    primary={
                      <Typography variant="body2" fontWeight="medium">
                        {typeName}
                      </Typography>
                    }
                    secondary={
                      <>
                        {ev.description}
                        <br />
                        <Typography variant="caption" color="text.secondary">
                          {new Date(ev.occurred_at).toLocaleString()}
                        </Typography>
                      </>
                    }
                  />
                </ListItem>
              );
            })}
          </List>
        )}
      </Box>
    </Drawer>
  );
}
