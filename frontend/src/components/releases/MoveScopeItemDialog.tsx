/**
 * MoveScopeItemDialog — move a scope item to a different release (or to backlog).
 */
import { useEffect, useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import type { AppDispatch } from '../../store';
import { moveReleaseChange } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import { releaseService } from '../../services/releaseService';
import type { ReleaseListItemResponse } from '../../types/release';

interface Props {
  open: boolean;
  onClose: () => void;
  changeId: number;
  currentReleaseId: number | null;
  itemTitle?: string;
  onMoved?: () => void;
}

export default function MoveScopeItemDialog({
  open,
  onClose,
  changeId,
  currentReleaseId,
  itemTitle,
  onMoved,
}: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const [releases, setReleases] = useState<ReleaseListItemResponse[]>([]);

  const [targetReleaseId, setTargetReleaseId] = useState<number | null>(currentReleaseId);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // This dialog needs its own copy of the release list rather than reading
  // `state.release.list` — that slice is now the Releases tab's current
  // filtered/sorted page (server-side paging), so whatever status/type
  // filter the user left active there would silently narrow the "Target
  // Release" options here too, with nothing indicating anything is missing.
  // Fetched directly into local state on every open, unconditionally, so it
  // never depends on — or overwrites — the shared slice.
  useEffect(() => {
    if (open) {
      setTargetReleaseId(currentReleaseId);
      setNotes('');
      releaseService
        .list({ limit: 200 })
        .then(({ rows }) => setReleases(rows))
        .catch(() => setReleases([]));
    }
  }, [open, currentReleaseId]);

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSave = async () => {
    setSubmitting(true);
    try {
      await dispatch(
        moveReleaseChange({
          changeId,
          payload: {
            release_id: targetReleaseId,
            notes: notes.trim() || null,
          },
        })
      ).unwrap();
      snackbar.success('Scope item moved');
      onMoved?.();
      handleClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to move scope item');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        Move scope item{itemTitle ? `: ${itemTitle}` : ''}
      </DialogTitle>
      <DialogContent>
        <TextField
          select
          label="Target Release"
          fullWidth
          value={targetReleaseId ?? ''}
          onChange={(e) => {
            const v = e.target.value;
            setTargetReleaseId(v === '' ? null : Number(v));
          }}
          disabled={submitting}
          sx={{ mt: 1, mb: 2 }}
        >
          <MenuItem value="">Backlog / None</MenuItem>
          {releases.map((r) => (
            <MenuItem key={r.id} value={r.id}>
              {r.name}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Notes (optional)"
          multiline
          rows={2}
          fullWidth
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={submitting}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={submitting}
          onClick={handleSave}
        >
          Move
        </Button>
      </DialogActions>
    </Dialog>
  );
}
