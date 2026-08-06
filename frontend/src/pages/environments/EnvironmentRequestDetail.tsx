/**
 * EnvironmentRequestDetail — a single environment request: its fields, the
 * transitions this actor may make, an admin-only operating-group picker for
 * a draft new-environment request, and the Welcome Pack once fulfilled.
 *
 * Route: /environment-requests/:id
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchAllowedTransitions,
  fetchEnvironmentRequest,
  transitionEnvironmentRequest,
  updateEnvironmentRequest,
} from '../../store/environmentRequestSlice';
import { fetchUserGroups } from '../../store/userGroupSlice';
import WelcomePack from '../../components/environments/WelcomePack';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'info',
  fulfilled: 'success',
  rejected: 'error',
  cancelled: 'default',
};

export default function EnvironmentRequestDetail() {
  const { id } = useParams<{ id: string }>();
  const requestId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const { current, allowedTransitions, loading } = useSelector(
    (state: RootState) => state.environmentRequest
  );
  const user = useSelector((state: RootState) => state.auth.user);
  const groups = useSelector((state: RootState) => state.userGroup.groups);

  const [actionError, setActionError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);

  const [groupId, setGroupId] = useState<number | ''>('');
  const [groupError, setGroupError] = useState<string | null>(null);
  const [savingGroup, setSavingGroup] = useState(false);

  useEffect(() => {
    dispatch(fetchEnvironmentRequest(requestId));
    dispatch(fetchAllowedTransitions(requestId));
  }, [dispatch, requestId]);

  useEffect(() => {
    setGroupId(current?.operations_group_id ?? '');
  }, [current?.operations_group_id]);

  const isAdmin = user?.role === 'Admin' || user?.is_master_admin === true;

  // A new-environment request cannot be fulfilled without an
  // operations_group_id (fulfilment 409s otherwise). The picker only ever
  // works while the request is still 'draft': PATCH /environment-requests/{id}
  // 409s once a request has left draft ("A request can only be edited while
  // it is a draft" — environment_request_service.update_request), so an
  // admin must assign the team before the request is submitted, not after.
  const showGroupPicker = isAdmin && current?.kind === 'new_environment' && current?.status === 'draft';

  useEffect(() => {
    if (showGroupPicker) dispatch(fetchUserGroups({}));
  }, [dispatch, showGroupPicker]);

  const handleTransition = async (toState: string) => {
    setTransitioning(true);
    setActionError(null);
    const result = await dispatch(transitionEnvironmentRequest({ id: requestId, toState }));
    setTransitioning(false);
    if (transitionEnvironmentRequest.rejected.match(result)) {
      // `result.payload`, never `result.error.message` — the 403/409 here
      // names WHY a transition was refused.
      setActionError(result.payload ?? 'Failed to update the request state');
      return;
    }
    setActionError(null);
    // The allowed set changes with the state — re-fetch both rather than
    // trust the slice's own transitionEnvironmentRequest.fulfilled handler,
    // which only updates `current`.
    dispatch(fetchEnvironmentRequest(requestId));
    dispatch(fetchAllowedTransitions(requestId));
  };

  const handleGroupSave = async () => {
    if (!groupId) return;
    setSavingGroup(true);
    setGroupError(null);
    const result = await dispatch(
      updateEnvironmentRequest({ id: requestId, data: { operations_group_id: Number(groupId) } })
    );
    setSavingGroup(false);
    if (updateEnvironmentRequest.rejected.match(result)) {
      setGroupError(result.payload ?? 'Failed to set the operations group');
      return;
    }
    setGroupError(null);
    dispatch(fetchEnvironmentRequest(requestId));
  };

  if (loading && !current) {
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (!current) return null;

  const target =
    current.kind === 'access'
      ? (current.environment_name ?? '—')
      : `${current.proposed_name ?? '—'} (new)`;

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1 }}>
        <IconButton onClick={() => navigate('/environment-requests')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" fontWeight="bold" sx={{ flexGrow: 1 }}>
          {target}
        </Typography>
        <Chip
          label={current.status}
          size="small"
          color={STATUS_COLORS[current.status] ?? 'default'}
        />
      </Box>

      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack spacing={1.5} divider={<Divider />}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Kind
            </Typography>
            <Typography variant="body2">
              {current.kind === 'access' ? 'Access' : 'New environment'}
            </Typography>
          </Box>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Requested by
            </Typography>
            <Typography variant="body2">{current.requester_username ?? '—'}</Typography>
          </Box>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Justification
            </Typography>
            <Typography variant="body2">{current.justification}</Typography>
          </Box>
          {current.kind === 'access' ? (
            <Box>
              <Typography variant="overline" color="text.secondary">
                Environment
              </Typography>
              <Typography variant="body2">{current.environment_name ?? '—'}</Typography>
            </Box>
          ) : (
            <>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Proposed name
                </Typography>
                <Typography variant="body2">{current.proposed_name ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Tier
                </Typography>
                <Typography variant="body2">{current.tier_name ?? '—'}</Typography>
              </Box>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Expiry
                </Typography>
                <Typography variant="body2">
                  {current.expires_at ? new Date(current.expires_at).toLocaleDateString() : '—'}
                </Typography>
              </Box>
            </>
          )}
          <Box>
            <Typography variant="overline" color="text.secondary">
              Needed by
            </Typography>
            <Typography variant="body2">
              {current.needed_by ? new Date(current.needed_by).toLocaleDateString() : '—'}
            </Typography>
          </Box>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Operations group
            </Typography>
            <Typography variant="body2">{current.operations_group_name ?? '— no group'}</Typography>
          </Box>
        </Stack>
      </Paper>

      {showGroupPicker && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Operations Group
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            A new-environment request cannot be fulfilled until an operating team is assigned —
            set it before submitting this request.
          </Typography>
          {groupError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {groupError}
            </Alert>
          )}
          <Stack direction="row" spacing={2} alignItems="center">
            <FormControl sx={{ minWidth: 240 }}>
              <InputLabel id="request-operations-group-label">Operations Group</InputLabel>
              <Select
                labelId="request-operations-group-label"
                label="Operations Group"
                value={groupId}
                onChange={(e) => setGroupId(e.target.value as number)}
              >
                {groups.map((g) => (
                  <MenuItem key={g.id} value={g.id}>
                    {g.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              onClick={handleGroupSave}
              disabled={!groupId || savingGroup}
            >
              Save
            </Button>
          </Stack>
        </Paper>
      )}

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Actions
        </Typography>
        {actionError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {actionError}
          </Alert>
        )}
        {allowedTransitions.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No actions are available to you for this request right now.
          </Typography>
        ) : (
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {allowedTransitions.map((t) => (
              <Button
                key={t.to_state}
                variant="contained"
                disabled={transitioning}
                onClick={() => handleTransition(t.to_state)}
              >
                {t.label}
              </Button>
            ))}
          </Stack>
        )}
      </Paper>

      {current.status === 'fulfilled' && <WelcomePack requestId={requestId} />}
    </Box>
  );
}
