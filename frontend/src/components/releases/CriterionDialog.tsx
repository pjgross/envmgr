import { useEffect, useState } from 'react';
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle,
  Stack, TextField, MenuItem,
} from '@mui/material';
import type {
  GateCriterion, GateCriterionCreatePayload, GateCriterionUpdatePayload,
} from '../../types/gateCriterion';

interface User { id: number; username: string }

interface Props {
  open: boolean;
  initial?: GateCriterion | null;
  users: User[];
  onClose: () => void;
  onSubmit: (payload: GateCriterionCreatePayload | GateCriterionUpdatePayload) => void;
}

export default function CriterionDialog({ open, initial, users, onClose, onSubmit }: Props) {
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [assignee, setAssignee] = useState<number | ''>('');

  useEffect(() => {
    setTitle(initial?.title ?? '');
    setNotes(initial?.notes ?? '');
    setDueDate(initial?.due_date ? initial.due_date.slice(0, 16) : '');
    setAssignee(initial?.assigned_to_user_id ?? '');
  }, [initial, open]);

  const handleSubmit = () => {
    onSubmit({
      title: title.trim(),
      notes: notes.trim() || null,
      due_date: dueDate ? new Date(dueDate).toISOString() : null,
      assigned_to_user_id: assignee === '' ? null : Number(assignee),
    });
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{initial ? 'Edit criterion' : 'Add criterion'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Title" value={title} onChange={(e) => setTitle(e.target.value)}
            required fullWidth inputProps={{ maxLength: 250 }}
          />
          <TextField
            label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)}
            multiline rows={3} fullWidth
          />
          <TextField
            label="Due date" type="datetime-local" value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            InputLabelProps={{ shrink: true }} fullWidth
          />
          <TextField
            label="Assignee" select value={assignee}
            onChange={(e) => setAssignee(e.target.value === '' ? '' : Number(e.target.value))}
            fullWidth
          >
            <MenuItem value="">(unassigned)</MenuItem>
            {users.map((u) => (
              <MenuItem key={u.id} value={u.id}>{u.username}</MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!title.trim()} onClick={handleSubmit}>
          {initial ? 'Save' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
