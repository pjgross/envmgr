import { useEffect, useState } from 'react';
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle,
  Stack, TextField, MenuItem,
} from '@mui/material';
import type {
  GateCriterion, GateCriterionCreatePayload, GateCriterionUpdatePayload,
} from '../../types/gateCriterion';

const ASSIGNABLE_ROLES = ['Release Manager', 'Test Manager', 'Admin', 'Developer', 'Viewer'];

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
  const [assignee, setAssignee] = useState<number | ''>('');
  const [assignedRole, setAssignedRole] = useState<string>('');

  useEffect(() => {
    setTitle(initial?.title ?? '');
    setNotes(initial?.notes ?? '');
    setAssignee(initial?.assigned_to_user_id ?? '');
    setAssignedRole(initial?.assigned_role ?? '');
  }, [initial, open]);

  const handleSubmit = () => {
    const role = assignedRole || null;
    onSubmit({
      title: title.trim(),
      notes: notes.trim() || null,
      assigned_role: role,
      assigned_to_user_id: role ? null : (assignee === '' ? null : Number(assignee)),
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
            label="Assignee" select value={assignee}
            disabled={!!assignedRole}
            onChange={(e) => {
              const val = e.target.value;
              if (val !== '') setAssignedRole('');
              setAssignee(val === '' ? '' : Number(val));
            }}
            fullWidth
          >
            <MenuItem value="">(unassigned)</MenuItem>
            {users.map((u) => (
              <MenuItem key={u.id} value={u.id}>{u.username}</MenuItem>
            ))}
          </TextField>
          <TextField
            label="Assign to role" select value={assignedRole}
            disabled={!!assignee}
            onChange={(e) => {
              const val = e.target.value;
              if (val !== '') setAssignee('');
              setAssignedRole(val);
            }}
            fullWidth
          >
            <MenuItem value="">(no role)</MenuItem>
            {ASSIGNABLE_ROLES.map((r) => (
              <MenuItem key={r} value={r}>{r}</MenuItem>
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
