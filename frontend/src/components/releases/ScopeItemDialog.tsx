/**
 * ScopeItemDialog — create or edit a scope item (release change).
 */
import { useEffect, useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '../../store';
import {
  createReleaseChange,
  updateReleaseChange,
} from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ReleaseChangeResponse } from '../../types/releaseChange';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  item?: ReleaseChangeResponse | null;
}

const CHANGE_KINDS = ['story', 'defect', 'task', 'spike'];

export default function ScopeItemDialog({ open, onClose, releaseId, item }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const isEdit = !!item;

  const [title, setTitle] = useState('');
  const [changeKind, setChangeKind] = useState('story');
  const [externalKey, setExternalKey] = useState('');
  const [description, setDescription] = useState('');
  const [externalStatus, setExternalStatus] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setTitle(item?.title ?? '');
      setChangeKind(item?.change_kind ?? 'story');
      setExternalKey(item?.external_key ?? '');
      setDescription(item?.description ?? '');
      setExternalStatus(item?.external_status ?? '');
    }
  }, [open, item]);

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSave = async () => {
    if (!title.trim()) return;
    setSubmitting(true);
    try {
      if (isEdit && item) {
        await dispatch(
          updateReleaseChange({
            changeId: item.id,
            data: {
              title: title.trim(),
              description: description || null,
              external_key: externalKey || null,
              external_status: externalStatus || null,
            },
          })
        ).unwrap();
        snackbar.success('Scope item updated');
      } else {
        await dispatch(
          createReleaseChange({
            releaseId,
            data: {
              title: title.trim(),
              change_kind: changeKind,
              description: description || null,
              external_key: externalKey || null,
              external_status: externalStatus || null,
            },
          })
        ).unwrap();
        snackbar.success('Scope item added');
      }
      handleClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save scope item');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Scope Item' : 'Add Scope Item'}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            label="Title"
            required
            fullWidth
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={submitting}
          />
          <TextField
            select
            label="Kind"
            fullWidth
            value={changeKind}
            onChange={(e) => setChangeKind(e.target.value)}
            disabled={submitting || isEdit}
          >
            {CHANGE_KINDS.map((k) => (
              <MenuItem key={k} value={k}>
                {k}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="External Key (e.g. Jira issue)"
            fullWidth
            value={externalKey}
            onChange={(e) => setExternalKey(e.target.value)}
            disabled={submitting}
          />
          <TextField
            label="External Status"
            fullWidth
            value={externalStatus}
            onChange={(e) => setExternalStatus(e.target.value)}
            disabled={submitting}
          />
          <TextField
            label="Description"
            multiline
            rows={2}
            fullWidth
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={submitting}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={!title.trim() || submitting}
          onClick={handleSave}
        >
          {isEdit ? 'Save' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
