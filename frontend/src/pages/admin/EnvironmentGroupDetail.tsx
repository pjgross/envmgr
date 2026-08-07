import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
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

import type { AppDispatch, RootState } from '../../store';
import {
  addGroupMember,
  fetchEnvironmentGroup,
  fetchGroupMembers,
  removeGroupMember,
} from '../../store/environmentGroupSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';

export default function EnvironmentGroupDetail() {
  const { id } = useParams<{ id: string }>();
  const groupId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { current: group, members, memberTotal, error: loadError } = useSelector(
    (s: RootState) => s.environmentGroup
  );
  // GET /environment-groups/{id} and .../members are open to any tenant
  // member; POST/DELETE on membership are require_tenant_admin() — the same
  // split as Projects.tsx/ProjectDetail.tsx and UserGroups.tsx/UserGroupDetail.tsx.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const { environments, loading: environmentsLoading } = useAllEnvironments();

  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState<number | ''>('');
  const [addError, setAddError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isNaN(groupId)) {
      // Fetched directly rather than read off the list slice: a deep link or
      // a refresh on this route has never populated `groups`, and the list
      // is a server-paged window that may not even contain this group.
      dispatch(fetchEnvironmentGroup(groupId));
      dispatch(fetchGroupMembers(groupId));
    }
  }, [dispatch, groupId]);

  const handleAddMember = async () => {
    if (!selectedEnvironmentId) return;
    setAddError(null);
    const result = await dispatch(
      addGroupMember({
        groupId,
        data: { environment_id: Number(selectedEnvironmentId) },
      })
    );
    if (addGroupMember.rejected.match(result)) {
      // `payload`, not `error.message` — see environmentGroupSlice.ts's
      // module docblock: miniSerializeError drops response.data.detail.
      setAddError(result.payload ?? 'Failed to add environment to group');
      return;
    }
    setSelectedEnvironmentId('');
    // The slice deliberately has no fulfilled handler for member add/remove
    // (server-paged slice, see environmentGroupSlice.ts) — refetch rather
    // than splice the new row in locally.
    dispatch(fetchGroupMembers(groupId));
  };

  const handleRemoveMember = async (memberId: number) => {
    setRemoveError(null);
    const result = await dispatch(removeGroupMember({ groupId, memberId }));
    if (removeGroupMember.rejected.match(result)) {
      setRemoveError(result.payload ?? 'Failed to remove environment from group');
      return;
    }
    dispatch(fetchGroupMembers(groupId));
  };

  const memberEnvironmentIds = new Set(members.map((m) => m.environment_id));
  const availableEnvironments = environments.filter((e) => !memberEnvironmentIds.has(e.id));

  return (
    <Box sx={{ p: 3 }}>
      <Button size="small" onClick={() => navigate('/tenant/environment-groups')} sx={{ mb: 2 }}>
        Back to Environment Groups
      </Button>

      {loadError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {loadError}
        </Alert>
      )}

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Typography variant="h5">{group?.name ?? 'Environment Group'}</Typography>
        {group && (
          <Chip
            size="small"
            label={group.is_active ? 'Active' : 'Archived'}
            color={group.is_active ? 'success' : 'default'}
          />
        )}
      </Box>
      {group?.description && (
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          {group.description}
        </Typography>
      )}

      <Typography variant="h6" sx={{ mt: 1, mb: 1 }}>
        Members
      </Typography>
      <Alert severity="info" sx={{ mb: 2 }}>
        Membership is frozen at booking time — changing this group's environments
        does not affect existing bookings. Removing an environment here does not
        cancel or otherwise touch any booking already made through this group.
      </Alert>

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
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 2, flexWrap: 'wrap' }}>
          <TextField
            select
            label="Environment"
            size="small"
            disabled={environmentsLoading}
            value={selectedEnvironmentId}
            onChange={(e) =>
              setSelectedEnvironmentId(e.target.value ? Number(e.target.value) : '')
            }
            sx={{ minWidth: 220 }}
          >
            {availableEnvironments.map((env) => (
              <MenuItem key={env.id} value={env.id}>
                {env.name}
              </MenuItem>
            ))}
          </TextField>
          <Button
            variant="contained"
            size="small"
            onClick={handleAddMember}
            disabled={!selectedEnvironmentId}
          >
            Add
          </Button>
        </Box>
      )}

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        {memberTotal} environment{memberTotal === 1 ? '' : 's'}
      </Typography>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Environment</TableCell>
              <TableCell>Added</TableCell>
              {canWrite && <TableCell />}
            </TableRow>
          </TableHead>
          <TableBody>
            {members.map((m) => (
              <TableRow key={m.id}>
                {/* environment_name travels with the member row the API
                    returned — never resolved against useAllEnvironments,
                    which is capped, so a miss there would render `—` and
                    lose information no truncation banner can recover. */}
                <TableCell>{m.environment_name}</TableCell>
                <TableCell>{new Date(m.created_at).toLocaleDateString()}</TableCell>
                {canWrite && (
                  <TableCell align="right">
                    <Button size="small" color="error" onClick={() => handleRemoveMember(m.id)}>
                      Remove
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  );
}
