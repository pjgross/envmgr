import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import api from '../../services/api';
import type { AppDispatch, RootState } from '../../store';
import { addGroupMember, fetchGroupMembers, removeGroupMember } from '../../store/userGroupSlice';

export default function UserGroupDetail() {
  const { id } = useParams<{ id: string }>();
  const groupId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { groups, members } = useSelector((s: RootState) => s.userGroup);

  const group = groups.find((g) => g.id === groupId);

  const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
  const [addError, setAddError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isNaN(groupId)) dispatch(fetchGroupMembers(groupId));
  }, [dispatch, groupId]);

  // GET /tenant/users/lite is bounded, but at its own larger contract
  // (default 1000, max 5000) rather than the shared 500/1000 — a truncated
  // picker loses users rather than shortening a page. A tenant past 1000
  // active users needs a type-to-search picker here; see docs/pagination.md.
  // (EnvironmentList and GatesTable call it the same way.)
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  useEffect(() => {
    api
      .get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => setUsers(r.data))
      .catch(() => setUsers([])); // member picker stays empty on failure
  }, []);

  const handleAddMember = async () => {
    if (!selectedUserId) return;
    setAddError(null);
    const result = await dispatch(
      addGroupMember({ groupId, userId: Number(selectedUserId) })
    );
    if (addGroupMember.rejected.match(result)) {
      // `payload`, not `error.message` — the 409 says who is already a member.
      setAddError(result.payload ?? 'Failed to add member');
      return;
    }
    setSelectedUserId('');
  };

  const handleRemoveMember = async (userId: number) => {
    setRemoveError(null);
    const result = await dispatch(removeGroupMember({ groupId, userId }));
    if (removeGroupMember.rejected.match(result)) {
      setRemoveError(result.payload ?? 'Failed to remove member');
    }
  };

  const memberUserIds = new Set(members.map((m) => m.user_id));
  const availableUsers = users.filter((u) => !memberUserIds.has(u.id));

  return (
    <Box sx={{ p: 3 }}>
      <Button size="small" onClick={() => navigate('/tenant/groups')} sx={{ mb: 2 }}>
        Back to User Groups
      </Button>

      <Typography variant="h5">{group?.name ?? 'User Group'}</Typography>
      {group?.description && (
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          {group.description}
        </Typography>
      )}

      {addError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {addError}
        </Alert>
      )}
      {removeError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {removeError}
        </Alert>
      )}

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 2 }}>
        <TextField
          select
          label="Add member"
          size="small"
          value={selectedUserId}
          onChange={(e) => setSelectedUserId(e.target.value ? Number(e.target.value) : '')}
          sx={{ minWidth: 240 }}
        >
          {availableUsers.map((u) => (
            <MenuItem key={u.id} value={u.id}>
              {u.username}
            </MenuItem>
          ))}
        </TextField>
        <Button variant="contained" size="small" onClick={handleAddMember} disabled={!selectedUserId}>
          Add
        </Button>
      </Box>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell>
              <TableCell>Added</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {members.map((m) => (
              <TableRow key={m.id}>
                <TableCell>{m.username}</TableCell>
                <TableCell>{new Date(m.created_at).toLocaleDateString()}</TableCell>
                <TableCell align="right">
                  <Button size="small" color="error" onClick={() => handleRemoveMember(m.user_id)}>
                    Remove
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  );
}
