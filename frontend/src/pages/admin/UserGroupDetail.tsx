import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import api from '../../services/api';
import type { AppDispatch, RootState } from '../../store';
import {
  addGroupMember,
  fetchGroupMembers,
  fetchUserGroup,
  removeGroupMember,
} from '../../store/userGroupSlice';
import DetailPageHeader from '../../components/layout/DetailPageHeader';

export default function UserGroupDetail() {
  const { id } = useParams<{ id: string }>();
  const groupId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const { currentGroup, members, memberTotal, error: loadError } = useSelector(
    (s: RootState) => s.userGroup
  );
  // GET /tenant/groups/{id} is open to any tenant member; POST/DELETE on
  // membership are require_tenant_admin(). Mirror that split for the write
  // controls the way UserGroups.tsx does for its row actions.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const group = currentGroup?.id === groupId ? currentGroup : null;

  const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
  const [addError, setAddError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isNaN(groupId)) {
      // Fetched directly rather than read off the list slice: a deep link or
      // a refresh on this route has never populated `groups`, and the list
      // is a server-paged window that may not even contain this group.
      dispatch(fetchUserGroup(groupId));
      dispatch(fetchGroupMembers(groupId));
    }
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
      <DetailPageHeader back={{ to: '/admin/user-groups', label: 'User groups' }} title={group?.name} />

      {loadError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {loadError}
        </Alert>
      )}

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

      {canWrite && (
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
      )}

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Members ({members.length}
        {memberTotal > members.length ? ` of ${memberTotal}` : ''})
      </Typography>
      {memberTotal > members.length && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Showing the first {members.length} of {memberTotal} members. The "Add
          member" picker above is filtered against only this window, so a
          member past it could still be offered there — adding them would 409
          as already a member.
        </Alert>
      )}

      <Paper variant="outlined">
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Username</TableCell>
                <TableCell>Added</TableCell>
                {canWrite && <TableCell />}
              </TableRow>
            </TableHead>
            <TableBody>
              {members.map((m) => (
                <TableRow key={m.id}>
                  <TableCell>{m.username}</TableCell>
                  <TableCell>{new Date(m.created_at).toLocaleDateString()}</TableCell>
                  {canWrite && (
                    <TableCell align="right">
                      <Button size="small" color="error" onClick={() => handleRemoveMember(m.user_id)}>
                        Remove
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Box>
  );
}
