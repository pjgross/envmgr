/**
 * Create or edit one process action.
 *
 * `closure_note` appears only for a closing status: asking for one on an open
 * action invites a note about work that has not happened.
 */
import { useEffect, useState } from 'react';
import {
  Alert, Autocomplete, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  MenuItem, Stack, TextField,
} from '@mui/material';
import api from '../../../services/api';
import { formatApiError } from '../../../services/apiError';
import { pirService } from '../../../services/pirService';
import type { PirAction, PirActionStatus, PirActionWrite } from '../../../types/pir';

const STATUSES: { value: PirActionStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'done', label: 'Done' },
  { value: 'cancelled', label: 'Cancelled' },
];

const CLOSING: PirActionStatus[] = ['done', 'cancelled'];

interface UserLite { id: number; username: string }

interface Props {
  open: boolean;
  action: PirAction | null;
  releaseId: number;
  findingId: number;
  onClose: () => void;
  onSaved: () => void;
}

export default function PirActionDialog({
  open, action, releaseId, findingId, onClose, onSaved,
}: Props) {
  const [title, setTitle] = useState('');
  const [detail, setDetail] = useState('');
  const [ownerId, setOwnerId] = useState<number | null>(null);
  const [dueDate, setDueDate] = useState('');
  const [status, setStatus] = useState<PirActionStatus>('open');
  const [closureNote, setClosureNote] = useState('');
  const [users, setUsers] = useState<UserLite[]>([]);
  const [usersFailed, setUsersFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle(action?.title ?? '');
    setDetail(action?.detail ?? '');
    setOwnerId(action?.owner_id ?? null);
    // The API speaks instants; the input speaks days. Slice the UTC date so a
    // due date written as T00:00:00Z reads as the same day everywhere.
    setDueDate(action?.due_date ? action.due_date.slice(0, 10) : '');
    setStatus(action?.status ?? 'open');
    setClosureNote(action?.closure_note ?? '');
    setError(null);
  }, [open, action]);

  useEffect(() => {
    if (!open) return;
    // The lite endpoint is tenant-member-accessible and carries its own larger
    // contract (default 1000) precisely because every consumer is a picker.
    // A failed lookup and an empty tenant are NOT the same thing, and rendering
    // both as an empty picker tells the user their colleagues do not exist.
    api.get<UserLite[]>('/tenant/users/lite')
      .then((r) => { setUsers(r.data); setUsersFailed(false); })
      .catch(() => { setUsers([]); setUsersFailed(true); });
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    const payload: PirActionWrite = {
      title,
      detail: detail || null,
      owner_id: ownerId,
      due_date: dueDate ? `${dueDate}T00:00:00Z` : null,
      status,
      closure_note: CLOSING.includes(status) ? (closureNote || null) : null,
    };
    try {
      if (action) {
        await pirService.updateAction(releaseId, findingId, action.id, payload);
      } else {
        await pirService.createAction(releaseId, findingId, payload);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{action ? 'Edit action' : 'Add action'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)}
                     required fullWidth autoFocus />
          <TextField label="Detail" value={detail} onChange={(e) => setDetail(e.target.value)}
                     multiline minRows={2} fullWidth />
          <Autocomplete
            options={users}
            getOptionLabel={(u) => u.username}
            value={users.find((u) => u.id === ownerId) ?? null}
            onChange={(_, v) => setOwnerId(v ? v.id : null)}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Owner"
                helperText={usersFailed ? 'Could not load the user list' : undefined}
              />
            )}
          />
          <TextField label="Due date" type="date" value={dueDate}
                     onChange={(e) => setDueDate(e.target.value)}
                     InputLabelProps={{ shrink: true }} fullWidth />
          <TextField label="Status" select value={status}
                     onChange={(e) => setStatus(e.target.value as PirActionStatus)} fullWidth>
            {STATUSES.map((s) => (
              <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
            ))}
          </TextField>
          {CLOSING.includes(status) && (
            <TextField label="Closure note" value={closureNote}
                       onChange={(e) => setClosureNote(e.target.value)}
                       multiline minRows={2} fullWidth />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || !title.trim()}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
